"""Bounded local discovery and source-linked observations, independent of models."""

import hashlib
import json
import math
import os
import re
import tempfile
import uuid
from pathlib import Path

from .media import INPUT_OPTIONS, fingerprint, frame_at, probe, run, video_stream
from .models import OuttakeError

EXTENSIONS = {".mkv", ".mp4", ".mov", ".webm", ".avi", ".ts", ".m4v"}


def identity(prefix):
    return prefix + "_" + uuid.uuid4().hex


def save_record(client, collection, record):
    record.setdefault("schema_version", 1)
    directory = client.state / collection
    directory.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            "w", dir=directory, encoding="utf-8", delete=False
        ) as file:
            temporary = Path(file.name)
            json.dump(record, file, ensure_ascii=False, allow_nan=False)
        temporary.replace(directory / (record["id"] + ".json"))
    finally:
        if temporary:
            temporary.unlink(missing_ok=True)


def load_record(client, collection, record_id):
    if not isinstance(record_id, str) or not re.fullmatch(r"[a-z]+_[a-f0-9]{32,64}", record_id):
        raise OuttakeError(
            "INVALID_ID", "Invalid retained identity.", "Use an ID returned by Outtake."
        )
    path = client.state / collection / (record_id + ".json")
    if not path.is_file():
        raise OuttakeError(
            "RECORD_MISSING",
            "The requested record is not available.",
            "Use its original state folder or repeat discovery.",
            record_id,
        )
    return json.loads(path.read_text())


def source_path(client, source_id):
    record = load_record(client, "sources", source_id)
    return client._source(record["path"])


def catalog(client, title, scope, limit, scan_limit, budget):
    if (
        not isinstance(title, str)
        or len(title) > 200
        or not 1 <= limit <= 100
        or not 1 <= scan_limit <= 100_000
    ):
        raise OuttakeError(
            "INVALID_INPUT",
            "Invalid discovery query or bounds.",
            "Use title <=200 characters, limit 1..100, scan_limit 1..100000.",
        )
    from .lib import _inside

    roots = [_inside(Path(scope), client.roots)] if scope else list(client.roots)
    tokens = re.findall(r"\w+", title.casefold())
    entries, errors, seen = [], [], set()
    examined, exhausted = 0, False
    for root in roots:
        if not root.is_dir():
            raise OuttakeError(
                "INVALID_ROOT",
                "Discovery scope must be a directory.",
                "Select a directory inside source roots.",
            )
        pending = [root]
        while pending and not exhausted:
            budget.check()
            directory = pending.pop()
            try:
                with os.scandir(directory) as items:
                    for item in items:
                        budget.check()
                        examined += 1
                        if examined > scan_limit:
                            exhausted = True
                            break
                        path = Path(item.path)
                        # Do not follow directory symlinks, including cycles or root escapes.
                        if item.is_dir(follow_symlinks=False):
                            if not item.name.startswith(".") and path.resolve() not in (
                                client.state,
                                client.output,
                            ):
                                pending.append(path)
                            continue
                        if path.suffix.casefold() not in EXTENSIONS:
                            continue
                        relative = str(path.relative_to(root)).casefold()
                        if not all(token in relative for token in tokens):
                            continue
                        try:
                            actual = client._source(str(path))
                            if str(actual) in seen:
                                continue
                            seen.add(str(actual))
                            sid = "source_" + hashlib.sha256(str(actual).encode()).hexdigest()
                            record = {
                                "id": sid,
                                "path": str(actual),
                                "label": actual.stem,
                                "identity_verified": False,
                            }
                            save_record(client, "sources", record)
                            entries.append(record)
                            if len(entries) >= limit:
                                exhausted = True
                                break
                        except (OSError, OuttakeError) as exc:
                            errors.append(
                                {"path": str(path), "code": getattr(exc, "code", "IO_ERROR")}
                            )
            except OSError:
                errors.append({"path": str(directory), "code": "IO_ERROR"})
    return {
        "schema_version": 1,
        "status": "partial" if exhausted or errors else "ready",
        "sources": entries,
        "errors": errors,
        "examined_entries": min(examined, scan_limit),
        "scope_complete": not exhausted and not errors,
        "limitation": "Names are clues; matching a filename does not verify the requested content.",
    }


