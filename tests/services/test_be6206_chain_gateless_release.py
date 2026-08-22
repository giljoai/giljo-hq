# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-6206 (§14, CHAIN_ARCHITECTURE.md) — the live chain deadlock fix: gateless release.

THE LIVE BUG (§14): a chain sub-orchestrator was launched with a thin prompt telling it
to call get_job_mission, but get_agent_mission ran the implementation gate FIRST and
returned a BLOCKED 'wait for the conductor' response — so the sub-orch could never read
its mission, while the conductor waited for a staging_complete the blocked sub-orch could
never produce. Two agents waited on each other forever.

THE FIX (matches §9/§14): a released chain sub-orchestrator is NEVER gated. The
conductor's spawn IS the start; the sub-orch gets its COMBINED protocol immediately and
runs free. The staging→implementation transition (impl_launched_at + the run's
"implementing" status / current_index advance) is recorded server-side at the sub-orch's
OWN staging-end, replacing the removed conductor launch_implementation gate-cross.

Pinned here:
  1. CORE (DB, real get_agent_mission): a chain-member orchestrator with
     implementation_launched_at NULL is NOT blocked — it gets its combined
     CH_SUB_ORCHESTRATOR protocol and flips waiting→working. RED before the fix.
  2. SOLO control (DB): a solo orchestrator (no active run) with NULL impl_launched_at
     still gets the byte-identical human-gate BLOCKED response (Deletion Test on the gate).
  3. STAGING-END stamp (DB, real complete_job): a chain member's staging-end is classified
     as staging-end (NOT closeout) AND stamps implementation_launched_at + marks the run
     member "planning" (FE-9493: promoted to "implementing" separately once its first
     spawned worker starts) so subsequent reads see "running", not "still staging".
  4. SOLO control (DB, real complete_job): a solo staging-end does NOT stamp
     implementation_launched_at (it waits for the human Implement press) — byte-identical.

