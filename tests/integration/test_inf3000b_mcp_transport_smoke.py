# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import inspect
import json
from typing import Any
from unittest.mock import create_autospec

import pytest

from api.endpoints.mcp_sdk_server import mcp
from tests.helpers.mcp_dispatch import attach_registry_service_autospecs
from tests.helpers.mcp_session_fixture import create_connected_server_and_client_session




EXPECTED_SMOKE_TOOLS: frozenset[str] = frozenset(
    {
        "create_project",
        "list_projects",
        "update_project",
        "update_project_mission",
        "diagnose_project_state",
        "create_task",
        "update_task",
        "list_tasks",
        "get_roadmap",
        "save_roadmap",
        "request_approval",
        "decide_approval",
        "create_thread",
        "update_thread",
        "join_thread",
        "post_to_thread",
        "get_my_turn",
        "get_participant_liveness",
        "set_next_actor",
        "list_threads",
        "get_thread_history",
        "get_staging_instructions",
        "update_job_mission",
        "report_progress",
        "complete_job",
        "finalize_job",
        "resume_or_dismiss_job",
        "set_agent_status",
        "get_job_mission",
        "spawn_job",
        "get_agent_result",
        "get_workflow_status",
        "get_context",
        "search_memory",
        "write_project_closeout",
        "write_memory_entry",
        "get_vision_document",
        "update_product_context",
        "create_product",
        "create_vision_document",
        "health_check",
        "get_giljo_guide",
        "giljo_setup",
        "apply_context_tuning",
        "stage_project",
        "get_implementation_prompt",
        "launch_implementation",
        "link_projects",
        "unlink_projects",
    }
)


_DATE_PARAMS: frozenset[str] = frozenset(
    {
        "created_after",
        "created_before",
        "completed_after",
        "completed_before",
    }
)

_LITERAL_STRING_OVERRIDES: dict[str, str] = {"hidden": "true"}
_ISO_SAMPLE = "2026-01-01T00:00:00Z"


def _live_tools() -> dict[str, Any]:
    return {tool.name: tool for tool in mcp._tool_manager.list_tools()}


def _synth_value(name: str, prop_schema: dict[str, Any]) -> Any:
    if "anyOf" in prop_schema:
        for sub in prop_schema["anyOf"]:
            if sub.get("type") != "null":
                return _synth_value(name, sub)
        return None
    if "$ref" in prop_schema:
        return {}
    if prop_schema.get("enum"):
        return prop_schema["enum"][0]
    t = prop_schema.get("type")
    if t in ("integer", "number"):
        return 1
    if t == "boolean":
        return False
    if t == "array":
        return []
    if t == "object":
        return {}
    if name in _DATE_PARAMS:
        return _ISO_SAMPLE
    if name in _LITERAL_STRING_OVERRIDES:
        return _LITERAL_STRING_OVERRIDES[name]
    return "smoke"


def _synth_args(tool: Any) -> dict[str, Any]:
    schema = tool.parameters if isinstance(tool.parameters, dict) else {}
    props = schema.get("properties", {}) if isinstance(schema, dict) else {}
    return {name: _synth_value(name, prop) for name, prop in props.items()}


def _error_text(result) -> str:
    parts = []
    for block in getattr(result, "content", None) or []:
        text = getattr(block, "text", None)
        if text:
            parts.append(text)
    return "\n".join(parts)


@pytest.fixture
def smoke_state(monkeypatch):
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
            getattr(accessor, attr_name).return_value = {"smoke": True}

    attach_registry_service_autospecs(accessor, {"smoke": True})

    state.tool_accessor = accessor
    state.tenant_manager = TenantManager()
    state.db_manager = None

    tenant_key = TenantManager.generate_tenant_key()
    monkeypatch.setattr(_base, "_resolve_tenant", lambda ctx: tenant_key)
    monkeypatch.setattr(_base, "_resolve_user_id", lambda ctx: None)

    try:
        yield accessor
    finally:
        state.tool_accessor = prior_accessor
        state.tenant_manager = prior_tenant_manager
        state.db_manager = prior_db_manager


def test_smoke_coverage_is_the_full_registry():
    live = set(_live_tools())
    assert live == EXPECTED_SMOKE_TOOLS, (
        f"smoke roster drift. Unsmoked new tools: {sorted(live - EXPECTED_SMOKE_TOOLS)}; "
        f"stale roster entries: {sorted(EXPECTED_SMOKE_TOOLS - live)}"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("tool_name", sorted(EXPECTED_SMOKE_TOOLS))
async def test_tool_dispatches_through_transport(tool_name, smoke_state):
    tool = _live_tools()[tool_name]
    args = _synth_args(tool)

    async with create_connected_server_and_client_session(mcp) as session:
        result = await session.call_tool(tool_name, args)

    assert result.is_error is False, (
        f"tool {tool_name!r} failed at the transport/dispatch boundary with args {args!r}: {_error_text(result)}"
    )
    if result.content:
        first = result.content[0]
        text = getattr(first, "text", None)
        if text is not None:
            json.loads(text)
