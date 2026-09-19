import asyncio
import base64
import os
import sqlite3
import threading
import time

import pytest

from outtake.collaboration import public_projection
from outtake.discovery import save_record
from outtake.mcp_adapter import create_server
from outtake.models import OuttakeError


def _wait(tool, operation_id):
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        result = tool.get_operation(operation_id)
        if result["status"] in {"completed", "failed", "cancelled", "interrupted", "uncertain"}:
            return result
        time.sleep(0.05)
    raise AssertionError("retained operation did not finish")


def test_review_drafts_and_scoped_material_are_retained(tool, fixture_video):
    plan = tool.plan(str(fixture_video), 0, 1, captions_enabled=False)
    receipt = tool.render(plan)
    review = tool.open_review("artifact", receipt["artifact_id"])
    first = tool.save_review_draft(review["review_id"], plan.id, {"title": "typing"}, 0)
    assert first["version"] == 1
    with pytest.raises(OuttakeError, match="newer raw draft"):
        tool.save_review_draft(review["review_id"], plan.id, {"title": "old"}, 0)
    snapshot = tool.review_snapshot(review["review_id"])
    assert snapshot["draft"]["value"]["title"] == "typing"
    descriptor = tool.describe_media(review["review_id"], "artifact", receipt["artifact_id"])
    chunk = tool.read_media(review["review_id"], descriptor["media_id"], 0, 100)
    assert base64.b64decode(chunk["data_base64"])
    projected = public_projection(receipt)
    assert "artifact" not in projected and "receipt" not in projected
    other = tool.plan(str(fixture_video), 1, 2, captions_enabled=False)
    other_receipt = tool.render(other)
    with pytest.raises(OuttakeError, match="outside explicit review scope"):
        tool.describe_media(review["review_id"], "artifact", other_receipt["artifact_id"])


def test_admission_exact_retry_conflict_and_detached_render(tool, fixture_video):
    plan = tool.plan(str(fixture_video), 0, 1, captions_enabled=False)
    first = tool.admit_operation("render-one", "render", {"plan": plan.model_dump()})
    retried = tool.admit_operation("render-one", "render", {"plan": plan.model_dump()})
    assert retried["operation_id"] == first["operation_id"]
    with pytest.raises(OuttakeError, match="different operation"):
        tool.admit_operation("render-one", "preview", {"plan": plan.model_dump()})
    result = _wait(tool, first["operation_id"])
    assert result["status"] == "completed"
    assert result["result"]["status"] == "ready"
    assert result["result"]["artifact_id"] == first["output_id"]
    assert tool.artifact(first["output_id"])["sha256"] == result["result"]["sha256"]


def test_cancellation_before_claim_publishes_nothing(tool, fixture_video, monkeypatch):
    plan = tool.plan(str(fixture_video), 0, 1, captions_enabled=False)
    monkeypatch.setattr("outtake.collaboration._spawn", lambda client, operation_id: None)
    admitted = tool.admit_operation("cancel-before-claim", "render", {"plan": plan.model_dump()})
    cancelled = tool.cancel_operation(admitted["operation_id"])
    assert cancelled["status"] == "cancelled"
    with pytest.raises(OuttakeError, match="unavailable"):
        tool.artifact(admitted["output_id"])
    assert tool.recover_operations()["replayed"] is False


def test_recovery_records_preassigned_published_output_without_replay(
    tool, fixture_video, monkeypatch
):
    plan = tool.plan(str(fixture_video), 0, 1, captions_enabled=False)
    monkeypatch.setattr("outtake.collaboration._spawn", lambda client, operation_id: None)
    admitted = tool.admit_operation("recover-published", "render", {"plan": plan.model_dump()})
    receipt = tool._render_retained(plan, admitted["output_id"], "render", lambda: True, os.rename)
    assert receipt["artifact_id"] == admitted["output_id"]
    recovered = tool.recover_operations()
    assert recovered["recovered"] == [
        {"operation_id": admitted["operation_id"], "status": "completed"}
    ]
    assert tool.get_operation(admitted["operation_id"])["status"] == "completed"


