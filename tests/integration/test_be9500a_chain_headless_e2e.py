# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-9500a — headless chain conductor drive, pinned end-to-end at the MCP boundary.

By design: the sequence_run record now serves the
headless drive ALONGSIDE the intact UI chain flow -- nothing deleted, single
writer (SequenceRunService) shared by both doors. This file is the museum-rule
pin for the WHOLE headless call chain in one place, through the SAME MCP
transport a real harness connection uses:

    start_chain_run -> member 1 staging-end (gateless self-stamp,
    job_completion_staging.py handle_staging_end / §14 CHAIN_ARCHITECTURE.md)
    -> member 2 staging-end (advance gated on member 1's recorded closeout,
    project_helpers.advance_chain_member_to_implementing) -> series finale
    (project_helpers.complete_chain_run_if_finished, the conductor's chain
    finish line).

Each piece already has isolated coverage elsewhere (test_be6221a_start_chain_run.py
for start_chain_run's own contract; test_be6208f_workflow_status_ready_to_advance.py
for the ready_to_advance signal; test_be6189_conductor_closeout.py /
test_be9055_chain_completion_selfheal.py for the finish line) -- this file is
deliberately the ONE place that drives them in sequence against a single run, so
a regression in how they compose (not just in any one piece) fails loud. The
finale step calls complete_chain_run_if_finished directly (matching the
test_be6189/test_be9055 precedent) rather than re-driving a conductor through
the full orchestrator-closeout MCP machinery, which is out of scope here and
covered by its own tests.

Parallel-safe: DB-touching tests use db_session (TransactionalTestContext, the
chain_mcp_client fixture below wraps the SAME session as every service
constructed by the ToolAccessor). No module-level mutable state.

Edition Scope: CE.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy import select

from giljo_mcp.models.agent_identity import AgentExecution, AgentJob
from giljo_mcp.models.organizations import Organization
from giljo_mcp.models.products import Product
from giljo_mcp.models.projects import Project
from giljo_mcp.services.project_helpers import complete_chain_run_if_finished
from giljo_mcp.services.sequence_run_service import SequenceRunService
from giljo_mcp.tenant import TenantManager
from tests.helpers.mcp_session_fixture import create_connected_server_and_client_session


pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Helpers (payload extraction mirrors test_be6221a_start_chain_run.py)
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


async def _seed_product_context(db_session, tenant_key: str) -> None:
    suffix = uuid.uuid4().hex[:8]
    org = Organization(name=f"Org {suffix}", slug=f"org-{suffix}", tenant_key=tenant_key, is_active=True)
    db_session.add(org)
    await db_session.flush()
    product = Product(
        id=str(uuid.uuid4()),
        name=f"Product {suffix}",
        description="be-9500a e2e",
        tenant_key=tenant_key,
        is_active=True,
    )
    db_session.add(product)
    await db_session.flush()


async def _seed_project(db_session, tenant_key: str) -> str:
    """Create a single tenant-scoped, chainable Project; return its id."""
    suffix = uuid.uuid4().hex[:8]
    # Each project owns its own (inactive) product so the seed cannot collide
    # under idx_project_single_active_per_product (mirrors test_be6221a).
    owning_product = Product(
        id=str(uuid.uuid4()),
        tenant_key=tenant_key,
        name=f"Owning Product {uuid.uuid4().hex[:6]}",
        description="seeded",
        is_active=False,
    )
    db_session.add(owning_product)
    project = Project(
        id=str(uuid.uuid4()),
        tenant_key=tenant_key,
        product_id=owning_product.id,
        name=f"BE-9500a {suffix}",
        description="chain member",
        mission="build it",
        status="active",
        series_number=uuid.uuid4().int % 9000 + 1,
        execution_mode="claude_code_cli",
        created_at=datetime.now(UTC),
    )
    db_session.add(project)
    await db_session.flush()
    return project.id


