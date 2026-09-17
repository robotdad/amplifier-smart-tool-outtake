"""Provider-owned authentication; credentials never enter Outtake records."""

import asyncio
import importlib
import os
import sys

from .models import OuttakeError

COPILOT_ENV = ("COPILOT_AGENT_TOKEN", "COPILOT_GITHUB_TOKEN", "GH_TOKEN", "GITHUB_TOKEN")
SOURCES = {
    "github-copilot": "f337d44124ebe8d8f8187833bd7cd512ef30d1b5",
    "openai-chatgpt": "4a6ffdc11483a4192e1514189916fc4a91c202ed",
}


def chatgpt_path():
    from amplifier_agent_cli.provider_sources import oauth_token_path

    return str(oauth_token_path())


def chatgpt_available():
    try:
        import json
        from pathlib import Path

        data = json.loads(Path(chatgpt_path()).read_text())
        return bool(data.get("access_token") or data.get("refresh_token"))
    except (ImportError, OSError, ValueError, AttributeError):
        return False


def entry(provider, model):
    config = {"default_model": model}
    if provider == "github-copilot":
        key = next((os.environ[k] for k in COPILOT_ENV if os.environ.get(k)), None)
        if not key:
            raise OuttakeError(
                "PROVIDER_UNAVAILABLE",
                "GitHub Copilot needs a host credential.",
                'Run gh auth login, then export GH_TOKEN="$(gh auth token)" before starting Outtake. Copilot access is required.',
            )
        config.update(github_token=key, max_retries=0)
    else:
        if not chatgpt_available():
            raise OuttakeError(
                "PROVIDER_UNAVAILABLE",
                "ChatGPT sign-in is required.",
                "Run outtake provider-login with provider openai-chatgpt.",
            )
        config.update(token_file_path=chatgpt_path(), login_on_mount=False)
    return {
        "module": "provider-" + provider,
        "source": f"git+https://github.com/microsoft/amplifier-module-provider-{provider}@{SOURCES[provider]}",
        "config": config,
    }


async def oauth_module(prepared):
    source = await prepared.resolver.async_resolve(
        "provider-openai-chatgpt",
        source_hint="git+https://github.com/microsoft/amplifier-module-provider-openai-chatgpt@"
        + SOURCES["openai-chatgpt"],
    )
    path = str(source.resolve())
    if path not in sys.path:
        sys.path.insert(0, path)
    return importlib.import_module("amplifier_module_provider_openai_chatgpt.oauth")


async def refresh_auth(prepared, provider_entry):
    if provider_entry["module"] != "provider-openai-chatgpt":
        return
    oauth = await oauth_module(prepared)
    path = provider_entry["config"]["token_file_path"]
    tokens = oauth.load_tokens(path)
    if not oauth.is_token_valid(tokens) and tokens and tokens.get("refresh_token"):
        tokens = await oauth.refresh_tokens(tokens["refresh_token"], path=path)
    if not oauth.is_token_valid(tokens):
        raise OuttakeError(
            "PROVIDER_UNAVAILABLE",
            "ChatGPT sign-in is missing or expired.",
            "Run outtake provider-login with provider openai-chatgpt.",
        )


def login(provider, timeout_seconds=300, progress=lambda message: None):
    if provider != "openai-chatgpt":
        raise OuttakeError(
            "INVALID_INPUT",
            "Device login is for openai-chatgpt.",
            'For Copilot use gh auth login, then export GH_TOKEN="$(gh auth token)".',
        )
    if not 1 <= timeout_seconds <= 600:
        raise OuttakeError(
            "INVALID_INPUT", "Login timeout must be 1–600 seconds.", "Choose a bounded timeout."
        )

    async def run():
        from amplifier_agent_lib import __version__
        from amplifier_agent_lib.bundle.cache import load_and_prepare_cached

        prepared = await load_and_prepare_cached(aaa_version=__version__)
        oauth = await oauth_module(prepared)
        await oauth.login(token_file_path=chatgpt_path(), print_fn=progress)

    try:
        asyncio.run(asyncio.wait_for(run(), timeout_seconds))
    except ImportError:
        raise OuttakeError(
            "MISSING_PREREQUISITE", "Install the smart extra.", "Install outtake[smart]."
        ) from None
    except Exception:
        raise OuttakeError(
            "PROVIDER_LOGIN_FAILED",
            "ChatGPT login did not complete.",
            "Retry explicit login and complete the device flow.",
        ) from None
    return {
        "status": "ready",
        "provider": provider,
        "credential_storage": "Amplifier Agent OAuth cache",
    }
