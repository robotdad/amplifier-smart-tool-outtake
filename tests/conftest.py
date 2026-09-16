import math
import struct
import subprocess
import wave

import pytest
from PIL import Image

from outtake import Outtake, Settings


@pytest.fixture(scope="session")
def fixture_video(tmp_path_factory):
    """Independent oracle: 10fps RGB bands and a tone starting at 1.2 seconds."""
    root = tmp_path_factory.mktemp("known-media")
    for frame in range(30):
        color = [(240, 0, 0), (0, 240, 0), (0, 0, 240)][frame // 10]
        image = Image.new("RGB", (160, 96), color)
        # Spatial marker gives each source frame a separately readable identity.
        for x in range(frame + 1):
            for y in range(5):
                image.putpixel((x, y), (255, 255, 255))
        image.save(root / f"{frame:03}.png")
    with wave.open(str(root / "tone.wav"), "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(48000)
        samples = [
            int(16000 * math.sin(2 * math.pi * 440 * n / 48000)) if 1.2 <= n / 48000 < 1.4 else 0
            for n in range(144000)
        ]
        audio.writeframes(struct.pack(f"<{len(samples)}h", *samples))
    video = root / "source.mkv"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-framerate",
            "10",
            "-i",
            str(root / "%03d.png"),
            "-i",
            str(root / "tone.wav"),
            "-c:v",
            "ffv1",
            "-c:a",
            "pcm_s16le",
            str(video),
        ],
        check=True,
    )
    return video


@pytest.fixture
def tool(tmp_path, fixture_video):
    return Outtake(
        Settings(
            source_roots=(str(fixture_video.parent),),
            output_root=str(tmp_path / "exports"),
            state_root=str(tmp_path / "state"),
        )
    )
