"""Public Outtake capabilities. CLI and future dashboard call this module."""

import importlib.resources
import json
import os
import re
import sys
import tempfile
import threading
import uuid
from datetime import datetime, timezone
from functools import wraps
from pathlib import Path

import yaml
from PIL import Image, ImageDraw

from .capabilities import OPERATIONS
from .media import INPUT_OPTIONS, Budget, fingerprint, frame_at, probe, run, video_stream
from .models import (
    CandidateInput,
    FindRequest,
    ModelGrant,
    OuttakeError,
    Overlay,
    Plan,
    Settings,
    Source,
    TextCue,
)

_RENDER_LOCK = threading.Lock()


def _io_errors(method):
    @wraps(method)
    def call(*args, **kwargs):
        try:
            return method(*args, **kwargs)
        except OSError as exc:
            raise OuttakeError(
                "IO_ERROR",
                str(exc),
                "Check the configured folders, permissions, and available disk space.",
            ) from exc

    return call


def manifest():
    text = importlib.resources.files("outtake").joinpath("SMART_TOOL.md").read_text()
    _, frontmatter, body = text.split("---", 2)
    return {**yaml.safe_load(frontmatter), "body": body.strip()}


def skill(command=None):
    if command is not None:
        from .help import command_skill

        return command_skill(command)
    from .help import EXTRA_COMMANDS

    root = importlib.resources.files("outtake")
    return (
        f'<skill_content name="outtake">\nSkill directory: {root}\n'
        "Repository: https://github.com/robotdad/amplifier-smart-tool-outtake\n\n"
        + manifest()["body"]
        + "\n## Available capabilities\n"
        + "\n".join(
            f"- `{name}` [{'model-backed' if name in {'find', 'make'} else 'deterministic'}] — {description} See `outtake {name} --help`."
            for name, description in {**OPERATIONS, **EXTRA_COMMANDS}.items()
        )
        + "\n<skill_resources>\n<file>lib.py</file>\n"
        "<file>models.py</file>\n</skill_resources>\n</skill_content>"
    )


def schemas():
    return {
        "TextCue": TextCue.model_json_schema(),
        "schema_version": 1,
        "plan": Plan.model_json_schema(),
        "settings": Settings.model_json_schema(),
        "overlay": Overlay.model_json_schema(),
        "find_request": FindRequest.model_json_schema(),
        "model_grant": ModelGrant.model_json_schema(),
        "candidate_input": CandidateInput.model_json_schema(),
    }


def _id(kind):
    return kind + "_" + uuid.uuid4().hex