def test_optional_mcp_adapter_uses_typed_scoped_tools(tool, fixture_video):
    plan = tool.plan(str(fixture_video), 0, 1, captions_enabled=False)
    review = tool.open_review("plan", plan.id)
    server = create_server(tool.settings, [review["review_id"]])
    tools = asyncio.run(server.list_tools())
    by_name = {item.name: item for item in tools}
    assert "outtake_review" in by_name
    assert by_name["outtake_review"].output_schema
    assert by_name["outtake_review"].annotations.read_only_hint is True
    assert "outtake_describe_media" in by_name
    assert "outtake_saved_outputs" in by_name
    assert "expected_plan_id" in by_name["outtake_rename_saved_output"].input_schema["properties"]


def test_real_mcp_saved_output_scope_pages_and_rejects_forged_ids(tool, fixture_video):
    from mcp import Client

    first_plan = tool.plan(str(fixture_video), 0, 1, captions_enabled=False)
    first = tool.render(first_plan)
    second = tool.render(tool.plan(str(fixture_video), 1, 2, captions_enabled=False))
    review_id = tool.open_review("artifact", first["artifact_id"])["review_id"]

    async def run():
        async with Client(create_server(tool.settings, [review_id])) as client:
            listed = await client.call_tool(
                "outtake_saved_outputs", {"offset": 0, "limit": 1, "sort_by": "newest"}
            )
            page = listed.structured_content["result"]
            assert page["total"] == 1
            assert page["outputs"][0]["artifact_id"] == first["artifact_id"]
            assert "artifact" not in page["outputs"][0]
            for name, arguments in (
                ("outtake_open_saved_output", {"artifact_id": second["artifact_id"]}),
                (
                    "outtake_describe_saved_output_media",
                    {"artifact_id": second["artifact_id"]},
                ),
            ):
                denied = await client.call_tool(name, arguments)
                assert denied.is_error

    asyncio.run(run())


def test_scoped_saved_outputs_are_bounded_reopenable_and_do_not_expose_siblings(
    tool, fixture_video
):
    from outtake.collaboration import ReviewScope

    first_plan = tool.plan(str(fixture_video), 0, 1, captions_enabled=False)
    first = tool.render(first_plan)
    second_plan = tool.plan(str(fixture_video), 1, 2, captions_enabled=False)
    second = tool.render(second_plan)
    preview = tool.preview(first_plan)
    review_id = tool.open_review("artifact", first["artifact_id"])["review_id"]
    scope = ReviewScope([review_id])

    page = tool.get_scoped_saved_outputs(limit=1, sort_by="newest", scope=scope)
    assert page["total"] == 1
    assert page["outputs"][0]["artifact_id"] == first["artifact_id"]
    assert preview["artifact_id"] not in {item["artifact_id"] for item in page["outputs"]}

    opened = tool.open_scoped_saved_output(first["artifact_id"], scope, "open-first")
    replay = tool.open_scoped_saved_output(first["artifact_id"], scope, "open-first")
    assert replay["review_id"] == opened["review_id"]
    draft = tool.save_review_draft(
        opened["review_id"], first_plan.id, {"title": "unapplied saved text"}, 0, scope=scope
    )
    reopened = tool.open_scoped_saved_output(first["artifact_id"], scope, "open-again")
    assert reopened["review_id"] == opened["review_id"]
    assert (
        tool.get_review_draft(opened["review_id"], first_plan.id, scope)["version"]
        == draft["version"]
    )
    # Derived export review remains authorized after a server reconnect with only
    # its original parent review, not an unbounded allow-review list.
    restarted_scope = ReviewScope([review_id])
    assert (
        tool.review_snapshot(opened["review_id"], restarted_scope)["workspace_id"]
        == first["artifact_id"]
    )
    with pytest.raises(OuttakeError, match="not within"):
        tool.rename_scoped_saved_output(
            opened["review_id"],
            second["artifact_id"],
            "forged",
            expected_plan_id=second_plan.id,
            scope=restarted_scope,
        )
    with pytest.raises(OuttakeError, match="not within"):
        tool.describe_scoped_saved_output_media(second["artifact_id"], restarted_scope)


