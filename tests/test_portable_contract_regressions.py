"""Independent contract regressions for the portable retained-work boundary."""

import asyncio

import pytest

pytest.importorskip("mcp")
from mcp import Client

from outtake.mcp_adapter import create_server
from outtake.models import OuttakeError


def test_raw_draft_cannot_cross_review_workspace(tool, fixture_video):
    first = tool.plan(str(fixture_video), 0, 1, captions_enabled=False)
    unrelated = tool.plan(str(fixture_video), 1, 2, captions_enabled=False)
    review_id = tool.open_review("plan", first.id)["review_id"]

    with pytest.raises(OuttakeError):
        tool.save_review_draft(review_id, unrelated.id, {"title": "Wrong target"}, 0)
    snapshot = tool.review_snapshot(review_id)
    assert not snapshot.get("draft")


def test_sdk_projected_plan_is_editable_by_retained_identity(tool, fixture_video):
    original = tool.plan(str(fixture_video), 0, 1, captions_enabled=False)
    review_id = tool.open_review("plan", original.id)["review_id"]

    async def run():
        async with Client(create_server(tool.settings, [review_id])) as client:
            read = await client.call_tool("outtake_review", {"review_id": review_id})
            assert not read.is_error, read.content
            snapshot = read.structured_content["result"]
            shown = snapshot["workspace"]["plan"]
            assert "path" not in shown["source"]
            changed = await client.call_tool(
                "outtake_apply_changes",
                {
                    "review_id": review_id,
                    "plan_id": shown["id"],
                    "changes": {"title": "Edited from the portable projection"},
                },
            )
            assert not changed.is_error, changed.content
            return changed.structured_content["result"]["plan"]

    changed = asyncio.run(run())
    assert changed["id"] != original.id
    assert tool.get_workspace(original.id)["plan"]["id"] == changed["id"]
    assert tool.get_plan(changed["id"]).title == "Edited from the portable projection"


def test_sdk_cancel_does_not_cross_review_scope(tool, fixture_video, monkeypatch):
    first = tool.plan(str(fixture_video), 0, 1, captions_enabled=False)
    other = tool.plan(str(fixture_video), 1, 2, captions_enabled=False)
    first_review = tool.open_review("plan", first.id)["review_id"]
    other_review = tool.open_review("plan", other.id)["review_id"]
    monkeypatch.setattr("outtake.collaboration._spawn", lambda *_: None)

    async def run():
        async with Client(create_server(tool.settings, [first_review, other_review])) as client:
            admitted = await client.call_tool(
                "outtake_admit",
                {
                    "review_id": first_review,
                    "request_id": "scope-cancel-probe",
                    "operation": "render",
                    "arguments": {"plan": first.model_dump(mode="json")},
                },
            )
            assert not admitted.is_error, admitted.content
            operation_id = admitted.structured_content["result"]["operation_id"]
            denied = await client.call_tool(
                "outtake_cancel",
                {"review_id": other_review, "operation_id": operation_id},
            )
            assert denied.is_error
            assert tool.get_operation(operation_id)["status"] == "accepted"

    asyncio.run(run())


def test_completed_finding_is_terminal_and_receives_cancellation_probe(tool, monkeypatch):
    from outtake import Outtake
    from outtake.collaboration import run_worker

    seen = {}

    def scripted_find(self, request, grant, **kwargs):
        seen.update(kwargs)
        return {"status": "needs_selection", "candidates": []}

    monkeypatch.setattr("outtake.collaboration._spawn", lambda *_: None)
    monkeypatch.setattr(Outtake, "find", scripted_find)
    accepted = tool.admit_operation(
        "terminal-finding",
        "find",
        {
            "request": {
                "title": "Generated fixture",
                "description": "Red then green",
                "request_id": "terminal-finding",
            }
        },
        {"provider": "openai", "model": "scripted", "allow_request": True},
    )
    run_worker(tool.state, accepted["operation_id"])
    completed = tool.get_operation(accepted["operation_id"])
    assert completed["result"]["status"] == "needs_selection"
    assert callable(seen.get("cancelled")), "Finding must receive the worker ownership/cancel probe"
    cancelled = tool.cancel_operation(accepted["operation_id"])
    assert cancelled["status"] == completed["status"]
    assert cancelled["status"] not in {"accepted", "running", "cancelling"}


def test_mcp_resource_permission_failure_hides_local_paths(tool, fixture_video, monkeypatch):
    from pathlib import Path

    plan = tool.plan(str(fixture_video), 0, 1, captions_enabled=False)
    receipt = tool.render(plan)
    review_id = tool.open_review("artifact", receipt["artifact_id"])["review_id"]
    artifact = Path(receipt["artifact"])
    original_open = Path.open

    def denied_open(path, *args, **kwargs):
        if path == artifact:
            raise PermissionError(13, "Permission denied", str(path))
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", denied_open)

    async def run():
        async with Client(create_server(tool.settings, [review_id])) as client:
            result = await client.call_tool(
                "outtake_describe_media",
                {"review_id": review_id, "kind": "artifact", "identity": receipt["artifact_id"]},
            )
            assert result.is_error
            for item in result.content:
                text = getattr(item, "text", "")
                assert str(artifact) not in text
                assert str(tool.output) not in text

    asyncio.run(run())


