# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.


from __future__ import annotations

import random
import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.models import AgentExecution, AgentJob, Product, Project
from giljo_mcp.services.orchestration_agent_state_service import OrchestrationAgentStateService
from giljo_mcp.services.orchestration_service import OrchestrationService
from giljo_mcp.services.project_closeout_service import ProjectCloseoutService
from giljo_mcp.tenant import TenantManager


pytestmark = pytest.mark.asyncio

RESULT = {"summary": "Fixed the query", "artifacts": ["src/x.py"], "commits": ["abc123"]}


async def _seed_project(session: AsyncSession, tenant_key: str) -> str:
    product = Product(
        id=str(uuid.uuid4()),
        tenant_key=tenant_key,
        name=f"BE-9820 product {uuid.uuid4().hex[:6]}",
        description="seeded",
        is_active=False,
    )
    session.add(product)
    project = Project(
        id=str(uuid.uuid4()),
        name="BE-9820 project",
        description="closed job results",
        mission="closed job results",
        status="active",
        tenant_key=tenant_key,
        product_id=product.id,
        execution_mode="multi_terminal",
        series_number=random.randint(1, 9000),
        created_at=datetime.now(UTC),
    )
    session.add(project)
    await session.commit()
    return project.id


async def _seed_job(
    session: AsyncSession,
    tenant_key: str,
    project_id: str,
    *,
    status: str,
    result: dict | None,
    job_type: str = "implementer",
) -> AgentJob:
    job = AgentJob(
        job_id=str(uuid.uuid4()),
        tenant_key=tenant_key,
        project_id=project_id,
        job_type=job_type,
        mission=f"mission {job_type}",
        status="active",
    )
    session.add(job)
    session.add(
        AgentExecution(
            job_id=job.job_id,
            tenant_key=tenant_key,
            agent_display_name=job_type,
            status=status,
            result=result,
            completed_at=datetime.now(UTC) if status == "complete" else None,
            messages_sent_count=0,
            messages_waiting_count=0,
            messages_read_count=0,
        )
    )
    await session.commit()
    return job


def _orchestration(session: AsyncSession) -> OrchestrationService:
    return OrchestrationService(db_manager=None, tenant_manager=TenantManager(), test_session=session)


async def test_finalized_job_still_returns_its_result(db_session):
    tenant = TenantManager.generate_tenant_key()
    project_id = await _seed_project(db_session, tenant)
    worker = await _seed_job(db_session, tenant, project_id, status="complete", result=RESULT)
    caller = await _seed_job(db_session, tenant, project_id, status="working", result=None, job_type="orchestrator")

    closed = await OrchestrationAgentStateService(
        db_manager=None, tenant_manager=TenantManager(), test_session=db_session
    ).close_job(job_id=worker.job_id, tenant_key=tenant, caller_job_id=caller.job_id)
    assert closed["new_status"] == "closed"

    assert await _orchestration(db_session).get_agent_result(job_id=worker.job_id, tenant_key=tenant) == RESULT


async def test_job_closed_by_project_closeout_still_returns_its_result(db_session):
    tenant = TenantManager.generate_tenant_key()
    project_id = await _seed_project(db_session, tenant)
    worker = await _seed_job(db_session, tenant, project_id, status="complete", result=RESULT)

    closed_names, _events = await ProjectCloseoutService(
        None, TenantManager(), test_session=db_session
    ).close_completed_agents(db_session, project_id, tenant)
    await db_session.commit()
    assert closed_names == ["implementer"]

    assert await _orchestration(db_session).get_agent_result(job_id=worker.job_id, tenant_key=tenant) == RESULT


async def test_decommissioned_job_returns_no_result(db_session):
    tenant = TenantManager.generate_tenant_key()
    project_id = await _seed_project(db_session, tenant)
    job = await _seed_job(db_session, tenant, project_id, status="decommissioned", result=RESULT)

    assert await _orchestration(db_session).get_agent_result(job_id=job.job_id, tenant_key=tenant) is None


async def test_closed_job_result_is_not_visible_to_another_tenant(db_session):
    tenant = TenantManager.generate_tenant_key()
    project_id = await _seed_project(db_session, tenant)
    job = await _seed_job(db_session, tenant, project_id, status="closed", result=RESULT)
    other_tenant = TenantManager.generate_tenant_key()

    assert await _orchestration(db_session).get_agent_result(job_id=job.job_id, tenant_key=other_tenant) is None
