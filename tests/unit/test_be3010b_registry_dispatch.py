# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import functools
import inspect
from unittest.mock import MagicMock

from api.endpoints.mcp_tools._base import TOOL_DISPATCH, _resolve_tool_func
from giljo_mcp.tenant import TenantManager
from giljo_mcp.tools.tool_accessor import ToolAccessor


_ADAPTER_TOOLS = frozenset(
    {
        "get_agent_result",
        "request_approval",
        "stage_project",
        "get_implementation_prompt",
        "launch_implementation",
        "update_project_mission",
        "set_agent_status",
        "join_thread",
        "write_project_closeout",
        "write_memory_entry",
        "get_context",
        "get_vision_document",
        "update_product_context",
        "list_agent_templates",
        "apply_context_tuning",
    }
)


def _accessor() -> ToolAccessor:
    return ToolAccessor(db_manager=MagicMock(), tenant_manager=TenantManager())


def test_every_resolver_targets_a_service_method_not_the_mixin():
    accessor = _accessor()
    for name, resolver in TOOL_DISPATCH.items():
        fn = resolver(accessor)
        target = fn.func if isinstance(fn, functools.partial) else fn
        owner = type(target.__self__).__name__
        assert owner != "ToolAccessor", f"{name!r} resolves back into the ToolAccessor mixin"
        assert owner.endswith("Service"), f"{name!r} resolves to {owner}, not a *Service"


def test_every_resolved_target_is_async_and_accepts_tenant_key():
    accessor = _accessor()
    for name, resolver in TOOL_DISPATCH.items():
        fn = resolver(accessor)
        underlying = fn.func if isinstance(fn, functools.partial) else fn
        assert inspect.iscoroutinefunction(underlying), f"{name!r} target is not async"
        assert "tenant_key" in inspect.signature(fn).parameters, f"{name!r} target lacks tenant_key"


def test_adapter_tools_are_absent_from_the_registry():
    overlap = _ADAPTER_TOOLS & set(TOOL_DISPATCH)
    assert not overlap, f"adapter tools must not be registry-dispatched: {sorted(overlap)}"


def test_resolve_tool_func_falls_back_to_accessor_for_adapters():
    accessor = _accessor()
    fn = _resolve_tool_func(accessor, "get_agent_result")
    assert fn.__self__ is accessor, "adapter must resolve to the accessor's own mixin method"


def test_dep_injecting_entries_bind_their_construction_deps():
    accessor = _accessor()
    for name in ("create_project", "list_projects", "update_project_metadata"):
        fn = TOOL_DISPATCH[name](accessor)
        assert isinstance(fn, functools.partial)
        assert "websocket_manager" in fn.keywords
    create_task = TOOL_DISPATCH["create_task"](accessor)
    assert isinstance(create_task, functools.partial)
    assert "db_manager" in create_task.keywords
    assert "websocket_manager" in create_task.keywords


def test_orchestration_facades_are_typed_not_varargs():
    from giljo_mcp.services.orchestration_service import OrchestrationService

    for method_name, expected_param in (("spawn_job", "agent_display_name"), ("report_progress", "job_id")):
        sig = inspect.signature(getattr(OrchestrationService, method_name))
        kinds = {p.kind for p in sig.parameters.values()}
        assert inspect.Parameter.VAR_POSITIONAL not in kinds, f"{method_name} still has *args"
        assert inspect.Parameter.VAR_KEYWORD not in kinds, f"{method_name} still has **kwargs"
        assert expected_param in sig.parameters, f"{method_name} missing typed param {expected_param!r}"
