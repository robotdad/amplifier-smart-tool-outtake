"""Optional standard MCP adapter over the retained public library."""

import argparse
import importlib.resources
import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from .models import FindRequest, ModelGrant


class ToolResult(BaseModel):
    result: dict


class AdmissionInput(BaseModel):
    """Typed adapter input; exactly one of a retained plan or a model request."""

    request_id: str = Field(min_length=1, max_length=80)
    operation: Literal["preview", "render", "find", "make"]
    plan_id: str | None = None
    request: FindRequest | None = None
    grant: ModelGrant | None = None
    format: Literal["mp4", "gif", "png"] = "mp4"
    profile: Literal["mobile", "share", "editing"] = "share"
    # Compatibility for callers already using the initial review adapter. New clients
    # should use the typed fields above; this is normalized before admission.
    arguments: dict | None = None

    @model_validator(mode="before")
    @classmethod
    def normalize_legacy(cls, value):
        if isinstance(value, dict) and value.get("arguments") and not value.get("plan_id"):
            arguments = value["arguments"]
            value = dict(value)
            if isinstance(arguments, dict):
                if value.get("operation") in {"preview", "render"}:
                    value["plan_id"] = arguments.get("plan_id") or arguments.get("plan", {}).get(
                        "id"
                    )
                else:
                    value["request"] = arguments.get("request")
                    value["format"] = arguments.get("format", value.get("format", "mp4"))
                    value["profile"] = arguments.get("profile", value.get("profile", "share"))
        return value

    @model_validator(mode="after")
    def valid_target(self):
        local = self.operation in {"preview", "render"}
        if local != (self.plan_id is not None):
            raise ValueError("preview/render need plan_id; find/make need request")
        if local and (self.request is not None or self.grant is not None):
            raise ValueError("preview/render do not accept request or grant")
        if not local and (self.request is None or self.grant is None):
            raise ValueError("find/make need request and ModelGrant")
        return self


