# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.models.agent_identity import AgentExecution, AgentJob
from giljo_mcp.models.products import Product
from giljo_mcp.models.projects import Project
from giljo_mcp.services.job_completion_service import JobCompletionService


@pytest.fixture
async def test_product(db_session: AsyncSession, test_tenant_key: str) -> Product:
    product = Product(
        id=str(uuid4()),
        tenant_key=test_tenant_key,
        name="INF-5076 Product",
        description="No-git-warning regression",
        product_memory={},
    )
    db_session.add(product)
    await db_session.commit()
    await db_session.refresh(product)
    return product


@pytest.fixture
async def active_project(
    db_session: AsyncSession,
    test_tenant_key: str,
    test_product: Product,
) -> Project:
    project = Project(
        id=str(uuid4()),
        tenant_key=test_tenant_key,
        product_id=test_product.id,
        name="INF-5076 Project",
        description="x",
        mission="x",
        status="active",
        created_at=datetime.now(UTC),
        series_number=random.randint(1, 9000),
    )
    db_session.add(project)
    await db_session.commit()
    await db_session.refresh(project)
    return project


@pytest.fixture
def completion_service(db_session: AsyncSession, test_tenant_key: str) -> JobCompletionService:
    db_manager = MagicMock()
    tenant_manager = MagicMock()
    tenant_manager.get_current_tenant.return_value = test_tenant_key
    return JobCompletionService(
        db_manager=db_manager,
        tenant_manager=tenant_manager,
        test_session=db_session,
    )


async def _seed_orchestrator(
    db_session: AsyncSession,
    tenant_key: str,
    project_id: str,
) -> AgentJob:
    job_id = str(uuid4())
    job = AgentJob(
        job_id=job_id,
        tenant_key=tenant_key,
        project_id=project_id,
        job_type="orchestrator",
        mission="INF-5076 regression",
        status="active",
    )
    db_session.add(job)

    now = datetime.now(UTC)
    execution = AgentExecution(
        job_id=job_id,
        tenant_key=tenant_key,
        agent_display_name="orchestrator",
        status="working",
        messages_sent_count=0,
        messages_waiting_count=0,
        messages_read_count=0,
        started_at=now - timedelta(minutes=5),
    )
    db_session.add(execution)
    await db_session.commit()
    await db_session.refresh(job)
    return job


@pytest.mark.asyncio
async def test_orchestrator_complete_job_no_git_warning(
    db_session: AsyncSession,
    completion_service: JobCompletionService,
    test_tenant_key: str,
    active_project: Project,
):
    job = await _seed_orchestrator(db_session, test_tenant_key, active_project.id)

    result = await completion_service.complete_job(
        job_id=job.job_id,
        result={"summary": "INF-5076 closeout — no commits in this call by design"},
        tenant_key=test_tenant_key,
    )

    assert result.status == "success"
    git_warnings = [w for w in result.warnings if "Git integration" in w or "git commit" in w.lower()]
    assert git_warnings == [], (
        f"INF-5076 regression: orchestrator complete_job should not emit a git-commits warning. Got: {git_warnings!r}"
    )


@pytest.mark.asyncio
async def test_orchestrator_complete_job_closeout_checklist_still_built(
    db_session: AsyncSession,
    completion_service: JobCompletionService,
    test_tenant_key: str,
    active_project: Project,
):
    job = await _seed_orchestrator(db_session, test_tenant_key, active_project.id)

    result = await completion_service.complete_job(
        job_id=job.job_id,
        result={"summary": "checklist still expected"},
        tenant_key=test_tenant_key,
    )

    assert result.status == "success"
    assert result.closeout_checklist is not None, "closeout_checklist must still be built for orchestrator complete_job"
