"""Version-pinned Amplifier Agent embedding and the provider disclosure boundary."""

import asyncio
import base64
import copy
import io
import json
import os
import sys
import tempfile
import time
from pathlib import Path

from PIL import Image

from .media import fingerprint
from .models import OuttakeError

PROVIDERS = {
    "openai": ("9831ad3c0221bc6dac5dc717122ef0834af0f77e", ("OPENAI_API_KEY",)),
    "anthropic": ("8a1f837730049b80340a3a2819f48f6563b10368", ("ANTHROPIC_API_KEY",)),
    "gemini": ("a7c5e0ceb11251499009d77b7993b9bbb375be48", ("GOOGLE_API_KEY", "GEMINI_API_KEY")),
}


def provider_entry(grant):
    try:
        import amplifier_agent_lib  # noqa: F401
    except ImportError:
        raise OuttakeError(
            "MISSING_PREREQUISITE",
            "Amplifier Agent is not installed.",
            "Install Outtake with the smart extra: uv pip install '.[smart]'.",
        ) from None
    if grant.provider in {"github-copilot", "openai-chatgpt"}:
        from .providers import entry

        return entry(grant.provider, grant.model)
    revision, variables = PROVIDERS[grant.provider]
    key = next((os.environ[name] for name in variables if os.environ.get(name)), None)
    if not key:
        raise OuttakeError(
            "PROVIDER_UNAVAILABLE",
            "The selected provider has no environment credential.",
            "Set " + " or ".join(variables) + " before starting Outtake.",
        )
    return {
        "module": "provider-" + grant.provider,
        "source": f"git+https://github.com/microsoft/amplifier-module-provider-{grant.provider}@{revision}",
        "config": {
            "api_key": key,
            "default_model": grant.model,
            "max_retries": 0,
            **({"use_streaming": False} if grant.provider == "gemini" else {}),
        },
    }


class Finished(BaseException):
    """Stop the model loop after a validated submission, without another paid call."""


class ProviderGate:
    def __init__(self, provider, tools):
        self.inner, self.tools = provider, tools

    def __getattr__(self, name):
        # Prefer the non-streaming path, so a partial response never becomes a result.
        if name == "stream":
            raise AttributeError(name)
        return getattr(self.inner, name)

    async def complete(self, request, **kwargs):
        from amplifier_core.message_models import Message

        owner = self.tools
        owner.budget.check()
        if owner.fatal:
            raise owner.fatal
        if owner.result is not None:
            raise Finished()
        if owner.model_calls >= owner.grant.max_model_calls:
            owner.fatal = OuttakeError(
                "RESOURCE_LIMIT",
                "Model-call allowance exhausted.",
                "Narrow the request or authorize a new bounded operation.",
            )
            raise owner.fatal
        pending = {
            key: value for key, value in owner.observations.items() if key not in owner.delivered
        }
        content, image_bytes = (
            [
                {
                    "type": "text",
                    "text": (
                        f"Work remaining: {owner.grant.max_model_calls - owner.model_calls} model calls, "
                        f"{owner.grant.max_frames - owner.frames} new frames, "
                        f"{owner.grant.max_tool_calls - owner.calls} tools. "
                        "Once the event/context is supported, submit a proposed cut with uncertainty. "
                        "Do not spend the remaining budget chasing frame-perfect boundaries. "
                        "Use submit_candidates or report_limitation before the final call. "
                        "Images are JPEG review copies of retained source observations."
                    ),
                }
            ],
            0,
        )
        for eid, evidence in pending.items():
            if evidence["kind"] != "frames":
                continue
            if not owner.grant.allow_frames or not owner.grant.vision:
                raise OuttakeError(
                    "DISCLOSURE_DENIED",
                    "Frame disclosure is not authorized.",
                    "Supply a compatible explicit grant.",
                )
            for frame in evidence["frames"]:
                path = Path(frame["image"])
                if fingerprint(path, owner.budget) != frame["sha256"]:
                    raise OuttakeError(
                        "STALE_EVIDENCE", "A retained frame changed.", "Repeat observation."
                    )
                # Retain the lossless observation locally, transmit a bounded review copy.
                buffer = io.BytesIO()
                with Image.open(path) as image:
                    image.convert("RGB").save(buffer, format="JPEG", quality=90)
                encoded = base64.b64encode(buffer.getvalue()).decode()
                image_bytes += len(encoded)
                content += [
                    {
                        "type": "text",
                        "text": f"Evidence {eid}, source {evidence['source_id']}, video time {frame['time']} seconds. Gaps are not observed.",
                    },
                    {
                        "type": "image",
                        "source": {"type": "base64", "media_type": "image/jpeg", "data": encoded},
                    },
                ]
        # Count each transmitted transcript in full, including repeated material.
        text_bytes = len(request.model_dump_json().encode()) + sum(
            len(c.get("text", "").encode()) for c in content
        )
        if (
            owner.text_bytes + text_bytes > owner.grant.max_text_bytes
            or owner.image_bytes + image_bytes > owner.grant.max_image_bytes
        ):
            owner.fatal = OuttakeError(
                "RESOURCE_LIMIT",
                "Provider disclosure byte allowance exhausted.",
                "Reduce context or start a new explicitly bounded request.",
            )
            raise owner.fatal
        owner.model_calls += 1
        owner.text_bytes += text_bytes
        owner.image_bytes += image_bytes
        messages = [*request.messages]
        if content:
            messages.append(Message(role="user", content=content))
        request = request.model_copy(
            update={
                "messages": messages,
                "model": owner.grant.model,
                "max_output_tokens": owner.grant.max_response_tokens,
                "timeout": max(0.01, owner.budget.deadline - time.monotonic()),
                "stream": False,
            }
        )
        try:
            response = await self.inner.complete(request, **kwargs)
        except Exception as exc:
            # Provider errors can embed credentials, request excerpts or local paths.
            owner.fatal = OuttakeError(
                "PROVIDER_ERROR",
                "The configured provider rejected or failed the request.",
                "Check model credentials and image capability; no automatic retry was made.",
            )
            raise owner.fatal from exc
        owner.budget.check()
        # Provider metadata can contain an SDK transport object (including streaming
        # SimpleNamespace wrappers). It is not model-visible response content.
        response_bytes = len(response.model_dump_json(exclude={"metadata"}).encode())
        owner.text_bytes += response_bytes
        if owner.text_bytes > owner.grant.max_text_bytes:
            owner.fatal = OuttakeError(
                "RESOURCE_LIMIT",
                "Model response exceeded the shared text allowance.",
                "Use a smaller response limit or a new grant.",
            )
            raise owner.fatal
        owner.delivered.update(pending)
        return response


