# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
BE-6042a characterization test — locks the public surface of ToolAccessor.

This suite is the behavior lock for the mechanical mixin split of
``tool_accessor.py`` into a ``tool_accessor/`` subpackage. It runs GREEN
against the unmodified god-class FIRST, then unchanged against the split
package. It asserts:

- The public import path ``from giljo_mcp.tools.tool_accessor import ToolAccessor``
  resolves (load-bearing for api/startup/core_services.py + the boundary test
  fixtures).
- The public tool methods are present, callable, and async — catches the
  one real mixin failure mode: a dropped, duplicated, or shadowed method.
- A representative thin delegator dispatches verbatim to the same service method
  with the same arguments (no signature / service-call drift).

BE-6118: after BE-3010b, ``_call_tool`` dispatches the ~30 PURE MCP tools
straight to their terminal service bound method via ``TOOL_DISPATCH`` instead of
through the ToolAccessor mixin, so the pure pass-through mixin methods were
deleted. The surface below is now exactly the ~18 ADAPTER methods that survive on
the ``getattr`` fallback (reshape results / build envelopes / inject deps into
standalone tool-functions / map params). The registry side of this split is
locked separately in ``test_be3010b_registry_dispatch.py``; the advertised
@mcp.tool roster (unchanged — the wrappers stay) in
``test_be6042d_mcp_tool_registry_surface.py``.
"""

import inspect

import pytest

from giljo_mcp.tools.tool_accessor import ToolAccessor


# The ADAPTER tool methods that remain on ToolAccessor after BE-6118. Each is
# deliberately ABSENT from ``TOOL_DISPATCH`` and resolves through ``_call_tool``'s
# ``getattr`` fallback because it does more than forward args to one service
# method (reshapes a result, builds an envelope, injects construction deps into a
# standalone tool-function, maps params, or constructs a differently-built
# service). The ~30 pure pass-throughs were deleted (they now dispatch straight to
# their terminal service).
PUBLIC_TOOL_METHODS = frozenset(
    {
        # Project lifecycle adapters
        "update_project_mission",  # injects the current tenant
        "diagnose_project_state",  # constructs ProjectCloseoutService (BE-6111c)
        "stage_project",  # mode mapping + human-gate stop instruction (INF-6049b)
        "implement_project",  # structured gate error (INF-6049b)
        "launch_implementation",  # two-door implement gate CLI door (BE-6115a)
        "start_chain_run",  # headless chain entry: creates run + mints conductor (BE-6221a)
        # Message adapters
        "request_approval",  # RequestApprovalInput validation before the service
        "decide_approval",  # BE-9499d: DecideApprovalInput validation before the service
        # Agent Message Hub adapter (BE-6054b)
        "join_thread",  # maps agent_id -> participant_id + participant_type
        # Job lifecycle adapters
        "get_agent_result",  # reshapes None -> message envelope
        "set_agent_status",  # absorbs extra **kwargs
        # Memory adapters (inject db_manager into standalone tool-functions)
        "write_project_closeout",
        "write_memory_entry",
        "search_memory",  # BE-6225b: resolves active product + reuses ProductMemoryService search
        # Context adapters (inject deps into standalone tool-functions)
        "get_context",
        "get_vision_doc",
        "update_product_context",
        # BE-9201: product bootstrap adapters (construct the tenant-scoped
        # ProductService / inject db_manager into the standalone tool-function)
        "create_product",
        "create_vision_document",
        # Setup / misc adapters
        "bootstrap_setup",
        "list_agent_templates",
        # BE-6225c: renamed from propose_product_context_update (applies tuning directly).
        "apply_context_tuning",
    }
)


def test_public_import_resolves():
    """Load-bearing import used by core_services.py + ~15 test files."""
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
    # Sub-service references collapsed from OrchestrationService (sprint 002f).
    assert accessor._mission_service is accessor._orchestration_service._mission
    assert accessor._progress_service is accessor._orchestration_service._progress
    assert accessor._agent_state_service is accessor._orchestration_service._agent_state
    assert accessor._workflow_status_service is accessor._orchestration_service._workflow_status
    assert accessor._job_completion_service is accessor._orchestration_service._job_completion


@pytest.mark.asyncio
async def test_update_project_mission_delegates_to_project_service(mock_db_manager, mock_tenant_manager):
    """Representative adapter-delegation lock (BE-6118: replaces the deleted
    create_project / update_job_mission pure-delegation cases). update_project_mission
    survives as an adapter — it resolves the current tenant before forwarding."""
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
