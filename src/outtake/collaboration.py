"""Retained collaborative review, operations, and scoped material.

This is deliberately library-only: the CLI and MCP adapter are thin callers.  SQLite
is used for cross-process compare-and-swap, not as an authority beyond caller-selected
Outtake settings and explicit review disclosure.
"""

import base64
import hashlib
import json
import math
import mimetypes
import os
import re
import sqlite3
import stat
import subprocess
import sys
import time
import uuid
from contextlib import closing
from pathlib import Path

from pydantic import BaseModel, Field

from .models import FindRequest, ModelGrant, OuttakeError

_TERMINAL = {"completed", "failed", "cancelled", "interrupted", "uncertain"}
_CHUNK = 192 * 1024
_MAX_DRAFT_BYTES = 256 * 1024
_MAX_WORKERS = 2
_SNAPSHOT_DRAFTS = 8
_SNAPSHOT_OPERATIONS = 8
_SNAPSHOT_BYTES = 256 * 1024
_RESULT_PAGE_BYTES = 64 * 1024
_SAVED_OUTPUT_SCOPE = "mcp-saved-output"


class ReviewScope(frozenset):
    """Server disclosure authority; collection access is explicit, never implicit."""

    def __new__(cls, review_ids=(), *, allow_saved_outputs=False):
        value = super().__new__(cls, review_ids)
        value.allow_saved_outputs = allow_saved_outputs
        return value


class ReviewView(BaseModel):
    """Public semantic navigation, separate from workspace heads and raw drafts."""

    plan_id: str | None = None
    finding_id: str | None = None
    candidate_id: str | None = None
    cue_id: str | None = None
    playhead: float | None = Field(default=None, ge=0)


def _id(kind):
    return f"{kind}_{uuid.uuid4().hex}"


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _db(client):
    db = sqlite3.connect(client.state / "collaboration.sqlite3", timeout=30)
    db.row_factory = sqlite3.Row
    db.executescript(
        """
        PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS reviews (
          id TEXT PRIMARY KEY, target_kind TEXT NOT NULL, target_id TEXT NOT NULL,
          workspace_id TEXT, scope TEXT NOT NULL, view TEXT NOT NULL DEFAULT '{}',
          view_version INTEGER NOT NULL DEFAULT 1, source_ids TEXT NOT NULL DEFAULT '[]',
          parent_review_id TEXT,
          created REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS drafts (
          review_id TEXT NOT NULL, base_plan_id TEXT NOT NULL, version INTEGER NOT NULL,
          request_id TEXT, signature TEXT, draft TEXT NOT NULL, updated REAL NOT NULL,
          PRIMARY KEY (review_id, base_plan_id)
        );
        CREATE TABLE IF NOT EXISTS operations (
          id TEXT PRIMARY KEY, request_id TEXT UNIQUE NOT NULL, signature TEXT NOT NULL,
          operation TEXT NOT NULL, arguments TEXT NOT NULL, settings TEXT NOT NULL,
          grant TEXT, output_id TEXT, status TEXT NOT NULL, result TEXT,
          cancel_requested INTEGER NOT NULL DEFAULT 0, lease_token TEXT,
          lease_until REAL, review_id TEXT, created REAL NOT NULL, updated REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS media (
          id TEXT PRIMARY KEY, review_id TEXT NOT NULL, file TEXT NOT NULL,
          sha256 TEXT NOT NULL, bytes INTEGER NOT NULL, mime TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS mutations (
          review_id TEXT NOT NULL, request_id TEXT NOT NULL, signature TEXT NOT NULL,
          action TEXT NOT NULL, status TEXT NOT NULL, result TEXT, created REAL NOT NULL,
          PRIMARY KEY (review_id, request_id)
        );
        CREATE TABLE IF NOT EXISTS selections (
          review_id TEXT NOT NULL, request_id TEXT NOT NULL, signature TEXT NOT NULL,
          finding_id TEXT NOT NULL, candidate_id TEXT NOT NULL, format TEXT NOT NULL,
          profile TEXT NOT NULL, plan_id TEXT NOT NULL, view_version INTEGER NOT NULL,
          status TEXT NOT NULL, result TEXT, created REAL NOT NULL,
          PRIMARY KEY (review_id, request_id)
        );
        """
    )
    # Forward-only migrations for state written by the first implementation.
    for table, column, sql in (
        ("reviews", "view", "ALTER TABLE reviews ADD COLUMN view TEXT NOT NULL DEFAULT '{}'"),
        (
            "reviews",
            "view_version",
            "ALTER TABLE reviews ADD COLUMN view_version INTEGER NOT NULL DEFAULT 1",
        ),
        (
            "reviews",
            "source_ids",
            "ALTER TABLE reviews ADD COLUMN source_ids TEXT NOT NULL DEFAULT '[]'",
        ),
        (
            "reviews",
            "parent_review_id",
            "ALTER TABLE reviews ADD COLUMN parent_review_id TEXT",
        ),
        ("drafts", "request_id", "ALTER TABLE drafts ADD COLUMN request_id TEXT"),
        ("drafts", "signature", "ALTER TABLE drafts ADD COLUMN signature TEXT"),
        ("operations", "review_id", "ALTER TABLE operations ADD COLUMN review_id TEXT"),
    ):
        if column not in {row[1] for row in db.execute(f"PRAGMA table_info({table})")}:
            db.execute(sql)
    draft_columns = {row[1]: row[5] for row in db.execute("PRAGMA table_info(drafts)")}
    if draft_columns.get("review_id") == 1 and draft_columns.get("base_plan_id", 0) == 0:
        db.executescript(
            """
            ALTER TABLE drafts RENAME TO drafts_legacy;
            CREATE TABLE drafts (
              review_id TEXT NOT NULL, base_plan_id TEXT NOT NULL, version INTEGER NOT NULL,
              request_id TEXT, signature TEXT, draft TEXT NOT NULL, updated REAL NOT NULL,
              PRIMARY KEY (review_id, base_plan_id)
            );
            INSERT INTO drafts (review_id,base_plan_id,version,request_id,signature,draft,updated)
              SELECT review_id,COALESCE(base_plan_id,''),version,request_id,signature,draft,updated
              FROM drafts_legacy;
            DROP TABLE drafts_legacy;
            """
        )
    db.commit()
    return db


def _safe_settings(client):
    return {
        "source_roots": [str(root) for root in client.roots],
        "output_root": str(client.output),
        "limits": client.settings.limits.model_dump(mode="json"),
    }


def _review_allowed(client, row, scope):
    if row["target_kind"] == "artifact":
        try:
            client.artifact(row["target_id"])
        except OuttakeError:
            return False
    if scope is None or row["id"] in scope:
        return True
    if getattr(scope, "allow_saved_outputs", False) and row["scope"] == _SAVED_OUTPUT_SCOPE:
        return True
    parent = row["parent_review_id"]
    seen = {row["id"]}
    with closing(_db(client)) as db:
        while parent and parent not in seen:
            seen.add(parent)
            parent_row = db.execute("SELECT * FROM reviews WHERE id=?", (parent,)).fetchone()
            if not parent_row:
                return False
            if parent_row["target_kind"] == "artifact":
                try:
                    client.artifact(parent_row["target_id"])
                except OuttakeError:
                    return False
            if parent_row["id"] in scope:
                return True
            if (
                getattr(scope, "allow_saved_outputs", False)
                and parent_row["scope"] == _SAVED_OUTPUT_SCOPE
            ):
                return True
            parent = parent_row["parent_review_id"]
    return False


def _review(client, review_id, scope=None):
    if not isinstance(review_id, str) or not review_id.startswith("review_"):
        raise OuttakeError("INVALID_ID", "Invalid review identity.", "Use an Outtake review ID.")
    with closing(_db(client)) as db:
        row = db.execute("SELECT * FROM reviews WHERE id = ?", (review_id,)).fetchone()
    if not row:
        raise OuttakeError(
            "REVIEW_MISSING", "Review is not retained.", "Open an authorized review."
        )
    if not _review_allowed(client, row, scope):
        raise OuttakeError(
            "HOST_SCOPE_DENIED",
            "This review is not within the configured host disclosure scope.",
            "Restart with its parent in --allow-reviews or explicitly allow saved outputs.",
            review_id,
        )
    return row