async def run_agent(owner, entry, stop):
    from amplifier_agent_lib.engine import Engine
    from amplifier_agent_lib.protocol import PROTOCOL_VERSION, server_default_capabilities
    from amplifier_agent_lib.protocol_points.defaults_cli import CliApprovalSystem, CliDisplaySystem

    from .intelligence import SYSTEM

    async def turn(ctx):
        prepared = copy.copy(engine.session)
        prepared.mount_plan = copy.deepcopy(prepared.mount_plan)
        prepared.mount_plan.update(providers=[entry], tools=[], agents={}, hooks=[])
        from .providers import refresh_auth

        await refresh_auth(prepared, entry)
        # No source folder is used as an Agent working directory.
        with tempfile.TemporaryDirectory(prefix="outtake-agent-") as workspace:
            session = await prepared.create_session(
                session_id=owner.finding_id, session_cwd=Path(workspace)
            )
            async with session:
                providers = session.coordinator.get("providers")
                if len(providers) != 1:
                    raise OuttakeError(
                        "PROVIDER_CONFIGURATION",
                        "Expected exactly one approved provider.",
                        "Check the Amplifier installation.",
                    )
                for name, provider in list(providers.items()):
                    await session.coordinator.mount(
                        "providers", ProviderGate(provider, owner), name=name
                    )
                for tool in owner.mountables():
                    await session.coordinator.mount("tools", tool, name=tool.name)
                try:
                    await session.execute(ctx.prompt)
                except Finished:
                    pass
                except RuntimeError as exc:
                    if owner.fatal:
                        raise owner.fatal
                    # The Rust coordinator translates Python terminal exceptions.
                    if owner.result is None or "Finished" not in str(exc):
                        raise
        return "Validated result retained by Outtake."

    engine = Engine(
        turn_handler=turn,
        protocol_points={
            "approval": CliApprovalSystem(mode="no"),
            "display": CliDisplaySystem(stream=sys.stderr, verbosity="quiet"),
        },
    )

    async def execute():
        await engine.boot(
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": server_default_capabilities(),
                "sessionId": owner.finding_id,
                "resume": False,
            }
        )
        payload = {
            "title": owner.request.title,
            "description": owner.request.description,
            "context": owner.request.context,
            "sources": owner.public_sources(),
            "disclosure": {
                "frames": owner.grant.allow_frames,
                "captions": owner.grant.allow_captions,
            },
            "limits": {
                "frames": owner.grant.max_frames,
                "tools": owner.grant.max_tool_calls,
                "model_calls": owner.grant.max_model_calls,
                "max_cut_seconds": owner.budget.limits.max_duration_seconds,
            },
        }
        prompt = SYSTEM + "\nINPUT DATA:\n" + json.dumps(payload)
        # Caller context is explicit data, but must not accidentally disclose known source roots.
        for root in owner.client.roots:
            prompt = prompt.replace(str(root), "[local source root]")
        await engine.submit_turn({"sessionId": owner.finding_id, "turnId": "1", "prompt": prompt})

    task = asyncio.create_task(execute())
    try:
        while not task.done():
            owner.budget.check()
            await asyncio.wait({task}, timeout=0.05)
        await task
    finally:
        if not task.done():
            stop.set()
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        await engine.shutdown()