def _write(path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _inside(path: Path, roots):
    resolved = path.expanduser().resolve()
    if not any(resolved.is_relative_to(root) for root in roots):
        raise OuttakeError(
            "ACCESS_DENIED",
            "Path is outside caller-approved roots.",
            "Select a path in configured roots or explicitly change caller settings.",
        )
    return resolved


class Outtake:
    """Caller-selected filesystem authority. No provider or server is started.

    Settings are trusted caller input; do not construct Settings from a model's plan.
    Methods accept model objects or ordinary JSON-compatible dictionaries.
    """

    @_io_errors
    def __init__(self, settings: Settings | dict):
        self.settings = Settings.model_validate(settings)
        self.roots = tuple(
            Path(p).expanduser().resolve(strict=True) for p in self.settings.source_roots
        )
        if not all(p.is_dir() for p in self.roots):
            raise OuttakeError(
                "INVALID_ROOT", "Source roots must be directories.", "Choose existing folders."
            )
        self.output = Path(self.settings.output_root).expanduser().resolve()
        default_state = (
            Path.home() / "Library" / "Application Support" / "Outtake"
            if sys.platform == "darwin"
            else Path.home() / ".local" / "state" / "outtake"
        )
        state = self.settings.state_root or str(default_state)
        self.state = Path(state).expanduser().resolve()
        self.output.mkdir(parents=True, exist_ok=True)
        (self.state / "plans").mkdir(parents=True, exist_ok=True)

    def _source(self, path):
        source = _inside(Path(path), self.roots)
        if not source.is_file():
            raise OuttakeError(
                "SOURCE_MISSING",
                "Source is not a readable regular file.",
                "Choose an existing video.",
            )
        return source

    @_io_errors
    def preferences(self):
        from .workspace import preferences

        return preferences(self)

    @_io_errors
    def restore_configuration(self):
        """Explicitly trust saved workspace settings as caller-selected authority."""
        path = self.state / "preferences.json"
        if path.exists():
            saved = json.loads(path.read_text())
            return self.configure(
                saved["settings"], saved.get("model_grant"), saved.get("appearance", "system")
            )
        return self.preferences()

    @_io_errors
    def configure(self, settings: dict, model_grant: dict | None = None, appearance="system"):
        from .workspace import configure

        return configure(self, settings, model_grant, appearance)

    @_io_errors
    def review_frames(self, plan: Plan | dict, *, cancelled=lambda: False):
        from .workspace import review_frames

        return review_frames(self, Plan.model_validate(plan), cancelled)

    @_io_errors
    def artifact(self, artifact_id: str):
        from .workspace import artifact

        return artifact(self, artifact_id)

    def dashboard(self, port=0, plan_id=None, finding_id=None):
        """Explicitly start a loopback dashboard; returns a handle with url and close()."""
        from .dashboard import Dashboard

        return Dashboard(self, port=port, plan_id=plan_id, finding_id=finding_id)

    @_io_errors
    def inspect(self, source: str, *, cancelled=lambda: False):
        budget = Budget(self.settings.limits, cancelled)
        return self._inspect(source, budget)

    def _inspect(self, source, budget):
        path = self._source(source)
        info = probe(path, budget)
        stream = video_stream(info)
        self._check_media(info)
        duration = self._duration(info)
        before = path.stat()
        digest = fingerprint(path, budget)
        after = path.stat()
        if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
            raise OuttakeError(
                "STALE_SOURCE", "Source changed during inspection.", "Retry after writes complete."
            )
        return Source(
            path=str(path),
            sha256=digest,
            bytes=after.st_size,
            duration=duration,
            width=stream["width"],
            height=stream["height"],
            has_audio=any(s["codec_type"] == "audio" for s in info["streams"]),
            color_transfer=stream.get("color_transfer", "unspecified"),
            sample_aspect_ratio=stream.get("sample_aspect_ratio", "1:1"),
        )

    @_io_errors
    def catalog(
        self, title: str = "", scope: str | None = None, limit: int = 20, scan_limit: int = 5000
    ):
        """Bounded filename discovery; names are clues, never verified title identities."""
        from .discovery import catalog

        return catalog(self, title, scope, limit, scan_limit, Budget(self.settings.limits))

    @_io_errors
    def observe(self, source_id: str, times: list[float]):
        """Extract local timestamped frame evidence without any provider disclosure."""
        from .discovery import observe

        return observe(self, source_id, times, Budget(self.settings.limits))

    @_io_errors
    def captions(
        self, source_id: str, query: str, track: str = "sidecar", offset: float = 0, limit: int = 20
    ):
        """Search existing text captions only; no transcription or OCR."""
        from .discovery import captions

        return captions(self, source_id, query, track, offset, limit, Budget(self.settings.limits))

    @_io_errors
    def source_details(self, source_id: str, fingerprint_source: bool = True):
        from .discovery import details

        return details(self, source_id, Budget(self.settings.limits), fingerprint_source)

    @_io_errors
    def get_evidence(self, evidence_id: str):
        from .discovery import load_record

        return load_record(self, "evidence", evidence_id)

    @_io_errors
    def find(
        self,
        request: FindRequest | dict,
        grant: ModelGrant | dict | None = None,
        *,
        cancelled=lambda: False,
    ):
        """Run a bounded Amplifier search, or return its retained idempotent result."""
        from .intelligence import find

        return find(self, request, grant, cancelled)

    @_io_errors
    def get_finding(self, finding_id: str):
        from .discovery import load_record

        return load_record(self, "findings", finding_id)

    @_io_errors
    def select(
        self,
        finding_id: str,
        candidate_id: str,
        format="mp4",
        profile="share",
        overlay=None,
        plan_id: str | None = None,
    ):
        """Select a retained, source-checked candidate without another model call."""
        from .intelligence import select

        return select(self, finding_id, candidate_id, format, profile, overlay, plan_id=plan_id)

    @_io_errors
    def make(
        self,
        request: FindRequest | dict,
        grant: ModelGrant | dict | None = None,
        format="mp4",
        profile="share",
        *,
        cancelled=lambda: False,
    ):
        """Find and render only a single evidenced proposal; ambiguity stays selectable."""
        from .intelligence import make

        return make(self, request, grant, format, profile, cancelled)

    @staticmethod
    def _check_media(info):
        stream = video_stream(info)
        if stream.get("color_transfer") in ("smpte2084", "arib-std-b67") or any(
            "DOVI" in s.get("side_data_type", "") for s in stream.get("side_data_list", [])
        ):
            raise OuttakeError(
                "HDR_UNSUPPORTED",
                "HDR rendering is not yet implemented.",
                "Choose an SDR source; no implicit tone mapping is performed.",
            )
        if any(s.get("rotation", 0) for s in stream.get("side_data_list", [])):
            raise OuttakeError(
                "ROTATION_UNSUPPORTED",
                "Rotated video is not yet supported.",
                "Choose an unrotated source.",
            )

    @staticmethod
    def _duration(info):
        stream = video_stream(info)
        duration = stream.get("duration") or info["format"].get("duration")
        if not duration:
            raise OuttakeError(
                "TIMING_UNAVAILABLE",
                "No finite source duration is available.",
                "Use a seekable local video.",
            )
        # Matroska's Duration is the ending segment timestamp, which may include
        # a non-zero start offset. Other demuxers report an elapsed duration.
        if not stream.get("duration") and "matroska" in info["format"]["format_name"]:
            return float(duration) - float(stream.get("start_time", 0))
        return float(duration)

    def _retain(self, plan):
        # Unique names and atomic replace prevent a reader observing an incomplete plan.
        directory = self.state / "plans"
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", dir=directory, delete=False, encoding="utf-8"
            ) as file:
                temporary = Path(file.name)
                file.write(plan.model_dump_json(indent=2))
            temporary.replace(directory / f"{plan.id}.json")
        finally:
            if temporary:
                temporary.unlink(missing_ok=True)
        return plan

    @_io_errors
    def plan(
        self,
        source: str,
        start: float,
        end: float,
        *,
        format="mp4",
        profile="share",
        audio=None,
        frame=None,
        overlay=None,
        title="",
        cues=(),
        captions_enabled=True,
        max_width=None,
        fps=None,
    ):
        """Create and retain a caller-range plan. Seconds are relative to first video PTS."""
        source_info = self.inspect(source)
        plan = Plan(
            id=_id("plan"),
            source=source_info,
            start=start,
            end=end,
            frame=start if frame is None else frame,
            format=format,
            profile=profile,
            audio=audio or ("preserve" if format == "mp4" else "mute"),
            overlay=overlay,
            title=title or Path(source).stem[:120],
            cues=cues,
            captions_enabled=captions_enabled,
            max_width=max_width,
            fps=fps,
        )
        self._check_duration(plan)
        if captions_enabled:
            from .editing import import_captions

            plan = import_captions(self, plan)
        return self._retain(plan)

    def caption_tracks(self, plan):
        plan = Plan.model_validate(plan)
        path = self._source(plan.source.path)
        info = probe(path, Budget(self.settings.limits))
        from .subtitles import tracks

        return tracks(path, info)

    @_io_errors
    def caption_image(self, evidence_id, index):
        """Resolve one retained source subtitle image for local inspection."""
        from .discovery import validate_evidence
        from .subtitles import image_path

        evidence = self.get_evidence(evidence_id)
        if (
            evidence["kind"] != "image_captions"
            or not isinstance(index, int)
            or not 0 <= index < len(evidence["hits"])
        ):
            raise OuttakeError(
                "INVALID_EVIDENCE",
                "Unknown subtitle image.",
                "Use an image caption evidence ID and valid index.",
            )
        budget = Budget(self.settings.limits)
        validate_evidence(self, evidence, budget)
        hit = evidence["hits"][index]
        return {**hit, "path": str(image_path(self, evidence, hit, budget))}

    @staticmethod
    def fonts():
        from .editing import fonts

        return fonts()

    @staticmethod
    def output_profiles():
        return {
            "mobile": {"max_width": 480, "gif_fps": 10, "mp4_fps": 24},
            "share": {"max_width": 1280, "gif_fps": 15, "mp4_fps": 30},
            "editing": {"max_width": 8192, "gif_fps": 15, "mp4_fps": "source"},
        }

    @_io_errors
    def import_captions(self, plan, track=None, offset=0, cancelled=lambda: False):
        from .editing import import_captions

        base = Plan.model_validate(plan)
        budget = Budget(self.settings.limits, cancelled)
        self._check_identity(base)
        source = self._inspect(base.source.path, budget)
        if source.sha256 != base.source.sha256:
            raise OuttakeError(
                "STALE_SOURCE",
                "Video source changed.",
                "Create a new plan from the current source.",
            )
        result = import_captions(self, base, track, offset, budget)
        result = result.model_copy(
            update={"id": _id("plan"), "parent_id": base.id, "revision": base.revision + 1}
        )
        return self._retain(result)

    @_io_errors
    def convert_captions(self, plan, language=None, cancelled=lambda: False):
        """Explicit local OCR; new revision, manual cues retained, OCR requires review."""
        from .subtitles import convert

        base = Plan.model_validate(plan)
        budget = Budget(self.settings.limits, cancelled)
        self._validate(base, budget)
        result = convert(self, base, language, budget)
        return self._retain(
            result.model_copy(
                update={
                    "id": _id("plan"),
                    "parent_id": base.id,
                    "revision": base.revision + 1,
                }
            )
        )

    def provider_login(
        self, provider: str, timeout_seconds: int = 300, *, progress=lambda message: None
    ):
        """Explicit device login; progress reports the verification URL/code."""
        from .providers import login

        return login(provider, timeout_seconds, progress)

    @_io_errors
    def rename_output(self, artifact_id: str, title: str, expected_plan_id=None):
        from .workspace import rename_output

        return rename_output(self, artifact_id, title, expected_plan_id)

    @_io_errors
    def delete_output(self, artifact_id, expected_plan_id=None):
        from .editing import delete_output
        from .workspace import artifact, output_lock

        with output_lock(self):
            if (
                expected_plan_id is not None
                and artifact(self, artifact_id)["plan"]["id"] != expected_plan_id
            ):
                raise OuttakeError(
                    "TARGET_CONFLICT",
                    "Saved output changed since it was displayed.",
                    "Refresh the saved-output card and retry against its current plan identity.",
                )
            return delete_output(self, artifact_id)

    @_io_errors
    def get_plan(self, plan_id: str):
        if not re.fullmatch(r"plan_[a-f0-9]{32}", plan_id):
            raise OuttakeError("INVALID_ID", "Invalid plan ID.", "Use a returned plan ID.")
        path = self.state / "plans" / f"{plan_id}.json"
        if not path.is_file():
            raise OuttakeError(
                "PLAN_MISSING",
                "The requested plan is not retained.",
                "Use the original state folder or supply the plan value.",
            )
        return Plan.model_validate_json(path.read_text())

    @_io_errors
    def get_workspace(self, plan_id: str, artifact_id: str | None = None):
        from .workspace import get_workspace

        return get_workspace(self, plan_id, artifact_id)

    @_io_errors
    def finish_workspace_export(self, workspace_id: str, artifact_id: str):
        from .workspace import finish_workspace_export

        return finish_workspace_export(self, workspace_id, artifact_id)

    @_io_errors
    def save_workspace(self, workspace_id: str, plan: Plan | dict, changes: dict):
        from .workspace import save_workspace

        return save_workspace(self, workspace_id, plan, changes)

    @_io_errors
    def open_review(self, target_kind: str, target_id: str, scope="portable"):
        """Authorize one retained plan, export, or finding for a portable host."""
        from .collaboration import open_review

        return open_review(self, target_kind, target_id, scope)

    @_io_errors
    def get_scoped_saved_outputs(self, offset=0, limit=20, sort_by="newest", scope=None):
        """Read a bounded export collection constrained by review/collection authority."""
        from .collaboration import get_scoped_saved_outputs

        return get_scoped_saved_outputs(self, offset, limit, sort_by, scope)

    @_io_errors
    def open_scoped_saved_output(self, artifact_id, scope=None, request_id=None):
        """Open one authorized export in its retained export-specific workspace."""
        from .collaboration import open_scoped_saved_output

        return open_scoped_saved_output(self, artifact_id, scope, request_id)

    @_io_errors
    def rename_scoped_saved_output(
        self, review_id, artifact_id, title, expected_plan_id=None, scope=None, request_id=None
    ):
        from .collaboration import rename_scoped_saved_output

        return rename_scoped_saved_output(
            self, review_id, artifact_id, title, expected_plan_id, scope, request_id
        )

    @_io_errors
    def delete_scoped_saved_output(
        self, review_id, artifact_id, expected_plan_id=None, scope=None, request_id=None
    ):
        from .collaboration import delete_scoped_saved_output

        return delete_scoped_saved_output(
            self, review_id, artifact_id, expected_plan_id, scope, request_id
        )

    @_io_errors
    def describe_scoped_saved_output_media(self, artifact_id, scope=None):
        from .collaboration import describe_scoped_saved_output_media

        return describe_scoped_saved_output_media(self, artifact_id, scope)

    @_io_errors
    def read_scoped_saved_output_media(self, artifact_id, offset=0, length=192 * 1024, scope=None):
        from .collaboration import read_scoped_saved_output_media

        return read_scoped_saved_output_media(self, artifact_id, offset, length, scope)

    @_io_errors
    def review_snapshot(self, review_id: str, scope=None):
        from .collaboration import review_snapshot

        return review_snapshot(self, review_id, scope)

    @_io_errors
    def get_review_draft(self, review_id: str, base_plan_id: str, scope=None):
        from .collaboration import get_review_draft

        return get_review_draft(self, review_id, base_plan_id, scope)

    @_io_errors
    def get_review_finding_page(
        self, review_id: str, finding_id: str, offset=0, limit=20, scope=None
    ):
        from .collaboration import get_review_finding_page

        return get_review_finding_page(self, review_id, finding_id, offset, limit, scope)

    @_io_errors
    def navigate_review(
        self,
        review_id: str,
        view: dict,
        expected_version: int,
        request_id: str | None = None,
        scope=None,
    ):
        from .collaboration import navigate_review

        return navigate_review(self, review_id, view, expected_version, scope, request_id)

    @_io_errors
    def save_review_draft(
        self,
        review_id: str,
        base_plan_id: str,
        draft: dict,
        expected_version: int,
        request_id: str | None = None,
        scope=None,
    ):
        from .collaboration import save_review_draft

        return save_review_draft(
            self, review_id, base_plan_id, draft, expected_version, scope, request_id
        )

    @_io_errors
    def apply_review_changes(
        self,
        review_id: str,
        changes: dict,
        plan: Plan | dict | None = None,
        plan_id: str | None = None,
        request_id: str | None = None,
        scope=None,
    ):
        from .collaboration import apply_review_changes

        if (plan is None) == (plan_id is None):
            raise OuttakeError(
                "INVALID_INPUT",
                "Supply exactly one of plan or plan_id.",
                "Use the displayed immutable plan identity for portable review.",
            )
        base = plan.id if isinstance(plan, Plan) else plan if plan is not None else plan_id
        return apply_review_changes(self, review_id, base, changes, scope, request_id)

    @_io_errors
    def select_review_candidate(
        self,
        review_id: str,
        finding_id: str,
        candidate_id: str,
        format="mp4",
        profile="share",
        request_id=None,
        scope=None,
    ):
        from .collaboration import select_review_candidate

        return select_review_candidate(
            self, review_id, finding_id, candidate_id, format, profile, scope, request_id
        )

    @_io_errors
    def admit_operation(
        self,
        request_id: str,
        operation: str,
        arguments: dict,
        grant: ModelGrant | dict | None = None,
        *,
        allow_models=True,
        review_id=None,
    ):
        """Admit owned detached work. Direct callers retain existing find/make semantics."""
        from .collaboration import admit_operation

        return admit_operation(
            self,
            request_id,
            operation,
            arguments,
            grant,
            allow_models=allow_models,
            review_id=review_id,
        )

    @_io_errors
    def get_operation(self, operation_id: str, review_id=None):
        from .collaboration import get_operation

        return get_operation(self, operation_id, review_id)

    @_io_errors
    def get_operation_result_page(
        self, operation_id: str, offset=0, limit=64 * 1024, review_id=None
    ):
        from .collaboration import get_operation_result_page

        return get_operation_result_page(self, operation_id, offset, limit, review_id)

    @_io_errors
    def cancel_operation(self, operation_id: str, review_id=None):
        from .collaboration import cancel_operation

        return cancel_operation(self, operation_id, review_id)

    @_io_errors
    def recover_operations(self):
        from .collaboration import recover_operations

        return recover_operations(self)

    @_io_errors
    def describe_media(
        self, review_id: str, kind: str, identity: str, index: int | None = None, scope=None
    ):
        """Describe authorized retained export or evidence bytes without exposing a path."""
        from .collaboration import describe_media

        return describe_media(self, review_id, kind, identity, index, scope)

    @_io_errors
    def read_media(self, review_id: str, media_id: str, offset=0, length=192 * 1024, scope=None):
        from .collaboration import read_media

        return read_media(self, review_id, media_id, offset, length, scope)

    @_io_errors
    def revise(self, plan: Plan | dict, changes: dict):
        """Revise the explicitly supplied base, preserving source and prior revisions."""
        base = Plan.model_validate(plan)
        self._check_identity(base)
        allowed = {
            "start",
            "end",
            "frame",
            "format",
            "profile",
            "audio",
            "overlay",
            "title",
            "cues",
            "captions_enabled",
            "caption_mode",
            "max_width",
            "fps",
        }
        if set(changes) - allowed:
            raise OuttakeError(
                "INVALID_REVISION",
                "Revision contains unsupported fields.",
                f"Use only {sorted(allowed)}.",
            )
        values = base.model_dump()
        values.update(changes)
        values.update(id=_id("plan"), parent_id=base.id, revision=base.revision + 1)
        if "frame" not in changes and not values["start"] <= values["frame"] < values["end"]:
            values["frame"] = values["start"]
        if values["format"] != "mp4" and "audio" not in changes:
            values["audio"] = "mute"
        revised = Plan.model_validate(values)
        self._check_duration(revised)
        return self._retain(revised)

    def _check_duration(self, plan):
        if plan.end - plan.start > self.settings.limits.max_duration_seconds:
            raise OuttakeError(
                "RESOURCE_LIMIT",
                "Cut exceeds duration limit.",
                "Shorten the cut or explicitly increase max_duration_seconds.",
            )

    def _check_identity(self, plan):
        retained = self.state / "plans" / f"{plan.id}.json"
        if retained.exists() and Plan.model_validate_json(retained.read_text()) != plan:
            raise OuttakeError(
                "PLAN_CONFLICT",
                "The supplied plan differs from its retained revision.",
                "Load the original plan and use revise to make a new revision.",
                plan.id,
            )

    def _validate(self, plan, budget):
        self._check_identity(plan)
        if plan.evidence_ids:
            from .discovery import validate_evidence

            for evidence_id in plan.evidence_ids:
                evidence = self.get_evidence(evidence_id)
                if evidence["source_sha256"] != plan.source.sha256:
                    raise OuttakeError(
                        "INVALID_PLAN",
                        "Evidence belongs to another source.",
                        "Select the candidate again.",
                    )
                validate_evidence(self, evidence, budget)
        from .editing import load_font

        for overlay in ([plan.overlay] if plan.overlay else []) + list(plan.cues):
            load_font(overlay.font, overlay.size)
        for cue in plan.cues:
            if cue.evidence_id:
                from .discovery import validate_evidence

                evidence = self.get_evidence(cue.evidence_id)
                if evidence["source_sha256"] != plan.source.sha256:
                    raise OuttakeError(
                        "INVALID_PLAN",
                        "Cue evidence belongs to another source.",
                        "Import captions again.",
                    )
                validate_evidence(self, evidence, budget)
        if plan.caption_evidence_id:
            from .discovery import validate_evidence

            evidence = self.get_evidence(plan.caption_evidence_id)
            if (
                evidence["kind"] != "image_captions"
                or evidence["source_sha256"] != plan.source.sha256
            ):
                raise OuttakeError(
                    "INVALID_PLAN",
                    "Image captions belong to another source or type.",
                    "Import captions again.",
                )
            validate_evidence(self, evidence, budget)
            coverage = evidence["coverage"]
            if (
                plan.captions_enabled
                and plan.caption_mode == "original"
                and (plan.start < coverage["start"] or plan.end > coverage["end"])
            ):
                raise OuttakeError(
                    "CAPTION_COVERAGE",
                    "Cut extends beyond imported image captions.",
                    "Import the track again for the expanded cut.",
                )
        elif plan.captions_enabled and plan.caption_mode == "original":
            raise OuttakeError(
                "CAPTIONS_UNAVAILABLE",
                "No original image captions are imported.",
                "Import an image track or choose editable text.",
            )
        self._check_duration(plan)
        path = self._source(plan.source.path)
        if (
            path.stat().st_size != plan.source.bytes
            or fingerprint(path, budget) != plan.source.sha256
        ):
            raise OuttakeError(
                "STALE_SOURCE",
                "Source differs from the planned source.",
                "Inspect again and create a new plan.",
                plan.id,
            )
        info = probe(path, budget)
        self._check_media(info)
        stream = video_stream(info)
        if (
            plan.source.duration != self._duration(info)
            or plan.source.width != stream["width"]
            or plan.source.height != stream["height"]
            or plan.source.color_transfer != stream.get("color_transfer", "unspecified")
            or plan.source.has_audio != any(s["codec_type"] == "audio" for s in info["streams"])
        ):
            raise OuttakeError(
                "INVALID_PLAN",
                "Plan source metadata does not match the actual source.",
                "Create a new plan from an inspected source.",
            )
        return path, info

    @_io_errors
    def validate(self, plan: Plan | dict):
        plan = Plan.model_validate(plan)
        self._validate(plan, Budget(self.settings.limits))
        return {"schema_version": 1, "status": "ready", "plan_id": plan.id}

    @_io_errors
    def saved_outputs(self, include_previews=False, sort_by="newest"):
        """Read published receipts. Private staging directories are never results."""
        if sort_by not in {"newest", "oldest", "name", "size"}:
            raise OuttakeError(
                "INVALID_SORT", "Unknown output sort order.", "Choose newest, oldest, name or size."
            )
        receipts = []
        for path in sorted(self.output.glob("export_*/receipt.json")):
            if path.is_symlink() or path.parent.is_symlink():
                continue
            receipt = json.loads(path.read_text())
            if include_previews or receipt.get("purpose", "export") != "preview":
                # Older receipts have no publication timestamp; do not rewrite them.
                receipt.setdefault(
                    "created_at",
                    datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat(),
                )
                receipts.append(receipt)

        def created(receipt):
            return datetime.fromisoformat(receipt["created_at"]).timestamp()

        receipts.sort(key=lambda r: (created(r), r["artifact_id"]), reverse=True)
        if sort_by == "oldest":
            receipts.reverse()
        elif sort_by == "name":
            receipts.sort(
                key=lambda r: (
                    r["plan"].get("title") or Path(r["plan"]["source"]["path"]).stem
                ).casefold()
            )
        elif sort_by == "size":
            receipts.sort(key=lambda r: r["bytes"], reverse=True)
        return receipts

    def preview(self, plan: Plan | dict, *, cancelled=lambda: False):
        """Render the exact plan for local review; no alternate or canned preview."""
        plan = Plan.model_validate(plan)
        return self._render_with_budget(
            plan, Budget(self.settings.limits, cancelled), purpose="preview"
        )

    @_io_errors
    def render(self, plan: Plan | dict, *, cancelled=lambda: False):
        plan = Plan.model_validate(plan)
        return self._render_with_budget(plan, Budget(self.settings.limits, cancelled))

    def _render_with_budget(
        self, plan, budget, purpose="export", artifact_id=None, publish_guard=None, publisher=None
    ):
        # One render per process; reject instead of waiting outside the operation budget.
        if not _RENDER_LOCK.acquire(blocking=False):
            raise OuttakeError(
                "RESOURCE_LIMIT",
                "Another render is running in this process.",
                "Retry after it completes.",
            )
        try:
            return self._render(
                plan,
                budget,
                purpose=purpose,
                artifact_id=artifact_id,
                publish_guard=publish_guard,
                publisher=publisher,
            )
        finally:
            _RENDER_LOCK.release()

    def _render(
        self, plan, budget, purpose="export", artifact_id=None, publish_guard=None, publisher=None
    ):
        path, info = self._validate(plan, budget)
        stream = video_stream(info)
        requested = plan.frame if plan.format == "png" else plan.start
        first, origin = frame_at(path, requested, info, budget)
        if first >= plan.end + origin:
            raise OuttakeError(
                "EMPTY_CUT", "No selected frame exists before the end boundary.", "Extend the cut."
            )
        width, height = stream["width"], stream["height"]
        from fractions import Fraction

        sar = stream.get("sample_aspect_ratio", "1:1")
        ratio = Fraction(sar.replace(":", "/")) if sar not in ("N/A", "0:1") else Fraction(1)
        if not 0 < ratio <= 16:
            raise OuttakeError(
                "ASPECT_UNSUPPORTED",
                "Invalid source pixel aspect ratio.",
                "Inspect the source metadata.",
            )
        width = round(width * ratio)
        scale = min(
            1, (plan.max_width or self.output_profiles()[plan.profile]["max_width"]) / width
        )
        if width * height > 4096 * 2160:
            raise OuttakeError(
                "RESOURCE_LIMIT",
                "Source resolution exceeds the initial 4K limit.",
                "Use a smaller source.",
            )
        width, height = max(2, int(width * scale) // 2 * 2), max(2, int(height * scale) // 2 * 2)
        profile = self.output_profiles()[plan.profile]
        rate = str(
            plan.fps
            or (
                profile["gif_fps"]
                if plan.format == "gif"
                else stream.get("avg_frame_rate", "0/0")
                if profile["mp4_fps"] == "source"
                else profile["mp4_fps"]
            )
        )
        if rate == "0/0":
            raise OuttakeError(
                "TIMING_UNAVAILABLE", "Source frame rate is unknown.", "Choose the share profile."
            )
        artifact_id = artifact_id or _id("export")
        if not re.fullmatch(r"export_[a-f0-9]{32}", artifact_id):
            raise OuttakeError(
                "INVALID_ID", "Invalid output identity.", "Use an Outtake export ID."
            )
        destination = self.output / artifact_id
        if destination.exists():
            raise OuttakeError(
                "OUTPUT_CONFLICT",
                "The requested output identity already exists.",
                "Inspect the retained operation instead of publishing over an existing output.",
                artifact_id,
            )
        with tempfile.TemporaryDirectory(prefix=".outtake-", dir=self.output) as scratch:
            stage = Path(scratch)
            from .editing import filename as export_filename
            from .editing import load_font

            filename = export_filename(plan.title, plan.format)
            artifact = stage / filename
            seek = max(0, first - float(info["format"].get("start_time", 0)) - 2)
            args = [
                "-v",
                "error",
                "-nostdin",
                "-n",
                "-copyts",
                "-ss",
                f"{seek:.9f}",
                *INPUT_OPTIONS,
                "-i",
                str(path),
            ]
            filters = (
                f"[0:{stream['index']}]trim=start={first:.9f}:end={plan.end + origin:.9f},"
                f"setpts=PTS-{first:.9f}/TB,scale={width}:{height},setsar=1"
            )
            if plan.format != "png":
                filters += f",fps={rate}:start_time=0"
            filters += "[base]"
            label = "base"
            if (
                plan.captions_enabled
                and plan.caption_mode == "original"
                and plan.caption_evidence_id
            ):
                from .subtitles import image_path

                evidence = self.get_evidence(plan.caption_evidence_id)
                for index, hit in enumerate(evidence["hits"]):
                    if hit["end"] <= plan.start or hit["start"] >= plan.end:
                        continue
                    if plan.format == "png" and not hit["start"] <= first - origin < hit["end"]:
                        continue
                    original = image_path(self, evidence, hit, budget)
                    input_index = sum(1 for arg in args if arg == "-i")
                    args += ["-i", str(original)]
                    begin, finish = (
                        max(0, hit["start"] - (first - origin)),
                        hit["end"] - (first - origin),
                    )
                    enable = (
                        ""
                        if plan.format == "png"
                        else f":enable='gte(t,{begin:.9f})*lt(t,{finish:.9f})'"
                    )
                    filters += f";[{input_index}:v]scale={width}:{height},setsar=1[sub{index}];[{label}][sub{index}]overlay=eof_action=repeat:format=auto{enable}[caption{index}]"
                    label = f"caption{index}"
            overlays = [(plan.overlay, plan.start, plan.end)] if plan.overlay else []
            overlays += [
                (cue, cue.start, cue.end)
                for cue in plan.cues
                if cue.enabled
                and (
                    cue.origin != "caption"
                    or (plan.captions_enabled and plan.caption_mode == "editable")
                )
                and cue.end > plan.start
                and cue.start < plan.end
            ]
            for index, (overlay, cue_start, cue_end) in enumerate(overlays):
                if plan.format == "png" and not cue_start <= first - origin < cue_end:
                    continue
                budget.check()
                image = Image.new("RGBA", (width, height))
                draw = ImageDraw.Draw(image)
                font = load_font(overlay.font, overlay.size)
                anchor = {"left": "la", "center": "ma", "right": "ra"}[overlay.alignment]
                try:
                    draw.multiline_text(
                        (overlay.x * width, overlay.y * height),
                        overlay.text,
                        font=font,
                        fill=overlay.color,
                        anchor=anchor,
                        align=overlay.alignment,
                        stroke_width=overlay.outline_width,
                        stroke_fill=overlay.outline_color,
                    )
                except (ValueError, UnicodeError) as exc:
                    raise OuttakeError(
                        "OVERLAY_UNSUPPORTED", str(exc), "Choose another font or text."
                    ) from exc
                overlay_path = stage / f"overlay-{index}.png"
                image.save(overlay_path)
                image.close()
                input_index = sum(1 for arg in args if arg == "-i")
                args += ["-i", str(overlay_path)]
                output_label = f"text{index}"
                begin = max(0, cue_start - (first - origin))
                finish = cue_end - (first - origin)
                enable = (
                    ""
                    if plan.format == "png"
                    else f":enable='gte(t,{begin:.9f})*lt(t,{finish:.9f})'"
                )
                filters += f";[{label}][{input_index}:v]overlay=eof_action=repeat:format=auto{enable}[{output_label}]"
                label = output_label
            if plan.format == "gif":
                filters += f";[{label}]split[palette_input][pixels];[palette_input]palettegen[palette];[pixels][palette]paletteuse[v]"
            else:
                filters += f";[{label}]null[v]"
            audio_streams = [s for s in info["streams"] if s["codec_type"] == "audio"]
            with_audio = plan.format == "mp4" and plan.audio == "preserve" and bool(audio_streams)
            if with_audio:
                filters += (
                    f";[0:{audio_streams[0]['index']}]atrim=start={first:.9f}:end={plan.end + origin:.9f},"
                    f"asetpts=PTS-{first:.9f}/TB,aresample=async=1:first_pts=0[a]"
                )
            args += [
                "-filter_complex",
                filters,
                "-map",
                "[v]",
                "-map_metadata",
                "-1",
                "-map_chapters",
                "-1",
            ]
            if with_audio:
                args += ["-map", "[a]", "-c:a", "aac", "-b:a", "192k"]
            else:
                args += ["-an"]
            if plan.format == "mp4":
                args += [
                    "-c:v",
                    "libx264",
                    "-crf",
                    "18" if plan.profile == "editing" else "23",
                    "-pix_fmt",
                    "yuv420p",
                    "-movflags",
                    "+faststart",
                ]
            elif plan.format == "png":
                args += ["-frames:v", "1", "-update", "1"]
            else:
                args += ["-loop", "0"]
            run("ffmpeg", [*args, str(artifact)], budget, stage)
            if not artifact.is_file() or not artifact.stat().st_size:
                raise OuttakeError(
                    "EMPTY_OUTPUT", "Renderer produced no artifact.", "Check the selected interval."
                )
            if artifact.stat().st_size > budget.limits.max_output_bytes:
                raise OuttakeError(
                    "RESOURCE_LIMIT",
                    "Output exceeds the configured size allowance.",
                    "Shorten the cut or increase max_output_bytes.",
                )
            for overlay_file in stage.glob("overlay-*.png"):
                overlay_file.unlink()
            # Check again before publication, including source changes during encoding.
            self._validate(plan, budget)
            receipt = {
                "created_at": datetime.now(timezone.utc).isoformat(),
                "schema_version": 1,
                "purpose": purpose,
                "status": "ready",
                "artifact_id": artifact_id,
                "artifact": str(destination / filename),
                "receipt": str(destination / "receipt.json"),
                "plan": plan.model_dump(mode="json"),
                "sha256": fingerprint(artifact, budget),
                "bytes": artifact.stat().st_size,
                "resolved_start": first - origin,
                "requested_start": requested,
                "end": plan.end,
                "width": width,
                "height": height,
                "frame_rate": None if plan.format == "png" else rate,
                "audio": "preserved" if with_audio else "none",
                "tone_mapping": "none",
                "title": plan.title,
                "fonts": sorted({o.font for o, _, _ in overlays}),
                "warnings": list(plan.warnings)
                + ["Sound is unverified. Review local playback and revise boundaries as needed."],
            }
            if plan.audio == "preserve" and not audio_streams:
                receipt["warnings"].append("Source has no audio stream.")
            (stage / "overlay.png").unlink(missing_ok=True)
            _write(stage / "receipt.json", receipt)
            budget.check(stage)
            # The directory is the publication unit: artifact and receipt become visible together.
            # A retained worker must still own its lease at this exact boundary.
            if publish_guard is not None and not publish_guard():
                raise OuttakeError(
                    "CANCELLED",
                    "Cancellation or lease loss won before artifact publication.",
                    "Inspect the retained operation; no new artifact was published.",
                )
            if publisher is not None:
                publisher(stage, destination)
            else:
                os.rename(stage, destination)
        return receipt

    @_io_errors
    def _render_retained(self, plan, artifact_id, operation, owned, publisher):
        """Internal worker seam: a preassigned identity prevents lost-result ambiguity."""
        plan = Plan.model_validate(plan)
        if operation not in {"preview", "render"}:
            raise OuttakeError(
                "INVALID_INPUT", "Unknown retained render operation.", "Use preview or render."
            )
        return self._render_with_budget(
            plan,
            Budget(self.settings.limits, cancelled=lambda: not owned()),
            purpose="preview" if operation == "preview" else "export",
            artifact_id=artifact_id,
            publish_guard=owned,
            publisher=publisher,
        )
