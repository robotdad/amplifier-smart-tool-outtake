"""Argument and JSON I/O adapter; domain behavior lives in the library."""

import argparse
import json
import sys
import threading
from pathlib import Path

from pydantic import BaseModel, ValidationError

from .capabilities import OPERATIONS
from .lib import Outtake, manifest, schemas, skill
from .models import OuttakeError


def _read(path):
    return json.loads(sys.stdin.read() if path == "-" else Path(path).read_text())


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if argv == ["--help"]:
        print(skill())
        return 0
    parser = argparse.ArgumentParser(
        description="Outtake: local media library and bounded Amplifier finding."
    )
    commands = parser.add_subparsers(dest="command", required=True)
    dashboard = commands.add_parser("dashboard", help="Explicitly launch the local workspace.")
    dashboard.add_argument("--settings", required=True)
    dashboard.add_argument(
        "--saved-settings",
        action="store_true",
        help="Explicitly reuse folders and limits saved in this workspace.",
    )
    dashboard.add_argument("--port", type=int, default=0)
    dashboard.add_argument("--plan-id")
    dashboard.add_argument("--finding-id")
    for name, description in {
        "manifest": "Read the packaged manifest.",
        "schemas": "Read public JSON schemas.",
        **OPERATIONS,
    }.items():
        command = commands.add_parser(name, help=description, description=description)
        if name in OPERATIONS:
            command.add_argument(
                "--settings", required=True, help="Caller-owned Settings JSON file."
            )
            command.add_argument(
                "--saved-settings",
                action="store_true",
                help="Reuse caller-saved workspace folders and limits.",
            )
            command.add_argument(
                "--input",
                default="-",
                help="Request JSON file or - for stdin (default). Empty input is invalid.",
            )
    args = parser.parse_args(argv)
    try:
        if args.command == "dashboard":
            client = Outtake(_read(args.settings))
            if args.saved_settings:
                client.restore_configuration()
            with client.dashboard(
                port=args.port, plan_id=args.plan_id, finding_id=args.finding_id
            ) as server:
                print(json.dumps({"status": "ready", "url": server.url}), flush=True)
                threading.Event().wait()
            return 0
        if args.command == "manifest":
            result = manifest()
        elif args.command == "schemas":
            result = schemas()
        else:
            settings = _read(args.settings)
            request = _read(args.input)
            if not isinstance(request, dict):
                raise OuttakeError(
                    "INVALID_INPUT",
                    "Request must be a JSON object.",
                    "Read capability --help and schemas.",
                )
            client = Outtake(settings)
            if args.saved_settings:
                client.restore_configuration()
            result = getattr(client, args.command.replace("-", "_"))(**request)
        if isinstance(result, BaseModel):
            result = result.model_dump()
        print(json.dumps(result, ensure_ascii=False))
        return (
            1 if isinstance(result, dict) and result.get("status") in {"failed", "cancelled"} else 0
        )
    except OuttakeError as exc:
        print(json.dumps(exc.result()), file=sys.stdout)
        return 1
    except (ValidationError, ValueError, TypeError, OSError) as exc:
        message = str(exc)
        if isinstance(exc, ValidationError):
            message = "; ".join(f"{e['loc']}: {e['msg']}" for e in exc.errors(include_input=False))
        error = OuttakeError(
            "INVALID_INPUT",
            message,
            "Check request/settings JSON against outtake schemas and capability --help.",
        )
        print(json.dumps(error.result()))
        return 2
    except KeyboardInterrupt:
        print(
            json.dumps(
                OuttakeError(
                    "CANCELLED",
                    "Interrupted; temporary output cleaned up.",
                    "Existing exports remain available.",
                ).result()
            )
        )
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
