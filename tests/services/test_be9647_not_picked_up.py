# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.models import AgentExecution, AgentJob, Product, Project
from giljo_mcp.models.sequence_runs import SequenceRun
from giljo_mcp.services.job_query_service import JobQueryService
from giljo_mcp.services.workflow_status_service import WorkflowStatusService
from giljo_mcp.tenant import TenantManager


def _ago(minutes: float) -> datetime:
    return datetime.now(UTC) - timedelta(minutes=minutes)


async def _seed_project(
    session: AsyncSession,
    tenant_key: str,
    *,
    launched_at: datetime | None,
    closeout_executed_at: datetime | None = None,
) -> str:
    product = Product(
        id=str(uuid.uuid4()),
        tenant_key=tenant_key,
        name=f"BE-9647 product {uuid.uuid4().hex[:6]}",
        description="seeded",
        is_active=False,
    )
    session.add(product)
    project = Project(
        id=str(uuid.uuid4()),
        name=f"BE-9647 {uuid.uuid4().hex[:6]}",
        description="x",
        mission="x",
        status="active",
        tenant_key=tenant_key,
        product_id=product.id,
        series_number=1,
        execution_mode="claude_code_cli",
        implementation_launched_at=launched_at,
        closeout_executed_at=closeout_executed_at,
        created_at=_ago(120),
    )
    session.add(project)
    session.info["tenant_key"] = tenant_key
    await session.flush()
    return project.id


async def _seed_agent(
    session: AsyncSession,
    tenant_key: str,
    project_id: str,
    *,
    status: str,
    created_at: datetime,
    job_type: str = "implementer",
) -> str:
    job = AgentJob(
        job_id=str(uuid.uuid4()),
        project_id=project_id,
        tenant_key=tenant_key,
        job_type=job_type,
        mission="x",
        status="active",
        created_at=created_at,
    )
    session.add(job)
    await session.flush()
    session.add(
        AgentExecution(
            id=str(uuid.uuid4()),
            agent_id=str(uuid.uuid4()),
            job_id=job.job_id,
            tenant_key=tenant_key,
            agent_display_name=job_type,
            agent_name=job_type,
            status=status,
            started_at=None if status == "waiting" else created_at,
        )
    )
    await session.flush()
    return job.job_id


def _svc(session: AsyncSession) -> WorkflowStatusService:
    return WorkflowStatusService(db_manager=None, tenant_manager=TenantManager(), test_session=session)


def _flags(result) -> dict[str, bool]:
    return {a.job_id: a.not_picked_up for a in result.agents}


@pytest.mark.asyncio
async def test_waiting_past_cadence_is_flagged_and_counted(db_session: AsyncSession) -> None:
    tenant = TenantManager.generate_tenant_key()
    pid = await _seed_project(db_session, tenant, launched_at=_ago(15))
    job_id = await _seed_agent(db_session, tenant, pid, status="waiting", created_at=_ago(30))

    result = await _svc(db_session).get_workflow_status(pid, tenant)

    assert _flags(result) == {job_id: True}
    assert result.not_picked_up_agents == 1
    assert result.next_action is not None
    assert "launch it with the stored prompt" in result.next_action["why"]


@pytest.mark.asyncio
async def test_waiting_within_cadence_is_not_flagged(db_session: AsyncSession) -> None:
    tenant = TenantManager.generate_tenant_key()
    pid = await _seed_project(db_session, tenant, launched_at=_ago(5))
    job_id = await _seed_agent(db_session, tenant, pid, status="waiting", created_at=_ago(30))

    result = await _svc(db_session).get_workflow_status(pid, tenant)

    assert _flags(result) == {job_id: False}
    assert result.not_picked_up_agents == 0


@pytest.mark.asyncio
async def test_spawned_before_launch_is_not_flagged_until_launch(db_session: AsyncSession) -> None:
    tenant = TenantManager.generate_tenant_key()
    pid = await _seed_project(db_session, tenant, launched_at=None)
    job_id = await _seed_agent(db_session, tenant, pid, status="waiting", created_at=_ago(60))

    unlaunched = await _svc(db_session).get_workflow_status(pid, tenant)
    assert _flags(unlaunched) == {job_id: False}

    project = await db_session.get(Project, pid)
    project.implementation_launched_at = _ago(15)
    await db_session.flush()

    launched = await _svc(db_session).get_workflow_status(pid, tenant)
    assert _flags(launched) == {job_id: True}


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["working", "silent"])
async def test_working_or_silent_is_never_flagged(db_session: AsyncSession, status: str) -> None:
    tenant = TenantManager.generate_tenant_key()
    pid = await _seed_project(db_session, tenant, launched_at=_ago(60))
    job_id = await _seed_agent(db_session, tenant, pid, status=status, created_at=_ago(90))

    result = await _svc(db_session).get_workflow_status(pid, tenant)

    assert _flags(result) == {job_id: False}
    assert result.not_picked_up_agents == 0


