# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import logging

import pytest
import pytest_asyncio

from giljo_mcp.tenant import TenantManager
from tests.helpers.mcp_session_fixture import create_connected_server_and_client_session


pytestmark = pytest.mark.asyncio


def _text(result) -> str:
    return "\n".join(getattr(b, "text", "") or "" for b in result.content)


@pytest_asyncio.fixture
async def call_as(db_manager, monkeypatch):
    from api import app_state
    from api.endpoints import mcp_sdk_server
    from api.endpoints.mcp_tools import _base
    from giljo_mcp.tools.tool_accessor import ToolAccessor

    state = app_state.state
    prior = (state.tool_accessor, state.tenant_manager, state.db_manager)
    if state.tenant_manager is None:
        state.tenant_manager = TenantManager()
    state.db_manager = db_manager
    state.tool_accessor = ToolAccessor(db_manager=db_manager, tenant_manager=state.tenant_manager)
    monkeypatch.setattr(_base, "_resolve_user_id", lambda ctx: None)

    async def _call(tenant_key: str, tool: str, args: dict):
        monkeypatch.setattr(_base, "_resolve_tenant", lambda ctx: tenant_key)
        async with create_connected_server_and_client_session(mcp_sdk_server.mcp) as s:
            return await s.call_tool(tool, args)

    try:
        yield _call
    finally:
        state.tool_accessor, state.tenant_manager, state.db_manager = prior


@pytest.mark.parametrize(
    ("tool", "args"),
    [
        ("list_projects", {}),
        ("list_tasks", {}),
        ("get_roadmap", {}),
        ("get_context", {"categories": ["tech_stack"]}),
    ],
)
async def test_refusal_text_has_no_context_suffix(call_as, tool, args):
    tenant_key = TenantManager.generate_tenant_key()
    result = await call_as(tenant_key, tool, args)
    text = _text(result)
    assert result.is_error is True, text
    assert "(Context" not in text, text
    assert "tenant_key" not in text, text
    assert tenant_key not in text, text
    assert "operation" not in text, text


async def test_server_log_keeps_the_context(call_as, caplog):
    tenant_key = TenantManager.generate_tenant_key()
    with caplog.at_level(logging.INFO):
        await call_as(tenant_key, "list_projects", {})
    assert any(
        "(Context" in r.getMessage() and "'operation': 'list_projects'" in r.getMessage() for r in caplog.records
    ), [r.getMessage()[:120] for r in caplog.records]


async def test_next_step_guidance_in_the_context_still_reaches_the_client(call_as):
    tenant_key = TenantManager.generate_tenant_key()
    result = await call_as(tenant_key, "finalize_job", {"job_id": "00000000-0000-4000-8000-000000000000"})
    text = _text(result)
    assert result.is_error is True, text
    assert "diagnose_project_state" in text, text
    assert tenant_key not in text, text
    for server_only in ("'tenant_key'", "'operation'", "'method'"):
        assert server_only not in text, text