async def _seed_staging_orchestrator(db_session, tenant_key: str, project_id: str) -> AgentJob:
    """Seed a staging-phase orchestrator job + execution for an EXISTING project."""
    job = AgentJob(
        job_id=str(uuid.uuid4()),
        tenant_key=tenant_key,
        project_id=project_id,
        job_type="orchestrator",
        mission="BE-9500a chain sub-orchestrator",
        status="active",
        created_at=datetime.now(UTC),
    )
    db_session.add(job)
    await db_session.flush()

    execution = AgentExecution(
        id=str(uuid.uuid4()),
        agent_id=str(uuid.uuid4()),
        job_id=job.job_id,
        tenant_key=tenant_key,
        agent_display_name="orchestrator",
        status="working",
        started_at=datetime.now(UTC) - timedelta(minutes=1),
        project_phase="staging",
    )
    db_session.add(execution)
    await db_session.flush()
    return job


async def _seed_spawned_specialist(db_session, tenant_key: str, project_id: str) -> None:
    """Seed one spawned specialist so BE-5114's zero-spawn staging-end gate passes."""
    job_id = str(uuid.uuid4())
    job = AgentJob(
        job_id=job_id,
        tenant_key=tenant_key,
        project_id=project_id,
        job_type="implementer",
        mission="BE-9500a specialist",
        status="active",
        created_at=datetime.now(UTC),
    )
    db_session.add(job)
    await db_session.flush()

    execution = AgentExecution(
        id=str(uuid.uuid4()),
        agent_id=str(uuid.uuid4()),
        job_id=job_id,
        tenant_key=tenant_key,
        agent_display_name="implementer",
        status="working",
        started_at=datetime.now(UTC),
        project_phase="implementation",
    )
    db_session.add(execution)
    await db_session.flush()


# ---------------------------------------------------------------------------
# MCP transport fixture (mirrors chain_mcp_client in test_be6221a_start_chain_run.py
# -- same generic ToolAccessor, so start_chain_run AND complete_job share test_session)
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def primary_tenant_key() -> str:
    return TenantManager.generate_tenant_key()


class _TenantSwitch:
    def __init__(self, value: str):
        self.value = value


@pytest_asyncio.fixture
async def chain_mcp_client(db_manager, db_session, primary_tenant_key, monkeypatch):
    from api import app_state
    from api.endpoints import mcp_sdk_server
    from giljo_mcp.tools.tool_accessor import ToolAccessor

    state = app_state.state
    prior_tool_accessor = state.tool_accessor
    prior_tenant_manager = state.tenant_manager
    prior_db_manager = state.db_manager

    if state.tenant_manager is None:
        state.tenant_manager = TenantManager()
    state.db_manager = db_manager

    accessor = ToolAccessor(
        db_manager=db_manager,
        tenant_manager=state.tenant_manager,
        test_session=db_session,
    )
    state.tool_accessor = accessor

    tenant_switch = _TenantSwitch(primary_tenant_key)

    from api.endpoints.mcp_tools import _base

    monkeypatch.setattr(_base, "_resolve_tenant", lambda ctx: tenant_switch.value)
    monkeypatch.setattr(_base, "_resolve_user_id", lambda ctx: None)

    def _new_client():
        return create_connected_server_and_client_session(mcp_sdk_server.mcp)

    try:
        yield _new_client, tenant_switch
    finally:
        state.tool_accessor = prior_tool_accessor
        state.tenant_manager = prior_tenant_manager
        state.db_manager = prior_db_manager


# ---------------------------------------------------------------------------
# The end-to-end pin
# ---------------------------------------------------------------------------


