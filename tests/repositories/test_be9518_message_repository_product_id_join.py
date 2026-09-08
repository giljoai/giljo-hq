# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-9518 — MessageRepository.get_job_id_and_project_for_execution's new join.

The method used to select only (job_id, project_id). The auto-block WS broadcast
(``MessageRoutingService._auto_block_completed_recipients`` ->
``broadcast_job_status_update``) needs ``product_id`` too, resolved via a LEFT
OUTER JOIN to ``projects`` -- deliberately OUTER, not INNER, so a job with no
project (e.g. a project-less chain conductor) still returns its row instead of
being silently dropped.

DB-touching: ``db_session`` (TransactionalTestContext, rolled back). No
module-level mutable state, no ordering dependencies. Parallel-safe
(pytest-xdist -n auto). Edition Scope: CE.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.models.agent_identity import AgentJob
from giljo_mcp.models.products import Product
from giljo_mcp.models.projects import Project
from giljo_mcp.repositories.message_repository import MessageRepository
from giljo_mcp.tenant import TenantManager


pytestmark = pytest.mark.asyncio


async def test_returns_product_id_for_job_with_project(db_session: AsyncSession) -> None:
    tenant_key = TenantManager.generate_tenant_key()

    product = Product(
        id=str(uuid.uuid4()),
        tenant_key=tenant_key,
        name=f"BE-9518 repo join product {uuid.uuid4().hex[:8]}",
        description="seeded",
        is_active=False,
    )
    db_session.add(product)
    await db_session.flush()

    project = Project(
        id=str(uuid.uuid4()),
        tenant_key=tenant_key,
        product_id=product.id,
        name="BE-9518 repo join project",
        description="seeded",
        mission="seeded",
        status="active",
        series_number=1,
    )
    db_session.add(project)
    await db_session.flush()

    job_id = str(uuid.uuid4())
    job = AgentJob(
        job_id=job_id,
        tenant_key=tenant_key,
        project_id=project.id,
        job_type="implementer",
        mission="seeded",
        status="active",
    )
    db_session.add(job)
    await db_session.commit()

    row = await MessageRepository().get_job_id_and_project_for_execution(db_session, tenant_key, job_id)

    assert row is not None
    assert row.job_id == job_id
    assert row.project_id == project.id
    assert row.product_id == product.id


async def test_project_less_job_still_returns_row_not_dropped(db_session: AsyncSession) -> None:
    """The join is OUTER: a project-less job (e.g. a chain conductor) must still
    come back with a row -- product_id simply None -- not silently vanish.
    """
    tenant_key = TenantManager.generate_tenant_key()

    job_id = str(uuid.uuid4())
    job = AgentJob(
        job_id=job_id,
        tenant_key=tenant_key,
        project_id=None,
        job_type="orchestrator",
        mission=None,
        status="active",
    )
    db_session.add(job)
    await db_session.commit()

    row = await MessageRepository().get_job_id_and_project_for_execution(db_session, tenant_key, job_id)

    assert row is not None, "an INNER join would wrongly drop this project-less row"
    assert row.job_id == job_id
    assert row.project_id is None
    assert row.product_id is None
