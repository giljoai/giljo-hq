# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-6225c -- MCP-transport boundary test for the wire + honest-rename change.

CLAUDE.md mandates a regression test at the failing layer. The two fixes here live
at the FastMCP @mcp.tool registry / transport boundary:

* PART 2 RENAME: ``propose_product_context_update`` -> ``apply_context_tuning`` (a
  hard rename using the INF-6052a / ce_0049 rename-heal pattern). The failing layer
  is the @mcp.tool wrapper registry: a tool can pass every service test yet fail to
  register under its new name (the exact BE-5042 gap). So we drive the REAL
  in-memory transport and assert:
    (a) the NEW name ``apply_context_tuning`` resolves and dispatches (isError False);
    (b) the OLD name is GONE from the live surface AND the server-authored tuning
        prompt heals -- it now names the new tool and never the retired one, so any
        caller that used to reach for the old name is redirected (back-compat heal).

* PART 1 WIRE: ``diagnose_project_state`` (a real read-only self-heal tool that
  nothing told agents to call) is now named in ``get_giljo_guide`` -- and the guide
  names NO retired tool. We assert through the transport's ``get_giljo_guide`` call.

Parallel-safe: the autospec section needs no DB; no module-level mutable state; the
tenant key is freshly generated per fixture use.
"""

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
    """Install an autospec ToolAccessor + tenant resolution on the in-memory
    transport (mirrors the BE-3006d / INF-3000b smoke harness). Yields a client
    factory so a test can dispatch any tool over the real transport without a DB."""
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


# ---------------------------------------------------------------------------
# PART 2 -- the rename resolves over the transport, the old name is gone.
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_apply_context_tuning_resolves_over_transport(autospec_mcp):
    """(a) The NEW name dispatches cleanly through the real transport."""
    async with autospec_mcp() as session:
        result = await session.call_tool(
            "apply_context_tuning",
            {"product_id": str(uuid4()), "proposals": []},
        )
    assert result.is_error is False, f"apply_context_tuning must dispatch: {_error_text(result)}"


@pytest.mark.asyncio
async def test_apply_context_tuning_in_live_tool_surface():
    """The new name is registered on the live FastMCP instance; the old name is not."""
    live = {t.name for t in mcp._tool_manager.list_tools()}
    assert "apply_context_tuning" in live
    assert "propose_product_context_update" not in live
    # BE-9012b (BE-6225e) merged reactivate_job + dismiss_reactivation into one
    # resolve_reactivation tool, so the whole surface was 47 (was 48). BE-9012d
    # (bus retirement, phase d) hard-removed send_message / receive_messages /
    # get_messages (-> 44). BE-9201 added create_product + create_vision_document
    # (agent-side product bootstrap), so the whole surface is 46. BE-9296a added
    # await_my_turn (the server wake signal) -> 47, and get_participant_liveness
    # (the orchestrator's who-is-still-there read) -> 48.
    # BE-9385b added set_agent_export_alias (the install-time "keep both" rename,
    # which must round-trip to the server or spawn-by-name stops resolving) -> 49.
    # BE-9396 retracted it unreleased: giljo_setup guarantees server -> disk only,
    # so the install prose now flags a conflict for the LLM and the user to resolve
    # instead of the server enforcing a rename -> 48.
    assert len(live) == 48


@pytest.mark.asyncio
async def test_old_name_does_not_resolve_over_transport(autospec_mcp):
    """The retired name is no longer a live tool -- a call to it does not silently
    dispatch to the wrong handler. Robust to either transport behavior for an
    unknown tool: an error result (isError) or a raised protocol error."""
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
    """(b) Back-compat heal: the server-authored tuning prompt redirects callers to
    the NEW tool name and never names the retired one (no agent is told to call a
    dead tool). The prompt is the only place the tool name was 'stored', and it is
    regenerated server-side, so this is the heal that keeps the old name resolving."""
    from giljo_mcp.services.product_tuning_service import TUNING_PROMPT_TEMPLATE

    assert "apply_context_tuning" in TUNING_PROMPT_TEMPLATE
    assert "propose_product_context_update" not in TUNING_PROMPT_TEMPLATE


# ---------------------------------------------------------------------------
# PART 1 -- diagnose_project_state is wired into the guide; no retired tool named.
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_giljo_guide_wires_diagnose_and_names_no_retired_tool(autospec_mcp):
    """The guide (read over the transport) points agents at diagnose_project_state
    for recovery, and names no retired tool (incl. the just-renamed one)."""
    async with autospec_mcp() as session:
        result = await session.call_tool("get_giljo_guide", {})
    assert result.is_error is False, f"get_giljo_guide must dispatch: {_error_text(result)}"
    text = _error_text(result)

    assert "diagnose_project_state" in text, "the guide must wire the self-heal diagnostic"
    for retired in _RETIRED_TOOL_NAMES:
        assert retired not in text, f"guide still names a retired tool: {retired}"