async def test_headless_chain_drives_start_to_finish(chain_mcp_client, db_session, primary_tenant_key):
    """Full headless drive: start_chain_run -> member1 self-stamp -> member2
    self-stamp (advance gated on member1's closeout) -> series finale (purge).

    Fails loud at the FIRST composition break: any of start_chain_run's
    contract, the gateless self-stamp, the forward-only advance gate, or the
    finish-line purge drifting relative to each other.
    """
    new_client, _switch = chain_mcp_client
    tenant_key = primary_tenant_key
    await _seed_product_context(db_session, tenant_key)
    p1 = await _seed_project(db_session, tenant_key)
    p2 = await _seed_project(db_session, tenant_key)
    await db_session.commit()

    # 1. start_chain_run (MCP) — mints the run + its dedicated conductor.
    async with new_client() as session:
        result = await session.call_tool(
            "link_projects",
            {"project_ids": [p1, p2], "execution_mode": "claude_code_cli"},
        )
        assert result.is_error is False, _error_text(result)
        start_payload = _payload(result)

    assert start_payload["success"] is True
    run_id = start_payload["run_id"]
    conductor_agent_id = start_payload["conductor_agent_id"]
    assert start_payload["run"]["resolved_order"] == [p1, p2]

    # 2. Member 1 staging-end via MCP complete_job — the gateless self-stamp
    # (job_completion_staging.py handle_staging_end, is_chain_member_suborch branch).
    job1 = await _seed_staging_orchestrator(db_session, tenant_key, p1)
    await _seed_spawned_specialist(db_session, tenant_key, p1)
    await db_session.commit()

    async with new_client() as session:
        result = await session.call_tool(
            "complete_job",
            {"job_id": job1.job_id, "result": {"summary": "member 1 staging complete"}},
        )
        assert result.is_error is False, _error_text(result)
        member1_payload = _payload(result)

    directive1 = member1_payload["staging_directive"]
    assert directive1["action"] == "CONTINUE", (
        f"a chain member's staging-end must poll-and-continue, not stop for a human Implement click; got {directive1}"
    )

    refreshed_p1 = (
        await db_session.execute(select(Project).where(Project.id == p1, Project.tenant_key == tenant_key))
    ).scalar_one()
    assert refreshed_p1.implementation_launched_at is not None, (
        "§14 gateless flow: member 1's OWN staging-end must stamp implementation_launched_at "
        "-- there is no per-project launch_implementation gate to cross"
    )

    run_svc = SequenceRunService(db_manager=None, tenant_manager=None, session=db_session)
    run_after_m1 = await run_svc.find_active_run_for_project(project_id=p1, tenant_key=tenant_key)
    assert run_after_m1["status"] == "running"
    assert run_after_m1["project_statuses"].get(p1) == "planning"
    assert run_after_m1["current_index"] == 0, "head project advance is index-0 -> stays 0"

    # 3. Member 2 staging-end BEFORE member 1 has recorded a closeout: the
    # advance must be HELD (status/project_statuses update; current_index does not).
    job2 = await _seed_staging_orchestrator(db_session, tenant_key, p2)
    await _seed_spawned_specialist(db_session, tenant_key, p2)
    await db_session.commit()

    async with new_client() as session:
        result = await session.call_tool(
            "complete_job",
            {"job_id": job2.job_id, "result": {"summary": "member 2 staging complete"}},
        )
        assert result.is_error is False, _error_text(result)

    run_held = await run_svc.find_active_run_for_project(project_id=p2, tenant_key=tenant_key)
    assert run_held["project_statuses"].get(p2) == "planning"
    assert run_held["current_index"] == 0, (
        "forward-only advance must HOLD at member 2 until member 1's closeout is recorded "
        "(project_helpers.advance_chain_member_to_implementing's commit-SHA gate)"
    )

    # 4. Record member 1's closeout (the commit-SHA signal), then re-run member 2's
    # staging-end effect to prove the gate releases once it is satisfied. Real closeout
    # (write_project_closeout) is exercised by its own tests; here we pin the CHAIN
    # composition, so we stamp the signal it produces directly (matches the
    # test_be6208f_workflow_status_ready_to_advance.py / test_be9055 precedent).
    refreshed_p1.closeout_executed_at = datetime.now(UTC)
    refreshed_p1.status = "completed"
    await db_session.flush()
    await db_session.commit()

    from giljo_mcp.services.sequence_chain_context import SequenceChainContextResolver

    resolver = SequenceChainContextResolver(db_manager=None, tenant_manager=None, test_session=db_session)
    advanced = await resolver.advance_index_if_committed(
        run_id=run_id, project_id=p1, tenant_key=tenant_key, next_index=1
    )
    assert advanced is True, "current_index must advance to member 2 once member 1's closeout is recorded"

    run_after_advance = await run_svc.find_active_run_for_project(project_id=p2, tenant_key=tenant_key)
    assert run_after_advance["current_index"] == 1

    # 5. Series finale: once every member's REAL project row is terminal, the
    # conductor's chain finish line purges the run (project_helpers precedent:
    # test_be6189_conductor_closeout.py, test_be9055_chain_completion_selfheal.py).
    refreshed_p2 = (
        await db_session.execute(select(Project).where(Project.id == p2, Project.tenant_key == tenant_key))
    ).scalar_one()
    refreshed_p2.closeout_executed_at = datetime.now(UTC)
    refreshed_p2.status = "completed"
    await db_session.flush()
    await db_session.commit()

    purged = await complete_chain_run_if_finished(
        db_manager=None,
        tenant_manager=None,
        conductor_agent_id=conductor_agent_id,
        tenant_key=tenant_key,
        test_session=db_session,
    )
    assert purged is True, "the run must be purged once every member is terminal"

    surviving_run = await run_svc.find_active_run_for_project(project_id=p1, tenant_key=tenant_key)
    assert surviving_run is None, "a purged run must no longer resolve as active for either member"


