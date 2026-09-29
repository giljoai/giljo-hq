# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import inspect
import json

import pytest
import pytest_asyncio

from api.endpoints.mcp_sdk_server import mcp
from api.endpoints.mcp_tools._base import MCP_ID_MAX
from giljo_mcp.tenant import TenantManager
from tests.helpers.mcp_dispatch import attach_registry_service_autospecs
from tests.helpers.mcp_session_fixture import create_connected_server_and_client_session


_OVERSIZED = "x" * (MCP_ID_MAX + 1)


def _error_text(result) -> str:
    parts = []
    for block in result.content or []:
        text = getattr(block, "text", None)
        if text:
            parts.append(text)
    return "\n".join(parts)


def _assert_structured_validation_rejection(result) -> None:
    assert result.is_error is False, _error_text(result)
    payload = json.loads(result.content[0].text)
    assert payload.get("success") is False, payload
    assert payload.get("error") == "VALIDATION_ERROR", payload
    assert payload.get("field"), payload


@pytest_asyncio.fixture
async def autospec_mcp(monkeypatch):
    from unittest.mock import create_autospec

    from api import app_state
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
    from api.endpoints.mcp_tools import _base

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


_ID_CAPPED_CALLS: list[tuple[str, dict, str]] = [
    ("get_staging_instructions", {}, "job_id"),
    ("report_progress", {}, "job_id"),
    ("complete_job", {"result": {"summary": "done"}}, "job_id"),
    ("finalize_job", {}, "job_id"),
    ("set_agent_status", {"status": "idle"}, "job_id"),
    ("get_job_mission", {}, "job_id"),
    ("get_agent_result", {}, "job_id"),
    ("get_workflow_status", {"project_id": "11111111-1111-1111-1111-111111111111"}, "exclude_job_id"),
    ("get_workflow_status", {}, "project_id"),
    ("get_context", {}, "job_id"),
    ("get_context", {}, "project_id"),
]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("tool_name", "base_args", "field"), _ID_CAPPED_CALLS, ids=[f"{t}:{f}" for t, _a, f in _ID_CAPPED_CALLS]
)
async def test_oversized_id_argument_is_clean_422(autospec_mcp, tool_name, base_args, field):
    client = autospec_mcp
    args = {**base_args, field: _OVERSIZED}
    async with client() as session:
        result = await session.call_tool(tool_name, args)
    _assert_structured_validation_rejection(result)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("tool_name", "base_args", "field"), _ID_CAPPED_CALLS, ids=[f"{t}:{f}" for t, _a, f in _ID_CAPPED_CALLS]
)
async def test_max_length_id_argument_still_dispatches(autospec_mcp, tool_name, base_args, field):
    client = autospec_mcp
    args = {**base_args, field: "x" * MCP_ID_MAX}
    async with client() as session:
        result = await session.call_tool(tool_name, args)
    assert result.is_error is False, f"{tool_name}/{field} at exactly MCP_ID_MAX must dispatch: {_error_text(result)}"
