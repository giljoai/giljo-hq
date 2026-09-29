# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, Mock

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.database import DatabaseManager
from giljo_mcp.models import AgentExecution, AgentJob, Product, Project
from giljo_mcp.models.agent_identity import AgentTodoItem
from giljo_mcp.models.tasks import Message, MessageRecipient
from giljo_mcp.services.job_query_service import JobQueryService
from giljo_mcp.services.silence_detector import SilenceDetector
from giljo_mcp.services.workflow_status_service import WorkflowStatusService
from giljo_mcp.tenant import TenantManager


def _ago(minutes: float) -> datetime:
    return datetime.now(UTC) - timedelta(minutes=minutes)


async def _seed_project(session: AsyncSession, tenant_key: str) -> str:
    product = Product(
        id=str(uuid.uuid4()),
        tenant_key=tenant_key,
        name=f"BE-9655b product {uuid.uuid4().hex[:6]}",
        description="seeded",
        is_active=False,
    )
    session.add(product)
    project = Project(
        id=str(uuid.uuid4()),
        name=f"BE-9655b {uuid.uuid4().hex[:6]}",
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
    todo_statuses: list[str],
    job_type: str = "implementer",
    posted_deliverable: bool = False,
) -> tuple[str, str]:
    job = AgentJob(
        job_id=str(uuid.uuid4()),
        project_id=project_id,
        tenant_key=tenant_key,
        job_type=job_type,
        mission="x",
        status="active",
        created_at=_ago(90),
    )
    session.add(job)
    await session.flush()
    agent_id = str(uuid.uuid4())
    session.add(
        AgentExecution(
            id=str(uuid.uuid4()),
            agent_id=agent_id,
            job_id=job.job_id,
            tenant_key=tenant_key,
            agent_display_name=job_type,
            agent_name=job_type,
            status=status,
            started_at=_ago(80),
            last_progress_at=_ago(last_progress_minutes_ago),
        )
    )
    for seq, todo_status in enumerate(todo_statuses):
        session.add(
            AgentTodoItem(
                job_id=job.job_id, tenant_key=tenant_key, content=f"step {seq}", status=todo_status, sequence=seq
            )
        )
    if posted_deliverable:
        session.add(
            Message(
                tenant_key=tenant_key,
                project_id=project_id,
                content="PR open, holding for the EM gate.",
                from_agent_id=agent_id,
                from_kind="agent",
                message_type="broadcast",
                created_at=_ago(last_progress_minutes_ago - 1),
            )
        )
    await session.flush()
    return job.job_id, agent_id


def _detector() -> SilenceDetector:
    ws = AsyncMock()
    ws.broadcast_event_to_tenant = AsyncMock()
    return SilenceDetector(db_manager=Mock(spec=DatabaseManager), ws_manager=ws)


async def _status_of(session: AsyncSession, job_id: str) -> str:
    return (await session.execute(select(AgentExecution.status).where(AgentExecution.job_id == job_id))).scalar_one()


def _svc(session: AsyncSession) -> WorkflowStatusService:
    return WorkflowStatusService(db_manager=None, tenant_manager=TenantManager(), test_session=session)


@pytest.mark.asyncio
async def test_detector_leaves_a_holding_job_working(db_session: AsyncSession) -> None:
    tenant = TenantManager.generate_tenant_key()
    pid = await _seed_project(db_session, tenant)
    job_id, _ = await _seed_agent(
        db_session,
        tenant,
        pid,
        status="working",
        last_progress_minutes_ago=30,
        todo_statuses=["completed", "completed", "skipped"],
        posted_deliverable=True,
    )

    await _detector()._detect_silent_agents(db_session, threshold_minutes=10)

    assert await _status_of(db_session, job_id) == "working"


@pytest.mark.asyncio
async def test_detector_still_silences_a_real_stall_at_eleven_minutes(db_session: AsyncSession) -> None:
    tenant = TenantManager.generate_tenant_key()
    pid = await _seed_project(db_session, tenant)
    job_id, _ = await _seed_agent(
        db_session,
        tenant,
        pid,
        status="working",
        last_progress_minutes_ago=11,
        todo_statuses=["completed", "in_progress", "pending"],
    )

    await _detector()._detect_silent_agents(db_session, threshold_minutes=10)

    assert await _status_of(db_session, job_id) == "silent"


