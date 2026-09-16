"""Deterministic text, font, naming and saved-export operations."""

import hashlib
import re
import uuid
from pathlib import Path

from PIL import ImageFont

from . import discovery
from .media import Budget, probe
from .models import OuttakeError, TextCue


def font_files():
    # Discover a small set of familiar installed fonts; identifiers bind exact bytes.
    candidates = [
        ("Arial", "/System/Library/Fonts/Supplemental/Arial.ttf"),
        ("Arial Bold", "/System/Library/Fonts/Supplemental/Arial Bold.ttf"),
        ("Times New Roman", "/System/Library/Fonts/Supplemental/Times New Roman.ttf"),
        ("Courier New", "/System/Library/Fonts/Supplemental/Courier New.ttf"),
        ("DejaVu Sans", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
        ("DejaVu Sans Bold", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
        ("DejaVu Serif", "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf"),
        ("Arial", "C:/Windows/Fonts/arial.ttf"),
    ]
    return [
        ("font_" + hashlib.sha256(Path(path).read_bytes()).hexdigest(), name, path)
        for name, path in candidates
        if Path(path).is_file()
    ]


def fonts():
    return [{"id": "pillow-default", "name": "Default", "sha256": None}] + [
        {"id": fid, "name": name, "sha256": fid[5:]} for fid, name, _ in font_files()
    ]


def load_font(font_id, size):
    if font_id == "pillow-default":
        return ImageFont.load_default(size=size)
    for fid, _, path in font_files():
        if fid == font_id:
            return ImageFont.truetype(path, size=size)
    raise OuttakeError(
        "FONT_UNAVAILABLE",
        "Selected font is unavailable or changed.",
        "List fonts and explicitly choose an available font ID.",
    )


def filename(title, extension):
    stem = re.sub(r"[^\w -]", "", title, flags=re.UNICODE).strip().replace(" ", "-")[:80]
    return (stem or "moment") + "." + extension


def import_captions(client, plan, track=None, offset=0, budget=None):
    budget = budget or Budget(client.settings.limits)
    path = client._source(plan.source.path)
    info = probe(path, budget)
    from .subtitles import import_images
    from .subtitles import tracks as available_tracks

    tracks = available_tracks(path, info)
    if track is None:
        defaults = [t for t in tracks if t["default"]]
        selected = defaults if len(defaults) == 1 else tracks
        if len(selected) != 1:
            state = "needs_selection" if tracks else "missing"
            warning = (
                "Choose a caption track: "
                + ", ".join(t["id"] + " (" + t["language"] + ")" for t in tracks)
                if tracks
                else "No source captions; add text manually."
            )
            return plan.model_copy(update={"caption_status": state, "warnings": (warning,)})
        track = selected[0]["id"]
    selected = next((t for t in tracks if t["id"] == track), None)
    if selected is None:
        raise OuttakeError(
            "INVALID_TRACK", "Caption track is unavailable.", "List caption tracks and choose one."
        )
    if selected["kind"] == "image":
        return import_images(client, plan, selected, offset, budget)
    sid = "source_" + hashlib.sha256(str(path).encode()).hexdigest()
    discovery.save_record(
        client,
        "sources",
        {"id": sid, "path": str(path), "label": path.stem, "identity_verified": False},
    )
    evidence = discovery.captions(
        client, sid, "", track, offset, 101, budget, interval=(plan.start, plan.end)
    )
    if len(evidence["hits"]) > 100:
        raise OuttakeError(
            "RESOURCE_LIMIT",
            "More than 100 captions intersect this cut.",
            "Shorten the cut or opt out of captions.",
        )
    cues = [cue for cue in plan.cues if cue.origin != "caption"]
    cues.extend(
        TextCue(
            id="cue_" + uuid.uuid4().hex,
            start=h["start"],
            end=h["end"],
            text=re.sub(r"<[^>]+>|\{[^}]+\}", "", h["text"]),
            origin="caption",
            evidence_id=evidence["id"],
        )
        for h in evidence["hits"]
    )
    # Preserve selection evidence independently; cue evidence follows each cue.
    from .models import Plan

    values = plan.model_dump()
    values.update(
        cues=[c.model_dump() for c in cues],
        caption_status="imported",
        caption_mode="editable",
        caption_evidence_id=None,
        warnings=[],
        captions_enabled=True,
    )
    return Plan.model_validate(values)


def delete_output(client, artifact_id):
    if not re.fullmatch(r"export_[a-f0-9]{32}", artifact_id):
        raise OuttakeError("INVALID_ID", "Invalid export ID.", "Use a saved output ID.")
    directory = client.output / artifact_id
    if directory.is_symlink():
        raise OuttakeError(
            "ACCESS_DENIED", "Linked exports cannot be deleted.", "Use a published export."
        )
    if not directory.exists():
        return {
            "status": "ready",
            "artifact_id": artifact_id,
            "removed": [],
            "already_absent": True,
        }
    import json

    receipt_path = directory / "receipt.json"
    if receipt_path.is_symlink() or not receipt_path.is_file():
        raise OuttakeError(
            "DELETE_FAILED",
            "Export receipt missing or unsafe.",
            "Inspect the output folder; nothing was deleted.",
        )
    receipt = json.loads(receipt_path.read_text())
    path = Path(receipt["artifact"])
    if path.is_symlink() or path.parent.resolve() != directory.resolve():
        raise OuttakeError(
            "ACCESS_DENIED",
            "Export file is outside its directory.",
            "Inspect the receipt; nothing was deleted.",
        )
    auxiliary = {
        p
        for p in directory.iterdir()
        if re.fullmatch(r"overlay(?:-\d+)?\.png", p.name)
        and p != path
        and not p.is_symlink()
        and p.is_file()
    }
    if set(directory.iterdir()) - {path, receipt_path} - auxiliary:
        raise OuttakeError(
            "DELETE_FAILED",
            "Unexpected files in export directory.",
            "Inspect the directory; nothing was deleted.",
        )
    removed = []
    try:
        if path.exists():
            path.unlink()
            removed.append(path.name)
        for extra in auxiliary:
            extra.unlink()
            removed.append(extra.name)
        receipt_path.unlink()
        removed.append("receipt.json")
        directory.rmdir()
    except OSError as exc:
        raise OuttakeError(
            "DELETE_FAILED",
            f"Deletion incomplete; removed {removed}: {exc}",
            "Inspect the output directory before retrying.",
        ) from exc
    return {
        "status": "ready",
        "artifact_id": artifact_id,
        "removed": removed,
        "already_absent": False,
    }