def details(client, source_id, budget, fingerprint_source=True):
    path = source_path(client, source_id)
    info = probe(path, budget)
    if not isinstance(fingerprint_source, bool):
        raise ValueError("fingerprint_source must be a boolean.")
    if fingerprint_source:
        source = client._inspect(str(path), budget).model_dump()
    else:
        # Metadata is a resolution clue, never verified content evidence.
        stream = video_stream(info)
        client._check_media(info)
        source = {
            "path": str(path),
            "bytes": path.stat().st_size,
            "duration": client._duration(info),
            "width": stream["width"],
            "height": stream["height"],
            "has_audio": any(s["codec_type"] == "audio" for s in info["streams"]),
            "color_transfer": stream.get("color_transfer", "unspecified"),
        }
    tracks = []
    sidecar = path.with_suffix(".srt")
    if sidecar.exists():
        client._source(str(sidecar))
        tracks.append({"id": "sidecar", "kind": "text", "language": "und"})
    for stream in info["streams"]:
        if stream["codec_type"] == "subtitle":
            tracks.append(
                {
                    "id": f"stream:{stream['index']}",
                    "kind": "text"
                    if stream.get("codec_name")
                    in {"subrip", "ass", "ssa", "webvtt", "mov_text", "text"}
                    else "image",
                    "language": stream.get("tags", {}).get("language", "und"),
                }
            )
    return {
        "source_id": source_id,
        "source": source,
        "caption_tracks": tracks,
        "fingerprinted": fingerprint_source,
    }


def observe(client, source_id, times, budget):
    if (
        not isinstance(times, (list, tuple))
        or not 1 <= len(times) <= 12
        or any(
            isinstance(t, bool) or not isinstance(t, (int, float)) or not math.isfinite(t) or t < 0
            for t in times
        )
    ):
        raise OuttakeError(
            "INVALID_INPUT",
            "Frame sampling needs 1..12 finite nonnegative timestamps.",
            "Supply an ordered list of seconds from video start.",
        )
    if list(times) != sorted(set(times)):
        raise OuttakeError(
            "INVALID_INPUT",
            "Sample times must be strictly increasing.",
            "Sort and deduplicate timestamps.",
        )
    path = source_path(client, source_id)
    source = client._inspect(str(path), budget)
    if times[-1] >= source.duration:
        raise OuttakeError(
            "INVALID_INPUT",
            "Sample lies outside the source duration.",
            "Inspect source_details for its duration.",
        )
    info = probe(path, budget)
    stream = video_stream(info)
    eid = identity("evidence")
    directory = client.state / "frames"
    directory.mkdir(exist_ok=True)
    target = directory / eid
    frames = []
    with tempfile.TemporaryDirectory(prefix=".observing-", dir=directory) as scratch:
        stage = Path(scratch)
        for index, requested in enumerate(times):
            budget.check(stage)
            resolved, origin = frame_at(path, requested, info, budget)
            filename = f"{index}.png"
            # Accurate input seeking keeps late-film observations bounded. copyts
            # preserves original PTS so trim uses the same coordinate as ffprobe.
            seek = max(0, resolved - float(info["format"].get("start_time", 0)) - 2)
            filters = f"trim=start={resolved:.9f},scale=w='min(640,iw)':h=-2,setsar=1"
            run(
                "ffmpeg",
                [
                    "-v",
                    "error",
                    "-nostdin",
                    "-n",
                    "-copyts",
                    "-ss",
                    f"{seek:.9f}",
                    *INPUT_OPTIONS,
                    "-i",
                    str(path),
                    "-map",
                    f"0:{stream['index']}",
                    "-vf",
                    filters,
                    "-frames:v",
                    "1",
                    "-an",
                    "-update",
                    "1",
                    str(stage / filename),
                ],
                budget,
                stage,
            )
            if not (stage / filename).is_file():
                raise OuttakeError(
                    "NO_FRAME", "Frame extraction produced no image.", "Use another timestamp."
                )
            frames.append(
                {
                    "requested": requested,
                    "time": resolved - origin,
                    "image": str(target / filename),
                    "sha256": fingerprint(stage / filename, budget),
                }
            )
        if fingerprint(path, budget) != source.sha256:
            raise OuttakeError(
                "STALE_SOURCE", "Source changed during observation.", "Inspect the source again."
            )
        os.rename(stage, target)
    record = {
        "id": eid,
        "kind": "frames",
        "source_id": source_id,
        "source_sha256": source.sha256,
        "frames": frames,
        "time_basis": "seconds_from_video_start",
        "sampling_gaps": [b["time"] - a["time"] for a, b in zip(frames, frames[1:])],
        "limitation": "Sampled frames leave gaps; they do not prove sound or events between samples.",
    }
    save_record(client, "evidence", record)
    return record


def _seconds(value):
    hours, minutes, seconds = value.replace(",", ".").split(":")
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


