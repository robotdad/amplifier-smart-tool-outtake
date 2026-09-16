"""Bounded bitmap timing decoder, isolated so callers can cancel native decoding."""

import json
import sys

import av

from .media import FORMATS


def decode(request):
    events = []
    with av.open(
        request["path"], options={"protocol_whitelist": "file", "format_whitelist": FORMATS}
    ) as container:
        stream = container.streams[request["stream"]]
        for count, packet in enumerate(container.demux(stream)):
            if count >= 100_000:
                raise ValueError("Subtitle packet allowance exceeded")
            if not packet.size:
                continue
            subtitle = stream.codec_context.decode2(packet)
            if subtitle is None:
                continue
            pts = (
                subtitle.pts / 1_000_000
                if subtitle.pts is not None
                else float(packet.pts * packet.time_base)
            )
            start = pts + subtitle.start_display_time / 1000
            # A following display/clear event ends indefinite PGS displays.
            if events and events[-1]["end"] is None:
                events[-1]["end"] = start
                if start <= request["start"]:
                    events.pop()
            if start >= request["end"]:
                break
            end = pts + subtitle.end_display_time / 1000
            if subtitle.end_display_time >= 0xFFFFFFFF or end <= start:
                end = (
                    float((packet.pts + packet.duration) * packet.time_base)
                    if packet.duration
                    else None
                )
            rects = list(subtitle)
            if not rects:
                continue
            if any(r.type != b"bitmap" for r in rects):
                raise ValueError("Expected image subtitles")
            if any(r.width * r.height > 4096 * 2160 for r in rects):
                raise ValueError("Subtitle dimensions exceed allowance")
            if end is None or end > request["start"]:
                events.append({"start": start, "end": end})
            if len(events) > 100:
                raise ValueError("More than 100 subtitle displays intersect the cut")
    for event in events:
        if event["end"] is None:
            event["end"] = request["end"]
    return [e for e in events if e["end"] > request["start"] and e["start"] < request["end"]]


if __name__ == "__main__":
    print(json.dumps(decode(json.loads(sys.argv[1])), allow_nan=False))
