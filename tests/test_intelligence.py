import asyncio
import json
import os

import pytest

pytest.importorskip("amplifier_agent_lib")
from amplifier_core.message_models import ChatRequest, ChatResponse, Message, ToolCall

from outtake import FindRequest, ModelGrant, OuttakeError
from outtake.agent_runtime import ProviderGate
from outtake.intelligence import SearchTools
from outtake.media import Budget


@pytest.fixture
def grant():
    return ModelGrant(
        provider="gemini",
        model="fixture-model",
        allow_request=True,
        allow_metadata=True,
        allow_frames=True,
        vision=True,
    )


@pytest.fixture
def owner(tool, grant):
    sources = tool.catalog("source")["sources"]
    return SearchTools(
        tool,
        FindRequest(request_id="one", title="source", description="green becoming blue"),
        grant,
        sources,
        Budget(tool.settings.limits),
        "finding_" + "a" * 32,
    )


class RecordingProvider:
    def __init__(self):
        self.requests = []

    async def complete(self, request, **kwargs):
        self.requests.append(request)
        return ChatResponse(content=[])


def test_provider_gate_sends_images_not_paths_and_charges_repeated_context(owner):
    sid = next(iter(owner.sources))
    evidence = owner.call("sample_frames", {"source_id": sid, "times": [1, 2]})
    assert "image" not in evidence["frames"][0]
    assert owner.delivered == set()
    provider = RecordingProvider()
    gate = ProviderGate(provider, owner)
    request = ChatRequest(messages=[Message(role="user", content="Find the transition")])
    asyncio.run(gate.complete(request))
    wire = provider.requests[0].model_dump_json()
    assert "base64" in wire and str(owner.client.roots[0]) not in wire
    import base64
    import io

    from PIL import Image

    images = [
        block for block in json.loads(wire)["messages"][-1]["content"] if block["type"] == "image"
    ]
    assert images[0]["source"]["media_type"] == "image/jpeg"
    with Image.open(io.BytesIO(base64.b64decode(images[0]["source"]["data"]))) as decoded:
        assert decoded.width == 160
        assert decoded.getpixel((80, 50))[1] > 200
    assert str(owner.client.state) not in wire
    assert evidence["id"] in owner.delivered
    assert owner.image_bytes > 0 and owner.model_calls == 1
    previous = owner.text_bytes
    asyncio.run(gate.complete(request))
    assert owner.text_bytes > previous and owner.model_calls == 2
    assert "base64" not in provider.requests[1].model_dump_json()


def test_disclosure_scope_and_shared_limits(owner):
    sid = next(iter(owner.sources))
    owner.grant = owner.grant.model_copy(update={"allow_frames": False})
    with pytest.raises(OuttakeError) as error:
        owner.call("sample_frames", {"source_id": sid, "times": [1]})
    assert error.value.code == "DISCLOSURE_DENIED"
    with pytest.raises(OuttakeError) as error:
        owner.call("inspect_source", {"source_id": "source_" + "f" * 64})
    assert error.value.code == "ACCESS_DENIED"
    owner.grant = owner.grant.model_copy(update={"allow_frames": True, "max_frames": 1})
    owner.call("sample_frames", {"source_id": sid, "times": [1]})
    with pytest.raises(OuttakeError) as error:
        owner.call("sample_frames", {"source_id": sid, "times": [2]})
    assert error.value.code == "RESOURCE_LIMIT"
    assert len(owner.observations) == 1


def test_cannot_submit_invented_or_undelivered_evidence(owner):
    sid = next(iter(owner.sources))
    evidence = owner.call("sample_frames", {"source_id": sid, "times": [1, 2]})
    candidate = {
        "source_id": sid,
        "start": 1,
        "end": 2.5,
        "evidence_ids": [evidence["id"]],
        "explanation": "Green then blue",
        "uncertainty": "Motion between samples unobserved",
    }
    with pytest.raises(ValueError, match="delivered"):
        owner.submit([candidate])
    asyncio.run(ProviderGate(RecordingProvider(), owner).complete(ChatRequest(messages=[])))
    owner.submit([candidate])
    assert owner.result["status"] == "needs_selection"
    assert owner.result["candidates"][0]["human_confirmed"] is False


def test_model_limit_is_enforced_before_next_call(owner):
    owner.grant = owner.grant.model_copy(update={"max_model_calls": 1})
    provider = RecordingProvider()
    gate = ProviderGate(provider, owner)
    asyncio.run(gate.complete(ChatRequest(messages=[])))
    with pytest.raises(OuttakeError) as error:
        asyncio.run(gate.complete(ChatRequest(messages=[])))
    assert error.value.code == "RESOURCE_LIMIT" and len(provider.requests) == 1


