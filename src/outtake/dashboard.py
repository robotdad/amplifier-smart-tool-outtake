"""Explicit loopback HTTP adapter. All media and configuration behavior is library-owned."""

import json
import mimetypes
import re
import secrets
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files
from pathlib import Path
from urllib.parse import parse_qs, quote, urlencode, urlparse

from pydantic import BaseModel, ValidationError

from .models import OuttakeError

OPERATIONS = {
    "caption_tracks",
    "caption_image",
    "fonts",
    "output_profiles",
    "import_captions",
    "convert_captions",
    "delete_output",
    "rename_output",
    "catalog",
    "source_details",
    "observe",
    "captions",
    "get_evidence",
    "find",
    "get_finding",
    "select",
    "make",
    "inspect",
    "plan",
    "get_plan",
    "revise",
    "validate",
    "preview",
    "render",
    "saved_outputs",
    "preferences",
    "configure",
    "review_frames",
    "artifact",
}
READ_ONLY = {
    "caption_tracks",
    "caption_image",
    "fonts",
    "output_profiles",
    "preferences",
    "get_plan",
    "get_finding",
    "get_evidence",
    "artifact",
    "saved_outputs",
}
CANCELLABLE = {
    "import_captions",
    "convert_captions",
    "find",
    "make",
    "inspect",
    "preview",
    "render",
    "review_frames",
}


def serializable(value):
    return value.model_dump(mode="json") if isinstance(value, BaseModel) else value


