# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.models import AgentExecution, AgentJob, Product, Project
from giljo_mcp.models.agent_identity import AgentTodoItem
from giljo_mcp.services.job_query_service import JobQueryService
from giljo_mcp.services.workflow_status_service import WorkflowStatusService
from giljo_mcp.tenant import TenantManager


pytestmark = pytest.mark.asyncio


def _ago(minutes: float) -> datetime:
    return datetime.now(UTC) - timedelta(minutes=minutes)


async def _seed_project(session: AsyncSession, tenant_key: str) -> str:
    product = Product(
        id=str(uuid.uuid4()),
        tenant_key=tenant_key,
        name=f"BE-9717 product {uuid.uuid4().hex[:6]}",
        description="seeded",
        is_active=False,
    )
    session.add(product)
    project = Project(
        id=str(uuid.uuid4()),
        name=f"BE-9717 {uuid.uuid4().hex[:6]}",
        description="x",
        mission="x",
        status="active",
        tenant_key=tenant_key,
        product_id=product.id,
        series_number=1,
        execution_mode="claude_code_cli",
        implementation_launched_at=_ago(60),
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
    last_progress_minutes_ago: float,
    job_type: str = "implementer",
    todo_statuses: tuple[str, ...] = ("in_progress", "pending"),
    completed_minutes_ago: float | None = None,
    job_metadata: dict | None = None,
) -> str:
    job = AgentJob(
        job_id=str(uuid.uuid4()),
        project_id=project_id,
        tenant_key=tenant_key,
        job_type=job_type,
        mission="x",
        status="active",
        created_at=_ago(90),
        job_metadata=job_metadata or {},
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
            started_at=_ago(80),
            last_progress_at=_ago(last_progress_minutes_ago),
            completed_at=_ago(completed_minutes_ago) if completed_minutes_ago is not None else None,
        )
    )
    for seq, todo_status in enumerate(todo_statuses):
        session.add(
            AgentTodoItem(
                job_id=job.job_id, tenant_key=tenant_key, content=f"step {seq}", status=todo_status, sequence=seq
            )
        )
    await session.flush()
    return job.job_id


async def _seed_stale_orchestrator(session: AsyncSession, tenant_key: str, project_id: str) -> str:
    return await _seed_agent(
        session,
        tenant_key,
        project_id,
        status="silent",
        last_progress_minutes_ago=14,
        job_type="orchestrator",
        todo_statuses=("pending",) * 7,
    )


async def _states(session: AsyncSession, tenant_key: str, project_id: str) -> tuple[dict, dict]:
    listed = await JobQueryService(db_manager=None, tenant_manager=TenantManager(), test_session=session).list_jobs(
        tenant_key=tenant_key, project_id=project_id
    )
    status = await WorkflowStatusService(
        db_manager=None, tenant_manager=TenantManager(), test_session=session
    ).get_workflow_status(project_id, tenant_key)
    roster = {row["job_id"]: row["orchestrator_state"] for row in listed.jobs}
    workflow = {
        agent.job_id: (agent.orchestrator_state.model_dump() if agent.orchestrator_state else None)
        for agent in status.agents
    }
    return roster, workflow


async def test_stale_orchestrator_with_two_running_workers_reads_monitoring(db_session: AsyncSession) -> None:
    tenant = TenantManager.generate_tenant_key()
    pid = await _seed_project(db_session, tenant)
    orch = await _seed_stale_orchestrator(db_session, tenant, pid)
    worker_a = await _seed_agent(db_session, tenant, pid, status="working", last_progress_minutes_ago=1)
    worker_b = await _seed_agent(db_session, tenant, pid, status="working", last_progress_minutes_ago=3)

    roster, workflow = await _states(db_session, tenant, pid)

    assert roster == workflow
    assert roster[orch]["state"] == "monitoring"
    assert roster[orch]["agents"] == 2
    assert roster[orch]["label"] == "Monitoring (2 agents running)"
    assert roster[orch]["stale_minutes"] == 14
    assert (roster[orch]["todos_done"], roster[orch]["todos_total"]) == (0, 7)
    assert roster[worker_a] is None
    assert roster[worker_b] is None


async def test_stale_orchestrator_with_a_completed_unfinalized_worker_reads_result_waiting(
    db_session: AsyncSession,
) -> None:
    tenant = TenantManager.generate_tenant_key()
    pid = await _seed_project(db_session, tenant)
    orch = await _seed_stale_orchestrator(db_session, tenant, pid)
    await _seed_agent(db_session, tenant, pid, status="complete", last_progress_minutes_ago=9, completed_minutes_ago=9)
    await _seed_agent(db_session, tenant, pid, status="closed", last_progress_minutes_ago=30, completed_minutes_ago=30)

    roster, workflow = await _states(db_session, tenant, pid)

    assert roster == workflow
    assert roster[orch]["state"] == "result_waiting"
    assert roster[orch]["agents"] == 1
    assert roster[orch]["minutes"] == 9
    assert roster[orch]["label"] == "Result waiting, not picked up (9 min)"


async def test_stale_orchestrator_with_no_live_worker_reads_silent(db_session: AsyncSession) -> None:
    tenant = TenantManager.generate_tenant_key()
    pid = await _seed_project(db_session, tenant)
    orch = await _seed_stale_orchestrator(db_session, tenant, pid)
    await _seed_agent(db_session, tenant, pid, status="closed", last_progress_minutes_ago=30, completed_minutes_ago=30)
    await _seed_agent(db_session, tenant, pid, status="silent", last_progress_minutes_ago=20)

    roster, workflow = await _states(db_session, tenant, pid)

    assert roster == workflow
    assert roster[orch]["state"] == "silent"
    assert roster[orch]["agents"] == 0
    assert roster[orch]["label"] == "Silent"


async def test_fresh_holding_and_conductor_rows_carry_no_state(db_session: AsyncSession) -> None:
    tenant = TenantManager.generate_tenant_key()
    pid = await _seed_project(db_session, tenant)
    fresh = await _seed_agent(
        db_session, tenant, pid, status="working", last_progress_minutes_ago=2, job_type="orchestrator"
    )
    holding = await _seed_agent(
        db_session,
        tenant,
        pid,
        status="silent",
        last_progress_minutes_ago=30,
        job_type="orchestrator",
        todo_statuses=("completed", "completed"),
    )
    conductor = await _seed_agent(
        db_session,
        tenant,
        pid,
        status="silent",
        last_progress_minutes_ago=30,
        job_type="orchestrator",
        job_metadata={"chain_conductor": True},
    )
    await _seed_agent(db_session, tenant, pid, status="working", last_progress_minutes_ago=1)

    roster, workflow = await _states(db_session, tenant, pid)

    assert roster == workflow
    assert roster[fresh] is None
    assert roster[holding] is None
    assert roster[conductor] is None
