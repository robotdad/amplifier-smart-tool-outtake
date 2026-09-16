import shutil

import pytest
from PIL import Image

from outtake import Outtake, OuttakeError, Settings


def source_id(tool):
    return tool.catalog(title="source")["sources"][0]["id"]


def test_catalog_bounded_and_scoped(tool, fixture_video, tmp_path):
    result = tool.catalog("source")
    assert result["status"] == "ready"
    assert len(result["sources"]) == 1
    assert result["sources"][0]["identity_verified"] is False
    assert tool.catalog("missing")["sources"] == []
    assert tool.catalog(scan_limit=1)["status"] == "partial"
    with pytest.raises(OuttakeError) as error:
        tool.catalog(scope=str(tmp_path))
    assert error.value.code == "ACCESS_DENIED"


def test_ordered_frame_evidence_has_real_images_and_gaps(tool):
    evidence = tool.observe(source_id(tool), [0.95, 1.5, 2.1])
    assert [f["time"] for f in evidence["frames"]] == [1, 1.5, 2.1]
    assert evidence["sampling_gaps"] == pytest.approx([0.5, 0.6])
    assert Image.open(evidence["frames"][0]["image"]).getpixel((80, 40))[:3] == (0, 240, 0)
    assert Image.open(evidence["frames"][-1]["image"]).getpixel((80, 40))[:3] == (0, 0, 240)
    assert tool.get_evidence(evidence["id"]) == evidence
    assert tool.saved_outputs() == []
    with pytest.raises(OuttakeError):
        tool.observe(source_id(tool), [1.5, 0.95])


def test_srt_search_repeated_lines_and_offset(tmp_path, fixture_video):
    source = tmp_path / "Title.mkv"
    shutil.copy(fixture_video, source)
    source.with_suffix(".srt").write_text(
        "1\n00:00:00,100 --> 00:00:00,500\nplate of shrimp\n\n2\n00:00:01,200 --> 00:00:01,700\nPlate of shrimp again\n"
    )
    client = Outtake(
        Settings(
            source_roots=(str(tmp_path),),
            output_root=str(tmp_path / "out"),
            state_root=str(tmp_path / "state"),
        )
    )
    sid = client.catalog("Title")["sources"][0]["id"]
    assert client.source_details(sid)["caption_tracks"][0]["id"] == "sidecar"
    evidence = client.captions(sid, "plate of shrimp", offset=0.1)
    assert len(evidence["hits"]) == 2
    assert evidence["hits"][1]["start"] == pytest.approx(1.3)
    assert evidence["offset"] == 0.1
    assert client.captions(sid, "missing")["hits"] == []


def test_missing_captions_does_not_block_frames(tool):
    sid = source_id(tool)
    with pytest.raises(OuttakeError) as error:
        tool.captions(sid, "hello")
    assert error.value.code == "MISSING_TEXT_CAPTIONS"
    assert len(tool.observe(sid, [1])["frames"]) == 1


def test_source_id_does_not_override_new_roots(tool, tmp_path):
    sid = source_id(tool)
    restricted = Outtake(
        Settings(
            source_roots=(str(tmp_path),), state_root=str(tool.state), output_root=str(tool.output)
        )
    )
    with pytest.raises(OuttakeError) as error:
        restricted.observe(sid, [1])
    assert error.value.code == "ACCESS_DENIED"


def test_embedded_text_captions(tmp_path, fixture_video):
    import subprocess

    subtitles = tmp_path / "lines.srt"
    subtitles.write_text("1\n00:00:01,200 --> 00:00:01,700\nA remembered line\n")
    video = tmp_path / "embedded.mkv"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-i",
            str(fixture_video),
            "-i",
            str(subtitles),
            "-map",
            "0",
            "-map",
            "1",
            "-c",
            "copy",
            "-metadata:s:s:0",
            "language=eng",
            str(video),
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
    sid = client.catalog("embedded")["sources"][0]["id"]
    track = client.source_details(sid)["caption_tracks"][0]
    evidence = client.captions(sid, "remembered", track=track["id"])
    assert evidence["language"] == "eng"
    assert evidence["hits"][0]["start"] == 1.2


def test_resolution_metadata_does_not_hash_unselected_sources(tool, monkeypatch):
    source_id = tool.catalog("source")["sources"][0]["id"]

    def unexpected_hash(*args, **kwargs):
        raise AssertionError("Metadata-only resolution must not read the full source")

    monkeypatch.setattr(tool, "_inspect", unexpected_hash)
    details = tool.source_details(source_id, fingerprint_source=False)
    assert details["fingerprinted"] is False
    assert "sha256" not in details["source"]
    assert details["source"]["width"] == 160
    assert details["source"]["duration"] == 3
