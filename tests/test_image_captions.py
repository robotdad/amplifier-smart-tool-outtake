"""Synthetic PGS display set: HELLO appears at .5s, clears at 1.5s."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest
from PIL import Image

from outtake import OuttakeError


def test_original_pixels_timing_sar_offset_and_staleness(bitmap_tool, bitmap_source):
    from outtake import subtitles

    assert subtitles._subtitle_probe_interval(
        {"streams": [{"index": 1, "time_base": "1/1000"}]}, 1
    ) == pytest.approx(0.001)
    assert subtitles._subtitle_probe_interval(
        {"streams": [{"index": 0, "time_base": "1/1"}, {"index": 1, "time_base": "0/1"}]}, 1
    ) == pytest.approx(0.000001)
    tool = bitmap_tool
    plan = tool.plan(str(bitmap_source), 0, 2, fps=10)
    assert plan.caption_mode == "original" and not plan.cues
    assert tool.caption_tracks(plan)[0]["kind"] == "image"
    evidence = tool.get_evidence(plan.caption_evidence_id)
    assert [(h["start"], h["end"]) for h in evidence["hits"]] == [(0.5, 1.5)]
    receipt = tool.render(plan)
    assert (receipt["width"], receipt["height"]) == (320, 96)
    raw = subprocess.check_output(
        [
            "ffmpeg",
            "-v",
            "error",
            "-i",
            receipt["artifact"],
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgb24",
            "-",
        ]
    )

    def white(frame):
        size = 320 * 96 * 3
        im = Image.frombytes("RGB", (320, 96), raw[frame * size : (frame + 1) * size])
        return sum(min(p) > 180 for p in im.getdata())

    assert white(4) == 0 and white(5) > 50 and white(14) > 50 and white(15) == 0
    for frame, visible in [(0.5, True), (1.5, False)]:
        still = tool.render(tool.revise(plan, {"format": "png", "frame": frame}))
        with Image.open(still["artifact"]) as im:
            assert (sum(min(p[:3]) > 180 for p in im.getdata()) > 50) == visible
    partial = tool.plan(str(bitmap_source), 0.9, 1.2)
    assert tool.get_evidence(partial.caption_evidence_id)["hits"][0]["start"] == 0.5
    shifted = tool.import_captions(plan, track="stream:1", offset=0.2)
    assert tool.get_evidence(shifted.caption_evidence_id)["hits"][0]["start"] == 0.7
    with pytest.raises(OuttakeError) as error:
        tool.render(tool.revise(plan, {"end": 2.5}))
    assert error.value.code == "CAPTION_COVERAGE"
    refreshed = tool.import_captions(tool.revise(plan, {"end": 2.5}), track="stream:1")
    tool.validate(refreshed)
    with pytest.raises(OuttakeError) as error:
        tool.import_captions(plan, track="stream:1", cancelled=lambda: True)
    assert error.value.code == "CANCELLED"
    image = Path(tool.caption_image(plan.caption_evidence_id, 0)["path"])
    image.write_bytes(b"changed")
    with pytest.raises(OuttakeError) as error:
        tool.render(plan)
    assert error.value.code == "STALE_EVIDENCE"


@pytest.mark.skipif(not shutil.which("tesseract"), reason="Local OCR needs Tesseract")
def test_explicit_ocr_retains_originals_and_manual_edits(bitmap_tool, bitmap_source, monkeypatch):
    tool = bitmap_tool
    plan = tool.plan(
        str(bitmap_source), 0, 2, cues=[dict(id="cue_manual", start=0, end=1, text="Manual")]
    )
    converted = tool.convert_captions(plan)
    assert converted.caption_mode == "editable"
    assert converted.caption_evidence_id == plan.caption_evidence_id
    assert converted.cues[0].text == "Manual"
    cue = converted.cues[1]
    assert cue.text == "HELLO" and (cue.start, cue.end) == (0.5, 1.5)
    assert cue.extraction == "ocr" and cue.review_required and 0 <= cue.confidence <= 1
    changes = [c.model_dump() for c in converted.cues]
    changes[1]["text"] = "Edited words"
    edited = tool.revise(converted, {"cues": changes, "caption_mode": "original"})
    restored = tool.revise(edited, {"caption_mode": "editable", "captions_enabled": False})
    assert restored.cues[1].text == "Edited words"
    tool.render(restored)
    tool.render(tool.revise(restored, {"captions_enabled": True}))
    tool.render(edited)
    with pytest.raises(OuttakeError) as error:
        tool.convert_captions(plan, language="missing")
    assert error.value.code == "OCR_LANGUAGE_UNAVAILABLE"
    from outtake import subtitles

    real_run = subtitles.run

    def quoted_tsv(executable, arguments, *args):
        if executable == "tesseract" and arguments[-1] == "tsv":
            return 'level\tblock_num\tpar_num\tline_num\tconf\ttext\n5\t1\t1\t1\t95\t"Hello\n5\t1\t1\t1\t90\tfriend"\n'
        return real_run(executable, arguments, *args)

    monkeypatch.setattr(subtitles, "run", quoted_tsv)
    assert tool.convert_captions(plan).cues[1].text == '"Hello friend"'
    monkeypatch.setattr(subtitles.shutil, "which", lambda _: None)
    with pytest.raises(OuttakeError) as error:
        tool.convert_captions(plan)
    assert error.value.code == "MISSING_PREREQUISITE"
    assert tool.get_plan(plan.id).caption_mode == "original"


def test_caption_cli_capabilities(bitmap_tool, bitmap_source, tmp_path):
    tool = bitmap_tool
    plan = tool.plan(str(bitmap_source), 0, 2)
    settings = tmp_path / "settings.json"
    settings.write_text(tool.settings.model_dump_json())
    request = tmp_path / "request.json"
    request.write_text(json.dumps({"plan": plan.model_dump()}))
    result = subprocess.run(
        ["outtake", "caption-tracks", "--settings", str(settings), "--input", str(request)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr + result.stdout
    assert '"kind": "image"' in result.stdout
