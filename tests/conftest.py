import math
import struct
import subprocess
import wave

import pytest
from PIL import Image, ImageDraw, ImageFont

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


@pytest.fixture
def bitmap_source(tmp_path):
    image = Image.new("L", (140, 30))
    ImageDraw.Draw(image).text((3, 3), "HELLO", font=ImageFont.load_default(size=24), fill=255)

    def segment(t, kind, data):
        return b"PG" + struct.pack(">IIBH", int(t * 90000), 0, kind, len(data)) + data

    def composition(t, number, clear=False):
        data = struct.pack(
            ">HHBHBBBB", 160, 96, 0x10, number, 0x80 if number == 0 else 0, 0, 0, 0 if clear else 1
        )
        if not clear:
            data += struct.pack(">HBBHH", 0, 0, 0, 10, 50)
        return segment(t, 0x16, data)

    rle = b"".join(
        b"".join(
            b"\x01" if image.getpixel((x, y)) > 127 else b"\x00\x01" for x in range(image.width)
        )
        + b"\x00\x00"
        for y in range(image.height)
    )
    objects = (
        struct.pack(">HBB", 0, 0, 0xC0)
        + (len(rle) + 4).to_bytes(3, "big")
        + struct.pack(">HH", *image.size)
        + rle
    )
    data = composition(0.5, 0)
    data += segment(0.5, 0x17, struct.pack(">BBHHHH", 1, 0, 10, 50, 140, 30))
    data += segment(0.5, 0x14, bytes([0, 0, 0, 16, 128, 128, 0, 1, 235, 128, 128, 255]))
    data += segment(0.5, 0x15, objects) + segment(0.5, 0x80, b"")
    data += composition(1.5, 1, True) + segment(1.5, 0x80, b"")
    subtitle = tmp_path / "captions.sup"
    subtitle.write_bytes(data)
    source = tmp_path / "source.mkv"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-copyts",
            "-f",
            "lavfi",
            "-i",
            "color=red:s=160x96:r=10:d=3",
            "-i",
            str(subtitle),
            "-map",
            "0:v",
            "-map",
            "1:s",
            "-vf",
            "setsar=2/1",
            "-c:v",
            "ffv1",
            "-c:s",
            "copy",
            "-disposition:s:0",
            "default",
            "-metadata:s:s:0",
            "language=eng",
            str(source),
        ],
        check=True,
    )
    return source


@pytest.fixture
def bitmap_tool(tmp_path, bitmap_source):
    return Outtake(
        Settings(
            source_roots=(str(bitmap_source.parent),),
            output_root=str(tmp_path / "exports"),
            state_root=str(tmp_path / "state"),
        )
    )