def review_authorized(client, review_id, scope=None):
    """Validate a disclosed review identity without reading its material."""

    _review(client, review_id, scope)
    return True


def _source_ids_for_finding(client, finding_id):
    finding = client.get_finding(finding_id)
    return sorted(
        {item["source_id"] for item in finding.get("candidates", []) if "source_id" in item}
    )


def _finding_allowed(client, row, finding_id):
    """Disclosure is by retained identity/link, never merely a shared source file."""
    view = ReviewView.model_validate_json(row["view"])
    if finding_id == row["target_id"] and row["target_kind"] == "finding":
        return True
    if finding_id == view.finding_id:
        return True
    with closing(_db(client)) as db:
        rows = db.execute(
            "SELECT result FROM operations WHERE review_id=? AND result IS NOT NULL",
            (row["id"],),
        ).fetchall()
    for item in rows:
        try:
            result = json.loads(item["result"])
        except (TypeError, json.JSONDecodeError):
            continue
        if result.get("id") == finding_id or result.get("finding_id") == finding_id:
            return True
    return False


def _finding(client, row, finding_id):
    if not _finding_allowed(client, row, finding_id):
        raise OuttakeError(
            "TARGET_SCOPE_DENIED",
            "Finding is not linked to this retained review.",
            "Open an explicit review or navigate to a result produced by this review.",
        )
    return client.get_finding(finding_id)


def open_review(client, target_kind, target_id, scope="portable"):
    """Create a disclosure reference; opening never starts execution."""
    if target_kind not in {"plan", "artifact", "finding"}:
        raise OuttakeError(
            "INVALID_INPUT", "Unsupported review target.", "Use plan, artifact or finding."
        )
    if not isinstance(scope, str) or not scope or len(scope) > 120:
        raise OuttakeError(
            "INVALID_INPUT", "Review scope is invalid.", "Supply a short scope label."
        )
    workspace_id, source_ids, view = None, [], ReviewView()
    if target_kind == "plan":
        client.get_plan(target_id)
        workspace_id = client.get_workspace(target_id)["workspace_id"]
        view = ReviewView(plan_id=target_id)
    elif target_kind == "artifact":
        receipt = client.artifact(target_id)
        plan_id = receipt["plan"]["id"]
        workspace_id = client.get_workspace(plan_id, target_id)["workspace_id"]
        view = ReviewView(plan_id=plan_id)
    else:
        source_ids = _source_ids_for_finding(client, target_id)
        view = ReviewView(finding_id=target_id)
    review_id = _id("review")
    with closing(_db(client)) as db, db:
        db.execute(
            """INSERT INTO reviews
               (id, target_kind, target_id, workspace_id, scope, view, view_version, source_ids, created)
               VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?)""",
            (
                review_id,
                target_kind,
                target_id,
                workspace_id,
                scope,
                _json(view.model_dump(exclude_none=True)),
                _json(source_ids),
                time.time(),
            ),
        )
    return {
        "schema_version": 1,
        "review_id": review_id,
        "target": {"kind": target_kind, "id": target_id},
    }


def _authorized_reviews(client, scope):
    with closing(_db(client)) as db:
        rows = db.execute("SELECT * FROM reviews ORDER BY created").fetchall()
    return [row for row in rows if _review_allowed(client, row, scope)]


def _artifact_parent_review(client, artifact_id, scope):
    """Find explicit artifact authority or output owned by an allowed review."""

    client.artifact(artifact_id)
    for row in _authorized_reviews(client, scope):
        if row["target_kind"] == "artifact" and row["target_id"] == artifact_id:
            return row
        with closing(_db(client)) as db:
            owned = db.execute(
                "SELECT 1 FROM operations WHERE review_id=? AND output_id=?",
                (row["id"], artifact_id),
            ).fetchone()
        if owned:
            return row
    return None


def _artifact_in_review(client, row, artifact_id):
    """Artifact authority is explicit/operation-owned, never inferred from a shared plan."""

    if row["target_kind"] == "artifact" and row["target_id"] == artifact_id:
        return True
    with closing(_db(client)) as db:
        return bool(
            db.execute(
                "SELECT 1 FROM operations WHERE review_id=? AND output_id=?",
                (row["id"], artifact_id),
            ).fetchone()
        )


def _scoped_artifact(client, artifact_id, scope):
    parent = _artifact_parent_review(client, artifact_id, scope)
    if parent is None and not getattr(scope, "allow_saved_outputs", False):
        raise OuttakeError(
            "OUTPUT_SCOPE_DENIED",
            "Saved output is not within this server's authorized reviews.",
            "Attach its explicit review or restart with --allow-saved-outputs for this output collection.",
        )
    return client.artifact(artifact_id), parent


def get_scoped_saved_outputs(client, offset=0, limit=20, sort_by="newest", scope=None):
    """List only exported receipts visible through explicit review or collection authority."""

    if (
        not isinstance(offset, int)
        or not isinstance(limit, int)
        or offset < 0
        or not 1 <= limit <= 50
    ):
        raise OuttakeError(
            "INVALID_INPUT",
            "Saved-output page bounds are invalid.",
            "Use offset >= 0 and limit 1..50.",
        )
    visible = []
    for receipt in client.saved_outputs(include_previews=False, sort_by=sort_by):
        try:
            _scoped_artifact(client, receipt["artifact_id"], scope)
        except OuttakeError as error:
            if error.code == "OUTPUT_SCOPE_DENIED":
                continue
            raise
        visible.append(_project(receipt))
    return {
        "schema_version": 1,
        "offset": offset,
        "limit": limit,
        "total": len(visible),
        "outputs": visible[offset : offset + limit],
    }


def open_scoped_saved_output(client, artifact_id, scope=None, request_id=None):
    """Attach one visible export to its canonical export workspace without re-rendering."""

    receipt, parent = _scoped_artifact(client, artifact_id, scope)
    payload = [artifact_id]
    mutation_owner = parent["id"] if parent else _SAVED_OUTPUT_SCOPE
    try:
        cached = _begin_mutation(client, mutation_owner, request_id, "open-output", payload)
    except OuttakeError as error:
        if error.code != "MUTATION_INCOMPLETE":
            raise
        with closing(_db(client)) as db:
            existing = db.execute(
                """SELECT * FROM reviews WHERE target_kind='artifact' AND target_id=?
                   AND scope=? ORDER BY created LIMIT 1""",
                (artifact_id, _SAVED_OUTPUT_SCOPE),
            ).fetchone()
        if not existing:
            raise
        return _finish_mutation(
            client,
            mutation_owner,
            request_id,
            {
                "schema_version": 1,
                "review_id": existing["id"],
                "target": {"kind": "artifact", "id": artifact_id},
                "workspace_id": existing["workspace_id"],
            },
        )
    if cached is not False and cached is not None:
        return cached
    plan_id = receipt["plan"]["id"]
    workspace_id = client.get_workspace(plan_id, artifact_id)["workspace_id"]
    parent_id = parent["id"] if parent else None
    # An explicitly allowed artifact review is already the export's canonical
    # workspace. Reuse it so opening through Saved Outputs cannot strand its
    # raw drafts in a parallel review identity.
    if parent and parent["target_kind"] == "artifact" and parent["target_id"] == artifact_id:
        return _finish_mutation(
            client,
            mutation_owner,
            request_id,
            {
                "schema_version": 1,
                "review_id": parent["id"],
                "target": {"kind": "artifact", "id": artifact_id},
                "workspace_id": workspace_id,
            },
        )
    with closing(_db(client)) as db, db:
        db.execute("BEGIN IMMEDIATE")
        existing = db.execute(
            """SELECT * FROM reviews WHERE target_kind='artifact' AND target_id=?
               AND scope=? ORDER BY created LIMIT 1""",
            (artifact_id, _SAVED_OUTPUT_SCOPE),
        ).fetchone()
        if existing:
            review_id = existing["id"]
        else:
            review_id = _id("review")
            db.execute(
                """INSERT INTO reviews
                   (id,target_kind,target_id,workspace_id,scope,view,view_version,source_ids,parent_review_id,created)
                   VALUES (?, 'artifact', ?, ?, ?, ?, 1, '[]', ?, ?)""",
                (
                    review_id,
                    artifact_id,
                    workspace_id,
                    _SAVED_OUTPUT_SCOPE,
                    _json({"plan_id": plan_id}),
                    parent_id,
                    time.time(),
                ),
            )
    result = {
        "schema_version": 1,
        "review_id": review_id,
        "target": {"kind": "artifact", "id": artifact_id},
        "workspace_id": workspace_id,
    }
    return _finish_mutation(client, mutation_owner, request_id, result)