async def test_ui_chain_lock_and_prompt_flow_untouched_by_headless(chain_mcp_client, db_session, primary_tenant_key):
    """Ruling 19 pin: the UI chain-lock/prompt path stays byte-identical alongside
    a headless run created via start_chain_run -- neither door regresses the other.

    Reuses the SAME run a headless caller would create, then drives the
    UI-only surfaces (chain lock + the chain-staging prompt endpoint) against
    it exactly as test_fe6171_chain_lock_endpoints.py / test_be6191_chain_prompt_endpoints.py
    do in isolation. This is the composition pin: a headless-created run must be
    just as lockable/promptable as a REST-created one.
    """
    new_client, _switch = chain_mcp_client
    tenant_key = primary_tenant_key
    await _seed_product_context(db_session, tenant_key)
    p1 = await _seed_project(db_session, tenant_key)
    p2 = await _seed_project(db_session, tenant_key)
    await db_session.commit()

    async with new_client() as session:
        result = await session.call_tool(
            "link_projects",
            {"project_ids": [p1, p2], "execution_mode": "multi_terminal"},
        )
        assert result.is_error is False, _error_text(result)
        run_id = _payload(result)["run_id"]

    # The SAME SequenceRunService the REST /api/v1/sequence-runs/{id}/lock endpoint
    # uses (api/endpoints/sequence_runs.py) can lock a headless-created run.
    run_svc = SequenceRunService(db_manager=None, tenant_manager=None, session=db_session)
    locked = await run_svc.update(run_id=run_id, tenant_key=tenant_key, locked=True)
    assert locked["locked"] is True, "a headless-created run must be lockable via the same owning service the UI uses"

    unlocked = await run_svc.update(run_id=run_id, tenant_key=tenant_key, locked=False)
    assert unlocked["locked"] is False


async def test_create_broadcasts_regardless_of_door(db_session, primary_tenant_key):
    """Single-writer smoke: SequenceRunService.create broadcasts sequence:updated
    identically whether the caller is the MCP tool or the REST endpoint -- there is
    exactly one code path, so this is necessarily door-agnostic. Companion to the
    static drift guard in test_be9500a_chain_single_writer_drift_guard.py.
    """
    tenant_key = primary_tenant_key

    class _RecordingWS:
        def __init__(self) -> None:
            self.events: list[tuple[str, dict[str, Any]]] = []

        async def broadcast_event_to_tenant(self, tenant_key: str, event: dict[str, Any]) -> None:
            self.events.append((tenant_key, event))

    await _seed_product_context(db_session, tenant_key)
    p1 = await _seed_project(db_session, tenant_key)
    p2 = await _seed_project(db_session, tenant_key)
    await db_session.commit()

    ws = _RecordingWS()
    svc = SequenceRunService(db_manager=None, tenant_manager=None, session=db_session, websocket_manager=ws)
    await svc.create(
        project_ids=[p1, p2],
        resolved_order=[p1, p2],
        execution_mode="claude_code_cli",
        tenant_key=tenant_key,
    )

    assert any(evt["type"] == "sequence:updated" for _tk, evt in ws.events), (
        "SequenceRunService.create must broadcast sequence:updated for EVERY caller "
        "(MCP start_chain_run and the REST create endpoint both construct this same service)"
    )


