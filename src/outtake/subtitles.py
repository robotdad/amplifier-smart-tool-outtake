"""Local image subtitles: retain original pixels and explicitly OCR into text cues."""

import csv
import hashlib
import io
import json
import math
import re
import shutil
import sys
import tempfile
import uuid
from pathlib import Path

from PIL import Image, ImageOps, ImageStat

from . import discovery
from .media import INPUT_OPTIONS, fingerprint, probe, run, video_stream
from .models import OuttakeError, Plan, TextCue

TEXT_CODECS = {"subrip", "ass", "ssa", "webvtt", "mov_text", "text"}
IMAGE_CODECS = {"dvd_subtitle", "hdmv_pgs_subtitle", "dvb_subtitle"}


def tracks(path, info):
    result = [
        {
            "id": f"stream:{s['index']}",
            "language": s.get("tags", {}).get("language", "und"),
            "default": bool(s.get("disposition", {}).get("default")),
            "kind": "text" if s.get("codec_name") in TEXT_CODECS else "image",
            "codec": s.get("codec_name"),
        }
        for s in info["streams"]
        if s["codec_type"] == "subtitle" and s.get("codec_name") in TEXT_CODECS | IMAGE_CODECS
    ]
    if path.with_suffix(".srt").exists():
        result.append(
            {
                "id": "sidecar",
                "language": "und",
                "default": False,
                "kind": "text",
                "codec": "subrip",
            }
        )
    return result


def image_path(client, evidence, hit, budget):
    eid = evidence["id"]
    if not re.fullmatch(r"evidence_[a-f0-9]{32}", eid) or not re.fullmatch(
        r"[0-9]+\.png", hit["image"]
    ):
        raise OuttakeError(
            "INVALID_EVIDENCE", "Invalid subtitle image identity.", "Import captions again."
        )
    root = client.state / "subtitle-images"
    path = root / eid / hit["image"]
    if (
        path.is_symlink()
        or path.parent.is_symlink()
        or not path.is_file()
        or path.resolve().parent.parent != root.resolve()
    ):
        raise OuttakeError(
            "STALE_EVIDENCE", "Subtitle image is missing or unsafe.", "Import captions again."
        )
    if fingerprint(path, budget) != hit["sha256"]:
        raise OuttakeError("STALE_EVIDENCE", "Subtitle pixels changed.", "Import captions again.")
    return path


def import_images(client, plan, track, offset, budget):
    if not isinstance(offset, (int, float)) or not math.isfinite(offset) or abs(offset) > 3600:
        raise OuttakeError(
            "INVALID_OFFSET",
            "Caption offset must be finite and within one hour.",
            "Choose a smaller offset.",
        )
    path = client._source(plan.source.path)
    info = probe(path, budget)
    origin = float(video_stream(info).get("start_time", 0))
    sid = "source_" + hashlib.sha256(str(path).encode()).hexdigest()
    discovery.save_record(
        client,
        "sources",
        {"id": sid, "path": str(path), "label": path.stem, "identity_verified": False},
    )
    eid = "evidence_" + uuid.uuid4().hex
    root = client.state / "subtitle-images"
    root.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".import-", dir=root) as scratch:
        stage = Path(scratch)
        events = json.loads(
            run(
                sys.executable,
                [
                    "-m",
                    "outtake.subtitle_worker",
                    json.dumps(
                        {
                            "path": str(path),
                            "stream": int(track["id"].split(":")[1]),
                            "start": plan.start + origin - offset,
                            "end": plan.end + origin - offset,
                        }
                    ),
                ],
                budget,
                stage,
            )
        )
        hits = []
        for index, event in enumerate(events):
            start, end = (
                max(0, event["start"] - origin + offset),
                min(plan.source.duration, event["end"] - origin + offset),
            )
            if start >= end:
                continue
            target = stage / f"{index}.png"
            # Decode from the beginning to retain palettes and displays crossing the cut.
            run(
                "ffmpeg",
                [
                    "-v",
                    "error",
                    "-nostdin",
                    "-n",
                    "-copyts",
                    *INPUT_OPTIONS,
                    "-i",
                    str(path),
                    "-filter_complex",
                    f"[0:{track['id'].split(':')[1]}]trim=start={event['start']:.9f}:end={event['start'] + 0.000001:.9f},format=rgba[s]",
                    "-map",
                    "[s]",
                    "-fps_mode",
                    "passthrough",
                    "-frames:v",
                    "2",
                    str(stage / f"display-{index}-%d.png"),
                ],
                budget,
                stage,
            )
            # FFmpeg may emit a transparent initialization frame at the same PTS.
            displays = sorted(stage.glob(f"display-{index}-*.png"))
            for display in displays:
                with Image.open(display) as candidate:
                    visible = candidate.getbbox()
                if visible:
                    display.replace(target)
                display.unlink(missing_ok=True)
            if not target.exists():
                raise OuttakeError(
                    "CAPTION_DECODE_FAILED",
                    "No subtitle pixels at the decoded timestamp.",
                    "Choose another track.",
                )
            with Image.open(target) as image:
                if image.width * image.height > 4096 * 2160 or not image.getbbox():
                    raise OuttakeError(
                        "CAPTION_DECODE_FAILED",
                        "Subtitle display is empty or exceeds the image allowance.",
                        "Choose another track.",
                    )
            hits.append(
                {
                    "start": start,
                    "end": end,
                    "image": target.name,
                    "sha256": fingerprint(target, budget),
                }
            )
        if fingerprint(path, budget) != plan.source.sha256:
            raise OuttakeError(
                "STALE_SOURCE", "Source changed during caption import.", "Inspect the source again."
            )
        evidence = {
            "id": eid,
            "kind": "image_captions",
            "source_id": sid,
            "source_sha256": plan.source.sha256,
            "track": track["id"],
            "language": track["language"],
            "offset": offset,
            "coverage": {"start": plan.start, "end": plan.end},
            "hits": hits,
            "time_basis": "seconds_from_video_start",
        }
        budget.check(stage)
        stage.rename(root / eid)
        discovery.save_record(client, "evidence", evidence)
    return Plan.model_validate(
        {
            **plan.model_dump(),
            "caption_evidence_id": eid,
            "caption_mode": "original",
            "caption_status": "original" if hits else "empty",
            "captions_enabled": True,
            "warnings": [],
            "cues": [c.model_dump() for c in plan.cues if c.origin != "caption"],
        }
    )