@pytest.mark.asyncio
@pytest.mark.parametrize("stored_status", ["working", "silent"])
async def test_workflow_status_says_holding_and_not_wedged(db_session: AsyncSession, stored_status: str) -> None:
    tenant = TenantManager.generate_tenant_key()
    pid = await _seed_project(db_session, tenant)
    job_id, _ = await _seed_agent(
        db_session,
        tenant,
        pid,
        status=stored_status,
        last_progress_minutes_ago=30,
        todo_statuses=["completed", "completed"],
        posted_deliverable=True,
    )

    result = await _svc(db_session).get_workflow_status(pid, tenant)

    [agent] = result.agents
    assert agent.job_id == job_id
    assert agent.activity == "holding"
    assert result.holding_agents == 1
    assert result.silent_agents == 0
    assert "wedged" not in result.caller_note
    assert (result.next_action or {}).get("tool") != "diagnose_project_state"


@pytest.mark.asyncio
async def test_workflow_status_real_stall_is_silent_and_wedged(db_session: AsyncSession) -> None:
    tenant = TenantManager.generate_tenant_key()
    pid = await _seed_project(db_session, tenant)
    await _seed_agent(db_session, tenant, pid, status="silent", last_progress_minutes_ago=11, todo_statuses=["pending"])

    result = await _svc(db_session).get_workflow_status(pid, tenant)

    [agent] = result.agents
    assert agent.activity == "silent"
    assert result.silent_agents == 1
    assert result.holding_agents == 0
    assert "wedged" in result.caller_note
    assert result.next_action["tool"] == "diagnose_project_state"


@pytest.mark.asyncio
async def test_workflow_status_working_job_reads_working(db_session: AsyncSession) -> None:
    tenant = TenantManager.generate_tenant_key()
    pid = await _seed_project(db_session, tenant)
    await _seed_agent(
        db_session, tenant, pid, status="working", last_progress_minutes_ago=2, todo_statuses=["completed", "pending"]
    )

    result = await _svc(db_session).get_workflow_status(pid, tenant)

    [agent] = result.agents
    assert agent.activity == "working"
    assert result.active_agents == 1


@pytest.mark.asyncio
async def test_roster_row_carries_the_same_word(db_session: AsyncSession) -> None:
    tenant = TenantManager.generate_tenant_key()
    pid = await _seed_project(db_session, tenant)
    holding_job, _ = await _seed_agent(
        db_session,
        tenant,
        pid,
        status="silent",
        last_progress_minutes_ago=30,
        todo_statuses=["completed"],
        posted_deliverable=True,
    )
    stalled_job, _ = await _seed_agent(
        db_session, tenant, pid, status="silent", last_progress_minutes_ago=11, todo_statuses=["pending"]
    )

    listed = await JobQueryService(db_manager=None, tenant_manager=TenantManager(), test_session=db_session).list_jobs(
        tenant_key=tenant, project_id=pid
    )

    words = {row["job_id"]: row["activity"] for row in listed.jobs}
    assert words == {holding_job: "holding", stalled_job: "silent"}


@pytest.mark.asyncio
async def test_unread_action_required_post_for_the_orchestrator_is_on_its_row(db_session: AsyncSession) -> None:
    tenant = TenantManager.generate_tenant_key()
    pid = await _seed_project(db_session, tenant)
    orch_job, orch_agent = await _seed_agent(
        db_session,
        tenant,
        pid,
        status="working",
        last_progress_minutes_ago=2,
        todo_statuses=["in_progress"],
        job_type="orchestrator",
    )
    message = Message(
        tenant_key=tenant,
        project_id=pid,
        content="PR #1 is ready for your gate.",
        from_agent_id="worker",
        from_kind="agent",
        message_type="direct",
        requires_action=True,
    )
    db_session.add(message)
    await db_session.flush()
    db_session.add(MessageRecipient(message_id=message.id, agent_id=orch_agent, tenant_key=tenant))
    await db_session.flush()

    listed = await JobQueryService(db_manager=None, tenant_manager=TenantManager(), test_session=db_session).list_jobs(
        tenant_key=tenant, project_id=pid
    )

    [row] = listed.jobs
    assert row["job_id"] == orch_job
    assert row["agent_name"] == "orchestrator"
    assert row["action_required_unread"] == 1
    assert row["activity"] == "working"
