# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-3010b -- the MCP bound-method dispatch registry.

Locks the registry-dispatch invariants the WO's DoD depends on:

* Every ``TOOL_DISPATCH`` entry resolves (against a real ToolAccessor) to a
  callable on a terminal SERVICE -- NOT back into ToolAccessor -- so the mixin's
  hand-copied signature is out of the parameter path (add-a-param -> 2 files).
* The resolved target is an async callable that accepts ``tenant_key`` (the
  dispatcher injects the session tenant by signature inspection).
* The ADAPTER tools (which reshape results / inject deps into standalone
  functions / map params) are deliberately ABSENT from the registry, so they keep
  flowing through their ToolAccessor mixin via the ``getattr`` fallback.
* The two formerly ``*args/**kwargs`` OrchestrationService facades are now typed.

Edition Scope: Both. No DB writes (a MagicMock db_manager constructs the real
service instances); parallel-safe.
"""

from __future__ import annotations

import functools
import inspect
from unittest.mock import MagicMock

from api.endpoints.mcp_tools._base import TOOL_DISPATCH, _resolve_tool_func
from giljo_mcp.tenant import TenantManager
from giljo_mcp.tools.tool_accessor import ToolAccessor


# Tools that legitimately keep their ToolAccessor mixin logic (result reshaping,
# envelope building, dep injection into standalone tool-functions, param mapping).
# They MUST NOT be folded into the bound-method registry, or that logic is lost.
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
        # BE-6225c: renamed from propose_product_context_update (applies tuning directly).
        "apply_context_tuning",
    }
)


def _accessor() -> ToolAccessor:
    """A real ToolAccessor whose service sub-objects are real instances (a
    MagicMock db_manager is enough -- the constructors only store refs)."""
    return ToolAccessor(db_manager=MagicMock(), tenant_manager=TenantManager())


def test_every_resolver_targets_a_service_method_not_the_mixin():
    """The DoD property: a registry tool dispatches straight to its terminal
    SERVICE bound method, so the ToolAccessor mixin signature is bypassed."""
    accessor = _accessor()
    for name, resolver in TOOL_DISPATCH.items():
        fn = resolver(accessor)
        target = fn.func if isinstance(fn, functools.partial) else fn
        owner = type(target.__self__).__name__
        assert owner != "ToolAccessor", f"{name!r} resolves back into the ToolAccessor mixin"
        assert owner.endswith("Service"), f"{name!r} resolves to {owner}, not a *Service"


def test_every_resolved_target_is_async_and_accepts_tenant_key():
    """The dispatcher injects the session tenant by signature inspection; every
    terminal target must be an async callable that accepts ``tenant_key``."""
    accessor = _accessor()
    for name, resolver in TOOL_DISPATCH.items():
        fn = resolver(accessor)
        underlying = fn.func if isinstance(fn, functools.partial) else fn
        assert inspect.iscoroutinefunction(underlying), f"{name!r} target is not async"
        assert "tenant_key" in inspect.signature(fn).parameters, f"{name!r} target lacks tenant_key"


def test_adapter_tools_are_absent_from_the_registry():
    """Adapters keep their mixin logic via the getattr fallback -- they must NOT
    be in the bound-method registry."""
    overlap = _ADAPTER_TOOLS & set(TOOL_DISPATCH)
    assert not overlap, f"adapter tools must not be registry-dispatched: {sorted(overlap)}"


def test_resolve_tool_func_falls_back_to_accessor_for_adapters():
    """An adapter (not in the registry) resolves to the ToolAccessor mixin method."""
    accessor = _accessor()
    fn = _resolve_tool_func(accessor, "get_agent_result")
    assert fn.__self__ is accessor, "adapter must resolve to the accessor's own mixin method"


def test_dep_injecting_entries_bind_their_construction_deps():
    """create_project/list_projects/update_project_metadata bind websocket_manager;
    create_task additionally binds db_manager (functools.partial)."""
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
    """BE-3010b typed the two formerly *args/**kwargs facades; their signatures
    must now expose real parameters (no bare *args/**kwargs)."""
    from giljo_mcp.services.orchestration_service import OrchestrationService

    for method_name, expected_param in (("spawn_job", "agent_display_name"), ("report_progress", "job_id")):
        sig = inspect.signature(getattr(OrchestrationService, method_name))
        kinds = {p.kind for p in sig.parameters.values()}
        assert inspect.Parameter.VAR_POSITIONAL not in kinds, f"{method_name} still has *args"
        assert inspect.Parameter.VAR_KEYWORD not in kinds, f"{method_name} still has **kwargs"
        assert expected_param in sig.parameters, f"{method_name} missing typed param {expected_param!r}"