def convert(client, plan, language, budget):
    if not plan.caption_evidence_id:
        raise OuttakeError(
            "CAPTIONS_UNAVAILABLE",
            "Import an image subtitle track before conversion.",
            "Use import-captions with an image track.",
        )
    evidence = client.get_evidence(plan.caption_evidence_id)
    if evidence["kind"] != "image_captions":
        raise OuttakeError(
            "INVALID_EVIDENCE", "Expected image subtitle evidence.", "Import an image track."
        )
    discovery.validate_evidence(client, evidence, budget)
    if not shutil.which("tesseract"):
        raise OuttakeError(
            "MISSING_PREREQUISITE",
            "Local OCR requires Tesseract.",
            "Install Tesseract and the selected language data; original captions remain available.",
        )
    available = run("tesseract", ["--list-langs"], budget).splitlines()[1:]
    language = language or {"fre": "fra", "ger": "deu"}.get(
        evidence["language"], evidence["language"]
    )
    if language not in available or not re.fullmatch(r"[A-Za-z0-9_]+", language):
        raise OuttakeError(
            "OCR_LANGUAGE_UNAVAILABLE",
            f"OCR language {language!r} is unavailable.",
            f"Choose an installed language: {', '.join(available)}.",
        )
    hits, cues = [], [c for c in plan.cues if c.origin != "caption"]
    eid = "evidence_" + uuid.uuid4().hex
    with tempfile.TemporaryDirectory(prefix="outtake-ocr-") as scratch:
        stage = Path(scratch)
        for hit in evidence["hits"]:
            source = image_path(client, evidence, hit, budget)
            with Image.open(source) as image:
                cropped = image.convert("RGBA").crop(image.getbbox())
                # White lettering on a dark transparent background becomes dark-on-white.
                canvas = Image.new("RGBA", cropped.size, "black")
                canvas.alpha_composite(cropped)
                gray = canvas.convert("L")
                if ImageStat.Stat(gray).mean[0] < 128:
                    gray = ImageOps.invert(gray)
                factor = min(3, 4096 / max(gray.size))
                gray = gray.resize(
                    (max(1, int(gray.width * factor)), max(1, int(gray.height * factor)))
                )
                ImageOps.expand(gray, border=12, fill="white").save(stage / "cue.png")
            tsv = run(
                "tesseract",
                [str(stage / "cue.png"), "stdout", "-l", language, "--psm", "6", "tsv"],
                budget,
                stage,
            )
            lines, confidence = {}, []
            for row in csv.DictReader(io.StringIO(tsv), delimiter="\t", quoting=csv.QUOTE_NONE):
                text = row.get("text", "").strip()
                if row.get("level") == "5" and text:
                    key = (row["block_num"], row["par_num"], row["line_num"])
                    lines.setdefault(key, []).append(text)
                    confidence.append(max(0, min(100, float(row["conf"]))) / 100)
            text = "\n".join(" ".join(words) for words in lines.values())
            score = sum(confidence) / len(confidence) if confidence else 0
            hits.append(
                {
                    "start": hit["start"],
                    "end": hit["end"],
                    "text": text,
                    "confidence": score,
                    "review_required": True,
                }
            )
            cues.append(
                TextCue(
                    id="cue_" + uuid.uuid4().hex,
                    start=hit["start"],
                    end=hit["end"],
                    text=text,
                    origin="caption",
                    evidence_id=eid,
                    extraction="ocr",
                    confidence=score,
                    review_required=True,
                )
            )
    discovery.validate_evidence(client, evidence, budget)
    discovery.save_record(
        client,
        "evidence",
        {
            "id": eid,
            "kind": "ocr_captions",
            "source_id": evidence["source_id"],
            "source_sha256": evidence["source_sha256"],
            "image_evidence_id": evidence["id"],
            "language": language,
            "engine": "tesseract",
            "hits": hits,
            "time_basis": "seconds_from_video_start",
        },
    )
    return Plan.model_validate(
        {
            **plan.model_dump(),
            "cues": [c.model_dump() for c in cues],
            "caption_mode": "editable",
            "caption_status": "ocr_review_required",
            "captions_enabled": True,
            "warnings": [
                "Converted locally with OCR. Review each cue for recognition errors; source timing is retained."
            ],
        }
    )