def test_saved_output_collection_authority_is_explicit_and_never_crosses_roots(
    tool, fixture_video, tmp_path
):
    from outtake.collaboration import ReviewScope
    from outtake.lib import Outtake

    first = tool.render(tool.plan(str(fixture_video), 0, 1, captions_enabled=False))
    second = tool.render(tool.plan(str(fixture_video), 1, 2, captions_enabled=False))
    collection = ReviewScope([], allow_saved_outputs=True)
    page = tool.get_scoped_saved_outputs(limit=50, sort_by="name", scope=collection)
    assert {item["artifact_id"] for item in page["outputs"]} == {
        first["artifact_id"],
        second["artifact_id"],
    }

    foreign_settings = tool.settings.model_copy(
        update={"output_root": str(tmp_path / "private-output")}
    )
    foreign = Outtake(foreign_settings)
    private = foreign.render(foreign.plan(str(fixture_video), 0, 1, captions_enabled=False))
    with pytest.raises(OuttakeError) as denied:
        tool.describe_scoped_saved_output_media(private["artifact_id"], collection)
    assert denied.value.code in {"ARTIFACT_MISSING", "OUTPUT_SCOPE_DENIED"}


def test_scoped_saved_output_rename_and_delete_retry_without_rerender(tool, fixture_video):
    from outtake.collaboration import ReviewScope

    plan = tool.plan(str(fixture_video), 0, 1, captions_enabled=False)
    receipt = tool.render(plan)
    parent = tool.open_review("artifact", receipt["artifact_id"])["review_id"]
    scope = ReviewScope([parent])
    opened = tool.open_scoped_saved_output(receipt["artifact_id"], scope)
    renamed = tool.rename_scoped_saved_output(
        opened["review_id"],
        receipt["artifact_id"],
        "A retained name",
        expected_plan_id=plan.id,
        scope=scope,
        request_id="rename-once",
    )
    replay = tool.rename_scoped_saved_output(
        opened["review_id"],
        receipt["artifact_id"],
        "A retained name",
        expected_plan_id=plan.id,
        scope=scope,
        request_id="rename-once",
    )
    assert replay["plan"]["id"] == renamed["plan"]["id"]
    assert tool.artifact(receipt["artifact_id"])["sha256"] == receipt["sha256"]
    with pytest.raises(OuttakeError, match="changed since it was displayed"):
        tool.rename_scoped_saved_output(
            opened["review_id"],
            receipt["artifact_id"],
            "stale rename",
            expected_plan_id=plan.id,
            scope=scope,
            request_id="rename-stale",
        )
    deleted = tool.delete_scoped_saved_output(
        opened["review_id"],
        receipt["artifact_id"],
        expected_plan_id=renamed["plan"]["id"],
        scope=scope,
        request_id="delete-once",
    )
    assert deleted["already_absent"] is False
    assert (
        tool.delete_scoped_saved_output(
            opened["review_id"],
            receipt["artifact_id"],
            expected_plan_id=renamed["plan"]["id"],
            scope=scope,
            request_id="delete-once",
        )
        == deleted
    )


def test_scoped_rename_lost_completion_stays_incomplete_not_title_inferred(
    tool, fixture_video, monkeypatch
):
    import outtake.collaboration as collaboration

    plan = tool.plan(str(fixture_video), 0, 1, captions_enabled=False)
    receipt = tool.render(plan)
    review_id = tool.open_review("artifact", receipt["artifact_id"])["review_id"]
    scope = collaboration.ReviewScope([review_id])
    original_finish = collaboration._finish_mutation

    def lose_completion(*args, **kwargs):
        raise RuntimeError("response lost after receipt rename")

    monkeypatch.setattr(collaboration, "_finish_mutation", lose_completion)
    with pytest.raises(RuntimeError, match="lost after receipt rename"):
        tool.rename_scoped_saved_output(
            review_id,
            receipt["artifact_id"],
            "Same title is not proof",
            expected_plan_id=plan.id,
            scope=scope,
            request_id="rename-lost-completion",
        )
    monkeypatch.setattr(collaboration, "_finish_mutation", original_finish)
    # The receipt happened to change, but no retained completion proves that this
    # request caused it; retry must not turn a title match into success.
    assert tool.artifact(receipt["artifact_id"])["plan"]["title"] == "Same title is not proof"
    with pytest.raises(OuttakeError, match="prior mutation response is uncertain"):
        tool.rename_scoped_saved_output(
            review_id,
            receipt["artifact_id"],
            "Same title is not proof",
            expected_plan_id=plan.id,
            scope=scope,
            request_id="rename-lost-completion",
        )