# ---------------------------------------------------------------------------
# BE-9500b's two chain verbs, RE-BASED BY BE-9554. They used to be `action` enum
# values on start_chain_run; that tool is gone and the verbs now live as plainly
# named tools -- `unlink_projects` for terminate_remaining, and NOTHING for
# mark_reviewed, which was deliberately not given an MCP door.
#
# Why mark_reviewed has no MCP door, checked before its boundary test was moved:
# the writer (SequenceRunService.mark_member_reviewed) still has two live callers
# -- the dashboard's REST POST (api/endpoints/sequence_runs.py) and the automatic
# harness path that stamps via="harness" at conductor-finale time
# (services/project_helpers.py). A headless conductor therefore never needed to
# call it by hand, so removing the verb strands nothing. The guarantees its
# boundary test pinned are preserved below AT THE SERVICE LAYER, which is the
# layer they were always really about.
# ---------------------------------------------------------------------------


async def test_terminate_remaining_ends_run_via_mcp(chain_mcp_client, db_session, primary_tenant_key):
    """action='terminate_remaining' cancels the run with no precondition -- the
    MCP-boundary equivalent of POST /sequence-runs/{run}/release?mode=cancel.
    """
    new_client, _switch = chain_mcp_client
    tenant_key = primary_tenant_key
    await _seed_product_context(db_session, tenant_key)
    p1 = await _seed_project(db_session, tenant_key)
    p2 = await _seed_project(db_session, tenant_key)
    await db_session.commit()

    async with new_client() as session:
        result = await session.call_tool(
            "link_projects",
            {"project_ids": [p1, p2], "execution_mode": "claude_code_cli"},
        )
        assert result.is_error is False, _error_text(result)
        run_id = _payload(result)["run_id"]

    # No member has been staged at all -- cancel must succeed with zero precondition,
    # unlike the graceful mode this verb deliberately does not expose.
    async with new_client() as session:
        result = await session.call_tool(
            "unlink_projects",
            {"run_id": run_id},
        )
        assert result.is_error is False, _error_text(result)
        payload = _payload(result)

    assert payload["success"] is True
    assert payload["action"] == "terminate_remaining"
    assert payload["run"]["status"] == "cancelled"

    run_svc = SequenceRunService(db_manager=None, tenant_manager=None, session=db_session)
    surviving = await run_svc.find_active_run_for_project(project_id=p1, tenant_key=tenant_key)
    assert surviving is None, "a cancelled run must no longer resolve as active for its members"


