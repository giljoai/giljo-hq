# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from giljo_mcp.database import tenant_session_context
from giljo_mcp.models.products import Product
from giljo_mcp.models.projects import Project
from giljo_mcp.repositories.product_statistics_repository import ProductStatisticsRepository
from giljo_mcp.tenant import TenantManager


pytestmark = pytest.mark.asyncio


async def test_count_total_projects_counts_a_stale_deleted_at_row(db_session) -> None:
    tenant = TenantManager.generate_tenant_key()
    repo = ProductStatisticsRepository(db_manager=None)

    product = Product(
        id=str(uuid.uuid4()),
        tenant_key=tenant,
        name="BE-9668 stats product",
        description="seed",
        is_active=False,
    )
    db_session.add(product)
    await db_session.flush()

    project = Project(
        id=str(uuid.uuid4()),
        product_id=product.id,
        name="BE-9668 stale project",
        description="d",
        mission="m",
        status="active",
        tenant_key=tenant,
        series_number=1,
    )
    db_session.add(project)
    await db_session.commit()

    stale_row = (await db_session.execute(select(Project).where(Project.id == project.id))).scalar_one()
    stale_row.deleted_at = datetime.now(UTC)
    await db_session.commit()

    with tenant_session_context(db_session, tenant):
        count = await repo.count_total_projects(db_session, tenant)

    assert count == 1, "a stale-shape live project (status active, deleted_at set) must still be counted"
