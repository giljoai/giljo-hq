# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import select

from giljo_mcp.exceptions import ValidationError
from giljo_mcp.models import Project, Task, User
from giljo_mcp.models.products import Product
from giljo_mcp.repositories.project_repository import MAX_SERIES_NUMBER, ProjectRepository
from giljo_mcp.services.task_conversion_service import TaskConversionService


@pytest_asyncio.fixture
async def active_product(db_session, test_tenant_key) -> Product:
    product = Product(
        id=str(uuid4()),
        name=f"Cap Product {uuid4().hex[:6]}",
        description="Product for serial-cap tests",
        tenant_key=test_tenant_key,
        is_active=True,
    )
    db_session.add(product)
    await db_session.commit()
    await db_session.refresh(product)
    return product


async def _seed_project_at(db_session, tenant_key: str, product_id: str, series_number: int) -> Project:
    proj = Project(
        id=str(uuid4()),
        name=f"Watermark-{series_number}",
        description="watermark seed",
        mission="",
        tenant_key=tenant_key,
        product_id=product_id,
        status="inactive",
        series_number=series_number,
    )
    db_session.add(proj)
    await db_session.commit()
    await db_session.refresh(proj)
    return proj


class TestAllocatorCap:
    @pytest.mark.asyncio
    async def test_allocator_raises_at_cap(
        self,
        db_session,
        test_tenant_key: str,
        active_product: Product,
    ):
        await _seed_project_at(db_session, test_tenant_key, active_product.id, MAX_SERIES_NUMBER)

        repo = ProjectRepository()
        with pytest.raises(ValidationError, match="exhausted"):
            await repo.get_next_series_number_shared(db_session, test_tenant_key, active_product.id)

    @pytest.mark.asyncio
    async def test_allocator_allows_below_cap(
        self,
        db_session,
        test_tenant_key: str,
        active_product: Product,
    ):
        await _seed_project_at(db_session, test_tenant_key, active_product.id, MAX_SERIES_NUMBER - 1)

        repo = ProjectRepository()
        nxt = await repo.get_next_series_number_shared(db_session, test_tenant_key, active_product.id)
        assert nxt == MAX_SERIES_NUMBER


class TestConversionFallbackCap:
    @pytest.mark.asyncio
    async def test_untyped_conversion_gated_at_cap(
        self,
        db_manager,
        db_session,
        test_tenant_key: str,
        active_product: Product,
    ):
        from giljo_mcp.tenant import TenantManager

        tm = TenantManager()
        tm.set_current_tenant(test_tenant_key)
        conversion_service = TaskConversionService(db_manager=db_manager, tenant_manager=tm, session=db_session)

        user = User(
            id=str(uuid4()),
            tenant_key=test_tenant_key,
            username=f"u_{uuid4().hex[:8]}",
            email=f"{uuid4().hex[:8]}@test.local",
            role="admin",
        )
        db_session.add(user)
        await _seed_project_at(db_session, test_tenant_key, active_product.id, MAX_SERIES_NUMBER)

        task = Task(
            id=str(uuid4()),
            tenant_key=test_tenant_key,
            product_id=active_product.id,
            title="untyped at cap",
            description="legacy untyped task to convert when serial space is exhausted",
            status="pending",
            priority="medium",
            created_by_user_id=user.id,
        )
        db_session.add(task)
        await db_session.commit()
        await db_session.refresh(task)

        with pytest.raises(ValidationError, match="exhausted"):
            await conversion_service.convert_to_project(
                task_id=task.id,
                project_name=None,
                strategy="single",
                include_subtasks=False,
                user_id=user.id,
            )

        refreshed = (await db_session.execute(select(Task).where(Task.id == task.id))).scalar_one()
        assert refreshed.converted_to_project_id is None
