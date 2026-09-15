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
from giljo_mcp.services.task_conversion_service import TaskConversionService


@pytest_asyncio.fixture
async def conversion_service(db_manager, db_session, test_tenant_key):
    from giljo_mcp.tenant import TenantManager

    tm = TenantManager()
    tm.set_current_tenant(test_tenant_key)
    return TaskConversionService(db_manager=db_manager, tenant_manager=tm, session=db_session)


async def _admin(db_session, tenant_key: str) -> User:
    u = User(
        id=str(uuid4()),
        tenant_key=tenant_key,
        username=f"u_{uuid4().hex[:8]}",
        email=f"{uuid4().hex[:8]}@test.local",
        role="admin",
    )
    db_session.add(u)
    await db_session.commit()
    await db_session.refresh(u)
    return u


async def _product(db_session, tenant_key: str, *, is_active: bool) -> Product:
    p = Product(
        id=str(uuid4()),
        name=f"P {uuid4().hex[:6]}",
        description="be9415 conversion product",
        tenant_key=tenant_key,
        is_active=is_active,
    )
    db_session.add(p)
    await db_session.commit()
    await db_session.refresh(p)
    return p


async def _task_on(
    db_session,
    tenant_key: str,
    product: Product,
    user: User,
    *,
    series_number: int | None,
) -> Task:
    t = Task(
        id=str(uuid4()),
        tenant_key=tenant_key,
        product_id=product.id,
        title=f"promote me {uuid4().hex[:6]}",
        description="task that outgrew being a task",
        status="pending",
        priority="medium",
        created_by_user_id=user.id,
        series_number=series_number,
    )
    db_session.add(t)
    await db_session.commit()
    await db_session.refresh(t)
    return t


async def _get_project(db_session, project_id: str) -> Project:
    return (await db_session.execute(select(Project).where(Project.id == project_id))).scalar_one()


class TestConversionBindsToTheTasksProduct:

    @pytest.mark.asyncio
    async def test_conversion_lands_on_the_tasks_product_not_the_active_one(
        self,
        conversion_service: TaskConversionService,
        db_session,
        test_tenant_key: str,
    ):
        user = await _admin(db_session, test_tenant_key)
        owner = await _product(db_session, test_tenant_key, is_active=False)
        active = await _product(db_session, test_tenant_key, is_active=True)

        task = await _task_on(db_session, test_tenant_key, owner, user, series_number=17)

        result = await conversion_service.convert_to_project(
            task_id=task.id,
            project_name=None,
            strategy="single",
            include_subtasks=False,
            user_id=user.id,
        )

        project = await _get_project(db_session, result.project_id)
        assert project.product_id == owner.id, (
            "the promoted project must bind to the TASK's product; binding to the "
            "ambient active product is the BE-9415 misfile"
        )
        assert project.product_id != active.id

    @pytest.mark.asyncio
    async def test_result_echoes_the_bound_product(
        self,
        conversion_service: TaskConversionService,
        db_session,
        test_tenant_key: str,
    ):
        user = await _admin(db_session, test_tenant_key)
        owner = await _product(db_session, test_tenant_key, is_active=False)
        await _product(db_session, test_tenant_key, is_active=True)

        task = await _task_on(db_session, test_tenant_key, owner, user, series_number=23)

        result = await conversion_service.convert_to_project(
            task_id=task.id,
            project_name=None,
            strategy="single",
            include_subtasks=False,
            user_id=user.id,
        )

        assert result.product_id == owner.id
        assert result.product_name == owner.name

    @pytest.mark.asyncio
    async def test_serial_is_allocated_in_the_tasks_product_namespace(
        self,
        conversion_service: TaskConversionService,
        db_session,
        test_tenant_key: str,
    ):
        user = await _admin(db_session, test_tenant_key)
        owner = await _product(db_session, test_tenant_key, is_active=False)
        active = await _product(db_session, test_tenant_key, is_active=True)

        await _task_on(db_session, test_tenant_key, owner, user, series_number=5)
        await _task_on(db_session, test_tenant_key, active, user, series_number=50)

        task = await _task_on(db_session, test_tenant_key, owner, user, series_number=None)

        result = await conversion_service.convert_to_project(
            task_id=task.id,
            project_name=None,
            strategy="single",
            include_subtasks=False,
            user_id=user.id,
        )

        project = await _get_project(db_session, result.project_id)
        assert project.product_id == owner.id
        assert project.series_number == 6, (
            "the serial must come from the task's product bucket (max 5 -> 6); "
            "51 means it was drawn from the active product's counter"
        )

    @pytest.mark.asyncio
    async def test_same_serial_in_the_active_product_still_lands_on_the_tasks_product(
        self,
        conversion_service: TaskConversionService,
        db_session,
        test_tenant_key: str,
    ):
        user = await _admin(db_session, test_tenant_key)
        owner = await _product(db_session, test_tenant_key, is_active=False)
        active = await _product(db_session, test_tenant_key, is_active=True)

        occupant = Project(
            id=str(uuid4()),
            name="already here",
            description="untyped project squatting on serial 42",
            mission="",
            tenant_key=test_tenant_key,
            product_id=active.id,
            status="inactive",
            project_type_id=None,
            series_number=42,
        )
        db_session.add(occupant)
        await db_session.commit()

        task = await _task_on(db_session, test_tenant_key, owner, user, series_number=42)

        result = await conversion_service.convert_to_project(
            task_id=task.id,
            project_name=None,
            strategy="single",
            include_subtasks=False,
            user_id=user.id,
        )

        project = await _get_project(db_session, result.project_id)
        assert project.product_id == owner.id
        assert project.series_number == 42

    @pytest.mark.asyncio
    async def test_unresolvable_product_on_the_task_is_a_loud_rejection(
        self,
        conversion_service: TaskConversionService,
        db_session,
        test_tenant_key: str,
    ):
        from datetime import UTC, datetime

        user = await _admin(db_session, test_tenant_key)
        owner = await _product(db_session, test_tenant_key, is_active=False)
        await _product(db_session, test_tenant_key, is_active=True)

        task = await _task_on(db_session, test_tenant_key, owner, user, series_number=7)

        owner.deleted_at = datetime.now(UTC)
        await db_session.commit()

        with pytest.raises(ValidationError) as exc:
            await conversion_service.convert_to_project(
                task_id=task.id,
                project_name=None,
                strategy="single",
                include_subtasks=False,
                user_id=user.id,
            )

        assert owner.id in str(exc.value), "the rejection must name the product that failed to resolve"

        projects = (
            (await db_session.execute(select(Project).where(Project.tenant_key == test_tenant_key))).scalars().all()
        )
        assert projects == []
        surviving = (await db_session.execute(select(Task).where(Task.id == task.id))).scalar_one_or_none()
        assert surviving is not None
