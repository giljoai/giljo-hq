# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
INF-3000b — parametrized MCP-transport SMOKE over EVERY registered @mcp.tool.

Closes the residual BE-5042 gap the 2026-06-11 audit named: of the 35 registered
tools, ~17 had no runtime ``call_tool`` test, so the thin per-tool glue — the
literal dispatch-string each wrapper passes to ``_call_tool`` (e.g. ``giljo_setup``
dispatches to the accessor method ``"bootstrap_setup"``) and the kwargs it builds —
failed only at runtime. The registry-surface lock
(``test_be6042d_mcp_tool_registry_surface.py``) guards the *advertised* surface
(names/params/scope); this file guards the *dispatch path* for the whole surface.

How it works (matches the audit's own suggested fix — "parametrized transport
smoke test with stub accessor"):

* ``state.tool_accessor`` is replaced with ``create_autospec(ToolAccessor)``. The
  autospec is the test's leverage — it carries the REAL ToolAccessor method set
  and the REAL per-method signatures, so:
    - a wrapper dispatching to a non-existent accessor method  -> AttributeError
    - a wrapper passing a kwarg the accessor method does not accept -> TypeError
  Both surface as a ``call_tool`` error result, failing the smoke. No DB, no
  service logic — this is a glue test, not a behavior test (behavior lives in the
  per-tool service + transport suites).
* Every tool is driven through the SDK's in-memory transport with arguments
  synthesized from its own advertised input schema (enum/type aware), so a new
  tool is exercised automatically.
* ``test_smoke_coverage_is_the_full_registry`` is the DoD gate: it set-equality
  locks the frozen coverage roster against the live registry, so a newly-added
  tool with no smoke entry FAILS CI until it is added here.

Auth note: the in-memory transport has no HTTP scope, so ``_resolve_tenant`` /
``_resolve_user_id`` are monkeypatched on ``mcp_tools._base`` (the call site),
exactly as the other transport suites do.
"""

from __future__ import annotations

import inspect
import json
from typing import Any
from unittest.mock import create_autospec

import pytest

# Importing the transport module guarantees every domain wrapper module is
# imported and has registered its @mcp.tool against the shared instance.
from api.endpoints.mcp_sdk_server import mcp
from tests.helpers.mcp_dispatch import attach_registry_service_autospecs
from tests.helpers.mcp_session_fixture import create_connected_server_and_client_session


# Only the async dispatch test needs the asyncio mark; the coverage gate is a
# plain sync assertion (a module-level pytestmark would warn on it).


# ---------------------------------------------------------------------------
# Frozen coverage roster (the DoD gate). 49 registered tools — kept identical
# to the registry-surface lock's EXPECTED_TOOL_SURFACE.keys(). A new @mcp.tool
# added without an entry here fails ``test_smoke_coverage_is_the_full_registry``.
# (INF-6049b added stage_project + get_implementation_prompt; BE-6054b added 8 Hub thread
# tools; BE-6115a added launch_implementation; INF-6111b retired
# generate_download_token + renamed get_staging_context -> get_staging_instructions;
# BE-6111c added diagnose_project_state; BE-6225a retired get_pending_jobs,
# complete_task, and list_agent_templates (49 -> 46); BE-6221a added start_chain_run (-> 47);
# BE-6225b added search_memory (the missing 360-memory search JTBD) (-> 48).
# BE-9012d hard-removed send_message / receive_messages / get_messages (-> 44).)
# ---------------------------------------------------------------------------
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
        # BE-9499d: the harness-side door that clears awaiting_user. 48 -> 49.
        "decide_approval",
        # Agent Message Hub thread tools (BE-6054b): 40 -> 48.
        "create_thread",
        # FE-9530: retag a thread's product/project(s), or rename/set status.
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
        # BE-9012b (BE-6225e): reactivate_job + dismiss_reactivation merged into one.
        "resume_or_dismiss_job",
        "set_agent_status",
        "get_job_mission",
        "spawn_job",
        "get_agent_result",
        "get_workflow_status",
        "get_context",
        # BE-6225b: keyword search over 360 memory (the missing search JTBD). 47 -> 48.
        "search_memory",
        "write_project_closeout",
        "write_memory_entry",
        "get_vision_document",
        "update_product_context",
        # BE-9201: agent-side product bootstrap (44 -> 46).
        "create_product",
        "create_vision_document",
        "health_check",
        "get_giljo_guide",
        "giljo_setup",
        # BE-6225c: renamed from propose_product_context_update (applies tuning directly).
        "apply_context_tuning",
        "stage_project",
        "get_implementation_prompt",
        "launch_implementation",
        # BE-6221a: headless chain-start (Run Sequential equivalent). 49 -> 50.
        # BE-9554: start_chain_run's action-enum retired into two plainly-named verbs.
        # start_chain_run itself stays one release as a pointer-only compat shim.
        "link_projects",
        "unlink_projects",
    }
)


# String params that a wrapper parses as an ISO-8601 datetime before dispatch
# (``_base._parse_iso_datetime_param`` raises on non-ISO input). These are the
# only string params that need a structured value rather than a placeholder.
_DATE_PARAMS: frozenset[str] = frozenset(
    {
        "created_after",
        "created_before",
        "completed_after",
        "completed_before",
        "due_before",
        "due_date",
    }
)

# BE-9469 (U62-F2): list_tasks' ``hidden`` wrapper now REFUSES any value outside
# its recognized true/false spellings -- previously it silently degraded any
# placeholder to "no filter". "true" is accepted by every ``hidden`` param on
# this surface (list_tasks/update_task/list_projects all share the same
# true/false coercion), so this override is safe across all of them.
_LITERAL_STRING_OVERRIDES: dict[str, str] = {"hidden": "true"}
_ISO_SAMPLE = "2026-01-01T00:00:00Z"


def _live_tools() -> dict[str, Any]:
    """Map registered_name -> Tool from the live FastMCP registry."""
    return {tool.name: tool for tool in mcp._tool_manager.list_tools()}


def _synth_value(name: str, prop_schema: dict[str, Any]) -> Any:
    """Synthesize a schema-valid argument value for one tool parameter.

    Schema-driven (enum/type), with the one structural carve-out the wrappers
    require: date-shaped string params get an ISO-8601 sample. ``job_id`` gets a
    non-placeholder string ("smoke"), which clears ``get_agent_mission``'s
    placeholder guard. The autospec accessor does not validate VALUES (only the
    kwarg names against the real signature), so placeholders are sufficient for
    every other param.
    """
    # Unwrap Optional / unions (FastMCP emits anyOf for ``X | None``).
    if "anyOf" in prop_schema:
        for sub in prop_schema["anyOf"]:
            if sub.get("type") != "null":
                return _synth_value(name, sub)
        return None
    # BE-9118: a nested Pydantic-model param (e.g. update_product_context's grouped
    # tech_stack/architecture/quality/testing dicts) renders as a ``$ref`` into
    # ``$defs`` with no ``type`` key. Every such model is all-optional, so an empty
    # object is a schema-valid placeholder that dispatches.
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
    # string (or untyped) — structural carve-outs first.
    if name in _DATE_PARAMS:
        return _ISO_SAMPLE
    if name in _LITERAL_STRING_OVERRIDES:
        return _LITERAL_STRING_OVERRIDES[name]
    return "smoke"


def _synth_args(tool: Any) -> dict[str, Any]:
    """Build a full, schema-valid kwargs dict covering every advertised param."""
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


# ---------------------------------------------------------------------------
# Fixture: install an autospec ToolAccessor + tenant resolution for the
# in-memory transport. No DB, no service layer.
# ---------------------------------------------------------------------------
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
    # Every async accessor method returns a JSON-serializable dict so the wrapper
    # post-processing + FastMCP wire-contract serialization both succeed. ADAPTER
    # tools still dispatch through these mixin methods (getattr fallback).
    for attr_name in dir(ToolAccessor):
        if attr_name.startswith("_"):
            continue
        if inspect.iscoroutinefunction(getattr(ToolAccessor, attr_name, None)):
            getattr(accessor, attr_name).return_value = {"smoke": True}

    # BE-3010b: PURE tools now dispatch straight to the terminal service method
    # via TOOL_DISPATCH, so the autospec accessor must also carry autospec'd
    # service sub-objects (real signatures keep the kwarg-drift leverage intact).
    attach_registry_service_autospecs(accessor, {"smoke": True})

    state.tool_accessor = accessor
    state.tenant_manager = TenantManager()
    # db_manager stays None: the only tools that touch it are the job_id
    # auto-clear-silent / heartbeat side paths in _call_tool, which are wrapped
    # in a broad except (AttributeError included) and degrade to a logged no-op.
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


# ---------------------------------------------------------------------------
# DoD gate: a new unsmoked tool fails CI.
# ---------------------------------------------------------------------------
def test_smoke_coverage_is_the_full_registry():
    """The frozen smoke roster must equal the live @mcp.tool registry.

    Adding a tool without adding it here (or removing/renaming one) fails this
    assertion — the smoke can never silently fall behind the surface it guards.
    """
    live = set(_live_tools())
    assert live == EXPECTED_SMOKE_TOOLS, (
        f"smoke roster drift. Unsmoked new tools: {sorted(live - EXPECTED_SMOKE_TOOLS)}; "
        f"stale roster entries: {sorted(EXPECTED_SMOKE_TOOLS - live)}"
    )


# ---------------------------------------------------------------------------
# The smoke itself — every registered tool, through the real transport.
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
@pytest.mark.parametrize("tool_name", sorted(EXPECTED_SMOKE_TOOLS))
async def test_tool_dispatches_through_transport(tool_name, smoke_state):
    """Each wrapper unpacks its params, resolves its dispatch string to a REAL
    accessor method with signature-matching kwargs, and serializes the result
    back over the wire — proven by a non-error CallToolResult."""
    tool = _live_tools()[tool_name]
    args = _synth_args(tool)

    async with create_connected_server_and_client_session(mcp) as session:
        result = await session.call_tool(tool_name, args)

    assert result.is_error is False, (
        f"tool {tool_name!r} failed at the transport/dispatch boundary with args {args!r}: {_error_text(result)}"
    )
    # Sanity: a non-error result must carry decodable content (dict payload).
    if result.content:
        first = result.content[0]
        text = getattr(first, "text", None)
        if text is not None:
            json.loads(text)
