# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import inspect
from uuid import uuid4

import pytest
import pytest_asyncio

from api.endpoints.mcp_sdk_server import mcp
from tests.helpers.mcp_dispatch import attach_registry_service_autospecs
from tests.helpers.mcp_session_fixture import create_connected_server_and_client_session


_RETIRED_TOOL_NAMES = (
    "propose_product_context_update",
    "submit_tuning_review",
    "fetch_context",
    "write_360_memory",
    "close_project_and_update_memory",
    "inspect_messages",
    "get_agent_mission",
    "update_agent_mission",
    "update_product_fields",
    "get_pending_jobs",
    "complete_task",
    "list_agent_templates",
    "generate_download_token",
    "get_staging_context",
)


def _error_text(result) -> str:
    parts = []
    for block in result.content or []:
        text = getattr(block, "text", None)
        if text:
            parts.append(text)
    return "\n".join(parts)


@pytest_asyncio.fixture
async def autospec_mcp(monkeypatch):
    from unittest.mock import create_autospec

    from api import app_state
    from api.endpoints.mcp_tools import _base
    from giljo_mcp.tenant import TenantManager
    from giljo_mcp.tools.tool_accessor import ToolAccessor

    state = app_state.state
    prior_accessor = state.tool_accessor
    prior_tenant_manager = state.tenant_manager
    prior_db_manager = state.db_manager

    accessor = create_autospec(ToolAccessor, instance=True)
    for attr_name in dir(ToolAccessor):
        if attr_name.startswith("_"):
            continue
        if inspect.iscoroutinefunction(getattr(ToolAccessor, attr_name, None)):
            getattr(accessor, attr_name).return_value = {"ok": True}

    attach_registry_service_autospecs(accessor, {"ok": True})

    state.tool_accessor = accessor
    state.tenant_manager = TenantManager()
    state.db_manager = None

    tenant_key = TenantManager.generate_tenant_key()
    monkeypatch.setattr(_base, "_resolve_tenant", lambda ctx: tenant_key)
    monkeypatch.setattr(_base, "_resolve_user_id", lambda ctx: None)

    def _client():
        return create_connected_server_and_client_session(mcp)

    try:
        yield _client
    finally:
        state.tool_accessor = prior_accessor
        state.tenant_manager = prior_tenant_manager
        state.db_manager = prior_db_manager


@pytest.mark.asyncio
async def test_apply_context_tuning_resolves_over_transport(autospec_mcp):
    async with autospec_mcp() as session:
        result = await session.call_tool(
            "apply_context_tuning",
            {"product_id": str(uuid4()), "proposals": []},
        )
    assert result.is_error is False, f"apply_context_tuning must dispatch: {_error_text(result)}"


@pytest.mark.asyncio
async def test_apply_context_tuning_in_live_tool_surface():
    live = {t.name for t in mcp._tool_manager.list_tools()}
    assert "apply_context_tuning" in live
    assert "propose_product_context_update" not in live
    assert len(live) == 49


@pytest.mark.asyncio
async def test_old_name_does_not_resolve_over_transport(autospec_mcp):
    failed = False
    try:
        async with autospec_mcp() as session:
            result = await session.call_tool(
                "propose_product_context_update",
                {"product_id": str(uuid4()), "proposals": []},
            )
        failed = result.is_error is True
    except Exception:
        failed = True
    assert failed, "the retired old name must not silently dispatch"


@pytest.mark.asyncio
async def test_tuning_prompt_heals_to_new_name():
    from giljo_mcp.services.product_tuning_service import TUNING_PROMPT_TEMPLATE

    assert "apply_context_tuning" in TUNING_PROMPT_TEMPLATE
    assert "propose_product_context_update" not in TUNING_PROMPT_TEMPLATE


@pytest.mark.asyncio
async def test_giljo_guide_wires_diagnose_and_names_no_retired_tool(autospec_mcp):
    async with autospec_mcp() as session:
        result = await session.call_tool("get_giljo_guide", {})
    assert result.is_error is False, f"get_giljo_guide must dispatch: {_error_text(result)}"
    text = _error_text(result)

    assert "diagnose_project_state" in text, "the guide must wire the self-heal diagnostic"
    for retired in _RETIRED_TOOL_NAMES:
        assert retired not in text, f"guide still names a retired tool: {retired}"