def test_lost_admission_retry_survives_workspace_advance(tool, fixture_video, monkeypatch):
    plan = tool.plan(str(fixture_video), 0, 1, captions_enabled=False)
    review_id = tool.open_review("plan", plan.id)["review_id"]
    monkeypatch.setattr("outtake.collaboration._spawn", lambda *_: None)

    async def run():
        async with Client(create_server(tool.settings, [review_id])) as client:
            request = {
                "review_id": review_id,
                "request_id": "original-render-intent",
                "operation": "render",
                "arguments": {"plan": plan.model_dump(mode="json")},
            }
            accepted = await client.call_tool("outtake_admit", request)
            assert not accepted.is_error, accepted.content
            operation_id = accepted.structured_content["result"]["operation_id"]
            tool.save_workspace(plan.id, plan, {"title": "Newer concurrent edit"})
            retried = await client.call_tool("outtake_admit", request)
            assert not retried.is_error, retried.content
            assert retried.structured_content["result"]["operation_id"] == operation_id
            assert tool.get_operation(operation_id)["status"] == "accepted"

    asyncio.run(run())


def test_expired_claim_does_not_reexecute_unknown_work(tool, fixture_video, monkeypatch):
    import sqlite3

    from outtake.collaboration import _claim

    plan = tool.plan(str(fixture_video), 0, 1, captions_enabled=False)
    monkeypatch.setattr("outtake.collaboration._spawn", lambda *_: None)
    accepted = tool.admit_operation(
        "expired-owner", "render", {"plan": plan.model_dump(mode="json")}
    )
    operation_id = accepted["operation_id"]
    assert _claim(tool.state, operation_id) is not None
    with sqlite3.connect(tool.state / "collaboration.sqlite3") as database:
        database.execute("UPDATE operations SET lease_until = 0 WHERE id = ?", (operation_id,))
    assert _claim(tool.state, operation_id) is None
    tool.recover_operations()
    assert tool.get_operation(operation_id)["status"] in {"interrupted", "uncertain"}
    assert not (tool.output / accepted["output_id"]).exists()


def test_navigation_lost_response_retry_does_not_advance_view_twice(tool, fixture_video):
    plan = tool.plan(str(fixture_video), 0, 1, captions_enabled=False)
    review_id = tool.open_review("plan", plan.id)["review_id"]
    version = tool.review_snapshot(review_id)["view_version"]
    view = {"plan_id": plan.id, "playhead": 0.5}
    first = tool.navigate_review(review_id, view, version, request_id="same-navigation")
    retry = tool.navigate_review(review_id, view, version, request_id="same-navigation")
    assert retry == first
    assert tool.review_snapshot(review_id)["view_version"] == version + 1
    with pytest.raises(OuttakeError):
        tool.navigate_review(
            review_id,
            {"plan_id": plan.id, "playhead": 0.75},
            version,
            request_id="same-navigation",
        )


def test_packaged_app_discovery_has_official_csp_and_shared_visibility(tool, fixture_video):
    from mcp.client import advertise
    from mcp.server.apps import APP_MIME_TYPE, EXTENSION_ID

    plan = tool.plan(str(fixture_video), 0, 1, captions_enabled=False)
    review_id = tool.open_review("plan", plan.id)["review_id"]

    async def run():
        async with Client(
            create_server(tool.settings, [review_id]),
            extensions=[advertise(EXTENSION_ID, {"mimeTypes": [APP_MIME_TYPE]})],
        ) as client:
            tools = (await client.list_tools()).tools
            review = next(item for item in tools if item.name == "outtake_review")
            assert review.meta["ui"] == {
                "resourceUri": "ui://outtake/review",
                "visibility": ["model", "app"],
            }
            result = await client.read_resource("ui://outtake/review")
            html = result.contents[0]
            assert html.mime_type == APP_MIME_TYPE
            assert html.meta["ui"]["csp"] == {"connectDomains": [], "resourceDomains": []}
            assert "<script src=" not in html.text

    asyncio.run(run())


