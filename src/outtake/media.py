"""Local media operations. No shell, arbitrary filter input, or model dependency."""

import hashlib
import json
import shutil
import subprocess
import tempfile
import threading
import time
from collections import OrderedDict
from pathlib import Path

from .models import Limits, OuttakeError

FORMATS = "matroska,webm,mov,mp4,m4a,3gp,3g2,mj2,avi,mpegts"
INPUT_OPTIONS = ["-protocol_whitelist", "file", "-format_whitelist", FORMATS]
_HASH_CACHE = OrderedDict()
_HASH_LOCK = threading.Lock()


class Budget:
    def __init__(self, limits: Limits, cancelled=lambda: False):
        self.limits, self.cancelled = limits, cancelled
        self.deadline = time.monotonic() + limits.timeout_seconds

    def check(self, *directories: Path | None):
        if self.cancelled():
            raise OuttakeError(
                "CANCELLED",
                "Operation cancelled; cleanup completes before return.",
                "Retained plans and published exports are still available.",
            )
        if time.monotonic() >= self.deadline:
            raise OuttakeError(
                "RESOURCE_LIMIT",
                "Operation exceeded its wall-time limit.",
                "Use a shorter range or explicitly increase the time limit.",
            )
        if (
            sum(
                p.stat().st_size
                for directory in directories
                if directory
                for p in directory.rglob("*")
                if p.is_file()
            )
            > self.limits.max_temporary_bytes
        ):
            raise OuttakeError(
                "RESOURCE_LIMIT",
                "Operation exceeded temporary-space allowance.",
                "Reduce output size or increase max_temporary_bytes.",
            )


def run(executable: str, arguments: list[str], budget: Budget, directory: Path | None = None):
    binary = shutil.which(executable)
    if not binary:
        raise OuttakeError(
            "MISSING_PREREQUISITE",
            f"{executable} is not installed.",
            "Install FFmpeg with FFprobe and put both executables on PATH.",
        )
    budget.check(directory)
    with tempfile.TemporaryDirectory(prefix="outtake-process-") as scratch:
        root = Path(scratch)
        with (root / "stdout").open("w+b") as stdout, (root / "stderr").open("w+b") as stderr:
            process = subprocess.Popen(
                [binary, *arguments], stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr
            )
            try:
                while process.poll() is None:
                    budget.check(directory, root)
                    if stdout.tell() + stderr.tell() > min(
                        32 * 1024**2, budget.limits.max_temporary_bytes
                    ):
                        raise OuttakeError(
                            "RESOURCE_LIMIT",
                            "Media diagnostics exceeded allowance.",
                            "Inspect a smaller interval.",
                        )
                    time.sleep(0.025)
                budget.check(directory, root)
                if stdout.tell() + stderr.tell() > min(
                    32 * 1024**2, budget.limits.max_temporary_bytes
                ):
                    raise OuttakeError(
                        "RESOURCE_LIMIT",
                        "Media diagnostics exceeded allowance.",
                        "Inspect a smaller interval.",
                    )
                stdout.seek(0)
                stderr.seek(0)
                if process.returncode:
                    detail = stderr.read(4000).decode(errors="replace")
                    raise OuttakeError(
                        "MEDIA_ERROR",
                        f"{executable} failed: {detail}",
                        "Check the input is a supported local video and the requested range exists.",
                    )
                return stdout.read().decode(errors="replace")
            finally:
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()


def fingerprint(path: Path, budget: Budget):
    budget.check()
    before = path.stat()
    key = (
        str(path.resolve()),
        before.st_dev,
        before.st_ino,
        before.st_size,
        before.st_mtime_ns,
        before.st_ctime_ns,
    )
    with _HASH_LOCK:
        if key in _HASH_CACHE:
            _HASH_CACHE.move_to_end(key)
            return _HASH_CACHE[key]
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            budget.check()
            digest.update(chunk)
    after = path.stat()
    if (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (
        after.st_size,
        after.st_mtime_ns,
        after.st_ctime_ns,
    ):
        raise OuttakeError(
            "STALE_SOURCE", "File changed while hashing.", "Retry when source writes have stopped."
        )
    result = digest.hexdigest()
    with _HASH_LOCK:
        _HASH_CACHE[key] = result
        while len(_HASH_CACHE) > 128:
            _HASH_CACHE.popitem(last=False)
    return result


def probe(path: Path, budget: Budget):
    return json.loads(
        run(
            "ffprobe",
            [
                "-v",
                "error",
                *INPUT_OPTIONS,
                "-show_streams",
                "-show_format",
                "-of",
                "json",
                str(path),
            ],
            budget,
        )
    )


def video_stream(info):
    streams = [
        s
        for s in info["streams"]
        if s["codec_type"] == "video" and not s.get("disposition", {}).get("attached_pic")
    ]
    if not streams:
        raise OuttakeError("NO_VIDEO", "Source has no video stream.", "Select a video source.")
    return streams[0]


def frame_at(path: Path, seconds: float, info, budget: Budget):
    """Seek backwards to a keyframe, then select the first actual presentation time >= request."""
    stream = video_stream(info)
    origin = float(stream.get("start_time", 0))
    target = seconds + origin
    frames = json.loads(
        run(
            "ffprobe",
            [
                "-v",
                "error",
                *INPUT_OPTIONS,
                "-select_streams",
                str(stream["index"]),
                "-read_intervals",
                f"{target:.9f}%{target + 5:.9f}",
                "-show_frames",
                "-show_entries",
                "frame=best_effort_timestamp_time",
                "-of",
                "json",
                str(path),
            ],
            budget,
        )
    ).get("frames", [])
    times = [
        float(f["best_effort_timestamp_time"]) for f in frames if "best_effort_timestamp_time" in f
    ]
    matches = [t for t in times if t + 0.0000001 >= target]
    if not matches:
        raise OuttakeError(
            "NO_FRAME",
            "No frame was found at or after the requested time.",
            "Move the boundary earlier or select another source.",
        )
    return min(matches), origin