class Dashboard:
    def __init__(self, client, port=0, plan_id=None, finding_id=None):
        if not isinstance(port, int) or not 0 <= port <= 65535:
            raise ValueError("Port must be an integer between 0 and 65535.")
        self.client, self.token = client, secrets.token_urlsafe(32)
        self.jobs, self.lock = {}, threading.Lock()
        self.pool = ThreadPoolExecutor(max_workers=3, thread_name_prefix="outtake-ui")
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass  # Never log the session token or private media identifiers.

            def authorized(self):
                if self.headers.get("Host") != owner.authority:
                    return False
                if self.headers.get("Origin") not in (None, owner.origin):
                    return False
                bearer = self.headers.get("Authorization", "").removeprefix("Bearer ")
                cookie = SimpleCookie()
                try:
                    cookie.load(self.headers.get("Cookie", ""))
                except Exception:
                    return False
                candidate = bearer or (cookie["outtake"].value if "outtake" in cookie else "")
                return secrets.compare_digest(candidate, owner.token)

            def send_headers(self, status, kind, size=None):
                self.send_response(status)
                self.send_header("Content-Type", kind)
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.send_header("Referrer-Policy", "no-referrer")
                self.send_header(
                    "Content-Security-Policy",
                    "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self'; media-src 'self'; connect-src 'self'; frame-ancestors 'none'; object-src 'none'; base-uri 'none'",
                )
                if size is not None:
                    self.send_header("Content-Length", str(size))

            def respond(self, value, status=200):
                data = json.dumps(value, ensure_ascii=False).encode()
                self.send_headers(status, "application/json", len(data))
                self.end_headers()
                self.wfile.write(data)

            def do_POST(self):
                if not self.authorized():
                    return self.respond({"error": "Unauthorized dashboard request"}, 403)
                path = urlparse(self.path).path
                if path == "/api/session":
                    self.send_headers(200, "application/json", 2)
                    self.send_header(
                        "Set-Cookie", f"outtake={owner.token}; HttpOnly; SameSite=Strict; Path=/"
                    )
                    self.end_headers()
                    self.wfile.write(b"{}")
                    return
                try:
                    size = int(self.headers.get("Content-Length", "0"))
                    if (
                        not 0 < size <= 1_000_000
                        or self.headers.get_content_type() != "application/json"
                    ):
                        raise ValueError("Expected a JSON request of at most 1MB.")
                    value = json.loads(self.rfile.read(size))
                    if path == "/api/cancel":
                        with owner.lock:
                            job = owner.jobs[value["job_id"]]
                            job["stop"].set()
                        return self.respond(
                            {
                                "acknowledged": True,
                                "cleanup_complete": job["status"] in {"complete", "failed"},
                            }
                        )
                    if path != "/api/call":
                        return self.respond({"error": "Unknown route"}, 404)
                    return self.respond(
                        {"job_id": owner.call(value["operation"], value.get("arguments", {}))}, 202
                    )
                except (ValueError, TypeError, KeyError, OuttakeError) as exc:
                    return self.respond({"error": str(exc)}, 400)

            def do_GET(self):
                parsed = urlparse(self.path)
                if self.headers.get("Host") != owner.authority:
                    return self.respond({"error": "Invalid host"}, 403)
                assets = {"/": "index.html", "/app.js": "app.js", "/app.css": "app.css"}
                if parsed.path in assets:
                    name = assets[parsed.path]
                    data = files("outtake").joinpath("static", name).read_bytes()
                    self.send_headers(
                        200,
                        {
                            "index.html": "text/html; charset=utf-8",
                            "app.js": "text/javascript",
                            "app.css": "text/css",
                        }[name],
                        len(data),
                    )
                    self.end_headers()
                    self.wfile.write(data)
                    return
                if not self.authorized():
                    return self.respond({"error": "Unauthorized dashboard request"}, 403)
                if parsed.path.startswith("/api/jobs/"):
                    job_id = parsed.path.rsplit("/", 1)[-1]
                    with owner.lock:
                        job = owner.jobs.get(job_id)
                        snapshot = {k: v for k, v in job.items() if k != "stop"} if job else None
                    return self.respond(
                        snapshot or {"error": "Unknown job"}, 200 if snapshot else 404
                    )
                if parsed.path.startswith("/media/"):
                    try:
                        download_name = None
                        parts = parsed.path.split("/")
                        if len(parts) == 4 and parts[2] == "export":
                            receipt = owner.client.artifact(parts[3])
                            path = Path(receipt["artifact"])
                            from .editing import filename

                            download_name = filename(
                                receipt["plan"]["title"], receipt["plan"]["format"]
                            )
                        elif len(parts) == 5 and parts[2] == "subtitle":
                            path = Path(owner.client.caption_image(parts[3], int(parts[4]))["path"])
                        elif len(parts) == 5 and parts[2] == "frame":
                            evidence = owner.client.get_evidence(parts[3])
                            path = Path(evidence["frames"][int(parts[4])]["image"])
                            if path.is_symlink() or not path.resolve().is_relative_to(
                                owner.client.state / "frames"
                            ):
                                raise ValueError("Invalid frame reference")
                        else:
                            raise ValueError("Invalid media reference")
                        return self.media(path, "download" in parse_qs(parsed.query), download_name)
                    except (OuttakeError, OSError, ValueError, IndexError, KeyError):
                        return self.respond({"error": "Media unavailable"}, 404)
                return self.respond({"error": "Unknown route"}, 404)

            def media(self, path, download, download_name=None):
                size = path.stat().st_size
                start, end, status = 0, size - 1, 200
                requested = self.headers.get("Range")
                if requested:
                    match = re.fullmatch(r"bytes=(\d*)-(\d*)", requested)
                    if not match or not any(match.groups()):
                        return self.respond({"error": "Invalid range"}, 416)
                    if match[1]:
                        start = int(match[1])
                        end = min(size - 1, int(match[2]) if match[2] else size - 1)
                    else:
                        start = max(0, size - int(match[2]))
                    if start > end or start >= size:
                        return self.respond({"error": "Range outside file"}, 416)
                    status = 206
                self.send_headers(
                    status,
                    mimetypes.guess_type(path.name)[0] or "application/octet-stream",
                    end - start + 1,
                )
                self.send_header("Accept-Ranges", "bytes")
                if status == 206:
                    self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
                if download:
                    self.send_header(
                        "Content-Disposition",
                        f"attachment; filename*=UTF-8''{quote(download_name or path.name)}",
                    )
                self.end_headers()
                try:
                    with path.open("rb") as file:
                        file.seek(start)
                        remaining = end - start + 1
                        while remaining:
                            chunk = file.read(min(64 * 1024, remaining))
                            if not chunk:
                                break
                            self.wfile.write(chunk)
                            remaining -= len(chunk)
                except (BrokenPipeError, ConnectionResetError):
                    pass

        self.server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
        self.authority = f"127.0.0.1:{self.server.server_port}"
        self.origin = "http://" + self.authority
        query = {k: v for k, v in {"plan": plan_id, "finding": finding_id}.items() if v}
        self.url = (
            self.origin + "/" + ("?" + urlencode(query) if query else "") + "#token=" + self.token
        )
        self.thread = threading.Thread(
            target=self.server.serve_forever, name="outtake-dashboard", daemon=True
        )
        self.thread.start()

    def call(self, operation, arguments):
        if operation not in OPERATIONS or not isinstance(arguments, dict):
            raise ValueError("Unknown library capability or invalid arguments.")
        with self.lock:
            if operation not in READ_ONLY and any(
                j["status"] == "running" and j["operation"] not in READ_ONLY
                for j in self.jobs.values()
            ):
                raise ValueError("An operation is already running; wait or cancel it.")
            if len(self.jobs) >= 100:
                oldest = next(
                    (key for key, job in self.jobs.items() if job["status"] != "running"), None
                )
                if oldest is None:
                    raise ValueError("Too many pending requests. Wait for current work.")
                self.jobs.pop(oldest)
            job_id = uuid.uuid4().hex
            stop = threading.Event()
            self.jobs[job_id] = {"status": "running", "operation": operation, "stop": stop}

        def execute():
            try:
                kwargs = dict(arguments)
                if operation in CANCELLABLE:
                    kwargs["cancelled"] = stop.is_set
                value = getattr(self.client, operation)(**kwargs)
                result = {"status": "complete", "result": serializable(value)}
            except OuttakeError as exc:
                result = {"status": "failed", "result": exc.result()}
            except (ValueError, TypeError, OSError, ValidationError) as exc:
                result = {
                    "status": "failed",
                    "result": {
                        "status": "failed",
                        "error": {
                            "message": str(exc),
                            "remediation": "Check the request and configured folders.",
                        },
                    },
                }
            except Exception:
                result = {
                    "status": "failed",
                    "result": {
                        "status": "failed",
                        "error": {
                            "message": "Operation failed unexpectedly.",
                            "remediation": "Inspect the retained request or retry with a new request ID.",
                        },
                    },
                }
            with self.lock:
                self.jobs[job_id].update(result)

        self.pool.submit(execute)
        return job_id

    def close(self):
        with self.lock:
            for job in self.jobs.values():
                job["stop"].set()
        self.server.shutdown()
        self.server.server_close()
        self.pool.shutdown(wait=True, cancel_futures=True)
        self.thread.join(timeout=3)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
