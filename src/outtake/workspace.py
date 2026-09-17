"""Public workspace operations shared by the dashboard, CLI and calling agents."""

import hashlib
import json
import os
import re
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
