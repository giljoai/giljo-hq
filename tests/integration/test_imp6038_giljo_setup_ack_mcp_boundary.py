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
    parts = []
    for block in call_tool_result.content:
        text = getattr(block, "text", None)
        if text:
            parts.append(text)
    return "\n".join(parts)




@pytest_asyncio.fixture
async def giljo_setup_client(monkeypatch, db_manager):
    from api import app_state
    from api.endpoints import mcp_sdk_server

    state = app_state.state
    prior_tool_accessor = state.tool_accessor
    prior_tenant_manager = state.tenant_manager
    prior_db_manager = state.db_manager

    if state.tenant_manager is None:
        state.tenant_manager = TenantManager()

    state.db_manager = db_manager

    class _StubAccessor:
        async def bootstrap_setup(self, platform: str, user_id=None, **_kwargs):
            return {"status": "ok", "platform": platform}

    state.tool_accessor = _StubAccessor()

    tenant_key = TenantManager.generate_tenant_key()
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
        yield _new_client, tenant_key, db_manager
    finally:
        state.tool_accessor = prior_tool_accessor
        state.tenant_manager = prior_tenant_manager
        state.db_manager = prior_db_manager




async def test_giljo_setup_writes_ack_for_calling_tenant(giljo_setup_client):
    from giljo_mcp.tools.slash_command_templates import SKILLS_VERSION

    new_client, tenant_key, db_manager = giljo_setup_client

    async with new_client() as session:
        result = await session.call_tool("giljo_setup", {"platform": "claude_code"})

    assert result.is_error is False, _error_text(result)

    from giljo_mcp.services.settings_service import TenantSkillsAckService

    async with db_manager.get_session_async() as db:
        svc = TenantSkillsAckService(db, tenant_key)
        ack_version = await svc.get_acknowledged_version()

    assert ack_version is not None, "giljo_setup must write a TenantSkillsAck row"
    assert ack_version == SKILLS_VERSION, f"ack version {ack_version!r} != bundled SKILLS_VERSION {SKILLS_VERSION!r}"


async def test_giljo_setup_ack_response_carries_meta_skills_version(giljo_setup_client):
    from giljo_mcp.tools.slash_command_templates import SKILLS_VERSION

    new_client, _tenant_key, _db = giljo_setup_client

    async with new_client() as session:
        result = await session.call_tool("giljo_setup", {"platform": "generic"})

    assert result.is_error is False, _error_text(result)
    payload = _payload(result)
    assert "_meta" in payload, "_meta key missing from giljo_setup response"
    assert payload["_meta"]["skills_version"] == SKILLS_VERSION


async def test_giljo_setup_different_tenants_have_independent_acks(monkeypatch, db_manager):
    from unittest.mock import MagicMock

    from api import app_state
    from api.endpoints import mcp_sdk_server
    from giljo_mcp.tools.slash_command_templates import SKILLS_VERSION

    state = app_state.state
    prior_tool_accessor = state.tool_accessor
    prior_db_manager = state.db_manager
    prior_tenant_manager = state.tenant_manager

    if state.tenant_manager is None:
        state.tenant_manager = TenantManager()

    state.db_manager = db_manager

    class _Stub:
        async def bootstrap_setup(self, platform: str, user_id=None, **_kwargs):
            return {"status": "ok"}

    state.tool_accessor = _Stub()

    async def _noop(*a, **kw):
        return None

    monkeypatch.setattr("giljo_mcp.services.silence_detector.auto_clear_silent", _noop)
    monkeypatch.setattr("giljo_mcp.services.heartbeat.touch_heartbeat", _noop)

    tk_a = TenantManager.generate_tenant_key()
    tk_b = TenantManager.generate_tenant_key()

    def _make_ctx(tenant_key: str):
        ctx = MagicMock()
        ctx.request_context.request.scope = {"state": {"tenant_key": tenant_key}}
        return ctx

    try:
        await mcp_sdk_server.giljo_setup(platform="claude_code", ctx=_make_ctx(tk_a))
        await mcp_sdk_server.giljo_setup(platform="codex_cli", ctx=_make_ctx(tk_b))
    finally:
        state.tool_accessor = prior_tool_accessor
        state.db_manager = prior_db_manager
        state.tenant_manager = prior_tenant_manager

    from giljo_mcp.services.settings_service import TenantSkillsAckService

    async with db_manager.get_session_async() as db:
        ver_a = await TenantSkillsAckService(db, tk_a).get_acknowledged_version()
    async with db_manager.get_session_async() as db:
        ver_b = await TenantSkillsAckService(db, tk_b).get_acknowledged_version()

    assert ver_a == SKILLS_VERSION, f"tenant_A ack={ver_a!r}, expected {SKILLS_VERSION!r}"
    assert ver_b == SKILLS_VERSION, f"tenant_B ack={ver_b!r}, expected {SKILLS_VERSION!r}"
    assert tk_a != tk_b
