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
    text = getattr(first, "text", None)
    if text is None:  # pragma: no cover - defensive
        raise AssertionError(f"unexpected content block: {first!r}")
    return json.loads(text)


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

    requested: dict[str, object] = {}

    class _StubAccessor:
        async def bootstrap_setup(self, platform: str, user_id=None, product_id=None, **_kwargs):
            requested["product_id"] = product_id
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

    def _client():
        return create_connected_server_and_client_session(mcp_sdk_server.mcp)

    try:
        yield _client, requested
    finally:
        state.tool_accessor = prior_tool_accessor
        state.tenant_manager = prior_tenant_manager


async def test_giljo_setup_forwards_product_id_to_bootstrap_setup(setup_client):
    new_client, requested = setup_client
    product_id = "9c6a6b1e-5a2e-4b7b-9a1a-111111111111"

    async with new_client() as session:
        result = await session.call_tool("giljo_setup", {"platform": "claude_code", "product_id": product_id})

    assert result.is_error is False, _error_text(result)
    assert requested.get("product_id") == product_id


async def test_giljo_setup_omitted_product_id_forwards_empty_not_none(setup_client):
    new_client, requested = setup_client

    async with new_client() as session:
        result = await session.call_tool("giljo_setup", {"platform": "claude_code"})

    assert result.is_error is False, _error_text(result)
    assert requested.get("product_id") == ""


async def test_giljo_setup_description_documents_product_id_purpose():
    from api.endpoints import mcp_sdk_server

    tool = next(t for t in mcp_sdk_server.mcp._tool_manager.list_tools() if t.name == "giljo_setup")
    assert "product_id" in tool.description
    assert "PRODUCT_AMBIGUOUS" in tool.description
