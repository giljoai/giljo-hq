# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import select

from giljo_mcp.models import Task
from giljo_mcp.models.products import Product
from giljo_mcp.models.projects import TaxonomyType
from giljo_mcp.services.task_service import TaskService


@pytest_asyncio.fixture
async def be_taxonomy(db_session, test_tenant_key) -> TaxonomyType:
    tt = TaxonomyType(
        id=str(uuid4()),
        tenant_key=test_tenant_key,
        abbreviation="BE",
        label="Backend",
        color="#1f6feb",
        sort_order=1,
    )
    db_session.add(tt)
    await db_session.commit()
    await db_session.refresh(tt)
    return tt


@pytest_asyncio.fixture
async def active_product(db_session, test_tenant_key) -> Product:
    product = Product(
        id=str(uuid4()),
        name=f"Active Product {uuid4().hex[:6]}",
        description="Active product for task taxonomy tests",
        tenant_key=test_tenant_key,
        is_active=True,
    )
    db_session.add(product)
    await db_session.commit()
    await db_session.refresh(product)
    return product


class TestTaskSeriesAssignment:
    @pytest.mark.asyncio
    async def test_task_gets_tsk_tag_and_auto_series_number(
        self,
        task_service: TaskService,
        db_session,
        test_tenant_key: str,
        active_product: Product,
        be_taxonomy: TaxonomyType,
    ):
        result = await task_service.create_task_for_mcp(
            title="First task",
            description="should receive series 1",
            tenant_key=test_tenant_key,
        )

        assert result["success"] is True
        assert result["task_type"] == "TSK"
        task = (await db_session.execute(select(Task).where(Task.id == result["task_id"]))).scalar_one()
        assert task.task_type_id is not None
        assert task.task_type_id != be_taxonomy.id
        assert task.series_number == 1
        assert task.taxonomy_alias == "TSK-0001"
        assert result["taxonomy_alias"] == "TSK-0001"

    @pytest.mark.asyncio
    async def test_task_is_tsk_even_without_task_type(
        self,
        task_service: TaskService,
        db_session,
        test_tenant_key: str,
        active_product: Product,
    ):
        result = await task_service.create_task_for_mcp(
            title="Untyped task",
            description="no task_type supplied",
            tenant_key=test_tenant_key,
        )

        assert result["task_type"] == "TSK"
        task = (await db_session.execute(select(Task).where(Task.id == result["task_id"]))).scalar_one()
        assert task.task_type_id is not None
        assert task.series_number is not None
        assert task.taxonomy_alias.startswith("TSK-")

    @pytest.mark.asyncio
    async def test_monotonic_increment_within_bucket(
        self,
        task_service: TaskService,
        db_session,
        test_tenant_key: str,
        active_product: Product,
        be_taxonomy: TaxonomyType,
    ):
        r1 = await task_service.create_task_for_mcp(title="t1", description="t1", tenant_key=test_tenant_key)
        r2 = await task_service.create_task_for_mcp(title="t2", description="t2", tenant_key=test_tenant_key)
        r3 = await task_service.create_task_for_mcp(title="t3", description="t3", tenant_key=test_tenant_key)

        rows = (
            (await db_session.execute(select(Task).where(Task.id.in_([r1["task_id"], r2["task_id"], r3["task_id"]]))))
            .scalars()
            .all()
        )
        series = sorted(t.series_number for t in rows)
        assert series == [1, 2, 3]
