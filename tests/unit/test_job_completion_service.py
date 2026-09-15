# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import random
import uuid
from unittest.mock import MagicMock

import pytest

from giljo_mcp.database import tenant_session_context
from giljo_mcp.exceptions import ResourceNotFoundError, ValidationError
from giljo_mcp.models import AgentExecution, AgentJob, Product, Project
from giljo_mcp.services.job_completion_service import JobCompletionService


@pytest.fixture
def completion_service(db_session, test_tenant_key):
    db_manager = MagicMock()
    tenant_manager = MagicMock()
    tenant_manager.get_current_tenant.return_value = test_tenant_key
    return JobCompletionService(
        db_manager=db_manager,
        tenant_manager=tenant_manager,
        test_session=db_session,
    )


async def _seed_staging_project(session, tenant_key):
    product = Product(
        id=str(uuid.uuid4()),
        tenant_key=tenant_key,
        name=f"Completion Product {uuid.uuid4().hex[:6]}",
        description="seeded",
        is_active=False,
    )
    session.add(product)
    await session.flush()

    project = Project(
        tenant_key=tenant_key,
        product_id=product.id,
        name="Staging Project",
        description="seeded",
        mission="seeded mission",
        status="active",
        staging_status="staging",
        series_number=random.randint(1, 9000),
    )
    session.add(project)
    await session.flush()
    return project


async def _seed_orchestrator(session, tenant_key, project_id):
    job = AgentJob(
        tenant_key=tenant_key,
        project_id=project_id,
        mission="orchestrate",
        job_type="orchestrator",
        status="active",
    )
    session.add(job)
    await session.flush()
    execution = AgentExecution(
        job_id=job.job_id,
        tenant_key=tenant_key,
        agent_display_name="orchestrator",
        status="waiting",
    )
    session.add(execution)
    await session.flush()
    return job, execution


async def _seed_specialist(session, tenant_key, project_id):
    job = AgentJob(
        tenant_key=tenant_key,
        project_id=project_id,
        mission="implement",
        job_type="implementer",
        status="active",
    )
    session.add(job)
    await session.flush()
    execution = AgentExecution(
        job_id=job.job_id,
        tenant_key=tenant_key,
        agent_display_name="implementer",
        status="working",
    )
    session.add(execution)
    await session.flush()
    return execution


@pytest.mark.asyncio
async def test_complete_job_rejects_empty_job_id(completion_service, test_tenant_key):
    with pytest.raises(ValidationError):
        await completion_service.complete_job("", {"summary": "test"}, test_tenant_key)


@pytest.mark.asyncio
async def test_complete_job_rejects_non_dict_result(completion_service, test_tenant_key):
    with pytest.raises(ValidationError):
        await completion_service.complete_job("some-job-id", None, test_tenant_key)


@pytest.mark.asyncio
async def test_complete_job_raises_for_missing_execution(completion_service, test_tenant_key):
    with pytest.raises(ResourceNotFoundError):
        await completion_service.complete_job(
            "00000000-0000-0000-0000-000000000000", {"summary": "test"}, test_tenant_key
        )




@pytest.mark.asyncio
async def test_staging_end_rejected_when_no_specialist_agents(completion_service, db_session, test_tenant_key):
    with tenant_session_context(db_session, test_tenant_key):
        project = await _seed_staging_project(db_session, test_tenant_key)
        job, execution = await _seed_orchestrator(db_session, test_tenant_key, str(project.id))

        with pytest.raises(ValidationError) as exc_info:
            await completion_service._handle_staging_end(
                db_session,
                job,
                execution,
                test_tenant_key,
                is_staging_end=True,
                project=project,
            )

    assert exc_info.value.error_code == "STAGING_END_NO_AGENTS"
    assert project.staging_status != "staging_complete"


@pytest.mark.asyncio
async def test_staging_end_completes_when_specialist_present(completion_service, db_session, test_tenant_key):
    with tenant_session_context(db_session, test_tenant_key):
        project = await _seed_staging_project(db_session, test_tenant_key)
        job, execution = await _seed_orchestrator(db_session, test_tenant_key, str(project.id))
        await _seed_specialist(db_session, test_tenant_key, str(project.id))

        directive = await completion_service._handle_staging_end(
            db_session,
            job,
            execution,
            test_tenant_key,
            is_staging_end=True,
            project=project,
        )

    assert directive is not None
    assert project.staging_status == "staging_complete"
