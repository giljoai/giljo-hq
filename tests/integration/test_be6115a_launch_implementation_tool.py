# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-6115a — tests for the launch_implementation MCP tool (CLI door of the two-door gate).

This is the keystone of the CLI-readiness chain: the staging->implement HITL gate was
launchable ONLY from the dashboard Implement button (sole writer of
``implementation_launched_at``). BE-6115a adds a SECOND human-authorized door — the
``launch_implementation`` MCP tool — that flips the SAME flag through the SAME
single-writer (``ProjectStagingService.launch_implementation``), with NO parallel
write path and WITHOUT weakening the human gate.

Two-sided proof (the load-bearing DoD):

1. The CLI door WORKS (regression-at-the-failing-layer — the BE-5042 gap: a tool can
   pass every service test yet fail at the FastMCP @mcp.tool wrapper):
   - launch_implementation registers on the FastMCP instance AND, driven through the
     transport, stamps ``implementation_launched_at`` on the project row.
   - It is idempotent: a second call does NOT re-stamp (already_launched=True).

2. The human gate STILL BLOCKS, and clears ONLY after a launch:
   - Before launch, get_implementation_prompt returns gate_not_passed / not_launched and the
     flag is unset.
   - After launch_implementation flips the flag, get_implementation_prompt returns ``ready`` —
     proving BOTH doors flip the EXACT flag the downstream gate reads.

3. An agent CANNOT bypass the gate:
   - launch_implementation is deliberately EXCLUDED from the orchestrator auto-tool
     bundle (``CANONICAL_ORCHESTRATOR_TOOLS``) — a spawned/staging agent has no schema
     for it and cannot self-unlock. Its MCP permission prompt IS the human authorization.

4. Tenant isolation: tenant B cannot launch tenant A's project, and the flag stays unset.

