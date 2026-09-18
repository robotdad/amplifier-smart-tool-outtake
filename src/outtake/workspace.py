"""Public workspace operations shared by the dashboard, CLI and calling agents."""

import hashlib
import json
import os
import re
import sqlite3
from contextlib import closing
from pathlib import Path

from .discovery import observe, save_record
from .media import Budget
from .models import ModelGrant, OuttakeError, Settings


def preferences(client):
    from .providers import COPILOT_ENV, chatgpt_available

    path = client.state / "preferences.json"
    saved = json.loads(path.read_text()) if path.exists() else {}
    return {
        "schema_version": 1,
        "settings": client.settings.model_dump(mode="json"),
        "model_grant": saved.get("model_grant"),
        "appearance": saved.get("appearance", "system"),
        "credentials": {
            "github-copilot": any(os.environ.get(k) for k in COPILOT_ENV),
            "openai-chatgpt": chatgpt_available(),
            "openai": bool(os.environ.get("OPENAI_API_KEY")),
            "anthropic": bool(os.environ.get("ANTHROPIC_API_KEY")),
            "gemini": bool(os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")),
        },
    }


def configure(client, settings, model_grant, appearance):
    from .lib import Outtake

    if appearance not in {"light", "dark", "system"}:
        raise OuttakeError("INVALID_INPUT", "Unknown appearance.", "Choose light, dark or system.")
    updated = Settings.model_validate(settings)
    if updated.state_root and Path(updated.state_root).expanduser().resolve() != client.state:
        raise OuttakeError(
            "INVALID_INPUT",
            "An active workspace cannot change its state folder.",
            "Start a separate workspace for another state folder.",
        )
    updated = updated.model_copy(update={"state_root": str(client.state)})
    grant = ModelGrant.model_validate(model_grant).model_dump(mode="json") if model_grant else None
    replacement = Outtake(updated)
    record = {
        "id": "preferences",
        "settings": updated.model_dump(mode="json"),
        "model_grant": grant,
        "appearance": appearance,
    }
    save_record(client, ".", record)
    client.settings, client.roots, client.output = (
        replacement.settings,
        replacement.roots,
        replacement.output,
    )
    return preferences(client)


def review_frames(client, plan, cancelled):
    budget = Budget(client.settings.limits, cancelled)
    client._validate(plan, budget)
    path = client._source(plan.source.path)
    sid = "source_" + hashlib.sha256(str(path).encode()).hexdigest()
    save_record(
        client,
        "sources",
        {"id": sid, "path": str(path), "label": path.stem, "identity_verified": False},
    )
    span = plan.end - plan.start
    times = sorted(set(round(plan.start + span * i / 5, 6) for i in range(5)))
    return observe(client, sid, times, budget)


def artifact(client, artifact_id):
    if not re.fullmatch(r"export_[a-f0-9]{32}", artifact_id):
        raise OuttakeError("INVALID_ID", "Invalid export ID.", "Use a saved output identity.")
    directory = client.output / artifact_id
    if directory.is_symlink():
        raise OuttakeError(
            "ACCESS_DENIED", "Linked export directories are not served.", "Use a published export."
        )
    receipt_path = directory / "receipt.json"
    if not receipt_path.is_file() or receipt_path.is_symlink():
        raise OuttakeError(
            "ARTIFACT_MISSING",
            "Export receipt is unavailable.",
            "Check the configured output folder.",
        )
    result = json.loads(receipt_path.read_text())
    path = Path(result["artifact"])
    if path.is_symlink() or path.resolve().parent != directory.resolve() or not path.is_file():
        raise OuttakeError(
            "ARTIFACT_MISSING",
            "Export file is unavailable or outside its publication directory.",
            "Render the retained plan again.",
        )
    return result


def rename_output(client, artifact_id, title):
    """Update a saved name without reading sources or changing media bytes."""
    import tempfile
    import uuid
    from datetime import datetime, timezone

    from .models import Plan

    receipt = artifact(client, artifact_id)
    if not isinstance(title, str) or not title.strip() or len(title) > 120:
        raise OuttakeError(
            "INVALID_INPUT",
            "Use a nonempty title of at most 120 characters.",
            "Supply the new display name.",
        )
    title = title.strip()
    if receipt["plan"].get("title") == title:
        return receipt
    base = Plan.model_validate(receipt["plan"])
    revised = client._retain(
        base.model_copy(
            update={
                "id": "plan_" + uuid.uuid4().hex,
                "parent_id": base.id,
                "revision": base.revision + 1,
                "title": title,
            }
        )
    )
    path = client.output / artifact_id / "receipt.json"
    receipt.setdefault(
        "created_at", datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat()
    )
    receipt["plan"] = revised.model_dump(mode="json")
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", dir=path.parent, delete=False, encoding="utf-8"
        ) as f:
            temporary = Path(f.name)
            json.dump(receipt, f, ensure_ascii=False)
        temporary.replace(path)
    finally:
        if temporary and temporary.exists():
            temporary.unlink()
    return receipt


