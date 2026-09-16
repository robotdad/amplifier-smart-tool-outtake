import json
import shutil
import struct
import subprocess
from pathlib import Path

import pytest
from PIL import Image
from pydantic import ValidationError

from outtake import Limits, Outtake, OuttakeError, Settings


def test_png_selects_first_frame_at_or_after_and_preserves_source(tool, fixture_video):
    original = fixture_video.read_bytes()
    plan = tool.plan(str(fixture_video), 0.95, 2.05, format="png")
    receipt = tool.render(plan)
    assert receipt["resolved_start"] == 1.0
    image = Image.open(receipt["artifact"]).convert("RGB")
    assert image.getpixel((80, 40)) == (0, 240, 0)
    # Frame index 10 has exactly 11 white pixels in row zero.
    assert sum(image.getpixel((x, 0)) == (255, 255, 255) for x in range(160)) == 11
    assert fixture_video.read_bytes() == original
    assert json.loads(Path(receipt["receipt"]).read_text())["sha256"] == receipt["sha256"]


def test_mp4_decoded_frames_and_audio_alignment(tool, fixture_video, tmp_path):
    plan = tool.plan(str(fixture_video), 0.95, 2.05, profile="editing")
    receipt = tool.render(plan)
    frames = subprocess.run(
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
    size = 160 * 96 * 3
    assert len(frames) // size == 11
    first = frames[(40 * 160 + 80) * 3 : (40 * 160 + 80) * 3 + 3]
    assert first[1] > 200 and first[0] < 10 and first[2] < 10
    audio = subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-i",
            receipt["artifact"],
            "-vn",
            "-f",
            "s16le",
            "-ac",
            "1",
            "-ar",
            "48000",
            "-",
        ],
        capture_output=True,
        check=True,
    ).stdout
    samples = struct.unpack(f"<{len(audio) // 2}h", audio)
    onset = next(i for i, sample in enumerate(samples) if abs(sample) > 4000) / 48000
    assert abs(onset - 0.2) < 0.025


def test_gif_animated_and_silent(tool, fixture_video):
    plan = tool.plan(str(fixture_video), 0.5, 2.5, format="gif")
    result = tool.render(plan)
    gif = Image.open(result["artifact"])
    assert gif.is_animated
    assert gif.n_frames >= 20
    assert result["audio"] == "none"
    gif.seek(0)
    assert gif.convert("RGB").getpixel((80, 40))[0] > 200
    gif.seek(gif.n_frames - 1)
    assert gif.convert("RGB").getpixel((80, 40))[2] > 200


def test_overlay_is_literal_data_and_changes_pixels(tool, fixture_video, tmp_path):
    text = "$(touch OWNED); %{pts}: [x] ' hi"
    plan = tool.plan(
        str(fixture_video),
        1,
        2,
        format="png",
        overlay={"text": text, "size": 12, "x": 0, "y": 0.3, "alignment": "left"},
    )
    result = tool.render(plan)
    image = Image.open(result["artifact"]).convert("RGB")
    assert any(image.getpixel((x, y)) != (0, 240, 0) for y in range(29, 55) for x in range(160))
    assert not Path("OWNED").exists()
    assert result["plan"]["overlay"]["text"] == text


def test_revision_and_saved_receipt_restore_without_overwrite(tool, fixture_video):
    first = tool.plan(str(fixture_video), 0, 1, format="png")
    exported = tool.render(first)
    revised = tool.revise(first, {"start": 1, "end": 2})
    second = tool.preview(revised)
    assert first.id != revised.id
    assert revised.parent_id == first.id and revised.revision == 2
    assert tool.get_plan(first.id) == first
    assert tool.get_plan(revised.id) == revised
    assert exported["artifact"] != second["artifact"]
    assert len(tool.saved_outputs()) == 1
    assert len(tool.saved_outputs(include_previews=True)) == 2
    assert Image.open(exported["artifact"]).getpixel((80, 40))[:3] == (240, 0, 0)
    assert Image.open(second["artifact"]).getpixel((80, 40))[:3] == (0, 240, 0)


def test_stale_source_and_symlink_escape(tmp_path, fixture_video):
    root = tmp_path / "media"
    root.mkdir()
    source = root / "copy.mkv"
    shutil.copy(fixture_video, source)
    tool = Outtake(
        Settings(
            source_roots=(str(root),),
            output_root=str(tmp_path / "out"),
            state_root=str(tmp_path / "state"),
        )
    )
    plan = tool.plan(str(source), 0, 1, format="png")
    source.write_bytes(source.read_bytes() + b"changed")
    with pytest.raises(OuttakeError, match="differs") as error:
        tool.render(plan)
    assert error.value.code == "STALE_SOURCE"
    source.unlink()
    source.symlink_to(fixture_video)
    with pytest.raises(OuttakeError) as error:
        tool.render(plan)
    assert error.value.code == "ACCESS_DENIED"
    assert tool.saved_outputs() == []


