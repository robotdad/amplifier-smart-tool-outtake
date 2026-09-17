import asyncio
import json
from types import SimpleNamespace

import pytest

from outtake import ModelGrant, OuttakeError, providers
from outtake.agent_runtime import provider_entry


def test_copilot_credentials_and_pin(monkeypatch):
    for name in providers.COPILOT_ENV:
        monkeypatch.delenv(name, raising=False)
    grant = ModelGrant(provider="github-copilot", model="chosen-model")
    with pytest.raises(OuttakeError):
        provider_entry(grant)
    monkeypatch.setenv("GH_TOKEN", "test-token")
    monkeypatch.setenv("COPILOT_AGENT_TOKEN", "preferred-token")
    entry = provider_entry(grant)
    assert entry["config"]["github_token"] == "preferred-token"
    assert entry["config"]["default_model"] == "chosen-model"
    assert entry["config"]["max_retries"] == 0
    assert entry["source"].endswith(providers.SOURCES["github-copilot"])
    assert "preferred-token" not in grant.model_dump_json()


def test_chatgpt_cache_and_no_implicit_login(monkeypatch, tmp_path):
    path = tmp_path / "oauth.json"
    monkeypatch.setattr(providers, "chatgpt_path", lambda: str(path))
    assert not providers.chatgpt_available()
    grant = ModelGrant(provider="openai-chatgpt", model="chosen-model")
    with pytest.raises(OuttakeError):
        provider_entry(grant)
    path.write_text(json.dumps({"refresh_token": "test-secret"}))
    entry = provider_entry(grant)
    assert entry["config"]["login_on_mount"] is False
    assert entry["config"]["token_file_path"] == str(path)
    assert "test-secret" not in json.dumps(entry)
    assert entry["source"].endswith(providers.SOURCES["openai-chatgpt"])


def test_chatgpt_refresh_before_mount(monkeypatch):
    calls = []

    async def refresh(token, path):
        calls.append((token, path))
        return {"valid": True}

    oauth = SimpleNamespace(
        load_tokens=lambda path: {"refresh_token": "test-refresh"},
        is_token_valid=lambda tokens: bool(tokens and tokens.get("valid")),
        refresh_tokens=refresh,
    )

    async def module(prepared):
        return oauth

    monkeypatch.setattr(providers, "oauth_module", module)
    entry = {"module": "provider-openai-chatgpt", "config": {"token_file_path": "cache"}}
    asyncio.run(providers.refresh_auth(None, entry))
    assert calls == [("test-refresh", "cache")]
    oauth.load_tokens = lambda path: None
    with pytest.raises(OuttakeError, match="missing or expired"):
        asyncio.run(providers.refresh_auth(None, entry))


def test_preferences_do_not_leak_credentials(tool, monkeypatch):
    monkeypatch.setenv("GH_TOKEN", "never-persist-this")
    monkeypatch.setattr(providers, "chatgpt_available", lambda: True)
    result = tool.preferences()
    assert result["credentials"]["github-copilot"]
    assert result["credentials"]["openai-chatgpt"]
    assert "never-persist-this" not in json.dumps(result)