@pytest.mark.asyncio
async def test_spawned_after_launch_clock_starts_at_its_spawn(db_session: AsyncSession) -> None:
    tenant = TenantManager.generate_tenant_key()
    pid = await _seed_project(db_session, tenant, launched_at=_ago(60))
    fresh = await _seed_agent(db_session, tenant, pid, status="waiting", created_at=_ago(2))
    stale = await _seed_agent(db_session, tenant, pid, status="waiting", created_at=_ago(20))

    result = await _svc(db_session).get_workflow_status(pid, tenant)

    assert _flags(result) == {fresh: False, stale: True}


@pytest.mark.asyncio
async def test_chain_sub_orchestrator_flagged_once_conductor_reached_it(db_session: AsyncSession) -> None:
    tenant = TenantManager.generate_tenant_key()
    predecessor = await _seed_project(db_session, tenant, launched_at=_ago(90), closeout_executed_at=_ago(20))
    member = await _seed_project(db_session, tenant, launched_at=None)
    later = await _seed_project(db_session, tenant, launched_at=None)
    sub_orch = await _seed_agent(
        db_session, tenant, member, status="waiting", created_at=_ago(120), job_type="orchestrator"
    )
    worker = await _seed_agent(db_session, tenant, member, status="waiting", created_at=_ago(15))
    later_orch = await _seed_agent(
        db_session, tenant, later, status="waiting", created_at=_ago(120), job_type="orchestrator"
    )
    order = [predecessor, member, later]
    db_session.add(
        SequenceRun(
            id=str(uuid.uuid4()),
            tenant_key=tenant,
            project_ids=order,
            resolved_order=order,
            current_index=1,
            execution_mode="subagent",
            status="running",
            project_statuses={},
        )
    )
    await db_session.flush()

    reached = await _svc(db_session).get_workflow_status(member, tenant)
    assert _flags(reached) == {sub_orch: True, worker: False}

    not_reached = await _svc(db_session).get_workflow_status(later, tenant)
    assert _flags(not_reached) == {later_orch: False}


@pytest.mark.asyncio
async def test_roster_read_carries_the_same_flag(db_session: AsyncSession) -> None:
    tenant = TenantManager.generate_tenant_key()
    pid = await _seed_project(db_session, tenant, launched_at=_ago(15))
    stalled = await _seed_agent(db_session, tenant, pid, status="waiting", created_at=_ago(30))
    running = await _seed_agent(db_session, tenant, pid, status="working", created_at=_ago(30))

    svc = JobQueryService(db_manager=None, tenant_manager=TenantManager(), test_session=db_session)
    listed = await svc.list_jobs(tenant_key=tenant, project_id=pid)

    assert {j["job_id"]: j["not_picked_up"] for j in listed.jobs} == {stalled: True, running: False}


@pytest.mark.asyncio
async def test_first_chain_member_clock_starts_when_the_conductor_started(db_session: AsyncSession) -> None:
    tenant = TenantManager.generate_tenant_key()
    member = await _seed_project(db_session, tenant, launched_at=None)
    sub_orch = await _seed_agent(
        db_session, tenant, member, status="waiting", created_at=_ago(120), job_type="orchestrator"
    )
    conductor_agent_id = str(uuid.uuid4())
    conductor_job = AgentJob(
        job_id=str(uuid.uuid4()), project_id=None, tenant_key=tenant, job_type="orchestrator", status="active"
    )
    db_session.add(conductor_job)
    await db_session.flush()
    db_session.add(
        AgentExecution(
            id=str(uuid.uuid4()),
            agent_id=conductor_agent_id,
            job_id=conductor_job.job_id,
            tenant_key=tenant,
            agent_display_name="orchestrator",
            status="working",
            started_at=_ago(20),
        )
    )
    db_session.add(
        SequenceRun(
            id=str(uuid.uuid4()),
            tenant_key=tenant,
            project_ids=[member],
            resolved_order=[member],
            current_index=0,
            execution_mode="subagent",
            status="running",
            project_statuses={},
            conductor_agent_id=conductor_agent_id,
        )
    )
    await db_session.flush()

    result = await _svc(db_session).get_workflow_status(member, tenant)
    assert _flags(result) == {sub_orch: True}


@pytest.mark.asyncio
async def test_phase_gated_job_waits_its_turn_without_being_flagged(db_session: AsyncSession) -> None:
    tenant = TenantManager.generate_tenant_key()
    pid = await _seed_project(db_session, tenant, launched_at=_ago(60))
    first = await _seed_agent(db_session, tenant, pid, status="working", created_at=_ago(50))
    second = await _seed_agent(db_session, tenant, pid, status="waiting", created_at=_ago(50))
    for job_id, phase in ((first, 1), (second, 2)):
        (await db_session.get(AgentJob, job_id)).phase = phase
    await db_session.flush()

    in_turn_order = await _svc(db_session).get_workflow_status(pid, tenant)
    assert _flags(in_turn_order)[second] is False

    first_exec = (await db_session.execute(select(AgentExecution).where(AgentExecution.job_id == first))).scalar_one()
    first_exec.status = "complete"
    first_exec.completed_at = _ago(3)
    await db_session.flush()
    just_released = await _svc(db_session).get_workflow_status(pid, tenant)
    assert _flags(just_released)[second] is False

    first_exec.completed_at = _ago(15)
    await db_session.flush()
    released_long_ago = await _svc(db_session).get_workflow_status(pid, tenant)
    assert _flags(released_long_ago)[second] is True
