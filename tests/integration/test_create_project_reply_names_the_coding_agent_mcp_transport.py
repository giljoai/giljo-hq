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

CODING_AGENT_SENTENCE = (
    "A coding agent runs this project: connect one (for example Claude Code or Codex) "
    "and ask it to stage and implement it."
)


@pytest_asyncio.fixture
async def client(db_manager, db_session, monkeypatch):
    from api import app_state
    from api.endpoints import mcp_sdk_server
    from api.endpoints.mcp_tools import _base
    from giljo_mcp.tools.tool_accessor import ToolAccessor

    state = app_state.state
    prior = (state.tool_accessor, state.tenant_manager, state.db_manager)
    if state.tenant_manager is None:
        state.tenant_manager = TenantManager()
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


def _payload(result) -> dict:
    assert result.is_error is False, [getattr(b, "text", b) for b in result.content]
    if getattr(result, "structuredContent", None):
        return result.structured_content
    return json.loads(result.content[0].text)


@pytest.mark.parametrize("project_type", ["", "BE"])
async def test_create_project_reply_says_a_coding_agent_runs_it(client, project_type):
    async with client() as session:
        product = _payload(await session.call_tool("create_product", {"name": "Recipes", "description": "x"}))
        created = _payload(
            await session.call_tool(
                "create_project",
                {
                    "name": "Recipe page",
                    "description": "A page that lists recipes.",
                    "product_id": product["product_id"],
                    "project_type": project_type,
                },
            )
        )
    assert created["message"].endswith(CODING_AGENT_SENTENCE), created["message"]
    assert created["message"].startswith("Project 'Recipe page' created successfully"), created["message"]
