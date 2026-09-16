import subprocess
from pathlib import Path

import pytest
from PIL import Image

from outtake import OuttakeError


def test_timed_text_decoded_boundaries_still_and_fonts(tool, fixture_video):
    cues = [
        dict(id="cue_one", text="ONE", start=0.5, end=1, x=0.5, y=0.3, size=24),
        dict(id="cue_two", text="TWO", start=1.5, end=2, x=0.5, y=0.3, size=24),
    ]
    plan = tool.plan(str(fixture_video), 0, 2.5, cues=cues, fps=10, captions_enabled=False)
    receipt = tool.render(plan)
    raw = subprocess.run(
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
        ],
        capture_output=True,
        check=True,
    ).stdout

    def whites(frame):
        im = Image.frombytes(
            "RGB", (160, 96), raw[frame * 160 * 96 * 3 : (frame + 1) * 160 * 96 * 3]
        )
        return sum(min(pixel) > 190 for pixel in im.crop((25, 20, 135, 70)).getdata())

    assert whites(4) == 0 and whites(5) > 10
    assert whites(9) > 10 and whites(10) == 0
    assert whites(14) == 0 and whites(15) > 10 and whites(20) == 0
    for frame, visible in [(0.5, True), (1, False)]:
        still = tool.render(tool.revise(plan, {"format": "png", "frame": frame}))
        im = Image.open(still["artifact"]).convert("RGB")
        assert (sum(min(p) > 190 for p in im.crop((25, 20, 135, 70)).getdata()) > 10) == visible
    fonts = tool.fonts()
    chosen = fonts[-1]["id"]
    font_plan = tool.revise(plan, {"cues": [dict(cues[0], font=chosen)]})
    assert chosen in tool.render(font_plan)["fonts"]
    with pytest.raises(OuttakeError, match="font"):
        tool.render(tool.revise(plan, {"overlay": {"text": "X", "font": "missing-font"}}))


def test_default_captions_preserve_edits_optout_and_staleness(tool, fixture_video):
    sidecar = fixture_video.with_suffix(".srt")
    sidecar.write_text(
        "1\n00:00:00,400 --> 00:00:01,100\nHello\n\n2\n00:00:01,500 --> 00:00:02,200\nBye\n"
    )
    try:
        plan = tool.plan(str(fixture_video), 0.5, 2)
        assert [c.text for c in plan.cues] == ["Hello", "Bye"]
        assert plan.caption_status == "imported"
        changed = [c.model_dump() for c in plan.cues]
        changed[0]["text"] = "Edited"
        revision = tool.revise(plan, {"cues": changed, "start": 0.7, "end": 1.8})
        assert revision.cues[0].start == 0.4
        assert revision.cues[0].id == plan.cues[0].id
        assert tool.get_plan(revision.id).cues[0].text == "Edited"
        assert not tool.plan(str(fixture_video), 0, 2, captions_enabled=False).cues
        sidecar.write_text(sidecar.read_text().replace("Hello", "Changed"))
        with pytest.raises(OuttakeError) as error:
            tool.render(revision)
        assert error.value.code == "STALE_SOURCE"
        refreshed = tool.import_captions(revision)
        assert refreshed.cues[0].text == "Changed"
        tool.validate(refreshed)
    finally:
        sidecar.unlink()


def test_named_exports_presets_and_deletion(tool, fixture_video):
    plan = tool.plan(
        str(fixture_video), 0, 1, title="Sushi / without paying?", profile="mobile", format="gif"
    )
    first, second = tool.render(plan), tool.render(plan)
    assert Path(first["artifact"]).name == "Sushi--without-paying.gif"
    assert first["frame_rate"] == "10"
    assert first["bytes"] == Path(first["artifact"]).stat().st_size
    assert first["artifact"] != second["artifact"]
    result = tool.delete_output(first["artifact_id"])
    assert result["status"] == "ready" and not Path(first["artifact"]).exists()
    assert tool.delete_output(first["artifact_id"])["already_absent"]
    assert tool.get_plan(plan.id) == plan and fixture_video.exists()
    assert tool.artifact(second["artifact_id"])["bytes"] > 0
    with pytest.raises(OuttakeError):
        tool.delete_output("../source")