def test_scoped_output_cas_serializes_native_rename_and_blocks_stale_delete(
    tool, fixture_video, monkeypatch
):
    import outtake.collaboration as collaboration

    plan = tool.plan(str(fixture_video), 0, 1, captions_enabled=False)
    receipt = tool.render(plan)
    review_id = tool.open_review("artifact", receipt["artifact_id"])["review_id"]
    scope = collaboration.ReviewScope([review_id])
    original_begin = collaboration._begin_mutation
    injected = {"done": False}

    def native_wins_after_admission(client, mutation_review_id, request_id, action, payload):
        result = original_begin(client, mutation_review_id, request_id, action, payload)
        if action == "rename-output" and not injected["done"]:
            injected["done"] = True
            # Native callers take the same receipt lock. This write occurs after
            # portable admission but before its effect, so its old CAS must fail.
            tool.rename_output(receipt["artifact_id"], "Native newer name")
        return result

    monkeypatch.setattr(collaboration, "_begin_mutation", native_wins_after_admission)
    with pytest.raises(OuttakeError, match="changed since it was displayed"):
        tool.rename_scoped_saved_output(
            review_id,
            receipt["artifact_id"],
            "Portable stale name",
            expected_plan_id=plan.id,
            scope=scope,
            request_id="rename-raced",
        )
    assert tool.artifact(receipt["artifact_id"])["plan"]["title"] == "Native newer name"
    with pytest.raises(OuttakeError, match="prior mutation response is uncertain"):
        tool.rename_scoped_saved_output(
            review_id,
            receipt["artifact_id"],
            "Portable stale name",
            expected_plan_id=plan.id,
            scope=scope,
            request_id="rename-raced",
        )

    current = tool.artifact(receipt["artifact_id"])["plan"]["id"]
    tool.rename_output(receipt["artifact_id"], "Native wins before delete")
    with pytest.raises(OuttakeError, match="changed since it was displayed"):
        tool.delete_scoped_saved_output(
            review_id,
            receipt["artifact_id"],
            expected_plan_id=current,
            scope=scope,
            request_id="delete-raced",
        )
    assert tool.artifact(receipt["artifact_id"])["plan"]["title"] == "Native wins before delete"


def test_review_scope_never_leaks_same_plan_sibling_workspace_or_media(tool, fixture_video):
    from outtake.collaboration import ReviewScope

    plan = tool.plan(str(fixture_video), 0, 1, captions_enabled=False)
    first = tool.render(plan)
    second = tool.render(plan)
    first_review = tool.open_review("artifact", first["artifact_id"])["review_id"]
    second_review = tool.open_review("artifact", second["artifact_id"])["review_id"]
    scope = ReviewScope([first_review])
    tool.save_review_draft(first_review, plan.id, {"title": "first private draft"}, 0)
    tool.save_review_draft(second_review, plan.id, {"title": "second private draft"}, 0)

    listed = tool.get_scoped_saved_outputs(scope=scope)
    assert [item["artifact_id"] for item in listed["outputs"]] == [first["artifact_id"]]
    with pytest.raises(OuttakeError, match="not within"):
        tool.open_scoped_saved_output(second["artifact_id"], scope)
    with pytest.raises(OuttakeError, match="outside explicit review scope"):
        tool.describe_media(first_review, "artifact", second["artifact_id"], scope=scope)
    assert (
        tool.get_review_draft(first_review, plan.id, scope)["value"]["title"]
        == "first private draft"
    )
    collection = ReviewScope([first_review], allow_saved_outputs=True)
    assert {
        item["artifact_id"] for item in tool.get_scoped_saved_outputs(scope=collection)["outputs"]
    } == {first["artifact_id"], second["artifact_id"]}


def test_saved_output_derived_review_rejects_restart_on_another_output_root(
    tool, fixture_video, tmp_path
):
    from outtake.collaboration import ReviewScope
    from outtake.lib import Outtake

    plan = tool.plan(str(fixture_video), 0, 1, captions_enabled=False)
    receipt = tool.render(plan)
    parent = tool.open_review("artifact", receipt["artifact_id"])["review_id"]
    derived = tool.open_scoped_saved_output(
        receipt["artifact_id"], ReviewScope([parent]), "open-root-bound"
    )
    restarted = Outtake(
        tool.settings.model_copy(update={"output_root": str(tmp_path / "other-output")})
    )
    scope = ReviewScope([parent], allow_saved_outputs=True)
    assert restarted.get_scoped_saved_outputs(scope=scope)["outputs"] == []
    with pytest.raises(OuttakeError, match="not within"):
        restarted.review_snapshot(derived["review_id"], scope)


