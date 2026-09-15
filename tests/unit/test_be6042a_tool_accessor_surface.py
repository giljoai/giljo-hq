# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import inspect

import pytest

from giljo_mcp.tools.tool_accessor import ToolAccessor


PUBLIC_TOOL_METHODS = frozenset(
    {
        "update_project_mission",
        "diagnose_project_state",
        "stage_project",
        "implement_project",
        "launch_implementation",
        "start_chain_run",
        "request_approval",
        "decide_approval",
        "join_thread",
        "get_agent_result",
        "set_agent_status",
        "write_project_closeout",
        "write_memory_entry",
        "search_memory",
        "get_context",
        "get_vision_doc",
        "update_product_context",
        "create_product",
        "create_vision_document",
        "bootstrap_setup",
        "apply_context_tuning",
    }
)


def test_public_import_resolves():
    from giljo_mcp.tools.tool_accessor import ToolAccessor as Imported

    assert Imported is ToolAccessor


def test_all_tool_methods_present_callable_async(mock_db_manager, mock_tenant_manager):
    db_manager, _session = mock_db_manager
    accessor = ToolAccessor(db_manager=db_manager, tenant_manager=mock_tenant_manager)

    for name in PUBLIC_TOOL_METHODS:
        assert hasattr(accessor, name), f"missing tool method: {name}"
        attr = getattr(accessor, name)
        assert callable(attr), f"tool method not callable: {name}"
        assert inspect.iscoroutinefunction(attr), f"tool method not async: {name}"


def test_no_extra_or_dropped_public_async_methods(mock_db_manager, mock_tenant_manager):
    db_manager, _session = mock_db_manager
    accessor = ToolAccessor(db_manager=db_manager, tenant_manager=mock_tenant_manager)

    public_async = {
        name
        for name in dir(accessor)
        if not name.startswith("_") and inspect.iscoroutinefunction(getattr(accessor, name))
    }
    assert public_async == PUBLIC_TOOL_METHODS


def test_constructor_wiring_preserved(mock_db_manager, mock_tenant_manager):
    db_manager, _session = mock_db_manager
    accessor = ToolAccessor(db_manager=db_manager, tenant_manager=mock_tenant_manager)

    assert accessor.db_manager is db_manager
    assert accessor.tenant_manager is mock_tenant_manager
    assert accessor._mission_service is accessor._orchestration_service._mission
    assert accessor._progress_service is accessor._orchestration_service._progress
    assert accessor._agent_state_service is accessor._orchestration_service._agent_state
    assert accessor._workflow_status_service is accessor._orchestration_service._workflow_status
    assert accessor._job_completion_service is accessor._orchestration_service._job_completion


@pytest.mark.asyncio
async def test_update_project_mission_delegates_to_project_service(mock_db_manager, mock_tenant_manager):
    from unittest.mock import AsyncMock

    db_manager, _session = mock_db_manager
    accessor = ToolAccessor(db_manager=db_manager, tenant_manager=mock_tenant_manager)
    mock_tenant_manager.get_current_tenant = lambda: "tk"
    accessor._project_service.update_project_mission = AsyncMock(return_value={"ok": True})

    result = await accessor.update_project_mission("proj1", "new mission")

    assert result == {"ok": True}
    accessor._project_service.update_project_mission.assert_awaited_once_with("proj1", "new mission", tenant_key="tk")


@pytest.mark.asyncio
async def test_request_approval_requires_tenant_key(mock_db_manager, mock_tenant_manager):
    from giljo_mcp.exceptions import ValidationError

    db_manager, _session = mock_db_manager
    accessor = ToolAccessor(db_manager=db_manager, tenant_manager=mock_tenant_manager)

    with pytest.raises(ValidationError):
        await accessor.request_approval(
            job_id="j",
            project_id="p",
            reason="r",
            options=[{"id": "a", "label": "A"}],
            tenant_key=None,
        )