Parallel-safe: DB-touching tests use db_session (TransactionalTestContext). No module-level
mutable state. No ordering dependencies. Edition Scope: CE.
"""

from __future__ import annotations

import random
import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.models import Product, Project
from giljo_mcp.models.agent_identity import AgentExecution, AgentJob
from giljo_mcp.services.job_completion_service import JobCompletionService
from giljo_mcp.services.mission_service import MissionService
from giljo_mcp.services.sequence_run_service import SequenceRunService
from giljo_mcp.tenant import TenantManager


pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Seeding helpers
# ---------------------------------------------------------------------------


async def _seed_project(session: AsyncSession, tenant_key: str, *, staging_status: str | None = None) -> str:
    product = Product(
        id=str(uuid.uuid4()),
        name=f"BE-6206 Product {uuid.uuid4().hex[:6]}",
        description="Chain product.",
        tenant_key=tenant_key,
        is_active=False,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    session.add(product)
    await session.flush()
    project = Project(
        id=str(uuid.uuid4()),
        name=f"BE-6206 {uuid.uuid4().hex[:6]}",
        description="Chain member.",
        mission="Be a chain member.",
        status="active",
        tenant_key=tenant_key,
        product_id=product.id,
        series_number=random.randint(1, 9000),
        execution_mode="claude_code_cli",
        staging_status=staging_status,
        implementation_launched_at=None,
        created_at=datetime.now(UTC),
    )
    session.add(project)
    session.info["tenant_key"] = tenant_key
    await session.flush()
    return project.id


async def _seed_orchestrator_job(
    session: AsyncSession, tenant_key: str, project_id: str, *, project_phase: str = "staging"
) -> AgentJob:
    """Hand-mint a project-bound orchestrator job + execution (implementation NOT launched)."""
    job_id = str(uuid.uuid4())
    job = AgentJob(
        job_id=job_id,
        tenant_key=tenant_key,
        project_id=project_id,
        mission="orchestrate this project",
        job_type="orchestrator",
        status="active",
        job_metadata={},
    )
    session.add(job)
    session.add(
        AgentExecution(
            agent_id=str(uuid.uuid4()),
            job_id=job_id,
            tenant_key=tenant_key,
            agent_display_name="orchestrator",
            agent_name="SubOrch",
            status="waiting",
            health_status="unknown",
            project_phase=project_phase,
            started_at=datetime.now(UTC),
        )
    )
    session.info["tenant_key"] = tenant_key
    await session.flush()
    return job


async def _seed_worker(session: AsyncSession, tenant_key: str, project_id: str) -> None:
    """Hand-mint one non-orchestrator agent so the staging-end no-agents guard passes."""
    job_id = str(uuid.uuid4())
    session.add(
        AgentJob(
            job_id=job_id,
            tenant_key=tenant_key,
            project_id=project_id,
            mission="implement the thing",
            job_type="implementer",
            status="active",
            job_metadata={},
        )
    )
    session.add(
        AgentExecution(
            agent_id=str(uuid.uuid4()),
            job_id=job_id,
            tenant_key=tenant_key,
            agent_display_name="implementer",
            agent_name="implementer",
            status="working",
            health_status="unknown",
            project_phase="implementation",
        )
    )
    await session.flush()


def _run_svc(session: AsyncSession) -> SequenceRunService:
    return SequenceRunService(db_manager=None, tenant_manager=TenantManager(), session=session)


def _mission_svc(session: AsyncSession, db_manager) -> MissionService:
    return MissionService(db_manager=db_manager, tenant_manager=TenantManager(), test_session=session)


def _completion_svc(session: AsyncSession) -> JobCompletionService:
    return JobCompletionService(db_manager=None, tenant_manager=TenantManager(), test_session=session)


async def _reload_project(session: AsyncSession, project_id: str, tenant_key: str) -> Project:
    return (
        await session.execute(select(Project).where(Project.id == project_id, Project.tenant_key == tenant_key))
    ).scalar_one()


async def _reload_execution(session: AsyncSession, job_id: str, tenant_key: str) -> AgentExecution:
    return (
        await session.execute(
            select(AgentExecution).where(AgentExecution.job_id == job_id, AgentExecution.tenant_key == tenant_key)
        )
    ).scalar_one()


# ===========================================================================
# 1. CORE — a released chain member gets its combined protocol, NOT a block
# ===========================================================================


async def test_chain_member_get_agent_mission_returns_combined_protocol(db_session: AsyncSession, db_manager) -> None:
    """§14: a chain sub-orchestrator with implementation_launched_at NULL is NOT blocked.
    get_agent_mission returns its combined CH_SUB_ORCHESTRATOR protocol and flips it
    waiting→working. RED before the §14 fix (returned a BLOCKED 'wait for conductor')."""
    tenant = TenantManager.generate_tenant_key()
    p1 = await _seed_project(db_session, tenant)
    p2 = await _seed_project(db_session, tenant)
    # Active run mints the conductor; p1's hand-minted orchestrator (different agent_id)
    # is therefore a sub_orchestrator.
    await _run_svc(db_session).create(
        project_ids=[p1, p2], resolved_order=[p1, p2], execution_mode="claude_code_cli", tenant_key=tenant
    )
    job = await _seed_orchestrator_job(db_session, tenant, p1, project_phase="implementation")

    response = await _mission_svc(db_session, db_manager).get_agent_mission(job.job_id, tenant)

    assert not response.blocked, "§14: a released chain member must NOT be blocked"
    assert response.full_protocol and "CH_SUB_ORCHESTRATOR" in response.full_protocol, (
        "the released sub-orch must receive its combined CH_SUB_ORCHESTRATOR protocol immediately"
    )
    assert response.status == "working", "the first get_job_mission must flip waiting→working (no orphaned state)"

    refreshed = await _reload_execution(db_session, job.job_id, tenant)
    assert refreshed.status == "working", "the execution row must persist as working"


# ===========================================================================
# 1b. BE-9069 (Defect A) — enrollment must NOT un-gate a solo member parked at
#     the human Implement gate; and a genuinely released member still crosses.
# ===========================================================================


async def test_be9069_enrolled_member_awaiting_solo_implement_stays_blocked(
    db_session: AsyncSession, db_manager
) -> None:
    """BE-9069 (Defect A): a SOLO project parked at the human Implement gate
    (staging_status='staging_complete', implementation_launched_at NULL) that gets enrolled
    into a bare-'pending' chain run must STAY blocked. Mere membership in a freshly minted
    run (zero conductor activity, no human GO) is NOT a conductor release, so its
    orchestrator's get_agent_mission keeps the solo human-gate BLOCKED response (BE-6115a:
    a spawned/staging agent cannot self-unlock implementation)."""
    tenant = TenantManager.generate_tenant_key()
    # Both members sit at the solo Implement gate (staged, launch NULL).
    p1 = await _seed_project(db_session, tenant, staging_status="staging_complete")
    p2 = await _seed_project(db_session, tenant, staging_status="staging_complete")
    # Bare 'pending' run (create()'s default status) — no advance, no GO.
    await _run_svc(db_session).create(
        project_ids=[p1, p2], resolved_order=[p1, p2], execution_mode="claude_code_cli", tenant_key=tenant
    )
    job = await _seed_orchestrator_job(db_session, tenant, p1, project_phase="implementation")

    response = await _mission_svc(db_session, db_manager).get_agent_mission(job.job_id, tenant)

    assert response.blocked is True, "enrollment must NOT un-gate a member parked at the solo Implement gate"
    assert response.error == "BLOCKED: Implementation phase not launched", (
        "it must keep the solo human-gate BLOCKED response, not the chain exemption"
    )
    refreshed = await _reload_execution(db_session, job.job_id, tenant)
    assert refreshed.status == "waiting", "the still-blocked orchestrator must NOT flip to working"


async def test_be9069_released_member_mid_staging_still_gets_mission(db_session: AsyncSession, db_manager) -> None:
    """BE-9069 two-sided (happy path): a genuinely conductor-released member is exempted
    DURING its own staging — staging_status='staged', before its staging-end stamps
    launch + 'staging_complete' together. The narrowed predicate must still let it cross:
    the §9/§14 gateless release holds. (The pre-fix control is test 1, staging_status NULL.)"""
    tenant = TenantManager.generate_tenant_key()
    p1 = await _seed_project(db_session, tenant, staging_status="staged")
    p2 = await _seed_project(db_session, tenant, staging_status="staged")
    await _run_svc(db_session).create(
        project_ids=[p1, p2], resolved_order=[p1, p2], execution_mode="claude_code_cli", tenant_key=tenant
    )
    job = await _seed_orchestrator_job(db_session, tenant, p1, project_phase="implementation")

    response = await _mission_svc(db_session, db_manager).get_agent_mission(job.job_id, tenant)

    assert not response.blocked, "a released chain member still in staging must NOT be blocked"
    assert response.full_protocol and "CH_SUB_ORCHESTRATOR" in response.full_protocol, (
        "it must receive its combined CH_SUB_ORCHESTRATOR protocol"
    )
    assert response.status == "working", "the first get_job_mission must flip waiting→working"


# ===========================================================================
# 2. SOLO control — a solo orchestrator stays human-gate blocked (byte-identical)
# ===========================================================================


async def test_solo_orchestrator_still_human_gate_blocked(db_session: AsyncSession, db_manager) -> None:
    """A solo project (NO active run) with NULL impl_launched_at keeps the byte-identical
    human-gate BLOCKED response — the §14 change is strictly behind the chain predicate."""
    tenant = TenantManager.generate_tenant_key()
    p1 = await _seed_project(db_session, tenant)  # no run -> solo
    job = await _seed_orchestrator_job(db_session, tenant, p1, project_phase="implementation")

    response = await _mission_svc(db_session, db_manager).get_agent_mission(job.job_id, tenant)

    assert response.blocked is True, "a solo not-yet-launched orchestrator must stay blocked"
    # BE-9012d: softened "into the terminal" to a harness-neutral "agent session
    # (terminal, desktop, or web tab)" -- connectors/Desktop/web aren't terminals.
    assert response.user_instruction == (
        "Staging is complete but implementation has not been launched. "
        "Return to the dashboard and click Implement, then start (or paste) your "
        "orchestrator prompt in your agent session (terminal, desktop, or web tab)."
    ), "the SOLO human-gate message must remain byte-identical"

    refreshed = await _reload_execution(db_session, job.job_id, tenant)
    assert refreshed.status == "waiting", "a blocked solo orchestrator must NOT flip to working"


# ===========================================================================
# 3. STAGING-END — chain member: classified staging-end, stamps + marks implementing
# ===========================================================================


async def test_chain_member_staging_end_stamps_and_advances(db_session: AsyncSession) -> None:
    """§14 follow-up: a chain member's staging-end complete_job is classified as
    staging-end (NOT closeout) AND stamps implementation_launched_at + marks the run
    member 'planning' — the gateless replacement for the launch_implementation
    advance, so the conductor's running-vs-done detection still works.

    FE-9493: this used to assert "implementing" — the value has since split into
    "planning" (the sub-orch entering the project, written here) and "implementing"
    (promoted separately once the member's first spawned worker actually starts,
    in mission_service.get_agent_mission's atomic-start). Both still count as
    "implementation has begun" for job_completion_staging._RUN_IMPL_STARTED_STATUSES."""
    tenant = TenantManager.generate_tenant_key()
    p1 = await _seed_project(db_session, tenant, staging_status="staging")
    p2 = await _seed_project(db_session, tenant, staging_status="staging")
    await _run_svc(db_session).create(
        project_ids=[p1, p2], resolved_order=[p1, p2], execution_mode="claude_code_cli", tenant_key=tenant
    )
    job = await _seed_orchestrator_job(db_session, tenant, p1, project_phase="staging")
    await _seed_worker(db_session, tenant, p1)  # satisfies STAGING_END_NO_AGENTS guard

    result = await _completion_svc(db_session).complete_job(
        job_id=job.job_id, result={"summary": "staging done"}, tenant_key=tenant
    )

    # (a) classified as staging-end (NOT misdetected as the implementation closeout).
    assert result.phase == "staging_end", "a chain member's staging-end must classify as staging_end"

    # (b) implementation_launched_at is now stamped (was NULL) — the running signal.
    reloaded = await _reload_project(db_session, p1, tenant)
    assert reloaded.implementation_launched_at is not None, (
        "the gateless staging-end must stamp implementation_launched_at (replacing the launch gate-cross)"
    )
    assert reloaded.staging_status == "staging_complete", "staging-end still flips staging_status"

    # (c) the run member is marked "planning" so the conductor sees it running, not done
    # (FE-9493: promoted to "implementing" separately once a worker actually starts).
    run = await _run_svc(db_session).find_active_run_for_project(project_id=p1, tenant_key=tenant)
    assert run is not None
    assert run["project_statuses"].get(p1) == "planning", "the staging-end advance must mark the member planning"


# ===========================================================================
# 4. SOLO control — a solo staging-end does NOT stamp implementation_launched_at
# ===========================================================================


async def test_solo_staging_end_does_not_stamp(db_session: AsyncSession) -> None:
    """A SOLO project (no active run) staging-end must NOT stamp implementation_launched_at
    — it still waits for the human Implement press (byte-identical solo behaviour)."""
    tenant = TenantManager.generate_tenant_key()
    p_solo = await _seed_project(db_session, tenant, staging_status="staging")  # no run
    job = await _seed_orchestrator_job(db_session, tenant, p_solo, project_phase="staging")
    await _seed_worker(db_session, tenant, p_solo)

    result = await _completion_svc(db_session).complete_job(
        job_id=job.job_id, result={"summary": "staging done"}, tenant_key=tenant
    )

    assert result.phase == "staging_end", "a solo staging-end is still a staging-end"
    reloaded = await _reload_project(db_session, p_solo, tenant)
    assert reloaded.implementation_launched_at is None, (
        "a solo staging-end must NOT stamp implementation_launched_at (waits for the human Implement press)"
    )
    assert reloaded.staging_status == "staging_complete", "solo staging-end still flips staging_status"


# ===========================================================================
# 5. BE-9111 — the §14 direct-stamp path must BROADCAST project:implementation_launched
#    (source="mcp") for a chain member, NOT for solo, and a broadcast failure must
#    never fail the staging-end complete_job. (The stamp already worked — test 3 —
#    but the retired conductor launch path's broadcast was never restored, so
#    live-follow never carried a viewer to the jobs pane on a chain member's entry.)
# ===========================================================================


class _RecordingWS:
    """Minimal ``websocket_manager`` double: records ``broadcast_to_tenant`` calls and
    can be armed to raise on a chosen event (to prove a broadcast failure never fails
    the staging-end write). Keyword-only signature matches the production callers."""

    def __init__(self, *, raise_on_event: str | None = None) -> None:
        self.calls: list[dict[str, Any]] = []
        self._raise_on_event = raise_on_event

    async def broadcast_to_tenant(self, *, tenant_key: str, event_type: str, data: dict) -> None:
        self.calls.append({"tenant_key": tenant_key, "event_type": event_type, "data": data})
        if self._raise_on_event is not None and event_type == self._raise_on_event:
            raise RuntimeError(f"simulated WS failure for {event_type}")

    def events(self, event_type: str) -> list[dict]:
        return [c for c in self.calls if c["event_type"] == event_type]


def _completion_svc_ws(session: AsyncSession, ws: Any) -> JobCompletionService:
    return JobCompletionService(
        db_manager=None, tenant_manager=TenantManager(), test_session=session, websocket_manager=ws
    )


async def test_be9111_chain_member_staging_end_broadcasts_implementation_launched(db_session: AsyncSession) -> None:
    """BE-9111: a chain member's gateless staging-end must broadcast
    ``project:implementation_launched`` with ``source="mcp"`` and the launch payload
    shape (project_id + implementation_launched_at). RED before the fix — the §14
    direct-stamp path stamped the flag but emitted nothing, so a viewer was never
    carried to the jobs pane."""
    tenant = TenantManager.generate_tenant_key()
    p1 = await _seed_project(db_session, tenant, staging_status="staging")
    p2 = await _seed_project(db_session, tenant, staging_status="staging")
    await _run_svc(db_session).create(
        project_ids=[p1, p2], resolved_order=[p1, p2], execution_mode="claude_code_cli", tenant_key=tenant
    )
    job = await _seed_orchestrator_job(db_session, tenant, p1, project_phase="staging")
    await _seed_worker(db_session, tenant, p1)
    ws = _RecordingWS()

    result = await _completion_svc_ws(db_session, ws).complete_job(
        job_id=job.job_id, result={"summary": "staging done"}, tenant_key=tenant
    )

    assert result.phase == "staging_end"
    launched = ws.events("project:implementation_launched")
    assert len(launched) == 1, "the chain-member staging-end must broadcast implementation_launched exactly once"
    payload = launched[0]["data"]
    assert payload["source"] == "mcp", "the broadcast must carry source='mcp' so live-follow FOLLOWS the drive"
    assert payload["project_id"] == p1
    assert payload["implementation_launched_at"] is not None, "payload must carry the stamp for hydration"
    assert launched[0]["tenant_key"] == tenant, "tenant-scoped fan-out (ADR-009), never per-user"


async def test_be9111_solo_staging_end_does_not_broadcast_implementation_launched(db_session: AsyncSession) -> None:
    """BE-9111 solo control: a SOLO staging-end (no active run) must NOT broadcast
    ``project:implementation_launched`` — solo still waits for the human Implement press
    (that event is emitted by launch_implementation on the click, not here)."""
    tenant = TenantManager.generate_tenant_key()
    p_solo = await _seed_project(db_session, tenant, staging_status="staging")
    job = await _seed_orchestrator_job(db_session, tenant, p_solo, project_phase="staging")
    await _seed_worker(db_session, tenant, p_solo)
    ws = _RecordingWS()

    result = await _completion_svc_ws(db_session, ws).complete_job(
        job_id=job.job_id, result={"summary": "staging done"}, tenant_key=tenant
    )

    assert result.phase == "staging_end"
    assert ws.events("project:implementation_launched") == [], (
        "a solo staging-end must NOT broadcast implementation_launched (waits for the human click)"
    )


async def test_be9111_broadcast_failure_does_not_fail_complete_job(db_session: AsyncSession) -> None:
    """BE-9111 resilience: if the implementation_launched WS broadcast raises, the
    chain-member staging-end complete_job must still succeed and the stamp/advance must
    still persist — the broadcast is best-effort (matching mark_staging_complete)."""
    tenant = TenantManager.generate_tenant_key()
    p1 = await _seed_project(db_session, tenant, staging_status="staging")
    p2 = await _seed_project(db_session, tenant, staging_status="staging")
    await _run_svc(db_session).create(
        project_ids=[p1, p2], resolved_order=[p1, p2], execution_mode="claude_code_cli", tenant_key=tenant
    )
    job = await _seed_orchestrator_job(db_session, tenant, p1, project_phase="staging")
    await _seed_worker(db_session, tenant, p1)
    ws = _RecordingWS(raise_on_event="project:implementation_launched")

    result = await _completion_svc_ws(db_session, ws).complete_job(
        job_id=job.job_id, result={"summary": "staging done"}, tenant_key=tenant
    )

    assert result.phase == "staging_end", "a failed broadcast must NOT fail the staging-end complete_job"
    reloaded = await _reload_project(db_session, p1, tenant)
    assert reloaded.implementation_launched_at is not None, "the stamp must persist despite the broadcast failure"
    assert reloaded.staging_status == "staging_complete", "staging_status must still flip despite the broadcast failure"
