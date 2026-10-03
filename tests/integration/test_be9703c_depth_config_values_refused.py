# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import pytest
import pytest_asyncio

from giljo_mcp.tenant import TenantManager
from tests.helpers.mcp_session_fixture import create_connected_server_and_client_session


pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def client(db_manager, db_session, monkeypatch):
    from api import app_state
    from api.endpoints import mcp_sdk_server
    from api.endpoints.mcp_tools import _base
    from giljo_mcp.tools.tool_accessor import ToolAccessor

    state = app_state.state
    prior = (state.tool_accessor, state.tenant_manager, state.db_manager)
    state.tenant_manager = state.tenant_manager or TenantManager()
    state.db_manager = db_manager
    state.tool_accessor = ToolAccessor(
        db_manager=db_manager, tenant_manager=state.tenant_manager, test_session=db_session
    )
    tenant_key = TenantManager.generate_tenant_key()
    monkeypatch.setattr(_base, "_resolve_tenant", lambda ctx: tenant_key)
    monkeypatch.setattr(_base, "_resolve_user_id", lambda ctx: None)
    try:
        yield lambda: create_connected_server_and_client_session(mcp_sdk_server.mcp)
    finally:
        state.tool_accessor, state.tenant_manager, state.db_manager = prior


@pytest.mark.parametrize(
    "depth_config",
    [
        {"memory_360": "everything"},
        {"memory_360": {"last_n_projects": "many"}},
        {"memory_360": {"shape": "bodies"}},
        {"git_history": "lots"},
    ],
)
async def test_unusable_depth_value_is_refused(client, depth_config):
    category = next(iter(depth_config))
    async with client() as session:
        result = await session.call_tool(
            "get_context",
            {
                "product_id": "44444444-4444-4444-4444-444444444444",
                "categories": [category],
                "depth_config": depth_config,
            },
        )
    text = "\n".join(getattr(b, "text", "") for b in result.content)
    assert result.is_error is True, text
    assert "depth_config" in text and category in text, text
