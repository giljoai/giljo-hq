# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import json

import pytest
import pytest_asyncio

from giljo_mcp.tenant import TenantManager
from tests.helpers.mcp_session_fixture import create_connected_server_and_client_session


pytestmark = pytest.mark.asyncio


def _payload(result) -> dict:
    if getattr(result, "structuredContent", None):
        return result.structured_content
    first = result.content[0]
    return json.loads(first.text)


def _error_text(result) -> str:
    return "\n".join(b.text for b in result.content if getattr(b, "text", None))


@pytest_asyncio.fixture
async def setup_client(monkeypatch):
    from api import app_state
    from api.endpoints import mcp_sdk_server

    state = app_state.state
    prior_tool_accessor = state.tool_accessor
    prior_tenant_manager = state.tenant_manager
    if state.tenant_manager is None:
        state.tenant_manager = TenantManager()

    calls: list[str] = []

    class _StubAccessor:
        async def bootstrap_setup(self, platform: str, **_kwargs):
            calls.append("bootstrap_setup")
            return {"status": "ready", "platform": platform, "next_action": {"why": "install skills"}}

    state.tool_accessor = _StubAccessor()

    tenant_key = TenantManager.generate_tenant_key()
    from api.endpoints.mcp_tools import _base

    monkeypatch.setattr(_base, "_resolve_tenant", lambda ctx: tenant_key)
    monkeypatch.setattr(_base, "_resolve_user_id", lambda ctx: None)

    async def _noop(*args, **kwargs):
        return None

    monkeypatch.setattr("giljo_mcp.services.silence_detector.auto_clear_silent", _noop)
    monkeypatch.setattr("giljo_mcp.services.heartbeat.touch_heartbeat", _noop)

    def _client():
        return create_connected_server_and_client_session(mcp_sdk_server.mcp)

    try:
        yield _client, calls
    finally:
        state.tool_accessor = prior_tool_accessor
        state.tenant_manager = prior_tenant_manager


@pytest.mark.parametrize("scope", ["agents_only", "Agents only", "both", "commands_only"])
async def test_retired_scope_is_refused_before_dispatch(setup_client, scope):
    new_client, calls = setup_client
    async with new_client() as session:
        result = await session.call_tool("giljo_setup", {"platform": "claude_code", "scope": scope})

    assert result.is_error is False, _error_text(result)
    payload = _payload(result)
    assert payload.get("success") is False
    assert payload.get("error") == "VALIDATION_ERROR"
    assert payload.get("field") == "scope"
    assert payload.get("constraint") == "retired"
    message = payload.get("message", "")
    assert "agent_profile" in message, message
    assert "Download profile" in message, message
    assert calls == [], f"a refused call must not dispatch, got {calls}"


async def test_scope_parameter_exists_only_to_be_refused():
    from api.endpoints import mcp_sdk_server

    tool = next(t for t in mcp_sdk_server.mcp._tool_manager.list_tools() if t.name == "giljo_setup")
    props = tool.parameters["properties"]
    assert "scope" in props
    assert "retired" in props["scope"].get("description", "").lower()


@pytest.mark.parametrize("harness", ["web_sandbox", "chat"])
async def test_inline_branch_returns_no_agents(setup_client, harness):
    new_client, calls = setup_client
    async with new_client() as session:
        result = await session.call_tool("giljo_setup", {"platform": "claude_code", "harness": harness})

    assert result.is_error is False, _error_text(result)
    payload = _payload(result)
    assert payload.get("mode") == "inline"
    assert "agents" not in payload, sorted(payload)
    assert "install_paths" not in payload
    assert "template_count" not in payload
    assert "primer" in payload
    assert calls == [], f"inline mode must not dispatch to the accessor, got {calls}"
    blob = json.dumps(payload)
    assert "Agents only" not in blob
    assert "agent_profile" in blob, "inline mode must tell the agent where profiles now come from"


async def test_filesystem_branch_dispatches_bootstrap_only(setup_client):
    new_client, calls = setup_client
    async with new_client() as session:
        result = await session.call_tool("giljo_setup", {"platform": "claude_code"})
    assert result.is_error is False, _error_text(result)
    assert calls == ["bootstrap_setup"]


async def test_description_no_longer_offers_agent_installs():
    from api.endpoints import mcp_sdk_server

    tool = next(t for t in mcp_sdk_server.mcp._tool_manager.list_tools() if t.name == "giljo_setup")
    desc = tool.description
    assert "Agents only" not in desc
    assert "agent templates" not in desc.lower() or "no longer" in desc.lower()
    assert "skills_version" in desc
    assert "agent_profile" in desc
