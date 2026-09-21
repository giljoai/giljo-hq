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


def _payload(call_tool_result) -> dict:
    if getattr(call_tool_result, "structuredContent", None):
        return call_tool_result.structured_content
    first_block = call_tool_result.content[0]
    text = getattr(first_block, "text", None)
    if text is None:
        raise AssertionError(f"unexpected content block: {first_block!r}")
    return json.loads(text)


def _error_text(call_tool_result) -> str:
    return "\n".join(t for t in (getattr(b, "text", None) for b in call_tool_result.content) if t)


@pytest_asyncio.fixture
async def chain_client(monkeypatch):
    from api import app_state
    from api.endpoints import mcp_sdk_server
    from giljo_mcp.tools.tool_accessor._chain_tools import ChainToolsMixin

    state = app_state.state
    prior_tool_accessor = state.tool_accessor
    prior_tenant_manager = state.tenant_manager

    if state.tenant_manager is None:
        state.tenant_manager = TenantManager()

    tenant_key = TenantManager.generate_tenant_key()

    class _StubAccessor(ChainToolsMixin):
        service_reached = False

        def __init__(self):
            self.tenant_manager = state.tenant_manager
            self.db_manager = None
            self._websocket_manager = None
            self._test_session = None

        async def _reject_unchainable(self, project_ids, order, tenant_key):
            type(self).service_reached = True
            raise RuntimeError("no database in this test")

    accessor = _StubAccessor()
    state.tool_accessor = accessor

    from api.endpoints.mcp_tools import _base

    monkeypatch.setattr(_base, "_resolve_tenant", lambda ctx: tenant_key)
    monkeypatch.setattr(_base, "_resolve_user_id", lambda ctx: None)

    async def _noop(*args, **kwargs):
        return None

    monkeypatch.setattr("giljo_mcp.services.silence_detector.auto_clear_silent", _noop)
    monkeypatch.setattr("giljo_mcp.services.heartbeat.touch_heartbeat", _noop)

    def _new_client():
        return create_connected_server_and_client_session(mcp_sdk_server.mcp)

    try:
        yield _new_client, accessor
    finally:
        state.tool_accessor = prior_tool_accessor
        state.tenant_manager = prior_tenant_manager


async def test_omitted_execution_mode_returns_a_question_not_an_error(chain_client):
    new_client, _accessor = chain_client

    async with new_client() as session:
        result = await session.call_tool("link_projects", {"project_ids": ["p-1", "p-2"]})

    assert result.is_error is False, (
        "an omitted execution_mode must come back as normal tool content carrying the "
        f"question, not as an isError the agent has to interpret: {_error_text(result)}"
    )
    payload = _payload(result)
    assert payload["success"] is False
    assert payload["error"] == "EXECUTION_MODE_REQUIRED"
    assert payload["options"] == ["subagent", "multi_terminal"]

    why = payload["next_action"]["why"].lower()
    assert "ask the user" in why, f"the agent must be told to ASK, never guess: {why!r}"
    assert "subagent" in why and "multi_terminal" in why, (
        f"both doors must be named in words the agent can relay to a human: {why!r}"
    )


async def test_the_question_fires_before_any_chain_work(chain_client):
    new_client, accessor = chain_client
    type(accessor).service_reached = False

    async with new_client() as session:
        result = await session.call_tool("link_projects", {"project_ids": ["p-1", "p-2"]})

    assert _payload(result)["error"] == "EXECUTION_MODE_REQUIRED"
    assert accessor.service_reached is False, (
        "link_projects proceeded into chain creation after an omitted execution_mode"
    )


async def test_an_invalid_execution_mode_is_still_a_validation_error(chain_client):
    new_client, _accessor = chain_client

    async with new_client() as session:
        result = await session.call_tool(
            "link_projects", {"project_ids": ["p-1", "p-2"], "execution_mode": "telepathy"}
        )

    text = _error_text(result)
    assert "EXECUTION_MODE_REQUIRED" not in text, "a named-but-invalid mode must not be treated as unanswered"
    assert result.is_error is True or _payload(result).get("error") == "VALIDATION_ERROR", (
        f"an invalid execution_mode must stay a validation rejection: {text!r}"
    )
