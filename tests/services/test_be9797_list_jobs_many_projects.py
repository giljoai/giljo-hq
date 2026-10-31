# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.exceptions import ValidationError
from giljo_mcp.models import AgentExecution, AgentJob, Product, Project
from giljo_mcp.services.job_query_service import JobQueryService
from giljo_mcp.tenant import TenantManager
from tests.helpers.taxonomy_seeds import next_series_number


pytestmark = pytest.mark.asyncio


def _jobs_svc(session: AsyncSession) -> JobQueryService:
    return JobQueryService(db_manager=None, tenant_manager=TenantManager(), test_session=session)


async def _seed_project(session: AsyncSession, tenant_key: str, agents: tuple[str, ...]) -> tuple[str, set[str]]:
    product = Product(
        id=str(uuid.uuid4()),
        tenant_key=tenant_key,
        name=f"BE-9797 product {uuid.uuid4().hex[:6]}",
        description="seeded",
        is_active=False,
    )
    session.add(product)
    project = Project(
        id=str(uuid.uuid4()),
        name="BE-9797 project",
        description="board batch read",
        mission="board batch read mission",
        status="active",
        tenant_key=tenant_key,
        product_id=product.id,
        execution_mode="multi_terminal",
        series_number=next_series_number(),
        created_at=datetime.now(UTC),
    )
    session.add(project)
    await session.flush()

    job_ids: set[str] = set()
    for display_name in agents:
        job = AgentJob(
            job_id=str(uuid.uuid4()),
            tenant_key=tenant_key,
            project_id=project.id,
            job_type=display_name,
            mission=f"mission {display_name}",
            status="active",
        )
        session.add(job)
        session.add(
            AgentExecution(
                job_id=job.job_id,
                tenant_key=tenant_key,
                agent_display_name=display_name,
                status="working",
                messages_sent_count=0,
                messages_waiting_count=0,
                messages_read_count=0,
            )
        )
        job_ids.add(job.job_id)
    await session.flush()
    return project.id, job_ids


async def test_project_ids_returns_own_projects_jobs_and_never_a_foreign_tenants(db_session: AsyncSession) -> None:
    tenant_a = TenantManager.generate_tenant_key()
    tenant_b = TenantManager.generate_tenant_key()
    p1, p1_jobs = await _seed_project(db_session, tenant_a, ("orchestrator", "implementer"))
    p2, p2_jobs = await _seed_project(db_session, tenant_a, ("orchestrator",))
    p3, p3_jobs = await _seed_project(db_session, tenant_b, ("orchestrator", "tester"))
    _other, other_jobs = await _seed_project(db_session, tenant_a, ("analyzer",))

    result = await _jobs_svc(db_session).list_jobs(tenant_key=tenant_a, project_ids=[p1, p2, p3])

    got = {job["job_id"] for job in result.jobs}
    assert got == p1_jobs | p2_jobs, "the union of the named projects' jobs, nothing more"
    assert not got & p3_jobs, "a foreign tenant's project id must contribute nothing"
    assert not got & other_jobs, "an unnamed project of the same tenant must not leak in"
    assert {job["project_id"] for job in result.jobs} == {p1, p2}
    assert result.total == len(p1_jobs | p2_jobs)


async def test_project_ids_over_the_cap_is_refused(db_session: AsyncSession) -> None:
    tenant = TenantManager.generate_tenant_key()
    ids = [str(uuid.uuid4()) for _ in range(201)]
    with pytest.raises(ValidationError):
        await _jobs_svc(db_session).list_jobs(tenant_key=tenant, project_ids=ids)


async def test_project_ids_at_the_cap_is_accepted(db_session: AsyncSession) -> None:
    tenant = TenantManager.generate_tenant_key()
    p1, p1_jobs = await _seed_project(db_session, tenant, ("orchestrator",))
    ids = [p1] + [str(uuid.uuid4()) for _ in range(199)]
    result = await _jobs_svc(db_session).list_jobs(tenant_key=tenant, project_ids=ids)
    assert {job["job_id"] for job in result.jobs} == p1_jobs


async def test_project_id_and_project_ids_together_is_refused(db_session: AsyncSession) -> None:
    tenant = TenantManager.generate_tenant_key()
    p1, _ = await _seed_project(db_session, tenant, ("orchestrator",))
    with pytest.raises(ValidationError):
        await _jobs_svc(db_session).list_jobs(tenant_key=tenant, project_id=p1, project_ids=[p1])


async def test_empty_project_ids_is_refused_never_tenant_wide(db_session: AsyncSession) -> None:
    tenant = TenantManager.generate_tenant_key()
    await _seed_project(db_session, tenant, ("orchestrator",))
    with pytest.raises(ValidationError):
        await _jobs_svc(db_session).list_jobs(tenant_key=tenant, project_ids=[])
