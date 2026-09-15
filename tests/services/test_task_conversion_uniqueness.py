# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import select

from giljo_mcp.models import Project, Task, User
from giljo_mcp.models.products import Product
from giljo_mcp.services.task_conversion_service import TaskConversionService


@pytest_asyncio.fixture
async def task_conversion_service(db_manager, tenant_manager, db_session, test_tenant_key):
    tenant_manager.set_current_tenant(test_tenant_key)
    return TaskConversionService(
        db_manager=db_manager,
        tenant_manager=tenant_manager,
        session=db_session,
    )


async def _make_user(db_session, tenant_key: str) -> User:
    user = User(
        id=str(uuid4()),
        tenant_key=tenant_key,
        username=f"u_{uuid4().hex[:8]}",
        email=f"{uuid4().hex[:8]}@test.local",
        role="admin",
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


async def _make_active_product(db_session, tenant_key: str) -> Product:
    product = Product(
        id=str(uuid4()),
        name=f"Product {uuid4().hex[:6]}",
        description="Test product",
        tenant_key=tenant_key,
        is_active=True,
    )
    db_session.add(product)
    await db_session.commit()
    await db_session.refresh(product)
    return product


async def _make_task(db_session, tenant_key: str, product_id: str, user_id: str, title: str) -> Task:
    task = Task(
        id=str(uuid4()),
        tenant_key=tenant_key,
        product_id=product_id,
        title=title,
        description=f"Description for {title}",
        status="pending",
        priority="medium",
        created_by_user_id=user_id,
    )
    db_session.add(task)
    await db_session.commit()
    await db_session.refresh(task)
    return task


class TestTaskConversionUniqueness:

    @pytest.mark.asyncio
    async def test_two_sequential_conversions_under_same_product_succeed(
        self,
        task_conversion_service: TaskConversionService,
        db_session,
        test_tenant_key: str,
    ):
        user = await _make_user(db_session, test_tenant_key)
        product = await _make_active_product(db_session, test_tenant_key)
        task_a = await _make_task(db_session, test_tenant_key, product.id, user.id, "Task A")
        task_b = await _make_task(db_session, test_tenant_key, product.id, user.id, "Task B")

        result_a = await task_conversion_service.convert_to_project(
            task_id=task_a.id,
            project_name=None,
            strategy="single",
            include_subtasks=False,
            user_id=user.id,
        )

        result_b = await task_conversion_service.convert_to_project(
            task_id=task_b.id,
            project_name=None,
            strategy="single",
            include_subtasks=False,
            user_id=user.id,
        )

        assert result_a.project_id != result_b.project_id

        rows = (
            (
                await db_session.execute(
                    select(Project).where(Project.id.in_([result_a.project_id, result_b.project_id]))
                )
            )
            .scalars()
            .all()
        )
        series = sorted(p.series_number for p in rows)
        assert series[0] is not None and series[1] is not None, (
            f"both conversions must auto-assign series_number; got {series}"
        )
        assert series[0] != series[1], (
            f"series_numbers must differ to avoid uq_project_taxonomy_active collision; got {series}"
        )
