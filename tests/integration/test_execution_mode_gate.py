# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""Regression tests for the execution_mode NULL-state gates.

CLAUDE.md mandates a regression test at the failing layer. The original incident:
a project whose ``execution_mode`` was never explicitly chosen silently behaved
as ``multi_terminal`` — the spawn boundary handed the orchestrator a
multi_terminal dashboard pointer it could not run. The NULL-state redesign makes
``execution_mode`` nullable (NULL = "not yet selected") and GATES every boundary
so a NULL is refused, never silently coerced.

These tests exercise the gates at the exact layers that previously leaked:

1. ``spawn_job`` through the FastMCP ``@mcp.tool`` wrapper (the failing layer) —
   a NULL-mode project is REFUSED, a chosen-mode project still spawns (the gate
   only bites NEW unset projects, not existing multi_terminal ones).
2. ``get_job_mission`` through the wrapper — a NULL-mode project returns a
   blocked mission, not a fabricated multi_terminal one.
3. ``get_staging_instructions`` through the wrapper — a NULL-mode project
   returns a STOP directive instead of a multi_terminal protocol.
4. The staging-prompt endpoint (the PRIMARY user-facing gate where the mode is
   persisted) returns 409 when no mode is resolvable.

Pattern reference: ``tests/integration/test_multi_terminal_footgun.py`` (same
in-memory MCP transport, ``_resolve_tenant`` monkeypatch, shared-session
ToolAccessor rebinding).
"""

from __future__ import annotations

import json
import random
from datetime import UTC, datetime
from uuid import uuid4

import pytest
import pytest_asyncio
from fastapi import HTTPException

from giljo_mcp.models.agent_identity import AgentExecution, AgentJob
from giljo_mcp.models.organizations import Organization
from giljo_mcp.models.products import Product
from giljo_mcp.models.projects import Project
from giljo_mcp.models.templates import AgentTemplate
from giljo_mcp.tenant import TenantManager
from tests.helpers.mcp_session_fixture import create_connected_server_and_client_session


pytestmark = pytest.mark.asyncio


def _payload(call_tool_result) -> dict:
    if getattr(call_tool_result, "structuredContent", None):
        return call_tool_result.structured_content
    first_block = call_tool_result.content[0]
    text = getattr(first_block, "text", None)
    if text is None:
        raise AssertionError(f"unexpected content block: {first_block!r}")
    return json.loads(text)


def _error_text(call_tool_result) -> str:
    parts = []
    for block in call_tool_result.content:
        text = getattr(block, "text", None)
        if text:
            parts.append(text)
    return "\n".join(parts)


async def _seed(
    db_session,
    tenant_key: str,
    *,
    execution_mode: str | None,
    orchestrator: bool = False,
    implementer: bool = False,
) -> dict:
    """Seed org + product + project (+ optional orchestrator / implementer job).

    ``execution_mode=None`` reproduces a freshly-created project before the user
    has picked a mode — the state every boundary gate must refuse.
    """
    suffix = uuid4().hex[:8]
    org = Organization(name=f"Org {suffix}", slug=f"org-{suffix}", tenant_key=tenant_key, is_active=True)
    db_session.add(org)
    await db_session.flush()

    product = Product(
        id=str(uuid4()),
        name=f"Product {suffix}",
        description="execution_mode gate test",
        tenant_key=tenant_key,
        is_active=True,
    )
    db_session.add(product)
    await db_session.flush()

    project = Project(
        id=str(uuid4()),
        tenant_key=tenant_key,
        product_id=product.id,
        name=f"Project {suffix}",
        description="execution_mode NULL-state gate",
        mission="x",
        status="active",
        staging_status="staging",
        execution_mode=execution_mode,
        implementation_launched_at=datetime.now(UTC),
        series_number=random.randint(1, 9000),
    )
    db_session.add(project)
    await db_session.flush()

    template = AgentTemplate(
        tenant_key=tenant_key,
        name="implementer",
        role="implementer",
        description="gate test template",
        system_instructions="# implementer\nTest body.",
        is_active=True,
    )
    db_session.add(template)

    out: dict = {"org": org, "product": product, "project": project}

    if orchestrator:
        out["orchestrator_job"] = await _seed_job(db_session, tenant_key, project.id, "orchestrator")
    if implementer:
        out["implementer_job"] = await _seed_job(db_session, tenant_key, project.id, "implementer")

    await db_session.commit()
    return out


async def _seed_job(db_session, tenant_key: str, project_id: str, job_type: str) -> dict:
    job_id = str(uuid4())
    job = AgentJob(
        job_id=job_id,
        tenant_key=tenant_key,
        project_id=project_id,
        job_type=job_type,
        mission="x",
        status="active",
        created_at=datetime.now(UTC),
    )
    db_session.add(job)
    await db_session.flush()
    execution = AgentExecution(
        id=str(uuid4()),
        agent_id=str(uuid4()),
        job_id=job_id,
        tenant_key=tenant_key,
        agent_display_name=job_type,
        status="working",
        started_at=datetime.now(UTC),
        project_phase="implementation",
    )
    db_session.add(execution)
    await db_session.flush()
    return {"job_id": job_id, "agent_id": execution.agent_id}


@pytest_asyncio.fixture
async def gate_mcp_client(db_manager, db_session, monkeypatch):
    """Shared-session ToolAccessor wired to the in-memory MCP transport."""
    from api import app_state
    from api.endpoints import mcp_sdk_server
    from api.endpoints.mcp_tools import _base
    from giljo_mcp.tools.tool_accessor import ToolAccessor

    state = app_state.state
    prior_tool_accessor = state.tool_accessor
    prior_tenant_manager = state.tenant_manager
    prior_db_manager = state.db_manager

    if state.tenant_manager is None:
        state.tenant_manager = TenantManager()
    state.db_manager = db_manager

    tenant_key = TenantManager.generate_tenant_key()
    accessor = ToolAccessor(db_manager=db_manager, tenant_manager=state.tenant_manager, test_session=db_session)
    state.tool_accessor = accessor

    # Patch at the definition module (api.endpoints.mcp_tools._base): the tool
    # dispatch (_call_tool) resolves tenant via the _base module global, so a
    # monkeypatch on mcp_sdk_server's re-exported reference would miss the real
    # call site. The in-memory MCP transport has no HTTP request, so without this
    # _resolve_tenant would crash on request.scope (request is None).
    monkeypatch.setattr(_base, "_resolve_tenant", lambda ctx: tenant_key)
    monkeypatch.setattr(_base, "_resolve_user_id", lambda ctx: None)

    def _new_client():
        return create_connected_server_and_client_session(mcp_sdk_server.mcp)

    try:
        yield _new_client, tenant_key, db_session
    finally:
        state.tool_accessor = prior_tool_accessor
        state.tenant_manager = prior_tenant_manager
        state.db_manager = prior_db_manager


# ---------------------------------------------------------------------------
# spawn_job — the failing layer
# ---------------------------------------------------------------------------


async def test_spawn_job_refuses_null_execution_mode_at_mcp_boundary(gate_mcp_client):
    """THE FAILING LAYER. A NULL-mode project must be REFUSED at the spawn
    boundary, not silently handed a multi_terminal bootstrap pointer."""
    new_client, tenant_key, db_session = gate_mcp_client
    seed = await _seed(db_session, tenant_key, execution_mode=None)

    async with new_client() as session:
        result = await session.call_tool(
            "spawn_job",
            {
                "agent_display_name": "implementer",
                "agent_name": "implementer",
                "project_id": seed["project"].id,
                "mission": "do the thing",
            },
        )

    assert result.is_error is True, "spawn_job MUST refuse a NULL-execution_mode project"
    err = _error_text(result).lower()
    assert "execution mode" in err, f"expected an execution-mode gate message, got: {err!r}"


async def test_spawn_job_succeeds_for_chosen_mode(gate_mcp_client):
    """Control: the gate bites ONLY unset projects. An existing multi_terminal
    project still spawns exactly as before."""
    new_client, tenant_key, db_session = gate_mcp_client
    seed = await _seed(db_session, tenant_key, execution_mode="multi_terminal")

    async with new_client() as session:
        result = await session.call_tool(
            "spawn_job",
            {
                "agent_display_name": "implementer",
                "agent_name": "implementer",
                "project_id": seed["project"].id,
                "mission": "do the thing",
            },
        )

    assert result.is_error is False, _error_text(result)
    payload = _payload(result)
    assert payload.get("job_id")


# ---------------------------------------------------------------------------
# get_job_mission (was get_agent_mission, renamed INF-6052a)
# ---------------------------------------------------------------------------


async def test_get_agent_mission_blocks_null_execution_mode(gate_mcp_client):
    new_client, tenant_key, db_session = gate_mcp_client
    seed = await _seed(db_session, tenant_key, execution_mode=None, implementer=True)
    job_id = seed["implementer_job"]["job_id"]

    async with new_client() as session:
        result = await session.call_tool("get_job_mission", {"job_id": job_id})

    if result.is_error:
        assert "execution mode" in _error_text(result).lower()
    else:
        payload = _payload(result)
        # Structural discriminators the blocked MissionResponse guarantees — far
        # stronger than a bare substring (which a future protocol edit could
        # accidentally satisfy). blocked alone is insufficient because the
        # implementation-launch gate ALSO returns blocked=True, so the
        # mode-identifying text must live in error/user_instruction.
        assert payload.get("blocked") is True, f"expected a blocked mission, got: {payload!r}"
        assert payload.get("mission") is None, f"a blocked mission must carry no mission body, got: {payload!r}"
        gate_text = f"{payload.get('error', '')} {payload.get('user_instruction', '')}".lower()
        assert "execution mode" in gate_text, (
            f"the gate must identify the missing execution mode in error/user_instruction, got: {payload!r}"
        )


# ---------------------------------------------------------------------------
# get_staging_instructions
# ---------------------------------------------------------------------------


async def test_get_staging_instructions_blocks_null_execution_mode(gate_mcp_client):
    new_client, tenant_key, db_session = gate_mcp_client
    seed = await _seed(db_session, tenant_key, execution_mode=None, orchestrator=True)
    job_id = seed["orchestrator_job"]["job_id"]

    async with new_client() as session:
        result = await session.call_tool("get_staging_instructions", {"job_id": job_id})

    text = (_error_text(result) if result.is_error else json.dumps(_payload(result))).lower()
    assert "execution mode" in text, f"expected execution-mode STOP, got: {text!r}"
    if not result.is_error:
        payload = _payload(result)
        # The STOP shape must not carry a rendered orchestrator protocol.
        assert payload.get("action") == "STOP" or payload.get("status") == "BLOCKED", (
            f"NULL-mode orchestrator must get a STOP/BLOCKED directive, got keys: {list(payload)}"
        )


# ---------------------------------------------------------------------------
# staging-prompt endpoint — the PRIMARY user-facing gate
# ---------------------------------------------------------------------------


async def test_staging_prompt_endpoint_409s_when_no_mode_selected(db_session):
    """The staging endpoint is where the mode becomes concrete. With neither a
    query param nor a mode on the row, it must 409 (the gate that forces the
    user to pick) — never default to multi_terminal."""
    from types import SimpleNamespace

    from api.endpoints.prompts import generate_staging_prompt

    tenant_key = TenantManager.generate_tenant_key()
    # staging_status must NOT be staged/staging or the unrelated staging-guard
    # 409 fires first; use a fresh unstaged project.
    seed = await _seed(db_session, tenant_key, execution_mode=None)
    project = seed["project"]
    project.staging_status = None
    await db_session.commit()

    current_user = SimpleNamespace(tenant_key=tenant_key, id=str(uuid4()), username="tester")
    ws_dep = SimpleNamespace(is_available=lambda: False)

    with pytest.raises(HTTPException) as exc:
        await generate_staging_prompt(
            project_id=project.id,
            tool="claude-code",
            execution_mode=None,
            current_user=current_user,
            db=db_session,
            ws_dep=ws_dep,
        )

    assert exc.value.status_code == 409
    assert "execution mode" in str(exc.value.detail).lower()