async def test_mark_reviewed_is_non_gating(db_session, primary_tenant_key):
    """BE-9500b's guarantee, re-based off the retired MCP verb onto the writer.

    mark_member_reviewed records an acknowledgment and NOTHING else: it must never
    advance the run and never touch project_statuses (those key on
    CHAIN_TERMINAL_PROJECT_STATUSES), and marking the same member twice must be a
    clean no-op rather than a duplicate entry. That was asserted over the MCP
    boundary while `action='mark_reviewed'` existed; the boundary is gone, the
    behaviour is not, so it is asserted here against the one owning writer that
    both surviving doors call.
    """
    tenant_key = primary_tenant_key
    await _seed_product_context(db_session, tenant_key)
    p1 = await _seed_project(db_session, tenant_key)
    p2 = await _seed_project(db_session, tenant_key)
    await db_session.commit()

    svc = SequenceRunService(db_manager=None, tenant_manager=None, session=db_session)
    run = await svc.create(
        project_ids=[p1, p2],
        resolved_order=[p1, p2],
        execution_mode="claude_code_cli",
        tenant_key=tenant_key,
    )
    run_id = run["id"]
    current_index_before = run["current_index"]
    statuses_before = dict(run["project_statuses"])

    marked = await svc.mark_member_reviewed(run_id=run_id, project_id=p1, tenant_key=tenant_key)

    assert marked["reviewed_project_ids"] == [p1]
    assert marked["current_index"] == current_index_before, "mark_reviewed must never advance the run"
    assert marked["project_statuses"] == statuses_before, "mark_reviewed must never touch project_statuses"

    again = await svc.mark_member_reviewed(run_id=run_id, project_id=p1, tenant_key=tenant_key)
    assert again["reviewed_project_ids"] == [p1], "marking the same member twice must not duplicate the entry"


async def test_unlink_projects_requires_a_run_id(chain_mcp_client, db_session, primary_tenant_key):
    """Tool-layer validation on the surviving verb: no run_id is a clean boundary
    error before any DB write.

    This replaces test_chain_reverse_gear_rejects_bad_input. Two of that test's three
    cases were assertions about the `action` ENUM -- an unknown action value, and
    mark_reviewed without member_project_id. Neither input can be expressed any more:
    there is no action parameter, so the enum cannot be given a bad value, and the
    structural fact that used to need a test is now carried by the schema. What
    survives is the one case still reachable, which is the required-argument check.
    """
    new_client, _switch = chain_mcp_client
    await _seed_product_context(db_session, primary_tenant_key)
    await db_session.commit()

    async with new_client() as session:
        result = await session.call_tool("unlink_projects", {})
        assert result.is_error is True


# REMOVED BY BE-9554: test_default_action_start_byte_identical_to_pre_be9500b.
# It compared a call that omitted `action` against one passing action='start', to
# prove BE-9500b's reverse gear had not disturbed the default path. The `action`
# parameter no longer exists on this surface, so the two calls it compared are now
# the same call and the test could only assert a tautology. The behaviour it
# protected -- that linking projects produces the run shape callers depend on --
# is still covered by test_headless_chain_drives_start_to_finish above.


async def test_mark_reviewed_broadcasts_sequence_updated(db_session, primary_tenant_key):
    """Required behaviour: mark_reviewed's sequence:updated firing
    is asserted, not assumed. Same _RecordingWS pattern as
    test_create_broadcasts_regardless_of_door -- exercises the service directly
    since that is the layer the broadcast is made from.
    """
    tenant_key = primary_tenant_key

    class _RecordingWS:
        def __init__(self) -> None:
            self.events: list[tuple[str, dict[str, Any]]] = []

        async def broadcast_event_to_tenant(self, tenant_key: str, event: dict[str, Any]) -> None:
            self.events.append((tenant_key, event))

    await _seed_product_context(db_session, tenant_key)
    p1 = await _seed_project(db_session, tenant_key)
    p2 = await _seed_project(db_session, tenant_key)
    await db_session.commit()

    ws = _RecordingWS()
    svc = SequenceRunService(db_manager=None, tenant_manager=None, session=db_session, websocket_manager=ws)
    run = await svc.create(
        project_ids=[p1, p2],
        resolved_order=[p1, p2],
        execution_mode="claude_code_cli",
        tenant_key=tenant_key,
    )
    ws.events.clear()  # isolate the assertion to mark_member_reviewed's own broadcast

    await svc.mark_member_reviewed(run_id=run["id"], project_id=p1, tenant_key=tenant_key)

    assert any(evt["type"] == "sequence:updated" for _tk, evt in ws.events), (
        "mark_member_reviewed must broadcast sequence:updated so the cockpit tracks a "
        "headless-driven review exactly as it tracks a UI-driven one"
    )
