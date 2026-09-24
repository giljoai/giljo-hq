# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import select

from giljo_mcp.models.products import Product
from giljo_mcp.models.projects import Project
from giljo_mcp.models.roadmaps import Roadmap
from giljo_mcp.services.roadmap_service import RoadmapService
from giljo_mcp.tenant import TenantManager
from tests.helpers.taxonomy_seeds import next_series_number


pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def seeded(db_session, test_tenant_key):
    product = Product(
        id=str(uuid4()),
        name=f"RM {uuid4().hex[:6]}",
        description="fe9645 roadmap summary clear",
        tenant_key=test_tenant_key,
        is_active=True,
    )
    db_session.add(product)
    project = Project(
        id=str(uuid4()),
        tenant_key=test_tenant_key,
        product_id=product.id,
        name="P0",
        description="d",
        mission="m",
        series_number=next_series_number(),
        status="inactive",
    )
    db_session.add(project)
    await db_session.flush()
    return {"product_id": product.id, "project_id": project.id}


def _service(db_session):
    return RoadmapService(tenant_manager=TenantManager(), session=db_session)


async def _summary(db_session, test_tenant_key, product_id):
    row = (
        await db_session.execute(
            select(Roadmap).where(Roadmap.tenant_key == test_tenant_key, Roadmap.product_id == product_id)
        )
    ).scalar_one()
    return row.summary


async def test_removing_last_item_clears_summary(db_session, test_tenant_key, seeded):
    svc = _service(db_session)
    await svc.upsert_metadata(
        items=[{"item_type": "project", "project_id": seeded["project_id"], "sort_order": 0}],
        summary="Ships the highest-risk item first.",
        tenant_key=test_tenant_key,
    )
    assert await _summary(db_session, test_tenant_key, seeded["product_id"]) == "Ships the highest-risk item first."

    await svc.upsert_metadata(
        items=[],
        remove=[{"item_type": "project", "project_id": seeded["project_id"]}],
        tenant_key=test_tenant_key,
    )

    assert await _summary(db_session, test_tenant_key, seeded["product_id"]) is None


async def test_omitted_summary_unchanged_when_items_remain(db_session, test_tenant_key, seeded):
    svc = _service(db_session)
    await svc.upsert_metadata(
        items=[{"item_type": "project", "project_id": seeded["project_id"], "sort_order": 0}],
        summary="Original reasoning.",
        tenant_key=test_tenant_key,
    )

    await svc.upsert_metadata(
        items=[{"item_type": "project", "project_id": seeded["project_id"], "sort_order": 1}],
        tenant_key=test_tenant_key,
    )

    assert await _summary(db_session, test_tenant_key, seeded["product_id"]) == "Original reasoning."


async def test_explicit_summary_stored_when_items_present(db_session, test_tenant_key, seeded):
    svc = _service(db_session)

    await svc.upsert_metadata(
        items=[{"item_type": "project", "project_id": seeded["project_id"], "sort_order": 0}],
        summary="Fresh ranking rationale.",
        tenant_key=test_tenant_key,
    )

    assert await _summary(db_session, test_tenant_key, seeded["product_id"]) == "Fresh ranking rationale."