def test_cancel_and_output_limit_publish_nothing(tool, fixture_video):
    plan = tool.plan(str(fixture_video), 0, 1, format="png")
    with pytest.raises(OuttakeError) as error:
        tool.render(plan, cancelled=lambda: True)
    assert error.value.code == "CANCELLED"
    limited = Outtake(tool.settings.model_copy(update={"limits": Limits(max_output_bytes=1)}))
    with pytest.raises(OuttakeError) as error:
        limited.render(plan)
    assert error.value.code == "RESOURCE_LIMIT"
    assert list(tool.output.iterdir()) == []


def test_cancel_after_staging_begins_cleans_everything(tool, fixture_video):
    plan = tool.plan(str(fixture_video), 0, 2)

    def cancel_in_stage():
        return any(tool.output.glob(".outtake-*"))

    with pytest.raises(OuttakeError) as error:
        tool.render(plan, cancelled=cancel_in_stage)
    assert error.value.code == "CANCELLED"
    assert list(tool.output.iterdir()) == []
    assert tool.get_plan(plan.id) == plan


def test_cancellation_stops_running_renderer(tool, fixture_video, monkeypatch):
    from outtake import media

    plan = tool.plan(str(fixture_video), 0, 2)
    launched = []
    original = media.subprocess.Popen

    def track(argv, **kwargs):
        process = original(argv, **kwargs)
        if Path(argv[0]).name == "ffmpeg":
            launched.append(process)
        return process

    monkeypatch.setattr(media.subprocess, "Popen", track)
    with pytest.raises(OuttakeError) as error:
        tool.render(plan, cancelled=lambda: bool(launched))
    assert error.value.code == "CANCELLED"
    assert launched and all(p.poll() is not None for p in launched)
    assert list(tool.output.iterdir()) == []


def test_missing_ffmpeg_has_remedy(tool, fixture_video, monkeypatch):
    from outtake import media

    plan = tool.plan(str(fixture_video), 0, 1)
    original = media.shutil.which
    monkeypatch.setattr(
        media.shutil, "which", lambda name: None if name == "ffmpeg" else original(name)
    )
    with pytest.raises(OuttakeError) as error:
        tool.render(plan)
    assert error.value.code == "MISSING_PREREQUISITE"
    assert "Install FFmpeg" in error.value.remedy
    assert list(tool.output.iterdir()) == []


def test_mutating_retained_plan_requires_revision(tool, fixture_video):
    plan = tool.plan(str(fixture_video), 0, 1)
    changed = plan.model_dump()
    changed["end"] = 2
    with pytest.raises(OuttakeError) as error:
        tool.render(changed)
    assert error.value.code == "PLAN_CONFLICT"


def test_imported_plan_metadata_cannot_override_actual_duration(tool, fixture_video):
    plan = tool.plan(str(fixture_video), 0, 1)
    changed = plan.model_dump()
    changed["id"] = "plan_" + "0" * 32
    changed["source"]["duration"] = 999
    changed["end"] = 10
    with pytest.raises(OuttakeError) as error:
        tool.render(changed)
    assert error.value.code == "INVALID_PLAN"


def test_nonzero_video_timestamps(tmp_path):
    source = tmp_path / "offset.mkv"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=red:s=160x96:r=10:d=3",
            "-c:v",
            "ffv1",
            "-output_ts_offset",
            "5",
            str(source),
        ],
        check=True,
    )
    client = Outtake(
        Settings(
            source_roots=(str(tmp_path),),
            output_root=str(tmp_path / "out"),
            state_root=str(tmp_path / "state"),
        )
    )
    plan = client.plan(str(source), 0.95, 2, format="png")
    assert plan.source.duration == 3
    receipt = client.render(plan)
    assert receipt["resolved_start"] == 1
    assert Image.open(receipt["artifact"]).convert("RGB").getpixel((80, 40))[0] > 200


def test_playlist_is_not_a_supported_local_media_source(tool, fixture_video):
    playlist = fixture_video.parent / "external.m3u8"
    playlist.write_text(
        "#EXTM3U\n#EXT-X-TARGETDURATION:10\n#EXTINF:3,\nhttps://example.invalid/private.ts\n"
    )
    try:
        with pytest.raises(OuttakeError) as error:
            tool.inspect(str(playlist))
        assert error.value.code == "MEDIA_ERROR"
    finally:
        playlist.unlink()


@pytest.mark.parametrize(
    "changes", [{"start": float("nan")}, {"end": 99}, {"frame": -1}, {"format": "shell"}]
)
def test_invalid_plan_values(tool, fixture_video, changes):
    plan = tool.plan(str(fixture_video), 0, 1)
    with pytest.raises(ValidationError):
        tool.revise(plan, changes)
