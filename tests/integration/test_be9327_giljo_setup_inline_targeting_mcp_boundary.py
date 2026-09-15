# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import json

import pytest
import pytest_asyncio
from mcp.types import Implementation

from giljo_mcp.tenant import TenantManager
from tests.helpers.mcp_session_fixture import create_connected_server_and_client_session


pytestmark = pytest.mark.asyncio


_CHATGPT_INFO = Implementation(name="openai-mcp", version="1.0.0")
_CHATGPT_VALIDATION_INFO = Implementation(name="openai-mcp (ChatGPT)", version="1.0.0")
_CODEX_HOSTED_INFO = Implementation(name="openai-mcp (Codex)", version="1.0.0")
_ANTHROPIC_INFO = Implementation(name="Anthropic/ClaudeAI", version="1.0.0")
_CLAUDE_CODE_INFO = Implementation(name="claude-code", version="2.1.199")


def _payload(result) -> dict:
    if getattr(result, "structuredContent", None):
        return result.structured_content
    first = result.content[0]
    text = getattr(first, "text", None)
    if text is None:  # pragma: no cover - defensive
        raise AssertionError(f"unexpected content block: {first!r}")
    return json.loads(text)


def _error_text(result) -> str:
    return "\n".join(b.text for b in result.content if getattr(b, "text", None))


@pytest_asyncio.fixture
async def setup_client(monkeypatch, db_manager):
    from api import app_state
    from api.endpoints import mcp_sdk_server

    state = app_state.state
    prior_tool_accessor = state.tool_accessor
    prior_tenant_manager = state.tenant_manager
    prior_db_manager = state.db_manager

    if state.tenant_manager is None:
        state.tenant_manager = TenantManager()
    state.db_manager = db_manager

    requested: dict[str, str] = {}

    class _StubAccessor:
        async def bootstrap_setup(self, platform: str, user_id=None, **_kwargs):
            requested["bootstrap_platform"] = platform
            return {
                "status": "ready",
                "platform": platform,
                "next_action": {"why": "Download the zip and extract agents/* into ~/.claude/agents/."},
            }

    state.tool_accessor = _StubAccessor()

    tenant_key = TenantManager.generate_tenant_key()
    from api.endpoints.mcp_tools import _base

    monkeypatch.setattr(_base, "_resolve_tenant", lambda ctx: tenant_key)
    monkeypatch.setattr(_base, "_resolve_user_id", lambda ctx: None)

    async def _noop(*args, **kwargs):
        return None

    monkeypatch.setattr("giljo_mcp.services.silence_detector.auto_clear_silent", _noop)
    monkeypatch.setattr("giljo_mcp.services.heartbeat.touch_heartbeat", _noop)

    def _client(client_info):
        return create_connected_server_and_client_session(mcp_sdk_server.mcp, client_info=client_info)

    try:
        yield _client, requested
    finally:
        state.tool_accessor = prior_tool_accessor
        state.tenant_manager = prior_tenant_manager
        state.db_manager = prior_db_manager


@pytest.mark.parametrize(
    "client_info",
    [_CHATGPT_INFO, _CHATGPT_VALIDATION_INFO, _CODEX_HOSTED_INFO],
    ids=["chatgpt", "chatgpt-validation", "codex-hosted"],
)
async def test_openai_hosted_session_gets_inline_setup_without_declaring_a_harness(setup_client, client_info):
    new_client, _requested = setup_client

    async with new_client(client_info) as session:
        result = await session.call_tool("giljo_setup", {"platform": "claude_code"})

    assert result.is_error is False, _error_text(result)
    payload = _payload(result)

    assert payload.get("mode") == "inline", (
        f"{client_info.name} has no writable home directory but did NOT get inline setup; "
        f"payload keys={sorted(payload)}"
    )
    assert "install_paths" not in payload, "inline mode must not carry filesystem install paths"


async def test_anthropic_family_is_not_auto_targeted(setup_client):
    new_client, _requested = setup_client

    async with new_client(_ANTHROPIC_INFO) as session:
        result = await session.call_tool("giljo_setup", {"platform": "claude_code"})

    assert result.is_error is False, _error_text(result)
    payload = _payload(result)

    assert "mode" not in payload, "Anthropic/ClaudeAI must NOT be auto-targeted to the inline branch"
    assert "~/.claude/agents/" in payload["next_action"]["why"]


async def test_terminal_cli_session_is_unaffected(setup_client):
    new_client, requested = setup_client

    async with new_client(_CLAUDE_CODE_INFO) as session:
        result = await session.call_tool("giljo_setup", {"platform": "claude_code"})

    assert result.is_error is False, _error_text(result)
    payload = _payload(result)

    assert "mode" not in payload, "a terminal CLI must reach bootstrap_setup, not the inline branch"
    assert requested.get("bootstrap_platform") == "claude_code"


async def test_declared_desktop_app_harness_still_keeps_filesystem_path(setup_client):
    new_client, _requested = setup_client

    async with new_client(_CHATGPT_INFO) as session:
        result = await session.call_tool("giljo_setup", {"platform": "claude_code", "harness": "desktop_app"})

    assert result.is_error is False, _error_text(result)
    payload = _payload(result)

    assert "mode" not in payload, "declared desktop_app must beat the detected preset"
    assert "~/.claude/agents/" in payload["next_action"]["why"]
