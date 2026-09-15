# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


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




async def test_chain_member_get_agent_mission_returns_combined_protocol(db_session: AsyncSession, db_manager) -> None:
    tenant = TenantManager.generate_tenant_key()
    p1 = await _seed_project(db_session, tenant)
    p2 = await _seed_project(db_session, tenant)
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




async def test_be9069_enrolled_member_awaiting_solo_implement_stays_blocked(
    db_session: AsyncSession, db_manager
) -> None:
    tenant = TenantManager.generate_tenant_key()
    p1 = await _seed_project(db_session, tenant, staging_status="staging_complete")
    p2 = await _seed_project(db_session, tenant, staging_status="staging_complete")
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




async def test_solo_orchestrator_still_human_gate_blocked(db_session: AsyncSession, db_manager) -> None:
    tenant = TenantManager.generate_tenant_key()
    p1 = await _seed_project(db_session, tenant)
    job = await _seed_orchestrator_job(db_session, tenant, p1, project_phase="implementation")

    response = await _mission_svc(db_session, db_manager).get_agent_mission(job.job_id, tenant)

    assert response.blocked is True, "a solo not-yet-launched orchestrator must stay blocked"
    assert response.user_instruction == (
        "Staging is complete but implementation has not been launched. "
        "Return to the dashboard and click Implement, then start (or paste) your "
        "orchestrator prompt in your agent session (terminal, desktop, or web tab)."
    ), "the SOLO human-gate message must remain byte-identical"

    refreshed = await _reload_execution(db_session, job.job_id, tenant)
    assert refreshed.status == "waiting", "a blocked solo orchestrator must NOT flip to working"




async def test_chain_member_staging_end_stamps_and_advances(db_session: AsyncSession) -> None:
    tenant = TenantManager.generate_tenant_key()
    p1 = await _seed_project(db_session, tenant, staging_status="staging")
    p2 = await _seed_project(db_session, tenant, staging_status="staging")
    await _run_svc(db_session).create(
        project_ids=[p1, p2], resolved_order=[p1, p2], execution_mode="claude_code_cli", tenant_key=tenant
    )
    job = await _seed_orchestrator_job(db_session, tenant, p1, project_phase="staging")
    await _seed_worker(db_session, tenant, p1)

    result = await _completion_svc(db_session).complete_job(
        job_id=job.job_id, result={"summary": "staging done"}, tenant_key=tenant
    )

    assert result.phase == "staging_end", "a chain member's staging-end must classify as staging_end"

    reloaded = await _reload_project(db_session, p1, tenant)
    assert reloaded.implementation_launched_at is not None, (
        "the gateless staging-end must stamp implementation_launched_at (replacing the launch gate-cross)"
    )
    assert reloaded.staging_status == "staging_complete", "staging-end still flips staging_status"

    run = await _run_svc(db_session).find_active_run_for_project(project_id=p1, tenant_key=tenant)
    assert run is not None
    assert run["project_statuses"].get(p1) == "planning", "the staging-end advance must mark the member planning"




async def test_solo_staging_end_does_not_stamp(db_session: AsyncSession) -> None:
    tenant = TenantManager.generate_tenant_key()
    p_solo = await _seed_project(db_session, tenant, staging_status="staging")
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




class _RecordingWS:

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