def test_operation_database_migrates_existing_schema(tool, fixture_video):
    database = tool.state / "collaboration.sqlite3"
    database.parent.mkdir(exist_ok=True)
    with sqlite3.connect(database) as db:
        db.execute(
            """CREATE TABLE operations (
                id TEXT PRIMARY KEY, request_id TEXT UNIQUE NOT NULL, signature TEXT NOT NULL,
                operation TEXT NOT NULL, arguments TEXT NOT NULL, settings TEXT NOT NULL,
                grant TEXT, output_id TEXT, status TEXT NOT NULL, result TEXT,
                cancel_requested INTEGER NOT NULL DEFAULT 0, lease_token TEXT,
                lease_until REAL, created REAL NOT NULL, updated REAL NOT NULL
            )"""
        )
    plan = tool.plan(str(fixture_video), 0, 1, captions_enabled=False)
    tool.open_review("plan", plan.id)
    with sqlite3.connect(database) as db:
        columns = {row[1] for row in db.execute("PRAGMA table_info(operations)")}
    assert "review_id" in columns


def test_navigation_and_mutation_retry_keep_exact_displayed_base(tool, fixture_video):
    base = tool.plan(str(fixture_video), 0, 1, captions_enabled=False)
    review_id = tool.open_review("plan", base.id)["review_id"]
    initial = tool.review_snapshot(review_id)
    updated = tool.apply_review_changes(
        review_id,
        {"title": "one"},
        plan_id=base.id,
        request_id="apply-one",
    )
    replay = tool.apply_review_changes(
        review_id,
        {"title": "one"},
        plan_id=base.id,
        request_id="apply-one",
    )
    assert replay["plan"]["id"] == updated["plan"]["id"]
    with pytest.raises(OuttakeError, match="changed inputs"):
        tool.apply_review_changes(
            review_id,
            {"title": "different"},
            plan_id=base.id,
            request_id="apply-one",
        )
    # Workspace head advanced, but the displayed revision stays explicit until navigation.
    snapshot = tool.review_snapshot(review_id)
    assert snapshot["displayed_plan"]["id"] == base.id
    assert snapshot["head_plan_id"] == updated["plan"]["id"]
    navigated = tool.navigate_review(
        review_id, {"plan_id": updated["plan"]["id"], "playhead": 0.5}, initial["view_version"]
    )
    assert navigated["view"]["plan_id"] == updated["plan"]["id"]


def test_sdk_resource_templates_expose_safe_review_and_fixed_media_chunks(tool, fixture_video):
    from mcp import Client

    plan = tool.plan(str(fixture_video), 0, 1, captions_enabled=False)
    receipt = tool.render(plan)
    review_id = tool.open_review("artifact", receipt["artifact_id"])["review_id"]

    async def run():
        async with Client(create_server(tool.settings, [review_id])) as client:
            templates = await client.list_resource_templates()
            assert any(
                item.uri_template == "outtake://review/{review_id}/media/{media_id}/{offset}"
                for item in templates.resource_templates
            )
            review = await client.read_resource(f"outtake://review/{review_id}")
            assert "path" not in review.contents[0].text
            descriptor = await client.call_tool(
                "outtake_describe_media",
                {"review_id": review_id, "kind": "artifact", "identity": receipt["artifact_id"]},
            )
            value = descriptor.structured_content["result"]
            resource = await client.read_resource(value["resource_uri"])
            assert len(resource.contents[0].blob) <= 192 * 1024

    asyncio.run(run())


def test_navigation_denies_unlinked_finding_and_invalid_semantics(tool, fixture_video):
    from outtake.discovery import save_record

    plan = tool.plan(str(fixture_video), 0, 1, captions_enabled=False)
    review_id = tool.open_review("plan", plan.id)["review_id"]
    other = {
        "id": "finding_" + "a" * 32,
        "status": "needs_selection",
        "candidates": [
            {
                "id": "candidate_other",
                "source_id": "source_other",
                "evidence_ids": [],
                "start": 0,
                "end": 1,
            }
        ],
    }
    save_record(tool, "findings", other)
    snapshot = tool.review_snapshot(review_id)
    with pytest.raises(OuttakeError, match="not linked"):
        tool.navigate_review(review_id, {"finding_id": other["id"]}, snapshot["view_version"])
    with pytest.raises(OuttakeError, match="Cue"):
        tool.navigate_review(
            review_id, {"plan_id": plan.id, "cue_id": "cue_missing"}, snapshot["view_version"]
        )
    with pytest.raises(OuttakeError, match="finite"):
        tool.navigate_review(
            review_id, {"plan_id": plan.id, "playhead": float("inf")}, snapshot["view_version"]
        )