def _workspace_db(client):
    db = sqlite3.connect(client.state / "workspaces.sqlite3", timeout=30)
    db.execute("CREATE TABLE IF NOT EXISTS heads (id TEXT PRIMARY KEY, plan TEXT NOT NULL)")
    db.execute("CREATE TABLE IF NOT EXISTS aliases (id TEXT PRIMARY KEY, workspace TEXT NOT NULL)")
    db.execute("CREATE TABLE IF NOT EXISTS bases (id TEXT PRIMARY KEY, plan TEXT NOT NULL)")
    db.commit()
    return db


def get_workspace(client, plan_id, artifact_id=None):
    """Resume a draft scoped to a plan or a specific saved output."""
    initial = client.get_plan(plan_id)
    with closing(_workspace_db(client)) as db, db:
        if artifact_id is not None:
            if not re.fullmatch(r"export_[a-f0-9]{32}", artifact_id):
                raise OuttakeError("INVALID_ID", "Invalid export ID.", "Use a saved export ID.")
            workspace_id = artifact_id
            row = db.execute("SELECT plan FROM heads WHERE id = ?", (workspace_id,)).fetchone()
            if not row:
                receipt = client.artifact(artifact_id)
                initial = client.get_plan(receipt["plan"]["id"])
                db.execute("INSERT OR IGNORE INTO heads VALUES (?, ?)", (workspace_id, initial.id))
                db.execute("INSERT OR IGNORE INTO bases VALUES (?, ?)", (workspace_id, initial.id))
        else:
            row = db.execute("SELECT workspace FROM aliases WHERE id = ?", (plan_id,)).fetchone()
            workspace_id = row[0] if row else plan_id
            row = db.execute("SELECT plan FROM heads WHERE id = ?", (workspace_id,)).fetchone()
    plan = client.get_plan(row[0]) if row else initial
    return {"workspace_id": workspace_id, "plan": plan.model_dump(mode="json")}


def finish_workspace_export(client, workspace_id, artifact_id):
    """Give the published result its own draft; close only the exported source draft."""
    receipt = client.artifact(artifact_id)
    result = get_workspace(client, receipt["plan"]["id"], artifact_id)
    with closing(_workspace_db(client)) as db, db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT plan FROM heads WHERE id = ?", (workspace_id,)).fetchone()
        if row and row[0] == receipt["plan"]["id"] and workspace_id != artifact_id:
            base = db.execute("SELECT plan FROM bases WHERE id = ?", (workspace_id,)).fetchone()
            base_id = base[0] if base else client.get_plan(workspace_id).id
            db.execute("UPDATE heads SET plan = ? WHERE id = ?", (base_id, workspace_id))
    return result


def save_workspace(client, workspace_id, plan, changes):
    """Atomically advance an editing workspace, rejecting stale concurrent writers."""
    from .models import Plan

    if not re.fullmatch(r"(?:plan|export)_[a-f0-9]{32}", workspace_id):
        raise OuttakeError("INVALID_ID", "Invalid workspace ID.", "Use get-workspace first.")
    if workspace_id.startswith("plan_"):
        client.get_plan(workspace_id)
    base = Plan.model_validate(plan)
    client.get_plan(base.id)
    client._check_identity(base)
    with closing(_workspace_db(client)) as db, db:
        db.execute("BEGIN IMMEDIATE")
        alias = db.execute("SELECT workspace FROM aliases WHERE id = ?", (workspace_id,)).fetchone()
        workspace_id = alias[0] if alias else workspace_id
        row = db.execute("SELECT plan FROM heads WHERE id = ?", (workspace_id,)).fetchone()
        if not row and workspace_id.startswith("export_"):
            raise OuttakeError(
                "WORKSPACE_MISSING",
                "Open this output first.",
                "Use get-workspace with artifact_id.",
            )
        expected = row[0] if row else workspace_id
        ancestor = base
        # Also accept explicit caption-import or recovery revisions descended from the head.
        while ancestor.id != expected and ancestor.parent_id:
            ancestor = client.get_plan(ancestor.parent_id)
        if ancestor.id != expected:
            raise OuttakeError(
                "WORKSPACE_CONFLICT",
                "This workspace has newer saved edits.",
                "Load get-workspace before editing again; your supplied plan remains available.",
            )
        revised = client.revise(base, changes) if changes else base
        db.execute("INSERT OR REPLACE INTO heads VALUES (?, ?)", (workspace_id, revised.id))
        if workspace_id.startswith("plan_"):
            for identity in (workspace_id, base.id, revised.id):
                db.execute("INSERT OR REPLACE INTO aliases VALUES (?, ?)", (identity, workspace_id))
    return revised
