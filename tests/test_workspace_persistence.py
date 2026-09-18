import pytest

from outtake import Outtake
from outtake.models import OuttakeError


def test_workspace_survives_restart_and_rejects_stale_writer(tool, fixture_video):
    original = tool.plan(str(fixture_video), 0, 2, captions_enabled=False)
    current = tool.save_workspace(original.id, original, {"title": "Saved draft"})
    restarted = Outtake(tool.settings)
    assert restarted.get_workspace(original.id)["plan"]["id"] == current.id
    assert restarted.get_workspace(current.id)["workspace_id"] == original.id
    assert restarted.get_plan(original.id).title != "Saved draft"
    with pytest.raises(OuttakeError, match="newer saved edits"):
        restarted.save_workspace(original.id, original, {"title": "Stale edit"})
    other = tool.plan(str(fixture_video), 1, 2)
    with pytest.raises(OuttakeError, match="newer saved edits"):
        tool.save_workspace(original.id, other, {})
    imported = tool.revise(current, {"title": "Explicit revision"})
    tool.save_workspace(original.id, imported, {})
    assert restarted.get_workspace(original.id)["plan"]["id"] == imported.id


def test_publishing_preserves_newer_draft_and_deleted_output_workspace(tool, fixture_video):
    plan = tool.plan(str(fixture_video), 0, 2, title="Original", captions_enabled=False)
    full = tool.render(plan)
    workspace = tool.get_workspace(plan.id, full["artifact_id"])
    short = tool.save_workspace(
        workspace["workspace_id"], workspace["plan"], {"end": 1, "title": "Short"}
    )
    exported = tool.render(short)
    newer = tool.save_workspace(workspace["workspace_id"], short, {"title": "Still editing"})
    result = tool.finish_workspace_export(workspace["workspace_id"], exported["artifact_id"])
    assert result["plan"]["id"] == short.id
    assert tool.get_workspace(plan.id, full["artifact_id"])["plan"]["id"] == newer.id
    tool.delete_output(exported["artifact_id"])
    assert tool.get_workspace(short.id, exported["artifact_id"])["plan"]["title"] == "Short"