def _scoped_output_mutation(
    client, review_id, artifact_id, action, payload, expected_plan_id, scope, request_id
):
    _review(client, review_id, scope)
    try:
        cached = _begin_mutation(client, review_id, request_id, action, payload)
    except OuttakeError as error:
        if error.code != "MUTATION_INCOMPLETE":
            raise
        raise
    if cached is not False and cached is not None:
        return True, cached
    receipt, _ = _scoped_artifact(client, artifact_id, scope)
    return False, receipt


def rename_scoped_saved_output(
    client, review_id, artifact_id, title, expected_plan_id=None, scope=None, request_id=None
):
    if not isinstance(expected_plan_id, str) or not re.fullmatch(
        r"plan_[a-f0-9]{32}", expected_plan_id
    ):
        raise OuttakeError(
            "INVALID_TARGET",
            "Saved-output rename needs the exact displayed plan identity.",
            "Refresh the saved-output card and supply its plan ID.",
        )
    complete, receipt = _scoped_output_mutation(
        client,
        review_id,
        artifact_id,
        "rename-output",
        [artifact_id, expected_plan_id, title],
        expected_plan_id,
        scope,
        request_id,
    )
    if complete:
        return receipt
    result = client.rename_output(artifact_id, title, expected_plan_id)
    return _finish_mutation(client, review_id, request_id, result)


def delete_scoped_saved_output(
    client, review_id, artifact_id, expected_plan_id=None, scope=None, request_id=None
):
    if not isinstance(expected_plan_id, str) or not re.fullmatch(
        r"plan_[a-f0-9]{32}", expected_plan_id
    ):
        raise OuttakeError(
            "INVALID_TARGET",
            "Saved-output deletion needs the exact displayed plan identity.",
            "Refresh the saved-output card and supply its plan ID.",
        )
    # A completed deletion has no surviving artifact with which to revalidate
    # root membership. Its exact retained outcome is safe to replay only to a
    # caller that still names this review directly; it discloses no material.
    if request_id is not None and (scope is None or review_id in scope):
        signature = hashlib.sha256(
            _json([review_id, "delete-output", [artifact_id, expected_plan_id]]).encode()
        ).hexdigest()
        with closing(_db(client)) as db:
            mutation = db.execute(
                "SELECT * FROM mutations WHERE review_id=? AND request_id=?",
                (review_id, request_id),
            ).fetchone()
        if mutation:
            if mutation["action"] != "delete-output" or mutation["signature"] != signature:
                raise OuttakeError(
                    "REQUEST_CONFLICT",
                    "Mutation request ID changed inputs.",
                    "Use a new request ID.",
                )
            if mutation["status"] == "completed":
                return json.loads(mutation["result"])
    complete, receipt = _scoped_output_mutation(
        client,
        review_id,
        artifact_id,
        "delete-output",
        [artifact_id, expected_plan_id],
        expected_plan_id,
        scope,
        request_id,
    )
    if complete:
        return receipt
    result = client.delete_output(artifact_id, expected_plan_id)
    return _finish_mutation(client, review_id, request_id, result)


def describe_scoped_saved_output_media(client, artifact_id, scope=None):
    receipt, _ = _scoped_artifact(client, artifact_id, scope)
    path = Path(receipt["artifact"])
    _, size = _read_verified_material(client, path, receipt["sha256"], int(receipt["bytes"]))
    mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    return {
        "schema_version": 1,
        "artifact_id": artifact_id,
        "mime": mime,
        "bytes": size,
        "sha256": receipt["sha256"],
        "max_chunk_bytes": _CHUNK,
        "resource_uri": f"outtake://saved-output/{artifact_id}/0",
    }


def read_scoped_saved_output_media(client, artifact_id, offset=0, length=_CHUNK, scope=None):
    if (
        not isinstance(offset, int)
        or not isinstance(length, int)
        or offset < 0
        or not 1 <= length <= _CHUNK
    ):
        raise OuttakeError("INVALID_INPUT", "Media range is invalid.", f"Use length 1..{_CHUNK}.")
    receipt, _ = _scoped_artifact(client, artifact_id, scope)
    data, size = _read_verified_material(
        client,
        Path(receipt["artifact"]),
        receipt["sha256"],
        int(receipt["bytes"]),
        offset,
        length,
    )
    return {
        "schema_version": 1,
        "artifact_id": artifact_id,
        "mime": mimetypes.guess_type(receipt["artifact"])[0] or "application/octet-stream",
        "offset": offset,
        "bytes": len(data),
        "total_bytes": size,
        "sha256": receipt["sha256"],
        "data_base64": base64.b64encode(data).decode("ascii"),
    }


def _display_plan(client, row):
    view = ReviewView.model_validate_json(row["view"])
    if view.plan_id:
        return client.get_plan(view.plan_id)
    if row["target_kind"] == "artifact":
        return client.get_plan(client.artifact(row["target_id"])["plan"]["id"])
    if row["target_kind"] == "plan":
        return client.get_plan(row["target_id"])
    return None


def _workspace_head(client, row):
    if not row["workspace_id"]:
        return None
    plan_id = _display_plan(client, row)
    if not plan_id:
        return None
    return client.get_workspace(
        plan_id.id, row["target_id"] if row["target_kind"] == "artifact" else None
    )


def review_snapshot(client, review_id, scope=None):
    row = _review(client, review_id, scope)
    view = ReviewView.model_validate_json(row["view"])
    result = {
        "schema_version": 1,
        "review_id": review_id,
        "target": {"kind": row["target_kind"], "id": row["target_id"]},
        "view_version": row["view_version"],
        "view": view.model_dump(exclude_none=True),
        "workspace_id": row["workspace_id"],
    }
    if view.finding_id:
        finding = _finding(client, row, view.finding_id)
        if len(_json(finding).encode()) > _SNAPSHOT_BYTES:
            result["finding"] = {
                "id": view.finding_id,
                "limited": True,
                "remediation": "Use get_review_finding_page for bounded candidates.",
            }
        else:
            result["finding"] = _project(finding)
    displayed = _display_plan(client, row)
    if displayed:
        result["displayed_plan"] = _project(displayed.model_dump(mode="json"))
        workspace = _workspace_head(client, row)
        if workspace:
            result["workspace"] = _project(workspace)
            result["head_plan_id"] = workspace["plan"]["id"]
    with closing(_db(client)) as db:
        drafts = db.execute(
            "SELECT base_plan_id, version FROM drafts WHERE review_id=? ORDER BY updated DESC LIMIT ?",
            (review_id, _SNAPSHOT_DRAFTS),
        ).fetchall()
        operations = db.execute(
            "SELECT * FROM operations WHERE review_id=? ORDER BY created DESC LIMIT ?",
            (review_id, _SNAPSHOT_OPERATIONS),
        ).fetchall()
    result["drafts"] = [
        {
            "base_plan_id": item["base_plan_id"],
            "version": item["version"],
        }
        for item in drafts
    ]
    if displayed:
        result["draft"] = get_review_draft(client, review_id, displayed.id, scope)
    result["operations"] = [
        {key: _project(value) for key, value in _operation(item).items() if key != "result"}
        for item in operations
    ]
    result["snapshot_limits"] = {
        "draft_summaries": _SNAPSHOT_DRAFTS,
        "operations": _SNAPSHOT_OPERATIONS,
        "finding_bytes": _SNAPSHOT_BYTES,
    }
    return result


