# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import contextlib
import logging
import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.models import Product, Project
from giljo_mcp.models.agent_identity import AgentExecution, AgentJob
from giljo_mcp.services.agent_job_manager import AgentJobManager
from giljo_mcp.services.project_summary_service import ProjectSummaryService
from giljo_mcp.tenant import TenantManager, current_tenant


@contextlib.contextmanager
def _no_ambient_tenant():
    token = current_tenant.set(None)
    try:
        assert TenantManager.get_current_tenant() is None
        yield
    finally:
        current_tenant.reset(token)


async def _seed_project_with_agents(session: AsyncSession, tenant_key: str) -> tuple[str, str]:
    suffix = uuid.uuid4().hex[:8]
    product = Product(
        id=str(uuid.uuid4()),
        name=f"BE6004C-3 Product {suffix}",
        description="RC-2 regression product.",
        tenant_key=tenant_key,
        is_active=True,
        product_memory={},
    )
    session.add(product)

    project = Project(
        id=str(uuid.uuid4()),
        name=f"BE6004C-3 Project {suffix}",
        description="RC-2 regression project.",
        mission="Prove service reads are ContextVar-independent.",
        status="active",
        tenant_key=tenant_key,
        product_id=product.id,
        series_number=1,
        created_at=datetime.now(UTC),
    )
    session.add(project)

    job = AgentJob(
        job_id=str(uuid.uuid4()),
        tenant_key=tenant_key,
        project_id=project.id,
        job_type="worker",
        mission="seed job",
        status="active",
        created_at=datetime.now(UTC),
        job_metadata={},
    )
    session.add(job)

    execution = AgentExecution(
        agent_id=str(uuid.uuid4()),
        job_id=job.job_id,
        tenant_key=tenant_key,
        agent_display_name="worker",
        agent_name="Seed Worker",
        status="complete",
        progress=100,
        tool_type="universal",
        started_at=datetime.now(UTC),
        completed_at=datetime.now(UTC),
    )
    session.add(execution)

    session.info["tenant_key"] = tenant_key
    await session.flush()
    return project.id, product.id


@pytest.mark.asyncio
async def test_get_project_summary_succeeds_without_ambient_contextvar(db_session: AsyncSession) -> None:
    tenant_key = TenantManager.generate_tenant_key()
    project_id, _product_id = await _seed_project_with_agents(db_session, tenant_key)

    tenant_manager = TenantManager()
    service = ProjectSummaryService(
        db_manager=None,  # type: ignore[arg-type]
        tenant_manager=tenant_manager,
        test_session=db_session,
    )

    with _no_ambient_tenant():
        result = await service.get_project_summary(project_id=project_id, tenant_key=tenant_key)

        assert result.id == project_id
        assert result.total_jobs == 1
        assert result.completed_jobs == 1
        assert result.completion_percentage == 100.0
        assert result.product_name.startswith("BE6004C-3 Product")
        assert TenantManager.get_current_tenant() is None


@pytest.mark.asyncio
async def test_list_team_agents_succeeds_without_ambient_contextvar(db_session: AsyncSession) -> None:
    tenant_key = TenantManager.generate_tenant_key()
    project_id, _product_id = await _seed_project_with_agents(db_session, tenant_key)

    job_id = (
        (await db_session.execute(AgentJob.__table__.select().where(AgentJob.project_id == project_id))).first().job_id
    )

    manager = AgentJobManager(
        db_manager=None,  # type: ignore[arg-type]
        tenant_manager=TenantManager(),
        test_session=db_session,
    )

    with _no_ambient_tenant():
        members = await manager.list_team_agents(job_id=job_id, tenant_key=tenant_key, include_inactive=True)

    assert len(members) == 1
    assert members[0]["job_id"] == job_id
    assert members[0]["tenant_key"] == tenant_key


@pytest.mark.asyncio
async def test_get_project_summary_falls_back_to_ambient_when_key_omitted(db_session: AsyncSession) -> None:
    tenant_key = TenantManager.generate_tenant_key()
    project_id, _product_id = await _seed_project_with_agents(db_session, tenant_key)

    class _AmbientManager(TenantManager):
        def get_current_tenant(self):  # type: ignore[override]
            return tenant_key

    service = ProjectSummaryService(
        db_manager=None,  # type: ignore[arg-type]
        tenant_manager=_AmbientManager(),
        test_session=db_session,
    )

    logging.getLogger(__name__).debug("fallback path: tenant from manager")
    result = await service.get_project_summary(project_id=project_id)
    assert result.id == project_id
    assert result.total_jobs == 1