def test_export_review_rejects_sibling_workspace_descendant(tool, fixture_video):
    base = tool.plan(str(fixture_video), 0, 1, captions_enabled=False)
    receipt = tool.render(base)
    tool.get_workspace(base.id, receipt["artifact_id"])
    sibling = tool.save_workspace(base.id, base, {"title": "ordinary sibling"})
    review_id = tool.open_review("artifact", receipt["artifact_id"])["review_id"]
    with pytest.raises(OuttakeError, match="outside this review"):
        tool.apply_review_changes(review_id, {"title": "wrong export"}, plan_id=sibling.id)


def test_apply_recovers_after_finish_response_gap(tool, fixture_video, monkeypatch):
    import outtake.collaboration as collaboration

    base = tool.plan(str(fixture_video), 0, 1, captions_enabled=False)
    review_id = tool.open_review("plan", base.id)["review_id"]
    original_finish = collaboration._finish_mutation

    def lost_finish(*args, **kwargs):
        raise RuntimeError("simulated lost response after workspace commit")

    monkeypatch.setattr(collaboration, "_finish_mutation", lost_finish)
    with pytest.raises(RuntimeError, match="lost response"):
        tool.apply_review_changes(
            review_id, {"title": "once"}, plan_id=base.id, request_id="apply-lost-response"
        )
    monkeypatch.setattr(collaboration, "_finish_mutation", original_finish)
    recovered = tool.apply_review_changes(
        review_id, {"title": "once"}, plan_id=base.id, request_id="apply-lost-response"
    )
    assert recovered["plan"]["title"] == "once"
    assert tool.get_workspace(base.id)["plan"]["id"] == recovered["plan"]["id"]


def test_drafts_retain_old_request_outcomes_and_snapshot_stays_bounded(tool, fixture_video):
    base = tool.plan(str(fixture_video), 0, 1, captions_enabled=False)
    review_id = tool.open_review("plan", base.id)["review_id"]
    first = tool.save_review_draft(
        review_id, base.id, {"title": "first"}, 0, request_id="draft-first"
    )
    second = tool.save_review_draft(
        review_id, base.id, {"title": "second"}, 1, request_id="draft-second"
    )
    assert (
        tool.save_review_draft(review_id, base.id, {"title": "first"}, 0, request_id="draft-first")
        == first
    )
    assert second["version"] == 2
    with pytest.raises(OuttakeError, match="size limit"):
        tool.save_review_draft(review_id, base.id, {"text": "x" * (256 * 1024)}, 2)
    snapshot = tool.review_snapshot(review_id)
    assert "value" in snapshot["draft"]
    assert all("value" not in item for item in snapshot["drafts"])
    assert snapshot["snapshot_limits"]["draft_summaries"] == 8


def _selection_fixture(tool, fixture_video):
    base = tool.plan(str(fixture_video), 0, 1, captions_enabled=False)
    source_id = "source_" + "b" * 32
    save_record(
        tool,
        "sources",
        {
            "id": source_id,
            "path": str(fixture_video),
            "label": "fixture",
            "identity_verified": False,
        },
    )
    finding_id = "finding_" + "b" * 32
    candidate_id = "candidate_fixture"
    save_record(
        tool,
        "findings",
        {
            "id": finding_id,
            "request": {"description": "fixture selection"},
            "status": "needs_selection",
            "candidates": [
                {
                    "id": candidate_id,
                    "source_id": source_id,
                    "source_sha256": base.source.sha256,
                    "start": 0,
                    "end": 1,
                    "evidence_ids": [],
                    "uncertainty": "fixture",
                }
            ],
        },
    )
    return finding_id, candidate_id


def test_selection_retry_never_adopts_older_matching_plan(tool, fixture_video):
    finding_id, candidate_id = _selection_fixture(tool, fixture_video)
    older = tool.select(finding_id, candidate_id)
    edited = tool.revise(older, {"title": "unrelated old edit"})
    review_id = tool.open_review("finding", finding_id)["review_id"]

    selected = tool.select_review_candidate(
        review_id, finding_id, candidate_id, request_id="select-new"
    )
    assert selected["selected_plan_id"] not in {older.id, edited.id}
    assert tool.get_plan(selected["selected_plan_id"]).title != "unrelated old edit"


