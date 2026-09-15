# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from giljo_mcp.tenant import TenantManager


pytestmark = pytest.mark.asyncio


def _ctx(tenant_key: str) -> MagicMock:
    ctx = MagicMock()
    ctx.request_context.request.scope = {"state": {"tenant_key": tenant_key}}
    return ctx


async def _setup_stub(monkeypatch, stub_return):
    from api import app_state
    from api.endpoints import mcp_sdk_server

    state = app_state.state
    prior_accessor = state.tool_accessor
    prior_manager = state.tenant_manager

    if state.tenant_manager is None:
        state.tenant_manager = TenantManager()

    class _Stub:
        async def any_tool(self, *, tenant_key: str):
            return stub_return

    state.tool_accessor = _Stub()

    async def _noop(*a, **kw):
        return None

    monkeypatch.setattr("giljo_mcp.services.silence_detector.auto_clear_silent", _noop)
    monkeypatch.setattr("giljo_mcp.services.heartbeat.touch_heartbeat", _noop)

    return state, prior_accessor, prior_manager, mcp_sdk_server


async def test_call_tool_injects_meta_skills_version_into_plain_dict(monkeypatch):
    from giljo_mcp.tools.slash_command_templates import SKILLS_VERSION

    state, prior_accessor, prior_manager, sdk = await _setup_stub(monkeypatch, {"result": "ok"})
    tenant_key = TenantManager.generate_tenant_key()

    try:
        result = await sdk._call_tool(_ctx(tenant_key), "any_tool", {})
    finally:
        state.tool_accessor = prior_accessor
        state.tenant_manager = prior_manager

    assert isinstance(result, dict)
    assert "_meta" in result, "_meta key must be present"
    assert result["_meta"]["skills_version"] == SKILLS_VERSION


async def test_call_tool_preserves_existing_meta_keys(monkeypatch):
    from giljo_mcp.tools.slash_command_templates import SKILLS_VERSION

    state, prior_accessor, prior_manager, sdk = await _setup_stub(
        monkeypatch, {"data": "x", "_meta": {"custom_flag": True}}
    )
    tenant_key = TenantManager.generate_tenant_key()

    try:
        result = await sdk._call_tool(_ctx(tenant_key), "any_tool", {})
    finally:
        state.tool_accessor = prior_accessor
        state.tenant_manager = prior_manager

    assert result["_meta"]["skills_version"] == SKILLS_VERSION
    assert result["_meta"]["custom_flag"] is True, "pre-existing _meta keys must not be clobbered"


async def test_call_tool_does_not_inject_meta_on_non_dict_result(monkeypatch):
    from api import app_state
    from api.endpoints import mcp_sdk_server

    state = app_state.state
    prior_accessor = state.tool_accessor
    prior_manager = state.tenant_manager

    if state.tenant_manager is None:
        state.tenant_manager = TenantManager()

    class _StrStub:
        async def any_tool(self, *, tenant_key: str):
            return "plain string result"

    state.tool_accessor = _StrStub()

    async def _noop(*a, **kw):
        return None

    monkeypatch.setattr("giljo_mcp.services.silence_detector.auto_clear_silent", _noop)
    monkeypatch.setattr("giljo_mcp.services.heartbeat.touch_heartbeat", _noop)

    tenant_key = TenantManager.generate_tenant_key()
    try:
        result = await mcp_sdk_server._call_tool(_ctx(tenant_key), "any_tool", {})
    finally:
        state.tool_accessor = prior_accessor
        state.tenant_manager = prior_manager

    assert result == "plain string result"