Pattern reference: tests/integration/test_inf6049b_stage_implement_tools.py
(in-memory FastMCP transport + shared-session ToolAccessor + tenant monkeypatch).
"""

from __future__ import annotations

import json
import random
from datetime import UTC, datetime
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import select

from giljo_mcp.models.agent_identity import AgentExecution, AgentJob
from giljo_mcp.models.organizations import Organization
from giljo_mcp.models.products import Product
from giljo_mcp.models.projects import Project
from giljo_mcp.tenant import TenantManager
from tests.helpers.mcp_session_fixture import create_connected_server_and_client_session


pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Helpers (mirror the harness decoders used by the other transport tests)
# ---------------------------------------------------------------------------


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


async def _seed_product_project(
    db_session,
    tenant_key: str,
    *,
    staging_status: str | None = None,
    launched: bool = False,
    execution_mode: str = "claude_code_cli",
) -> dict:
    """Create org + product + project (product linked) for ``tenant_key``."""
    suffix = uuid4().hex[:8]
    org = Organization(name=f"Org {suffix}", slug=f"org-{suffix}", tenant_key=tenant_key, is_active=True)
    db_session.add(org)
    await db_session.flush()

    product = Product(
        id=str(uuid4()),
        name=f"Product {suffix}",
        description="BE-6115a launch_implementation tests",
        tenant_key=tenant_key,
        is_active=True,
        product_memory={},
    )
    db_session.add(product)
    await db_session.flush()

    project = Project(
        id=str(uuid4()),
        tenant_key=tenant_key,
        product_id=product.id,
        name=f"Project {suffix}",
        description="x",
        mission="x",
        status="active",
        execution_mode=execution_mode,
        staging_status=staging_status,
        implementation_launched_at=datetime.now(UTC) if launched else None,
        series_number=random.randint(1, 9000),
    )
    db_session.add(project)
    await db_session.commit()
    return {"project": project, "product": product}


async def _seed_orchestrator_and_agent(db_session, tenant_key: str, project) -> dict:
    """Seed a non-terminal orchestrator execution + one waiting child agent."""
    orch_job = AgentJob(
        job_id=str(uuid4()),
        tenant_key=tenant_key,
        project_id=project.id,
        job_type="orchestrator",
        mission="orchestrate",
        status="active",
        created_at=datetime.now(UTC),
    )
    db_session.add(orch_job)
    await db_session.flush()

    orch_exec = AgentExecution(
        id=str(uuid4()),
        agent_id=str(uuid4()),
        job_id=orch_job.job_id,
        tenant_key=tenant_key,
        agent_display_name="orchestrator",
        status="idle",
        started_at=datetime.now(UTC),
    )
    db_session.add(orch_exec)
    await db_session.flush()

    child_job = AgentJob(
        job_id=str(uuid4()),
        tenant_key=tenant_key,
        project_id=project.id,
        job_type="implementer",
        mission="implement",
        status="active",
        created_at=datetime.now(UTC),
    )
    db_session.add(child_job)
    await db_session.flush()

    child_exec = AgentExecution(
        id=str(uuid4()),
        agent_id=str(uuid4()),
        job_id=child_job.job_id,
        tenant_key=tenant_key,
        agent_display_name="implementer",
        status="waiting",
        spawned_by=orch_exec.agent_id,
        started_at=datetime.now(UTC),
    )
    db_session.add(child_exec)
    await db_session.commit()
    return {"orchestrator": orch_exec, "child": child_exec}


# ---------------------------------------------------------------------------
# Fixtures: shared-session ToolAccessor + tenant-aware in-memory MCP client
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def primary_tenant_key() -> str:
    return TenantManager.generate_tenant_key()


@pytest_asyncio.fixture
async def secondary_tenant_key() -> str:
    return TenantManager.generate_tenant_key()


class _TenantSwitch:
    def __init__(self, value: str):
        self.value = value


@pytest_asyncio.fixture
async def lifecycle_mcp_client(db_manager, db_session, primary_tenant_key, monkeypatch):
    """Yield ``(new_client, tenant_switch)`` for in-memory FastMCP transport tests.

    The ToolAccessor is built with ``test_session=db_session`` so the launch write
    (ProjectStagingService.launch_implementation) lands inside the rolled-back test
    transaction. ``_resolve_tenant`` / ``_resolve_user_id`` are monkeypatched on
    ``_base`` (the _call_tool + wrapper call site) since the in-memory transport has
    no auth middleware.
    """
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

    state.tool_accessor = ToolAccessor(
        db_manager=db_manager,
        tenant_manager=state.tenant_manager,
        test_session=db_session,
    )

    tenant_switch = _TenantSwitch(primary_tenant_key)
    monkeypatch.setattr(_base, "_resolve_tenant", lambda ctx: tenant_switch.value)
    monkeypatch.setattr(_base, "_resolve_user_id", lambda ctx: "test-human-user")

    def _new_client():
        return create_connected_server_and_client_session(mcp_sdk_server.mcp)

    try:
        yield _new_client, tenant_switch
    finally:
        state.tool_accessor = prior_tool_accessor
        state.tenant_manager = prior_tenant_manager
        state.db_manager = prior_db_manager


# ---------------------------------------------------------------------------
# 1. The CLI door WORKS — transport boundary: stamps the flag, idempotent
# ---------------------------------------------------------------------------


async def test_launch_implementation_through_transport_stamps_flag(
    lifecycle_mcp_client, db_session, primary_tenant_key
):
    new_client, _switch = lifecycle_mcp_client
    seeded = await _seed_product_project(
        db_session, primary_tenant_key, staging_status="staging_complete", launched=False
    )

    # Pre-condition: the flag is unset.
    row = (await db_session.execute(select(Project).where(Project.id == seeded["project"].id))).scalar_one()
    assert row.implementation_launched_at is None

    async with new_client() as session:
        result = await session.call_tool("launch_implementation", {"project_id": seeded["project"].id})

    assert result.is_error is False, _error_text(result)
    payload = _payload(result)
    assert payload["status"] == "launched"
    assert payload["success"] is True
    assert payload["already_launched"] is False
    assert payload["implementation_launched_at"], "first launch must return the new timestamp"

    # The CLI door wrote the SAME column the dashboard button writes.
    row = (await db_session.execute(select(Project).where(Project.id == seeded["project"].id))).scalar_one()
    assert row.implementation_launched_at is not None, "launch_implementation must stamp implementation_launched_at"


async def test_launch_implementation_is_idempotent(lifecycle_mcp_client, db_session, primary_tenant_key):
    new_client, _switch = lifecycle_mcp_client
    seeded = await _seed_product_project(
        db_session, primary_tenant_key, staging_status="staging_complete", launched=False
    )

    async with new_client() as session:
        first = await session.call_tool("launch_implementation", {"project_id": seeded["project"].id})
    assert first.is_error is False, _error_text(first)
    first_payload = _payload(first)
    assert first_payload["already_launched"] is False

    row = (await db_session.execute(select(Project).where(Project.id == seeded["project"].id))).scalar_one()
    original_ts = row.implementation_launched_at
    assert original_ts is not None

    async with new_client() as session:
        second = await session.call_tool("launch_implementation", {"project_id": seeded["project"].id})
    assert second.is_error is False, _error_text(second)
    second_payload = _payload(second)
    assert second_payload["already_launched"] is True
    assert second_payload["launched_at"], "idempotent call returns the original timestamp"

    # No re-stamp: the timestamp is unchanged.
    row = (await db_session.execute(select(Project).where(Project.id == seeded["project"].id))).scalar_one()
    assert row.implementation_launched_at == original_ts, "second launch must NOT re-stamp the flag"


# ---------------------------------------------------------------------------
# 2. The human gate STILL BLOCKS before launch, and clears ONLY after launch.
#    This proves BOTH doors flip the EXACT flag the downstream gate reads.
# ---------------------------------------------------------------------------


async def test_gate_blocks_before_launch_then_proceeds_after(lifecycle_mcp_client, db_session, primary_tenant_key):
    new_client, _switch = lifecycle_mcp_client
    seeded = await _seed_product_project(
        db_session,
        primary_tenant_key,
        staging_status="staging_complete",
        launched=False,
        execution_mode="multi_terminal",
    )
    await _seed_orchestrator_and_agent(db_session, primary_tenant_key, seeded["project"])

    # BEFORE launch: get_implementation_prompt refuses (the human gate blocks).
    async with new_client() as session:
        blocked = await session.call_tool("get_implementation_prompt", {"project_id": seeded["project"].id})
    assert blocked.is_error is False, _error_text(blocked)
    blocked_payload = _payload(blocked)
    assert blocked_payload["status"] == "gate_not_passed"
    assert blocked_payload["reason"] == "not_launched"

    # The CLI door (human-authorized) flips the gate.
    async with new_client() as session:
        launched = await session.call_tool("launch_implementation", {"project_id": seeded["project"].id})
    assert launched.is_error is False, _error_text(launched)
    assert _payload(launched)["already_launched"] is False

    # AFTER launch: get_implementation_prompt now proceeds — the downstream gate honors the
    # SAME flag the CLI door flipped.
    async with new_client() as session:
        ready = await session.call_tool("get_implementation_prompt", {"project_id": seeded["project"].id})
    assert ready.is_error is False, _error_text(ready)
    ready_payload = _payload(ready)
    assert ready_payload["status"] == "ready", "after launch_implementation the gate must clear"
    assert ready_payload["prompt"], "implementation prompt must be non-empty after launch"


# ---------------------------------------------------------------------------
# 3. An agent CANNOT bypass the gate — launch_implementation is registered (so a
#    human CAN call it) but EXCLUDED from the orchestrator auto-tool bundle (so a
#    spawned/staging agent has no schema for it and cannot self-unlock).
# ---------------------------------------------------------------------------


async def test_launch_implementation_excluded_from_orchestrator_auto_bundle():
    from giljo_mcp.prompts._canonical_tool_list import CANONICAL_ORCHESTRATOR_TOOLS

    assert "mcp__giljo_mcp__launch_implementation" not in CANONICAL_ORCHESTRATOR_TOOLS, (
        "SECURITY: launch_implementation must NOT be in the orchestrator auto-tool bundle — "
        "an orchestrator/staging agent could otherwise self-unlock implementation."
    )
    # Sibling lifecycle/gate tools share the exclusion (defensive: catches a future
    # accidental add of the whole lifecycle family to the boot bundle).
    assert "mcp__giljo_mcp__implement_project" not in CANONICAL_ORCHESTRATOR_TOOLS
    assert "mcp__giljo_mcp__stage_project" not in CANONICAL_ORCHESTRATOR_TOOLS


async def test_launch_implementation_is_registered_and_reachable(lifecycle_mcp_client):
    """It IS a real registered tool (the human door is reachable), just not auto-loaded."""
    new_client, _switch = lifecycle_mcp_client
    async with new_client() as session:
        tools = await session.list_tools()
    names = {t.name for t in tools.tools}
    assert "launch_implementation" in names, "the CLI door must be a registered, callable tool"


# ---------------------------------------------------------------------------
# 4. Tenant isolation — tenant B cannot launch tenant A's project.
# ---------------------------------------------------------------------------


async def test_launch_implementation_cross_tenant_blocked_flag_stays_unset(
    lifecycle_mcp_client, db_session, primary_tenant_key, secondary_tenant_key
):
    new_client, switch = lifecycle_mcp_client
    # Tenant A owns a staged-but-unlaunched project.
    switch.value = primary_tenant_key
    seeded = await _seed_product_project(
        db_session, primary_tenant_key, staging_status="staging_complete", launched=False
    )

    # Tenant B tries to launch tenant A's project.
    switch.value = secondary_tenant_key
    async with new_client() as session:
        result = await session.call_tool("launch_implementation", {"project_id": seeded["project"].id})

    assert result.is_error is True, "TENANT LEAK: tenant B must not launch tenant A's project"
    err = _error_text(result).lower()
    assert "not found" in err or "tenant" in err, f"expected a tenant-isolation block, got: {err!r}"

    # The SACRED flag must NOT have been set by the cross-tenant attempt.
    switch.value = primary_tenant_key
    row = (await db_session.execute(select(Project).where(Project.id == seeded["project"].id))).scalar_one()
    assert row.implementation_launched_at is None, "cross-tenant launch must NEVER stamp the flag"


# ---------------------------------------------------------------------------
# 5. BE-9499c goal-at-launch — an optional `mission` collapses "state your goal
#    and say go" into ONE call, writing through the SAME single writer
#    `update_project_mission` uses before the gate is stamped.
# ---------------------------------------------------------------------------


async def test_goal_at_launch_writes_mission_then_stamps_gate(lifecycle_mcp_client, db_session, primary_tenant_key):
    new_client, _switch = lifecycle_mcp_client
    seeded = await _seed_product_project(
        db_session, primary_tenant_key, staging_status="staging_complete", launched=False
    )

    async with new_client() as session:
        result = await session.call_tool(
            "launch_implementation",
            {"project_id": seeded["project"].id, "mission": "Ship the goal-at-launch feature end to end."},
        )

    assert result.is_error is False, _error_text(result)
    payload = _payload(result)
    assert payload["status"] == "launched"
    assert payload["already_launched"] is False

    row = (await db_session.execute(select(Project).where(Project.id == seeded["project"].id))).scalar_one()
    assert row.mission == "Ship the goal-at-launch feature end to end.", (
        "goal-at-launch must write the mission through the single-writer BEFORE stamping the gate"
    )
    assert row.implementation_launched_at is not None


async def test_launch_without_mission_leaves_existing_mission_untouched(
    lifecycle_mcp_client, db_session, primary_tenant_key
):
    """Omitting `mission` (the pre-existing call shape) must be byte-identical —
    no mission write, gate flips exactly as before this feature existed."""
    new_client, _switch = lifecycle_mcp_client
    seeded = await _seed_product_project(
        db_session, primary_tenant_key, staging_status="staging_complete", launched=False
    )
    original_mission = seeded["project"].mission

    async with new_client() as session:
        result = await session.call_tool("launch_implementation", {"project_id": seeded["project"].id})

    assert result.is_error is False, _error_text(result)
    row = (await db_session.execute(select(Project).where(Project.id == seeded["project"].id))).scalar_one()
    assert row.mission == original_mission, "no mission param -> mission must be left untouched"
    assert row.implementation_launched_at is not None