def test_real_stdio_detach_reconnect_keeps_one_render(tool, fixture_video, tmp_path):
    import json
    import sys
    import time

    from mcp.client.stdio import StdioServerParameters

    plan = tool.plan(str(fixture_video), 0, 1, captions_enabled=False)
    review_id = tool.open_review("plan", plan.id)["review_id"]
    settings = tmp_path / "settings.json"
    settings.write_text(tool.settings.model_dump_json())
    transport = StdioServerParameters(
        command=sys.executable,
        args=[
            "-m",
            "outtake.mcp_adapter",
            "--settings",
            str(settings),
            "--allow-reviews",
            review_id,
        ],
        cwd=str(tmp_path),
    )
    request = {
        "review_id": review_id,
        "admission": {
            "request_id": "stdio-detach-render",
            "operation": "render",
            "plan_id": plan.id,
        },
    }

    async def run():
        async with Client(transport) as client:
            accepted = await client.call_tool("outtake_admit", request)
            assert not accepted.is_error, accepted.content
            operation_id = accepted.structured_content["result"]["operation_id"]
        async with Client(transport) as client:
            repeated = await client.call_tool("outtake_admit", request)
            assert not repeated.is_error, repeated.content
            assert repeated.structured_content["result"]["operation_id"] == operation_id
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                response = await client.call_tool(
                    "outtake_operation",
                    {"review_id": review_id, "operation_id": operation_id},
                )
                assert not response.is_error, response.content
                record = response.structured_content["result"]
                if record["status"] not in {"accepted", "running", "cancelling"}:
                    break
                await asyncio.sleep(0.05)
            else:
                pytest.fail("Detached render did not reach a terminal outcome")
            assert record["status"] == "completed", record
            assert record["result"]["status"] == "ready"
            assert str(tool.output) not in json.dumps(record)
            import base64

            page = await client.call_tool(
                "outtake_operation_result_page",
                {"review_id": review_id, "operation_id": operation_id},
            )
            assert not page.is_error, page.content
            page_data = page.structured_content["result"]
            decoded = base64.b64decode(page_data["data_base64"]).decode()
            assert str(tool.output) not in decoded
            assert str(fixture_video) not in decoded
            return record

    record = asyncio.run(run())
    assert tool.artifact(record["output_id"])["plan"]["id"] == plan.id
    assert len(list(tool.output.glob("export_*"))) == 1


def test_artifact_review_rejects_other_workspace_sibling(tool, fixture_video):
    base = tool.plan(str(fixture_video), 0, 1, captions_enabled=False)
    receipt = tool.render(base)
    review_id = tool.open_review("artifact", receipt["artifact_id"])["review_id"]
    separate = tool.get_workspace(base.id)
    sibling = tool.save_workspace(separate["workspace_id"], base, {"title": "Other workspace"})
    with pytest.raises(OuttakeError):
        tool.save_review_draft(review_id, sibling.id, {"title": "Cross-workspace draft"}, 0)
    with pytest.raises(OuttakeError):
        tool.apply_review_changes(
            review_id, {"title": "Must not import sibling"}, plan_id=sibling.id
        )
    assert tool.review_snapshot(review_id)["head_plan_id"] == base.id


def test_plan_review_cannot_attach_unrelated_finding(tool, fixture_video):
    from outtake.discovery import save_record

    plan = tool.plan(str(fixture_video), 0, 1, captions_enabled=False)
    review_id = tool.open_review("plan", plan.id)["review_id"]
    finding_id = "finding_" + "a" * 64
    save_record(
        tool,
        "findings",
        {
            "id": finding_id,
            "status": "needs_selection",
            "request": {"description": "Private unrelated request"},
            "candidates": [],
        },
    )
    before = tool.review_snapshot(review_id)
    with pytest.raises(OuttakeError):
        tool.navigate_review(
            review_id,
            {"finding_id": finding_id},
            before["view_version"],
            request_id="unrelated-finding",
        )
    assert tool.review_snapshot(review_id)["view"] == before["view"]


def test_older_draft_retry_returns_original_outcome_without_clobber(tool, fixture_video):
    plan = tool.plan(str(fixture_video), 0, 1, captions_enabled=False)
    review_id = tool.open_review("plan", plan.id)["review_id"]
    first = tool.save_review_draft(
        review_id, plan.id, {"title": "Earlier"}, 0, request_id="earlier-draft"
    )
    tool.save_review_draft(
        review_id, plan.id, {"title": "Later"}, first["version"], request_id="later-draft"
    )
    retried = tool.save_review_draft(
        review_id, plan.id, {"title": "Earlier"}, 0, request_id="earlier-draft"
    )
    assert retried == first
    assert tool.review_snapshot(review_id)["draft"]["value"] == {"title": "Later"}


def test_sdk_exact_draft_read_handles_missing_and_retained_values(tool, fixture_video):
    plan = tool.plan(str(fixture_video), 0, 1, captions_enabled=False)
    review_id = tool.open_review("plan", plan.id)["review_id"]

    async def run():
        async with Client(create_server(tool.settings, [review_id])) as client:
            arguments = {"review_id": review_id, "base_plan_id": plan.id}
            missing = await client.call_tool("outtake_read_draft", arguments)
            assert not missing.is_error, missing.content
            assert missing.structured_content["result"]["draft"] is None
            tool.save_review_draft(review_id, plan.id, {"title": "Retained"}, 0)
            retained = await client.call_tool("outtake_read_draft", arguments)
            assert not retained.is_error, retained.content
            assert retained.structured_content["result"]["draft"]["value"] == {"title": "Retained"}

    asyncio.run(run())