def test_text_budget_stops_before_provider_and_errors_are_sanitized(owner):
    owner.grant = owner.grant.model_copy(update={"max_text_bytes": 1})
    provider = RecordingProvider()
    with pytest.raises(OuttakeError) as error:
        asyncio.run(
            ProviderGate(provider, owner).complete(
                ChatRequest(messages=[Message(role="user", content="too large")])
            )
        )
    assert error.value.code == "RESOURCE_LIMIT" and provider.requests == []


def test_provider_exception_does_not_expose_credentials(owner):
    class BrokenProvider:
        async def complete(self, request, **kwargs):
            raise RuntimeError("private-api-key /private/source.mkv")

    with pytest.raises(OuttakeError) as error:
        asyncio.run(ProviderGate(BrokenProvider(), owner).complete(ChatRequest(messages=[])))
    assert "private-api-key" not in str(error.value)
    assert error.value.code == "PROVIDER_ERROR"


def test_limitation_is_a_failure_with_next_question(owner):
    owner.call(
        "report_limitation",
        {
            "reason": "The sampled frames do not establish the event.",
            "question": "Which part of the film do you remember?",
        },
    )
    assert owner.result["status"] == "failed"
    assert owner.result["error"]["code"] == "INSUFFICIENT_EVIDENCE"
    assert owner.result["absence_proven"] is False
    assert owner.result["error"]["remediation"]


class ScriptedProvider:
    """A protocol fixture, not an evaluation of a model's scene understanding."""

    name = "fixture"

    def __init__(self):
        self.calls = 0
        self.requests = []

    def get_info(self):
        from amplifier_core.models import ProviderInfo

        return ProviderInfo(
            id="gemini",
            display_name="Offline fixture",
            credential_env_vars=[],
            capabilities=["tools"],
            defaults={"model": "fixture-model"},
        )

    def parse_tool_calls(self, response):
        return response.tool_calls or []

    async def complete(self, request, **kwargs):
        self.calls += 1
        self.requests.append(request)
        wire = request.model_dump_json()
        import re

        sid = re.search(r"source_[a-f0-9]{64}", wire).group()
        if self.calls == 1:
            name, arguments = "sample_frames", {"source_id": sid, "times": [1, 2]}
        else:
            eid = re.search(r"evidence_[a-f0-9]{32}", wire).group()
            name, arguments = (
                "submit_candidates",
                {
                    "candidates": [
                        {
                            "source_id": sid,
                            "start": 0.95,
                            "end": 2.5,
                            "evidence_ids": [eid],
                            "explanation": "Green then blue.",
                            "uncertainty": "Sampled frames leave a gap; sound requires user review.",
                        }
                    ]
                },
            )
        return ChatResponse(
            content=[],
            tool_calls=[ToolCall(id=f"call{self.calls}", name=name, arguments=arguments)],
        )


def fixture_prepared(provider):
    class Coordinator:
        def __init__(self):
            self.mounts = {"providers": {"fixture": provider}, "tools": {}}

        def get(self, kind):
            return self.mounts[kind]

        async def mount(self, kind, value, name):
            self.mounts[kind][name] = value

    class Session:
        def __init__(self):
            self.coordinator = Coordinator()

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def execute(self, prompt):
            request = ChatRequest(messages=[Message(role="user", content=prompt)])
            provider = self.coordinator.get("providers")["fixture"]
            for _ in range(4):
                response = await provider.complete(request)
                for call in response.tool_calls:
                    result = await self.coordinator.get("tools")[call.name].execute(call.arguments)
                    assert result.success, result
                    request.messages.append(Message(role="user", content=json.dumps(result.output)))

    class Prepared:
        mount_plan = {
            "tools": ["filesystem"],
            "agents": {"default": {}},
            "hooks": ["logging"],
            "providers": [],
        }

        async def create_session(self, **kwargs):
            assert self.mount_plan["tools"] == []
            assert self.mount_plan["agents"] == {}
            assert self.mount_plan["hooks"] == []
            return Session()

    return Prepared()


@pytest.fixture
def offline_agent(monkeypatch):
    import amplifier_agent_lib.engine as engine

    from outtake import agent_runtime

    provider = ScriptedProvider()

    async def prepared(**kwargs):
        return fixture_prepared(provider)

    monkeypatch.setattr(engine, "load_and_prepare_cached", prepared)
    monkeypatch.setattr(
        agent_runtime, "provider_entry", lambda grant: {"module": "offline-fixture"}
    )
    return provider


def test_find_select_revise_render_and_idempotent_retry(tool, grant, offline_agent):
    request = {"request_id": "flow", "title": "source", "description": "green becoming blue"}
    result = tool.find(request, grant)
    assert result["status"] == "needs_selection", result
    assert result["usage"]["model_calls"] == 2
    candidate = result["candidates"][0]
    plan = tool.select(result["id"], candidate["id"], format="png")
    assert plan.provenance == "model_proposal" and plan.evidence_ids
    receipt = tool.render(plan)
    assert receipt["resolved_start"] == 1
    assert tool.revise(plan, {"end": 2.8}).finding_id == result["id"]
    assert tool.find(request) == result  # Retained result needs no provider credentials.
    assert offline_agent.calls == 2
    with pytest.raises(OuttakeError) as error:
        tool.find({**request, "description": "different"}, grant)
    assert error.value.code == "REQUEST_CONFLICT"


