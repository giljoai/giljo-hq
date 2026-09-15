# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import random
import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.models.agent_identity import AgentExecution, AgentJob
from giljo_mcp.models.products import Product
from giljo_mcp.models.projects import Project
from giljo_mcp.repositories.agent_operations_repository import AgentOperationsRepository


async def _seed_project_agent_and_conductor(db_session: AsyncSession, tenant_key: str) -> tuple[Project, str, str]:
    _owning_product_project = Product(
        id=str(uuid.uuid4()),
        tenant_key=tenant_key,
        name=f"Owning Product {uuid.uuid4().hex[:6]}",
        description="seeded",
        is_active=False,
    )
    db_session.add(_owning_product_project)
    project = Project(
        id=str(uuid.uuid4()),
        name="BE6200 conductor-leak P1",
        description="d",
        mission="m",
        status="active",
        tenant_key=tenant_key,
        product_id=_owning_product_project.id,
        series_number=random.randint(1, 9000),
    )
    db_session.add(project)
    await db_session.flush()

    bound_job_id = str(uuid.uuid4())
    db_session.add(
        AgentJob(
            job_id=bound_job_id,
            project_id=project.id,
            tenant_key=tenant_key,
            job_type="implementer",
            mission="real project work",
        )
    )
    db_session.add(
        AgentExecution(
            job_id=bound_job_id,
            agent_id=str(uuid.uuid4()),
            tenant_key=tenant_key,
            status="working",
            agent_name="impl",
            agent_display_name="implementer",
        )
    )

    conductor_job_id = str(uuid.uuid4())
    db_session.add(
        AgentJob(
            job_id=conductor_job_id,
            project_id=None,
            tenant_key=tenant_key,
            job_type="orchestrator",
            mission="drive the chain",
            job_metadata={"chain_conductor": True},
        )
    )
    db_session.add(
        AgentExecution(
            job_id=conductor_job_id,
            agent_id=str(uuid.uuid4()),
            tenant_key=tenant_key,
            status="working",
            agent_name="conductor",
            agent_display_name="conductor",
        )
    )
    await db_session.commit()
    return project, bound_job_id, conductor_job_id


@pytest.mark.asyncio
async def test_workflow_executions_excludes_projectless_conductor(db_session: AsyncSession, test_tenant_key: str):
    project, bound_job_id, conductor_job_id = await _seed_project_agent_and_conductor(db_session, test_tenant_key)
    repo = AgentOperationsRepository()
    rows = await repo.get_workflow_executions(db_session, test_tenant_key, project.id)
    job_ids = {r.job_id for r in rows}
    assert bound_job_id in job_ids
    assert conductor_job_id not in job_ids


@pytest.mark.asyncio
async def test_list_jobs_paginated_excludes_projectless_conductor(db_session: AsyncSession, test_tenant_key: str):
    project, bound_job_id, conductor_job_id = await _seed_project_agent_and_conductor(db_session, test_tenant_key)
    repo = AgentOperationsRepository()
    rows, _total = await repo.list_jobs_paginated(db_session, test_tenant_key, project_id=project.id)
    job_ids = {job.job_id for (_execution, job) in rows}
    assert bound_job_id in job_ids
    assert conductor_job_id not in job_ids


def test_job_to_response_serializes_flat_chain_conductor_flag():
    from datetime import UTC, datetime

    from api.endpoints.agent_jobs.status import job_to_response

    base = {
        "job_id": "j",
        "tenant_key": "t",
        "project_id": "proj-1",
        "agent_display_name": "conductor",
        "mission": "m",
        "status": "working",
        "created_at": datetime.now(UTC),
    }
    assert job_to_response({**base, "chain_conductor": True}).chain_conductor is True
    assert job_to_response({**base, "chain_conductor": False}).chain_conductor is False
    assert job_to_response(base).chain_conductor is False