def get_review_draft(client, review_id, base_plan_id, scope=None):
    """Explicit full read for one draft; snapshots deliberately expose only the displayed one."""
    _review(client, review_id, scope)
    with closing(_db(client)) as db:
        row = db.execute(
            "SELECT base_plan_id, version, draft FROM drafts WHERE review_id=? AND base_plan_id=?",
            (review_id, base_plan_id),
        ).fetchone()
    if not row:
        return None
    return {
        "base_plan_id": row["base_plan_id"],
        "version": row["version"],
        "value": json.loads(row["draft"]),
    }


def get_review_finding_page(client, review_id, finding_id, offset=0, limit=20, scope=None):
    row = _review(client, review_id, scope)
    if (
        not isinstance(offset, int)
        or not isinstance(limit, int)
        or offset < 0
        or not 1 <= limit <= 50
    ):
        raise OuttakeError(
            "INVALID_INPUT", "Finding page bounds are invalid.", "Use offset >= 0 and limit 1..50."
        )
    finding = _finding(client, row, finding_id)
    candidates = finding.get("candidates", [])
    return {
        "schema_version": 1,
        "finding_id": finding_id,
        "offset": offset,
        "total": len(candidates),
        "candidates": _project(candidates[offset : offset + limit]),
    }


def navigate_review(client, review_id, view, expected_version, scope=None, request_id=None):
    """Persist explicit semantic navigation; it never advances workspace heads."""
    row = _review(client, review_id, scope)
    if not isinstance(expected_version, int) or expected_version < 1:
        raise OuttakeError(
            "INVALID_INPUT", "Review version is invalid.", "Use review_snapshot view_version."
        )
    requested = ReviewView.model_validate(view)
    if requested.playhead is not None and not math.isfinite(requested.playhead):
        raise OuttakeError(
            "INVALID_INPUT", "Playhead must be finite.", "Use a source-relative finite time."
        )
    if requested.plan_id:
        plan = client.get_plan(requested.plan_id)
        if not _plan_in_review(client, row, plan.id):
            raise OuttakeError(
                "TARGET_SCOPE_DENIED",
                "Plan is outside this review.",
                "Navigate to a review lineage plan.",
            )
    finding = None
    if requested.finding_id:
        finding = _finding(client, row, requested.finding_id)
        candidates = {item.get("id") for item in finding.get("candidates", [])}
        if requested.candidate_id is not None and requested.candidate_id not in candidates:
            raise OuttakeError(
                "INVALID_TARGET",
                "Candidate does not belong to the displayed finding.",
                "Use a retained candidate identity from this finding.",
            )
    elif requested.candidate_id is not None:
        raise OuttakeError(
            "INVALID_TARGET",
            "Candidate navigation requires its finding identity.",
            "Set finding_id and candidate_id together.",
        )
    if requested.plan_id:
        plan = client.get_plan(requested.plan_id)
        if requested.candidate_id and (
            plan.finding_id != requested.finding_id or plan.candidate_id != requested.candidate_id
        ):
            raise OuttakeError(
                "INVALID_TARGET",
                "Plan does not represent the requested finding candidate.",
                "Navigate to matching retained plan/candidate identities.",
            )
        if requested.cue_id is not None and requested.cue_id not in {cue.id for cue in plan.cues}:
            raise OuttakeError(
                "INVALID_TARGET",
                "Cue is not part of the displayed plan.",
                "Use a cue identity from the plan.",
            )
    elif requested.cue_id is not None:
        raise OuttakeError(
            "INVALID_TARGET", "Cue navigation requires plan_id.", "Set plan_id and cue_id together."
        )
    if requested.playhead is not None and requested.plan_id:
        plan = client.get_plan(requested.plan_id)
        if requested.playhead > plan.source.duration:
            raise OuttakeError(
                "INVALID_INPUT",
                "Playhead is outside source duration.",
                "Use a source-relative time.",
            )
    signature = _json(["navigate", requested.model_dump(exclude_none=True), expected_version])
    if request_id is not None and (
        not isinstance(request_id, str) or not request_id or len(request_id) > 80
    ):
        raise OuttakeError(
            "INVALID_INPUT", "Invalid request ID.", "Use a stable nonempty request ID."
        )
    result = {
        "schema_version": 1,
        "review_id": review_id,
        "request_id": request_id,
        "view": requested.model_dump(exclude_none=True),
        "view_version": expected_version + 1,
        "signature": hashlib.sha256(signature.encode()).hexdigest(),
    }
    with closing(_db(client)) as db, db:
        db.execute("BEGIN IMMEDIATE")
        if request_id is not None:
            previous = db.execute(
                "SELECT * FROM mutations WHERE review_id=? AND request_id=?",
                (review_id, request_id),
            ).fetchone()
            if previous:
                if previous["action"] != "navigate" or previous["signature"] != signature:
                    raise OuttakeError(
                        "REQUEST_CONFLICT",
                        "Navigation request ID changed inputs.",
                        "Retry the original request or use a new request ID for new intent.",
                    )
                return json.loads(previous["result"])
        current = db.execute("SELECT * FROM reviews WHERE id=?", (review_id,)).fetchone()
        if current["view_version"] != expected_version:
            raise OuttakeError(
                "REVIEW_CONFLICT",
                "Review navigation changed.",
                "Read review_snapshot and navigate explicitly again.",
            )
        db.execute(
            "UPDATE reviews SET view=?, view_version=view_version+1 WHERE id=?",
            (_json(requested.model_dump(exclude_none=True)), review_id),
        )
        if request_id is not None:
            db.execute(
                "INSERT INTO mutations VALUES (?, ?, ?, 'navigate', 'completed', ?, ?)",
                (review_id, request_id, signature, _json(result), time.time()),
            )
    return result


def _draft_signature(base_plan_id, draft, expected_version):
    return hashlib.sha256(
        _json(["draft", base_plan_id, draft, expected_version]).encode()
    ).hexdigest()