def test_find_requires_explicit_grant(tool):
    with pytest.raises(OuttakeError) as error:
        tool.find({"request_id": "no-grant", "title": "source", "description": "a scene"})
    assert error.value.code == "PROVIDER_NOT_AUTHORIZED"


def test_make_retries_return_same_artifact_without_spend(tool, grant, offline_agent):
    request = {"request_id": "make-once", "title": "source", "description": "green then blue"}
    result = tool.make(request, grant, format="png")
    assert result["status"] == "ready", result
    assert tool.make(request, format="png") == result
    assert offline_agent.calls == 2
    assert len(tool.saved_outputs()) == 1
    with pytest.raises(OuttakeError) as error:
        tool.make(request, format="gif")
    assert error.value.code == "REQUEST_CONFLICT"


def test_cancellation_stops_an_active_agent_call(tool, grant, monkeypatch):
    import amplifier_agent_lib.engine as engine

    from outtake import agent_runtime

    class WaitingProvider:
        started = False
        stopped = False

        async def complete(self, request, **kwargs):
            self.started = True
            try:
                await asyncio.sleep(10)
            finally:
                self.stopped = True

    provider = WaitingProvider()

    async def prepared(**kwargs):
        return fixture_prepared(provider)

    monkeypatch.setattr(engine, "load_and_prepare_cached", prepared)
    monkeypatch.setattr(agent_runtime, "provider_entry", lambda grant: {"module": "fixture"})
    result = tool.find(
        {"request_id": "cancel-active", "title": "source", "description": "anything"},
        grant,
        cancelled=lambda: provider.started,
    )
    assert result["status"] == "cancelled", result
    assert provider.started and provider.stopped
    assert tool.saved_outputs() == []


def test_actual_amplifier_session_with_scripted_provider(tool, grant, monkeypatch):
    if os.environ.get("OUTTAKE_TEST_CACHED_AMPLIFIER") != "1":
        pytest.skip("Opt-in: uses locally cached Amplifier bundle/modules with network denied.")
    from amplifier_agent_lib.bundle.cache import load_and_prepare_cached

    from outtake import agent_runtime

    prepared = asyncio.run(load_and_prepare_cached(aaa_version="0.17.0"))
    original = type(prepared).create_session
    provider = ScriptedProvider()

    async def create_session(self, **kwargs):
        self.mount_plan["providers"] = []
        session = await original(self, **kwargs)
        await session.coordinator.mount("providers", provider, name="fixture")
        return session

    monkeypatch.setattr(type(prepared), "create_session", create_session)
    monkeypatch.setattr(
        agent_runtime, "provider_entry", lambda grant: {"module": "offline-fixture"}
    )
    result = tool.find(
        {"request_id": "actual-engine", "title": "source", "description": "green then blue"}, grant
    )
    assert result["status"] == "needs_selection", result
    assert provider.calls == 2
    assert "base64" in provider.requests[1].model_dump_json()
    assert all(str(tool.roots[0]) not in r.model_dump_json() for r in provider.requests)
    assert all(str(tool.state) not in r.model_dump_json() for r in provider.requests)


def test_sdk_metadata_does_not_break_response_budget(owner):
    from types import SimpleNamespace

    class SDKProvider:
        async def complete(self, request, **kwargs):
            return ChatResponse(content=[], metadata={"raw_response": SimpleNamespace(parts=[])})

    asyncio.run(ProviderGate(SDKProvider(), owner).complete(ChatRequest(messages=[])))
    assert owner.model_calls == 1


def test_source_resolution_never_escapes_original_title_or_selected_sources(owner, fixture_video):
    import shutil

    other = fixture_video.parent / "unrelated.mkv"
    shutil.copyfile(fixture_video, other)
    result = owner.call("resolve_sources", {"clue": "unrelated"})
    assert result["sources"] == []
    owner.request = owner.request.model_copy(update={"source_ids": tuple(owner.sources)})
    assert (
        owner.call("resolve_sources", {"clue": "source"})["sources"][0]["source_id"]
        in owner.sources
    )
    other.unlink()


def test_denied_extra_frames_leave_room_for_honest_limitation(owner):
    owner.grant = owner.grant.model_copy(update={"max_frames": 0})
    sample = next(t for t in owner.mountables() if t.name == "sample_frames")
    result = asyncio.run(sample.execute({"source_id": next(iter(owner.sources)), "times": [1]}))
    assert result.success is False and owner.fatal is None
    owner.call(
        "report_limitation",
        {
            "reason": "No permitted frames to verify this event.",
            "question": "Allow frames or provide a more specific clue?",
        },
    )
    assert owner.result["error"]["code"] == "INSUFFICIENT_EVIDENCE"
    assert owner.result["absence_proven"] is False