def create_server(settings, allowed_reviews, allow_models=False, allow_saved_outputs=False):
    """Build the optional stdio server; importing base Outtake does not call this."""
    from mcp.server.apps import Apps, ResourceCsp
    from mcp.server.mcpserver import MCPServer
    from mcp.types import ToolAnnotations

    from .collaboration import ReviewScope, public_projection, review_authorized
    from .lib import Outtake
    from .models import OuttakeError

    client = Outtake(settings)
    scope = ReviewScope(allowed_reviews, allow_saved_outputs=allow_saved_outputs)
    ui_uri = "ui://outtake/review"
    app = importlib.resources.files("outtake").joinpath("resources/mcp_app.html")
    apps = Apps()
    if app.is_file():
        apps.add_html_resource(
            ui_uri,
            app.read_text(encoding="utf-8"),
            title="Outtake moment review",
            csp=ResourceCsp(connectDomains=[], resourceDomains=[]),
            prefers_border=True,
        )
    server = MCPServer(
        "outtake",
        title="Outtake collaborative review",
        version="0.1.0.dev0",
        extensions=[apps] if app.is_file() else [],
        instructions=(
            "Use an explicitly configured review reference. Results and resources are scoped "
            "retained material. This server does not provide Tasks, sampling, elicitation, "
            "subscriptions, arbitrary paths, or host-private APIs."
        ),
    )

    def checked(review_id):
        review_authorized(client, review_id, scope)

    @server.resource(
        "outtake://review/{review_id}",
        name="outtake-review",
        description="Safe bounded review JSON for an explicitly authorized retained review.",
        mime_type="application/json",
    )
    def review_resource(review_id: str) -> str:
        checked(review_id)
        return _json(public_projection(client.review_snapshot(review_id, scope)))

    @server.resource(
        "outtake://review/{review_id}/media/{media_id}/{offset}",
        name="outtake-media",
        description="Scoped retained media in fixed 196608-byte chunks; offset is a decimal byte offset.",
        mime_type="application/octet-stream",
    )
    def media_resource(review_id: str, media_id: str, offset: str) -> bytes:
        checked(review_id)
        try:
            value = int(offset)
        except ValueError as exc:
            raise OuttakeError(
                "INVALID_RANGE", "Media offset is invalid.", "Use a decimal byte offset."
            ) from exc
        result = client.read_media(review_id, media_id, value, 192 * 1024, scope)
        import base64

        return base64.b64decode(result["data_base64"])

    @server.resource(
        "outtake://saved-output/{artifact_id}/{offset}",
        name="outtake-saved-output-media",
        description="Scoped saved-output media in fixed 196608-byte chunks; only authorized exports resolve.",
        mime_type="application/octet-stream",
    )
    def saved_output_media_resource(artifact_id: str, offset: str) -> bytes:
        try:
            value = int(offset)
        except ValueError as exc:
            raise OuttakeError(
                "INVALID_RANGE", "Media offset is invalid.", "Use a decimal byte offset."
            ) from exc
        result = client.read_scoped_saved_output_media(artifact_id, value, 192 * 1024, scope)
        import base64

        return base64.b64decode(result["data_base64"])

    ui_meta = (
        {"ui": {"resourceUri": ui_uri, "visibility": ["model", "app"]}} if app.is_file() else None
    )

    @server.tool(
        name="outtake_review",
        description="Read a bounded authorized collaborative review.",
        annotations=ToolAnnotations(
            read_only_hint=True, idempotent_hint=True, open_world_hint=False
        ),
        meta=ui_meta,
        structured_output=True,
    )
    def review(review_id: str) -> ToolResult:
        checked(review_id)
        return ToolResult(result=public_projection(client.review_snapshot(review_id, scope)))

    @server.tool(
        name="outtake_saved_outputs",
        description="Read a bounded page of exports authorized by configured reviews or explicit saved-output collection authority.",
        annotations=ToolAnnotations(
            read_only_hint=True, idempotent_hint=True, open_world_hint=False
        ),
        meta=ui_meta,
        structured_output=True,
    )
    def saved_outputs(
        offset: int = 0,
        limit: int = 20,
        sort_by: Literal["newest", "oldest", "name", "size"] = "newest",
    ) -> ToolResult:
        return ToolResult(
            result=public_projection(client.get_scoped_saved_outputs(offset, limit, sort_by, scope))
        )

    @server.tool(
        name="outtake_open_saved_output",
        description="Attach one authorized export to its retained export-specific editing workspace without rendering.",
        annotations=ToolAnnotations(
            read_only_hint=False, idempotent_hint=True, open_world_hint=False
        ),
        meta=ui_meta,
        structured_output=True,
    )
    def open_saved_output(artifact_id: str, request_id: str | None = None) -> ToolResult:
        return ToolResult(
            result=public_projection(
                client.open_scoped_saved_output(artifact_id, scope, request_id)
            )
        )

    @server.tool(
        name="outtake_describe_saved_output_media",
        description="Describe authorized saved-output bytes and return a standard scoped resource URI.",
        annotations=ToolAnnotations(
            read_only_hint=True, idempotent_hint=True, open_world_hint=False
        ),
        meta=ui_meta,
        structured_output=True,
    )
    def saved_output_media_descriptor(artifact_id: str) -> ToolResult:
        return ToolResult(result=client.describe_scoped_saved_output_media(artifact_id, scope))

    @server.tool(
        name="outtake_rename_saved_output",
        description="Rename an authorized export without regenerating media or applying unrelated edits.",
        annotations=ToolAnnotations(
            read_only_hint=False, idempotent_hint=True, open_world_hint=False
        ),
        meta=ui_meta,
        structured_output=True,
    )
    def rename_saved_output(
        review_id: str,
        artifact_id: str,
        title: str,
        expected_plan_id: str,
        request_id: str | None = None,
    ) -> ToolResult:
        checked(review_id)
        return ToolResult(
            result=public_projection(
                client.rename_scoped_saved_output(
                    review_id, artifact_id, title, expected_plan_id, scope, request_id
                )
            )
        )

    @server.tool(
        name="outtake_delete_saved_output",
        description="Delete one authorized generated export; its source and retained plans remain.",
        annotations=ToolAnnotations(
            read_only_hint=False, idempotent_hint=True, destructive_hint=True, open_world_hint=False
        ),
        meta=ui_meta,
        structured_output=True,
    )
    def delete_saved_output(
        review_id: str,
        artifact_id: str,
        expected_plan_id: str,
        request_id: str | None = None,
    ) -> ToolResult:
        checked(review_id)
        return ToolResult(
            result=public_projection(
                client.delete_scoped_saved_output(
                    review_id, artifact_id, expected_plan_id, scope, request_id
                )
            )
        )

    @server.tool(
        name="outtake_navigate",
        description="Persist explicit versioned review focus without applying edits or work.",
        annotations=ToolAnnotations(
            read_only_hint=False, idempotent_hint=False, open_world_hint=False
        ),
        meta=ui_meta,
        structured_output=True,
    )
    def navigate(
        review_id: str, view: dict, expected_version: int, request_id: str | None = None
    ) -> ToolResult:
        checked(review_id)
        return ToolResult(
            result=public_projection(
                client.navigate_review(review_id, view, expected_version, request_id, scope)
            )
        )

    @server.tool(
        name="outtake_save_draft",
        description="CAS-save bounded raw input for one exact review base plan.",
        annotations=ToolAnnotations(
            read_only_hint=False, idempotent_hint=False, open_world_hint=False
        ),
        meta=ui_meta,
        structured_output=True,
    )
    def save_draft(
        review_id: str,
        base_plan_id: str,
        draft: dict,
        expected_version: int,
        request_id: str | None = None,
    ) -> ToolResult:
        checked(review_id)
        return ToolResult(
            result=public_projection(
                client.save_review_draft(
                    review_id, base_plan_id, draft, expected_version, request_id, scope
                )
            )
        )

    @server.tool(
        name="outtake_apply_changes",
        description="Apply exact retained plan changes through the shared workspace.",
        annotations=ToolAnnotations(
            read_only_hint=False, idempotent_hint=False, open_world_hint=False
        ),
        meta=ui_meta,
        structured_output=True,
    )
    def apply_changes(
        review_id: str, plan_id: str, changes: dict, request_id: str | None = None
    ) -> ToolResult:
        checked(review_id)
        return ToolResult(
            result=public_projection(
                client.apply_review_changes(
                    review_id, changes, plan_id=plan_id, request_id=request_id, scope=scope
                )
            )
        )

    @server.tool(
        name="outtake_select_candidate",
        description="Deterministically select a candidate from the displayed reviewed finding.",
        annotations=ToolAnnotations(
            read_only_hint=False, idempotent_hint=True, open_world_hint=False
        ),
        meta=ui_meta,
        structured_output=True,
    )
    def select_candidate(
        review_id: str,
        finding_id: str,
        candidate_id: str,
        format: Literal["mp4", "gif", "png"] = "mp4",
        profile: Literal["mobile", "share", "editing"] = "share",
        request_id: str | None = None,
    ) -> ToolResult:
        checked(review_id)
        return ToolResult(
            result=public_projection(
                client.select_review_candidate(
                    review_id, finding_id, candidate_id, format, profile, request_id, scope
                )
            )
        )

    @server.tool(
        name="outtake_admit",
        description="Persist typed exact work before detached execution.",
        annotations=ToolAnnotations(
            read_only_hint=False, idempotent_hint=True, open_world_hint=False
        ),
        meta=ui_meta,
        structured_output=True,
    )
    def admit(
        review_id: str,
        request_id: str | None = None,
        operation: Literal["preview", "render", "find", "make"] | None = None,
        plan_id: str | None = None,
        request: FindRequest | None = None,
        grant: ModelGrant | None = None,
        format: Literal["mp4", "gif", "png"] = "mp4",
        profile: Literal["mobile", "share", "editing"] = "share",
        arguments: dict | None = None,
        admission: AdmissionInput | None = None,
    ) -> ToolResult:
        checked(review_id)
        if admission is None:
            admission = AdmissionInput.model_validate(
                {
                    "request_id": request_id,
                    "operation": operation,
                    "plan_id": plan_id,
                    "request": request,
                    "grant": grant,
                    "format": format,
                    "profile": profile,
                    "arguments": arguments,
                }
            )
        arguments = (
            {"plan_id": admission.plan_id}
            if admission.plan_id
            else {
                "request": admission.request.model_dump(mode="json"),
                "format": admission.format,
                "profile": admission.profile,
            }
        )
        return ToolResult(
            result=public_projection(
                client.admit_operation(
                    admission.request_id,
                    admission.operation,
                    arguments,
                    admission.grant,
                    allow_models=allow_models,
                    review_id=review_id,
                )
            )
        )

    @server.tool(
        name="outtake_operation",
        description="Read retained operation lifecycle and its separate domain result.",
        annotations=ToolAnnotations(
            read_only_hint=True, idempotent_hint=True, open_world_hint=False
        ),
        meta=ui_meta,
        structured_output=True,
    )
    def operation(review_id: str, operation_id: str) -> ToolResult:
        checked(review_id)
        return ToolResult(result=public_projection(client.get_operation(operation_id, review_id)))

    @server.tool(
        name="outtake_cancel",
        description="Request cancellation; read operation afterward for the actual terminal result.",
        annotations=ToolAnnotations(
            read_only_hint=False, idempotent_hint=True, open_world_hint=False
        ),
        meta=ui_meta,
        structured_output=True,
    )
    def cancel(review_id: str, operation_id: str) -> ToolResult:
        checked(review_id)
        return ToolResult(
            result=public_projection(client.cancel_operation(operation_id, review_id))
        )

    @server.tool(
        name="outtake_describe_media",
        description="Describe review-scoped artifact or evidence-frame material.",
        annotations=ToolAnnotations(
            read_only_hint=True, idempotent_hint=True, open_world_hint=False
        ),
        meta=ui_meta,
        structured_output=True,
    )
    def media_descriptor(
        review_id: str, kind: Literal["artifact", "frame"], identity: str, index: int | None = None
    ) -> ToolResult:
        checked(review_id)
        return ToolResult(result=client.describe_media(review_id, kind, identity, index, scope))

    @server.tool(
        name="outtake_read_draft",
        description="Read the raw draft for an exact authorized review plan.",
        annotations=ToolAnnotations(
            read_only_hint=True, idempotent_hint=True, open_world_hint=False
        ),
        structured_output=True,
    )
    def read_draft(review_id: str, base_plan_id: str) -> ToolResult:
        checked(review_id)
        return ToolResult(
            result={
                "draft": public_projection(client.get_review_draft(review_id, base_plan_id, scope))
            }
        )

    @server.tool(
        name="outtake_finding_page",
        description="Read a bounded candidate page from a finding linked to this review.",
        annotations=ToolAnnotations(
            read_only_hint=True, idempotent_hint=True, open_world_hint=False
        ),
        structured_output=True,
    )
    def finding_page(
        review_id: str, finding_id: str, offset: int = 0, limit: int = 20
    ) -> ToolResult:
        checked(review_id)
        return ToolResult(
            result=public_projection(
                client.get_review_finding_page(review_id, finding_id, offset, limit, scope)
            )
        )

    @server.tool(
        name="outtake_operation_result_page",
        description="Read up to 64 KiB of host-safe operation-result JSON as base64 bytes.",
        annotations=ToolAnnotations(
            read_only_hint=True, idempotent_hint=True, open_world_hint=False
        ),
        structured_output=True,
    )
    def operation_result_page(
        review_id: str, operation_id: str, offset: int = 0, limit: int = 65536
    ) -> ToolResult:
        checked(review_id)
        return ToolResult(
            result=client.get_operation_result_page(operation_id, offset, limit, review_id)
        )

    return server


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Run Outtake's optional trusted stdio MCP adapter."
    )
    parser.add_argument("--settings", required=True, help="Caller-owned Outtake Settings JSON.")
    parser.add_argument(
        "--allow-reviews",
        required=True,
        action="append",
        help="Comma-separated explicitly authorized review IDs; repeatable.",
    )
    parser.add_argument(
        "--allow-models",
        action="store_true",
        help="Enable only portable model work with an explicit ModelGrant.",
    )
    parser.add_argument(
        "--allow-saved-outputs",
        action="store_true",
        help="Explicitly disclose the configured output collection (exports only, never arbitrary paths).",
    )
    args = parser.parse_args(argv)
    settings = json.loads(Path(args.settings).read_text())
    reviews = [item for group in args.allow_reviews for item in group.split(",") if item]
    if not reviews:
        parser.error("--allow-reviews must name at least one review identity")
    create_server(
        settings,
        reviews,
        args.allow_models,
        allow_saved_outputs=args.allow_saved_outputs,
    ).run(transport="stdio")


if __name__ == "__main__":
    main()