def captions(client, source_id, query, track, offset, limit, budget, interval=None):
    if (
        not isinstance(query, str)
        or not (0 if interval else 1) <= len(query) <= 500
        or not math.isfinite(offset)
        or abs(offset) > 3600
        or not 1 <= limit <= (101 if interval else 100)
    ):
        raise OuttakeError(
            "INVALID_INPUT",
            "Invalid caption query, offset or result limit.",
            "Use a nonempty query, offset within one hour, and limit 1..100.",
        )
    path = source_path(client, source_id)
    source = client._inspect(str(path), budget)
    info = probe(path, budget)
    language, caption_path = "und", None
    if track == "sidecar":
        caption_path = (
            client._source(str(path.with_suffix(".srt")))
            if path.with_suffix(".srt").exists()
            else None
        )
        if caption_path is None:
            raise OuttakeError(
                "MISSING_TEXT_CAPTIONS",
                "No same-basename SRT sidecar is available.",
                "Use source_details to choose an embedded text track, or inspect frames.",
            )
        if caption_path.stat().st_size > 4_000_000:
            raise OuttakeError(
                "RESOURCE_LIMIT",
                "Caption file exceeds 4MB.",
                "Use another track or smaller source.",
            )
        raw = caption_path.read_bytes()
        text = raw.decode("utf-8-sig")
        caption_hash = hashlib.sha256(raw).hexdigest()
        caption_origin = 0.0  # Sidecar times are relative to video start by convention.
    else:
        tracks = [
            s
            for s in info["streams"]
            if f"stream:{s['index']}" == track and s["codec_type"] == "subtitle"
        ]
        if not tracks or tracks[0].get("codec_name") not in {
            "subrip",
            "ass",
            "ssa",
            "webvtt",
            "mov_text",
            "text",
        }:
            raise OuttakeError(
                "MISSING_TEXT_CAPTIONS",
                "Selected track is not available as text.",
                "Choose a text track; image captions are not OCRed.",
            )
        language = tracks[0].get("tags", {}).get("language", "und")
        text = run(
            "ffmpeg",
            [
                "-v",
                "error",
                "-nostdin",
                "-copyts",
                *INPUT_OPTIONS,
                "-i",
                str(path),
                "-map",
                f"0:{tracks[0]['index']}",
                "-f",
                "srt",
                "-",
            ],
            budget,
        )
        caption_hash = hashlib.sha256(text.encode()).hexdigest()
        caption_origin = float(video_stream(info).get("start_time", 0))
    hits = []
    pattern = (
        r"(\d+:\d{2}:\d{2}[,.]\d+)\s*-->\s*(\d+:\d{2}:\d{2}[,.]\d+)[^\n]*\n(.*?)(?=\n\s*\n|\Z)"
    )
    for match in re.finditer(pattern, text.replace("\r\n", "\n"), re.DOTALL):
        budget.check()
        body = match.group(3).strip()
        if query.casefold() in body.casefold():
            start = _seconds(match.group(1)) - caption_origin + offset
            end = _seconds(match.group(2)) - caption_origin + offset
            if interval and (end <= interval[0] or start >= interval[1]):
                continue
            if start < end and end > 0 and start < source.duration:
                hits.append(
                    {"start": max(0, start), "end": min(end, source.duration), "text": body}
                )
            if len(hits) == limit:
                break
    record = {
        "id": identity("evidence"),
        "kind": "captions",
        "source_id": source_id,
        "source_sha256": source.sha256,
        "track": track,
        "caption_sha256": caption_hash,
        "caption_path": str(caption_path) if caption_path else None,
        "language": language,
        "offset": offset,
        "query": query,
        "hits": hits,
        "limit_reached": len(hits) == limit,
        "time_basis": "seconds_from_video_start",
        "limitation": "Caption matches do not establish complete scene boundaries.",
    }
    if (
        fingerprint(path, budget) != source.sha256
        or caption_path
        and fingerprint(caption_path, budget) != caption_hash
    ):
        raise OuttakeError(
            "STALE_SOURCE",
            "Source or captions changed during inspection.",
            "Repeat caption inspection.",
        )
    save_record(client, "evidence", record)
    return record


def validate_evidence(client, evidence, budget):
    path = source_path(client, evidence["source_id"])
    if fingerprint(path, budget) != evidence["source_sha256"]:
        raise OuttakeError("STALE_SOURCE", "Evidence source has changed.", "Find the moment again.")
    if evidence["kind"] == "captions" and evidence.get("caption_path"):
        caption = client._source(evidence["caption_path"])
        if fingerprint(caption, budget) != evidence["caption_sha256"]:
            raise OuttakeError(
                "STALE_SOURCE", "Caption evidence has changed.", "Repeat caption inspection."
            )

    if evidence["kind"] == "image_captions":
        from .subtitles import image_path

        for hit in evidence["hits"]:
            image_path(client, evidence, hit, budget)
    elif evidence["kind"] == "ocr_captions":
        original = load_record(client, "evidence", evidence["image_evidence_id"])
        if (
            original["kind"] != "image_captions"
            or original["source_sha256"] != evidence["source_sha256"]
        ):
            raise OuttakeError(
                "INVALID_EVIDENCE", "OCR source evidence mismatch.", "Convert captions again."
            )
        validate_evidence(client, original, budget)