def test_selection_recovers_only_preassigned_plan_after_interruption(
    tool, fixture_video, monkeypatch
):
    finding_id, candidate_id = _selection_fixture(tool, fixture_video)
    review_id = tool.open_review("finding", finding_id)["review_id"]
    original_workspace = tool.get_workspace
    calls = 0

    def interrupt_after_retain(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("interrupt after retained select")
        return original_workspace(*args, **kwargs)

    monkeypatch.setattr(tool, "get_workspace", interrupt_after_retain)
    with pytest.raises(RuntimeError, match="interrupt"):
        tool.select_review_candidate(
            review_id, finding_id, candidate_id, request_id="select-recover"
        )
    monkeypatch.setattr(tool, "get_workspace", original_workspace)
    selected = tool.select_review_candidate(
        review_id, finding_id, candidate_id, request_id="select-recover"
    )
    assert selected["selected_plan_id"].startswith("plan_")
    plans = [
        tool.get_plan(path.stem)
        for path in (tool.state / "plans").glob("plan_*.json")
        if tool.get_plan(path.stem).finding_id == finding_id
        and tool.get_plan(path.stem).candidate_id == candidate_id
    ]
    assert [plan.id for plan in plans] == [selected["selected_plan_id"]]


def test_selection_concurrent_retry_never_creates_second_plan(tool, fixture_video, monkeypatch):
    finding_id, candidate_id = _selection_fixture(tool, fixture_video)
    review_id = tool.open_review("finding", finding_id)["review_id"]
    original_select = tool.select
    entered, release = threading.Event(), threading.Event()

    def delayed_select(*args, **kwargs):
        entered.set()
        assert release.wait(5)
        return original_select(*args, **kwargs)

    monkeypatch.setattr(tool, "select", delayed_select)
    results = []

    def select():
        try:
            results.append(
                tool.select_review_candidate(
                    review_id, finding_id, candidate_id, request_id="select-concurrent"
                )
            )
        except OuttakeError as exc:
            results.append(exc.code)

    first = threading.Thread(target=select)
    second = threading.Thread(target=select)
    first.start()
    assert entered.wait(5)
    second.start()
    second.join(5)
    release.set()
    first.join(5)
    assert results.count("MUTATION_INCOMPLETE") == 1
    completed = next(item for item in results if isinstance(item, dict))
    assert (
        tool.select_review_candidate(
            review_id, finding_id, candidate_id, request_id="select-concurrent"
        )
        == completed
    )


def test_selection_recovery_preserves_newer_navigation(tool, fixture_video, monkeypatch):
    finding_id, candidate_id = _selection_fixture(tool, fixture_video)
    review_id = tool.open_review("finding", finding_id)["review_id"]
    original_workspace = tool.get_workspace
    monkeypatch.setattr(
        tool,
        "get_workspace",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("interrupt")),
    )
    with pytest.raises(RuntimeError):
        tool.select_review_candidate(
            review_id, finding_id, candidate_id, request_id="select-navigation-race"
        )
    monkeypatch.setattr(tool, "get_workspace", original_workspace)
    current = tool.review_snapshot(review_id)
    tool.navigate_review(
        review_id,
        {"finding_id": finding_id, "playhead": 0.2},
        current["view_version"],
        request_id="newer-navigation",
    )
    recovered = tool.select_review_candidate(
        review_id, finding_id, candidate_id, request_id="select-navigation-race"
    )
    assert recovered["view_updated"] is False
    assert tool.review_snapshot(review_id)["view"]["playhead"] == 0.2


def test_reopened_workspace_backfills_original_base_history(tool, fixture_video):
    base = tool.plan(str(fixture_video), 0, 1, captions_enabled=False)
    newer = tool.save_workspace(base.id, base, {"title": "newer workspace head"})
    database = tool.state / "workspaces.sqlite3"
    with sqlite3.connect(database) as db:
        db.execute("DELETE FROM history")
    review_id = tool.open_review("plan", base.id)["review_id"]
    assert tool.review_snapshot(review_id)["head_plan_id"] == newer.id
    draft = tool.save_review_draft(review_id, base.id, {"title": "base remains valid"}, 0)
    assert draft["base_plan_id"] == base.id
    with pytest.raises(OuttakeError, match="newer saved edits"):
        tool.apply_review_changes(review_id, {"title": "stale applies conflict"}, plan_id=base.id)