def save_review_draft(
    client, review_id, base_plan_id, draft, expected_version, scope=None, request_id=None
):
    """CAS-save bounded raw input per review *and exact base plan* without applying it."""
    row = _review(client, review_id, scope)
    if not isinstance(draft, dict) or not isinstance(expected_version, int) or expected_version < 0:
        raise OuttakeError(
            "INVALID_INPUT", "Draft and version are invalid.", "Supply an object and version."
        )
    if len(_json(draft).encode()) > _MAX_DRAFT_BYTES:
        raise OuttakeError(
            "RESOURCE_LIMIT", "Raw draft exceeds retained size limit.", "Save a smaller draft."
        )
    if not isinstance(base_plan_id, str):
        raise OuttakeError(
            "INVALID_INPUT", "Draft needs an exact base plan identity.", "Use displayed_plan.id."
        )
    client.get_plan(base_plan_id)
    if not _plan_in_review(client, row, base_plan_id):
        raise OuttakeError(
            "TARGET_SCOPE_DENIED",
            "Draft base is outside this review workspace.",
            "Use the displayed review plan.",
        )
    signature = _draft_signature(base_plan_id, draft, expected_version)
    with closing(_db(client)) as db, db:
        db.execute("BEGIN IMMEDIATE")
        if request_id is not None:
            mutation = db.execute(
                "SELECT * FROM mutations WHERE review_id=? AND request_id=?",
                (review_id, request_id),
            ).fetchone()
            if mutation:
                if mutation["signature"] != signature or mutation["action"] != "draft":
                    raise OuttakeError(
                        "REQUEST_CONFLICT",
                        "Draft request ID changed inputs.",
                        "Use a new request ID.",
                    )
                if mutation["status"] == "completed":
                    return json.loads(mutation["result"])
                raise OuttakeError(
                    "MUTATION_INCOMPLETE",
                    "Prior draft request is uncertain.",
                    "Read the exact draft; do not replay changed input.",
                )
        existing = db.execute(
            "SELECT * FROM drafts WHERE review_id=? AND base_plan_id=?", (review_id, base_plan_id)
        ).fetchone()
        if request_id and existing and existing["request_id"] == request_id:
            if existing["signature"] != signature:
                raise OuttakeError(
                    "REQUEST_CONFLICT", "Draft request ID changed inputs.", "Use a new request ID."
                )
            return {
                "schema_version": 1,
                "review_id": review_id,
                "base_plan_id": base_plan_id,
                "version": existing["version"],
                "request_id": request_id,
            }
        current = existing["version"] if existing else 0
        if current != expected_version:
            raise OuttakeError(
                "DRAFT_CONFLICT",
                "A newer raw draft is retained.",
                "Read review_snapshot and merge explicitly.",
            )
        db.execute(
            """INSERT OR REPLACE INTO drafts
               (review_id, base_plan_id, version, request_id, signature, draft, updated)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                review_id,
                base_plan_id,
                current + 1,
                request_id,
                signature,
                _json(draft),
                time.time(),
            ),
        )
        result = {
            "schema_version": 1,
            "review_id": review_id,
            "base_plan_id": base_plan_id,
            "version": current + 1,
            "request_id": request_id,
        }
        if request_id is not None:
            db.execute(
                "INSERT INTO mutations VALUES (?, ?, ?, 'draft', 'completed', ?, ?)",
                (review_id, request_id, signature, _json(result), time.time()),
            )
    return result


def _plan_in_review(client, row, plan_id):
    """Only explicit workspace history is authority; plan ancestry alone is not."""
    if row["workspace_id"]:
        from .workspace import workspace_contains

        return workspace_contains(client, row["workspace_id"], plan_id)
    return row["target_kind"] == "plan" and row["target_id"] == plan_id


def _begin_mutation(client, review_id, request_id, action, payload):
    """Return retained exact mutation outcome or reserve a new uncertain-safe effect."""
    if request_id is None:
        return None
    if not isinstance(request_id, str) or not request_id or len(request_id) > 80:
        raise OuttakeError(
            "INVALID_INPUT", "Mutation request ID is invalid.", "Use a stable nonempty request ID."
        )
    signature = hashlib.sha256(_json([review_id, action, payload]).encode()).hexdigest()
    with closing(_db(client)) as db, db:
        db.execute("BEGIN IMMEDIATE")
        existing = db.execute(
            "SELECT * FROM mutations WHERE review_id=? AND request_id=?", (review_id, request_id)
        ).fetchone()
        if existing:
            if existing["signature"] != signature:
                raise OuttakeError(
                    "REQUEST_CONFLICT",
                    "Mutation request ID changed inputs.",
                    "Use a new request ID.",
                )
            if existing["status"] == "completed":
                return json.loads(existing["result"])
            raise OuttakeError(
                "MUTATION_INCOMPLETE",
                "A prior mutation response is uncertain.",
                "Inspect review state; do not replay this request ID.",
            )
        db.execute(
            "INSERT INTO mutations VALUES (?,?,?,?, 'accepted',NULL,?)",
            (review_id, request_id, signature, action, time.time()),
        )
    return False


def _finish_mutation(client, review_id, request_id, result):
    if request_id is None:
        return result
    with closing(_db(client)) as db, db:
        db.execute(
            "UPDATE mutations SET status='completed',result=? WHERE review_id=? AND request_id=?",
            (_json(result), review_id, request_id),
        )
    return result


def apply_review_changes(client, review_id, plan_id, changes, scope=None, request_id=None):
    row = _review(client, review_id, scope)
    if not row["workspace_id"] or not isinstance(plan_id, str):
        raise OuttakeError(
            "INVALID_TARGET", "Review has no editable plan.", "Select a candidate first."
        )
    base = client.get_plan(plan_id)
    if not _plan_in_review(client, row, base.id):
        raise OuttakeError(
            "TARGET_SCOPE_DENIED", "Plan is outside this review.", "Use displayed_plan.id."
        )
    mutation_signature = hashlib.sha256(
        _json([review_id, "apply", [plan_id, changes]]).encode()
    ).hexdigest()
    if request_id is not None:
        from .workspace import workspace_mutation

        recovered = workspace_mutation(client, row["workspace_id"], request_id, mutation_signature)
        if recovered is not None:
            result = {
                "schema_version": 1,
                "review_id": review_id,
                "request_id": request_id,
                "plan": recovered.model_dump(mode="json"),
            }
            return _finish_mutation(client, review_id, request_id, result)
    cached = _begin_mutation(client, review_id, request_id, "apply", [plan_id, changes])
    if cached is not False and cached is not None:
        return cached
    from .workspace import save_workspace

    revised = save_workspace(
        client,
        row["workspace_id"],
        base,
        changes,
        request_id=request_id,
        signature=mutation_signature if request_id is not None else None,
    )
    return _finish_mutation(
        client,
        review_id,
        request_id,
        {
            "schema_version": 1,
            "review_id": review_id,
            "request_id": request_id,
            "plan": revised.model_dump(mode="json"),
        },
    )


def select_review_candidate(
    client,
    review_id,
    finding_id,
    candidate_id,
    format="mp4",
    profile="share",
    scope=None,
    request_id=None,
):
    row = _review(client, review_id, scope)
    payload = [finding_id, candidate_id, format, profile]
    plan = None
    if request_id is None:
        view = ReviewView.model_validate_json(row["view"])
        if not view.finding_id or view.finding_id != finding_id:
            raise OuttakeError(
                "INVALID_TARGET",
                "Candidate is outside this review finding.",
                "Use the displayed finding.",
            )
        plan = client.select(finding_id, candidate_id, format, profile)
        workspace_id = client.get_workspace(plan.id)["workspace_id"]
        with closing(_db(client)) as db, db:
            db.execute(
                """UPDATE reviews SET target_kind='plan', target_id=?, workspace_id=?, view=?,
                   view_version=view_version+1 WHERE id=?""",
                (
                    plan.id,
                    workspace_id,
                    _json(ReviewView(plan_id=plan.id, candidate_id=candidate_id).model_dump()),
                    review_id,
                ),
            )
        return {
            "schema_version": 1,
            "review_id": review_id,
            "request_id": None,
            "selected_plan_id": plan.id,
            "workspace_id": workspace_id,
        }

    signature = hashlib.sha256(_json([review_id, "select", payload]).encode()).hexdigest()
    with closing(_db(client)) as db, db:
        db.execute("BEGIN IMMEDIATE")
        existing = db.execute(
            "SELECT * FROM selections WHERE review_id=? AND request_id=?", (review_id, request_id)
        ).fetchone()
        if existing:
            if existing["signature"] != signature:
                raise OuttakeError(
                    "REQUEST_CONFLICT",
                    "Mutation request ID changed inputs.",
                    "Use a new request ID.",
                )
            if existing["status"] == "completed":
                return json.loads(existing["result"])
            plan_id = existing["plan_id"]
            try:
                plan = client.get_plan(plan_id)
            except OuttakeError as exc:
                raise OuttakeError(
                    "MUTATION_INCOMPLETE",
                    "Selection admission exists but its owned plan was not retained.",
                    "Inspect this request; do not replay it with a new plan.",
                ) from exc
        else:
            plan_id = _id("plan")
            db.execute(
                """INSERT INTO selections
                   (review_id,request_id,signature,finding_id,candidate_id,format,profile,plan_id,view_version,status,created)
                   VALUES (?,?,?,?,?,?,?,?,?,'accepted',?)""",
                (
                    review_id,
                    request_id,
                    signature,
                    finding_id,
                    candidate_id,
                    format,
                    profile,
                    plan_id,
                    row["view_version"],
                    time.time(),
                ),
            )
            db.execute(
                "INSERT INTO mutations VALUES (?,?,?,?, 'accepted',NULL,?)",
                (review_id, request_id, signature, "select", time.time()),
            )
            plan = None

    if plan is None:
        view = ReviewView.model_validate_json(row["view"])
        if not view.finding_id or view.finding_id != finding_id:
            raise OuttakeError(
                "INVALID_TARGET",
                "Candidate is outside this review finding.",
                "Use the displayed finding.",
            )
        # This is the sole execution for the preassigned plan ID. A retry never
        # invokes select again: it either finalizes this exact plan or stays explicit.
        plan = client.select(finding_id, candidate_id, format, profile, plan_id=plan_id)
    workspace_id = client.get_workspace(plan.id)["workspace_id"]
    with closing(_db(client)) as db, db:
        db.execute("BEGIN IMMEDIATE")
        binding = db.execute(
            "SELECT * FROM selections WHERE review_id=? AND request_id=?", (review_id, request_id)
        ).fetchone()
        if binding["status"] == "completed":
            return json.loads(binding["result"])
        current = db.execute("SELECT * FROM reviews WHERE id=?", (review_id,)).fetchone()
        view_updated = (
            current["view_version"] == binding["view_version"]
            and ReviewView.model_validate_json(current["view"]).finding_id == finding_id
        )
        if view_updated:
            db.execute(
                """UPDATE reviews SET target_kind='plan', target_id=?, workspace_id=?, view=?,
                   view_version=view_version+1 WHERE id=?""",
                (
                    plan.id,
                    workspace_id,
                    _json(ReviewView(plan_id=plan.id, candidate_id=candidate_id).model_dump()),
                    review_id,
                ),
            )
        result = {
            "schema_version": 1,
            "review_id": review_id,
            "request_id": request_id,
            "selected_plan_id": plan.id,
            "workspace_id": workspace_id,
            "view_updated": view_updated,
        }
        db.execute(
            "UPDATE selections SET status='completed',result=? WHERE review_id=? AND request_id=?",
            (_json(result), review_id, request_id),
        )
        db.execute(
            "UPDATE mutations SET status='completed',result=? WHERE review_id=? AND request_id=?",
            (_json(result), review_id, request_id),
        )
    return result


def _normalize_args(client, row, operation, arguments):
    if operation in {"preview", "render"}:
        if not isinstance(arguments, dict) or set(arguments) - {"plan_id", "plan"}:
            raise OuttakeError("INVALID_INPUT", "Render arguments are invalid.", "Use {plan_id}.")
        plan_id = arguments.get("plan_id")
        if plan_id is None and isinstance(arguments.get("plan"), dict):
            plan_id = arguments["plan"].get("id")
        if not isinstance(plan_id, str):
            raise OuttakeError(
                "INVALID_INPUT", "Render needs retained plan_id.", "Use displayed_plan.id."
            )
        plan = client.get_plan(plan_id)
        if row and not _plan_in_review(client, row, plan.id):
            raise OuttakeError(
                "TARGET_SCOPE_DENIED", "Plan is outside this review.", "Use displayed_plan.id."
            )
        return {"plan_id": plan.id}
    if operation in {"find", "make"}:
        if not isinstance(arguments, dict) or set(arguments) - {"request", "format", "profile"}:
            raise OuttakeError(
                "INVALID_INPUT",
                "Model arguments are invalid.",
                "Use request and optional format/profile.",
            )
        request = FindRequest.model_validate(arguments.get("request"))
        profile = arguments.get("profile", "share")
        format = arguments.get("format", "mp4")
        if profile not in {"mobile", "share", "editing"} or format not in {"mp4", "gif", "png"}:
            raise OuttakeError(
                "INVALID_INPUT",
                "Unsupported output choice.",
                "Use mp4/gif/png and a known profile.",
            )
        if row:
            allowed = set(json.loads(row["source_ids"]))
            if (
                request.scope is not None
                or not request.source_ids
                or not set(request.source_ids).issubset(allowed)
            ):
                raise OuttakeError(
                    "MODEL_SCOPE_DENIED",
                    "Portable model continuation cannot expand the reviewed source scope.",
                    "Use source IDs already approved by the reviewed finding and no new scope.",
                )
        return {"request": request.model_dump(mode="json"), "format": format, "profile": profile}
    raise OuttakeError("INVALID_INPUT", "Unknown operation.", "Use preview, render, find or make.")


def _signature(review_id, operation, arguments, settings, grant):
    return hashlib.sha256(
        _json([review_id, operation, arguments, settings, grant]).encode()
    ).hexdigest()


def admit_operation(
    client, request_id, operation, arguments, grant=None, *, allow_models=False, review_id=None
):
    """Durably admit typed normalized work before any worker starts."""
    if operation not in {"preview", "render", "find", "make"}:
        raise OuttakeError(
            "INVALID_INPUT", "Unsupported retained operation.", "Use preview, render, find or make."
        )
    if not isinstance(request_id, str) or not request_id or len(request_id) > 80:
        raise OuttakeError(
            "INVALID_INPUT", "Request ID is invalid.", "Use a stable nonempty request ID."
        )
    row = _review(client, review_id) if review_id else None
    if operation in {"find", "make"} and not allow_models:
        raise OuttakeError(
            "MODEL_SERVER_DISABLED",
            "Portable-server model work is not enabled.",
            "Restart with --allow-models and submit an authorized grant.",
        )
    normalized = _normalize_args(client, row, operation, arguments)
    model_grant = (
        ModelGrant.model_validate(grant).model_dump(mode="json") if grant is not None else None
    )
    if operation in {"find", "make"} and model_grant is None:
        raise OuttakeError(
            "PROVIDER_NOT_AUTHORIZED",
            "Model work needs ModelGrant.",
            "Supply explicit provider authority.",
        )
    settings = _safe_settings(client)
    signature = _signature(review_id, operation, normalized, settings, model_grant)
    output_id = _id("export") if operation in {"preview", "render", "make"} else None
    now = time.time()
    with closing(_db(client)) as db, db:
        db.execute("BEGIN IMMEDIATE")
        existing = db.execute(
            "SELECT * FROM operations WHERE request_id=?", (request_id,)
        ).fetchone()
        if existing:
            if existing["signature"] != signature:
                raise OuttakeError(
                    "REQUEST_CONFLICT",
                    "Request ID has a different operation, inputs, or authority.",
                    "Use a new request ID.",
                )
            return _operation(existing)
        active = db.execute(
            "SELECT count(*) FROM operations WHERE status IN ('accepted','running','cancelling')"
        ).fetchone()[0]
        if active >= _MAX_WORKERS:
            raise OuttakeError(
                "RESOURCE_LIMIT",
                "Retained work concurrency is full.",
                "Wait for a current operation.",
            )
        operation_id = _id("operation")
        db.execute(
            """INSERT INTO operations
               (id,request_id,signature,operation,arguments,settings,grant,output_id,status,review_id,created,updated)
               VALUES (?,?,?,?,?,?,?,?, 'accepted',?,?,?)""",
            (
                operation_id,
                request_id,
                signature,
                operation,
                _json(normalized),
                _json(settings),
                _json(model_grant) if model_grant else None,
                output_id,
                review_id,
                now,
                now,
            ),
        )
    try:
        _spawn(client, operation_id)
    except OSError:
        with closing(_db(client)) as db, db:
            db.execute(
                "UPDATE operations SET status='interrupted', updated=? WHERE id=?",
                (time.time(), operation_id),
            )
        raise OuttakeError(
            "OPERATION_INTERRUPTED",
            "Worker could not start after admission.",
            "Use get-operation; it was not replayed.",
        )
    return _operation_record(operation_id, request_id, operation, output_id, "accepted")


def _spawn(client, operation_id):
    with open(os.devnull, "wb") as sink:
        subprocess.Popen(
            [
                sys.executable,
                "-m",
                "outtake.worker",
                "--state",
                str(client.state),
                "--operation",
                operation_id,
            ],
            stdin=subprocess.DEVNULL,
            stdout=sink,
            stderr=sink,
            start_new_session=True,
            close_fds=True,
        )


def _operation_record(operation_id, request_id, operation, output_id, status):
    return {
        "schema_version": 1,
        "operation_id": operation_id,
        "request_id": request_id,
        "operation": operation,
        "status": status,
        "output_id": output_id,
    }


def _operation(row):
    result = _operation_record(
        row["id"], row["request_id"], row["operation"], row["output_id"], row["status"]
    )
    result["cancel_requested"] = bool(row["cancel_requested"])
    if row["result"]:
        raw = row["result"]
        if len(raw.encode()) > _SNAPSHOT_BYTES:
            result["result"] = {
                "limited": True,
                "bytes": len(raw.encode()),
                "remediation": "Use get_operation_result_page for explicit bounded result bytes.",
            }
        else:
            result["result"] = json.loads(raw)
    return result


def get_operation_result_page(
    client, operation_id, offset=0, limit=_RESULT_PAGE_BYTES, review_id=None
):
    """Explicit bounded retrieval for an operation result too large for an operation summary."""
    if (
        not isinstance(offset, int)
        or not isinstance(limit, int)
        or offset < 0
        or not 1 <= limit <= _RESULT_PAGE_BYTES
    ):
        raise OuttakeError(
            "INVALID_INPUT",
            "Operation result page bounds are invalid.",
            f"Use offset >= 0 and limit 1..{_RESULT_PAGE_BYTES}.",
        )
    with closing(_db(client)) as db:
        row = db.execute("SELECT * FROM operations WHERE id=?", (operation_id,)).fetchone()
    if not row or not row["result"]:
        raise OuttakeError(
            "OPERATION_RESULT_MISSING",
            "Operation has no retained terminal result.",
            "Read operation lifecycle or recover it first.",
        )
    if review_id is not None and row["review_id"] != review_id:
        raise OuttakeError(
            "OPERATION_SCOPE_DENIED", "Operation is outside this review.", "Use its owning review."
        )
    data = _json(_project(json.loads(row["result"]))).encode()
    if offset >= len(data):
        raise OuttakeError(
            "INVALID_RANGE", "Offset is beyond operation result.", "Use returned total_bytes."
        )
    chunk = data[offset : offset + limit]
    return {
        "schema_version": 1,
        "operation_id": operation_id,
        "offset": offset,
        "bytes": len(chunk),
        "total_bytes": len(data),
        "data_base64": base64.b64encode(chunk).decode("ascii"),
    }


def get_operation(client, operation_id, review_id=None):
    with closing(_db(client)) as db:
        row = db.execute("SELECT * FROM operations WHERE id=?", (operation_id,)).fetchone()
    if not row:
        raise OuttakeError(
            "OPERATION_MISSING", "Operation is not retained.", "Use its admission identity."
        )
    if review_id is not None and row["review_id"] != review_id:
        raise OuttakeError(
            "OPERATION_SCOPE_DENIED", "Operation is outside this review.", "Use its owning review."
        )
    return _operation(row)


def cancel_operation(client, operation_id, review_id=None):
    with closing(_db(client)) as db, db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT * FROM operations WHERE id=?", (operation_id,)).fetchone()
        if not row:
            raise OuttakeError(
                "OPERATION_MISSING", "Operation is not retained.", "Use its admission identity."
            )
        if review_id is not None and row["review_id"] != review_id:
            raise OuttakeError(
                "OPERATION_SCOPE_DENIED",
                "Operation is outside this review.",
                "Use its owning review.",
            )
        if row["status"] == "accepted":
            result = OuttakeError(
                "CANCELLED",
                "Cancellation took effect before a worker claimed this operation.",
                "No new artifact was published.",
            ).result()
            db.execute(
                "UPDATE operations SET cancel_requested=1,status='cancelled',result=?,updated=? WHERE id=?",
                (_json(result), time.time(), operation_id),
            )
        elif row["status"] not in _TERMINAL:
            db.execute(
                "UPDATE operations SET cancel_requested=1,status='cancelling',updated=? WHERE id=?",
                (time.time(), operation_id),
            )
    return get_operation(client, operation_id, review_id)


def recover_operations(client):
    """Recover only a known committed receipt; never resume or replay admitted work."""
    now, recovered = time.time(), []
    with closing(_db(client)) as db, db:
        db.execute("BEGIN IMMEDIATE")
        rows = db.execute(
            "SELECT * FROM operations WHERE status NOT IN ('completed','failed','cancelled','interrupted','uncertain')"
        ).fetchall()
        for row in rows:
            if row["output_id"]:
                try:
                    receipt = client.artifact(row["output_id"])
                except OuttakeError:
                    receipt = None
                if receipt:
                    result = {"schema_version": 1, "status": "ready", **receipt}
                    db.execute(
                        "UPDATE operations SET status='completed',result=?,lease_token=NULL,updated=? WHERE id=?",
                        (_json(result), now, row["id"]),
                    )
                    recovered.append({"operation_id": row["id"], "status": "completed"})
                    continue
            if row["lease_until"] is None or row["lease_until"] < now:
                db.execute(
                    "UPDATE operations SET status='interrupted',lease_token=NULL,updated=? WHERE id=?",
                    (now, row["id"]),
                )
                recovered.append({"operation_id": row["id"], "status": "interrupted"})
    return {"schema_version": 1, "recovered": recovered, "replayed": False}


def _claim(state, operation_id):
    with closing(sqlite3.connect(Path(state) / "collaboration.sqlite3", timeout=30)) as db, db:
        db.row_factory = sqlite3.Row
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT * FROM operations WHERE id=?", (operation_id,)).fetchone()
        if not row or row["status"] in _TERMINAL or row["cancel_requested"]:
            return None
        now, token = time.time(), uuid.uuid4().hex
        # Only recovery can classify a lost owner.  A fresh worker must never take
        # an expired lease because the old process could still later reach publish.
        if row["lease_token"]:
            return None
        db.execute(
            "UPDATE operations SET status='running',lease_token=?,lease_until=?,updated=? WHERE id=?",
            (token, now + 3900, now, operation_id),
        )
        return dict(
            db.execute("SELECT * FROM operations WHERE id=?", (operation_id,)).fetchone()
        ), token


def _owned(state, operation_id, token):
    with closing(sqlite3.connect(Path(state) / "collaboration.sqlite3", timeout=30)) as db:
        row = db.execute(
            "SELECT cancel_requested,lease_token,lease_until FROM operations WHERE id=?",
            (operation_id,),
        ).fetchone()
    return bool(row and not row[0] and row[1] == token and row[2] >= time.time())


def _complete(state, operation_id, token, result):
    with closing(sqlite3.connect(Path(state) / "collaboration.sqlite3", timeout=30)) as db, db:
        db.row_factory = sqlite3.Row
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT * FROM operations WHERE id=?", (operation_id,)).fetchone()
        if not row or row["lease_token"] != token:
            return False
        lifecycle = (
            "cancelled"
            if result.get("status") == "cancelled"
            else "failed"
            if result.get("status") == "failed"
            else "completed"
        )
        db.execute(
            "UPDATE operations SET status=?,result=?,lease_token=NULL,updated=? WHERE id=?",
            (lifecycle, _json(result), time.time(), operation_id),
        )
    return True


def _publish(state, operation_id, token, stage, destination):
    with closing(sqlite3.connect(Path(state) / "collaboration.sqlite3", timeout=30)) as db, db:
        db.row_factory = sqlite3.Row
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT * FROM operations WHERE id=?", (operation_id,)).fetchone()
        if (
            not row
            or row["lease_token"] != token
            or row["cancel_requested"]
            or row["lease_until"] < time.time()
        ):
            raise OuttakeError(
                "CANCELLED",
                "Cancellation or lease loss won before publication.",
                "No artifact was published.",
            )
        os.rename(stage, destination)


def run_worker(state, operation_id):
    claimed = _claim(state, operation_id)
    if not claimed:
        return
    row, token = claimed
    from .lib import Outtake
    from .models import Settings

    settings = json.loads(row["settings"])
    settings["state_root"] = str(state)
    client = Outtake(Settings.model_validate(settings))
    arguments = json.loads(row["arguments"])

    def cancelled():
        return not _owned(state, operation_id, token)

    try:
        if row["operation"] in {"render", "preview"}:
            result = client._render_retained(
                client.get_plan(arguments["plan_id"]),
                row["output_id"],
                row["operation"],
                lambda: not cancelled(),
                lambda stage, destination: _publish(state, operation_id, token, stage, destination),
            )
        else:
            # Nested intelligence identities are operation-owned so a direct find/make
            # using the caller's request_id cannot consume or collide with this admission.
            request = FindRequest.model_validate(arguments["request"]).model_copy(
                update={"request_id": f"op_{row['id'].split('_', 1)[1]}"}
            )
            grant = ModelGrant.model_validate_json(row["grant"])
            finding = client.find(request, grant, cancelled=cancelled)
            if (
                row["operation"] == "make"
                and finding.get("status") == "needs_selection"
                and len(finding.get("candidates", [])) == 1
            ):
                plan = client.select(
                    finding["id"],
                    finding["candidates"][0]["id"],
                    arguments["format"],
                    arguments["profile"],
                )
                result = client._render_retained(
                    plan,
                    row["output_id"],
                    "render",
                    lambda: not cancelled(),
                    lambda stage, destination: _publish(
                        state, operation_id, token, stage, destination
                    ),
                )
                result["finding_id"] = finding["id"]
            else:
                result = finding
    except OuttakeError as exc:
        result = exc.result()
    except BaseException:
        result = OuttakeError(
            "OPERATION_INTERRUPTED",
            "Owned worker stopped before a known outcome.",
            "Use get-operation and recover; do not blindly replay this request.",
        ).result()
        result["status"] = "interrupted"
    _complete(state, operation_id, token, result)


def _project(value):
    forbidden = {
        "path",
        "image",
        "artifact",
        "receipt",
        "source_roots",
        "output_root",
        "state_root",
        "token",
        "credentials",
    }
    if isinstance(value, dict):
        if {"code", "message", "remediation"}.issubset(value):
            return {
                key: _project(value[key])
                for key in ("code", "remediation", "identity")
                if key in value
            }
        return {
            key: _project(item)
            for key, item in value.items()
            if key not in forbidden and not key.endswith("_path") and key != "error_detail"
        }
    if isinstance(value, list):
        return [_project(item) for item in value]
    return value


def public_projection(value):
    return _project(value)


def _allowed_evidence(client, row):
    plan = _display_plan(client, row)
    if plan:
        return set(plan.evidence_ids) | (
            {plan.caption_evidence_id} if plan.caption_evidence_id else set()
        )
    view = ReviewView.model_validate_json(row["view"])
    if view.finding_id:
        finding = _finding(client, row, view.finding_id)
        return {
            eid
            for candidate in finding.get("candidates", [])
            for eid in candidate.get("evidence_ids", [])
        }
    return set()


def _material(client, row, kind, identity, index):
    if kind == "artifact":
        receipt = client.artifact(identity)
        if not _artifact_in_review(client, row, identity):
            raise OuttakeError(
                "MEDIA_SCOPE_DENIED",
                "Artifact is outside explicit review scope.",
                "Open its explicit review.",
            )
        return Path(receipt["artifact"]), receipt["sha256"], int(receipt["bytes"])
    if (
        kind != "frame"
        or identity not in _allowed_evidence(client, row)
        or not isinstance(index, int)
    ):
        raise OuttakeError(
            "MEDIA_SCOPE_DENIED",
            "Material is outside review scope.",
            "Use retained review evidence.",
        )
    evidence = client.get_evidence(identity)
    if evidence.get("kind") != "frames" or not 0 <= index < len(evidence["frames"]):
        raise OuttakeError(
            "INVALID_MEDIA", "Unknown evidence frame.", "Use a frame evidence ID and valid index."
        )
    frame = evidence["frames"][index]
    # Frame records deliberately call this field image; it is a local path and never projected.
    try:
        path = Path(frame["image"])
        size = path.stat().st_size
    except OSError as exc:
        raise OuttakeError(
            "MATERIAL_MISSING",
            "Retained evidence material is unavailable.",
            "Observe the source again.",
        ) from exc
    return path, frame["sha256"], size


def _read_verified_material(client, path, digest, expected_size, offset=0, length=0):
    """Hash incrementally and read one bounded chunk through the same open descriptor."""
    try:
        lexical = path.absolute()
        roots = (client.output.absolute(), (client.state / "frames").absolute())
        root = next((item for item in roots if lexical.is_relative_to(item)), None)
        if root is None:
            raise OuttakeError(
                "MEDIA_SCOPE_DENIED",
                "Material is outside approved retained roots.",
                "Use a descriptor.",
            )
        probe = lexical
        while probe != root:
            if probe.is_symlink():
                raise OuttakeError(
                    "MEDIA_SCOPE_DENIED",
                    "Linked material cannot be disclosed.",
                    "Use published material.",
                )
            probe = probe.parent
        if path.is_symlink():
            raise OuttakeError(
                "MEDIA_SCOPE_DENIED",
                "Linked material cannot be disclosed.",
                "Use published material.",
            )
        with path.open("rb") as source:
            before = os.fstat(source.fileno())
            if not stat.S_ISREG(before.st_mode):
                raise OuttakeError(
                    "MEDIA_SCOPE_DENIED", "Material is not a regular file.", "Use a descriptor."
                )
            hasher = hashlib.sha256()
            while chunk := source.read(1024 * 1024):
                hasher.update(chunk)
            after = os.fstat(source.fileno())
            if before.st_size != after.st_size or before.st_mtime_ns != after.st_mtime_ns:
                raise OuttakeError(
                    "MATERIAL_CHANGED", "Material changed while checked.", "Describe it again."
                )
            if before.st_size != expected_size or hasher.hexdigest() != digest:
                raise OuttakeError(
                    "MATERIAL_CHANGED", "Material changed after receipt.", "Describe it again."
                )
            if length:
                if offset >= before.st_size:
                    raise OuttakeError(
                        "INVALID_RANGE",
                        "Offset is beyond retained material.",
                        "Use descriptor byte size.",
                    )
                source.seek(offset)
                return source.read(min(length, before.st_size - offset)), before.st_size
            return b"", before.st_size
    except OuttakeError:
        raise
    except OSError as exc:
        raise OuttakeError(
            "MATERIAL_MISSING", "Retained material cannot be read.", "Regenerate or reopen review."
        ) from exc


def describe_media(client, review_id, kind, identity, index=None, scope=None):
    row = _review(client, review_id, scope)
    path, digest, size = _material(client, row, kind, identity, index)
    _, size = _read_verified_material(client, path, digest, size)
    media_id = _id("media")
    mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    with closing(_db(client)) as db, db:
        db.execute(
            "INSERT INTO media VALUES (?,?,?,?,?,?)",
            (media_id, review_id, str(path), digest, size, mime),
        )
    return {
        "schema_version": 1,
        "media_id": media_id,
        "kind": kind,
        "mime": mime,
        "bytes": size,
        "sha256": digest,
        "max_chunk_bytes": _CHUNK,
        "resource_uri": f"outtake://review/{review_id}/media/{media_id}/0",
    }


def read_media(client, review_id, media_id, offset=0, length=_CHUNK, scope=None):
    _review(client, review_id, scope)
    if (
        not isinstance(offset, int)
        or not isinstance(length, int)
        or offset < 0
        or not 1 <= length <= _CHUNK
    ):
        raise OuttakeError("INVALID_INPUT", "Media range is invalid.", f"Use length 1..{_CHUNK}.")
    with closing(_db(client)) as db:
        row = db.execute(
            "SELECT * FROM media WHERE id=? AND review_id=?", (media_id, review_id)
        ).fetchone()
    if not row:
        raise OuttakeError(
            "MEDIA_MISSING",
            "Media descriptor is not retained for this review.",
            "Describe scoped media first.",
        )
    data, size = _read_verified_material(
        client, Path(row["file"]), row["sha256"], row["bytes"], offset, length
    )
    return {
        "schema_version": 1,
        "media_id": media_id,
        "mime": row["mime"],
        "offset": offset,
        "bytes": len(data),
        "total_bytes": size,
        "sha256": row["sha256"],
        "data_base64": base64.b64encode(data).decode("ascii"),
    }
