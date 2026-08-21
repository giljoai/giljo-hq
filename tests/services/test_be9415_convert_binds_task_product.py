# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-9415: converting a task must bind the new project to the TASK's product.

Defect: ``TaskConversionService._convert_to_project_impl`` resolved the
destination product from ``get_active_product`` -- tenant-global *mutable* state
that another session, or the operator switching products in the dashboard,
changes under a running agent. So promoting a task filed the resulting project
onto whichever product happened to be active at that instant, not the product
the task itself belongs to. Same silent-misfile class BE-9411 closed for the
create tools; this is the second instance.

``tasks.product_id`` is ``nullable=False`` (Handover 0433), so the task always
names exactly one product and the binding needs no fallback.

Three sites had to move together, and the ``product_id`` assertion alone would
not have caught two of them: the destination product also feeds
``lock_rows_for_series_shared`` / ``get_next_series_number_shared``, which
allocate ``series_number`` from the ``(tenant_key, product_id)`` bucket
(BE-6049b -- ONE counter per product, shared by tasks and projects). Minting on
the wrong product therefore drew the serial from the wrong namespace too, which
is why ``test_serial_is_allocated_in_the_tasks_product_namespace`` and
``test_same_serial_in_the_active_product_still_lands_on_the_tasks_product``
exist alongside the binding test.
"""

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
    """A product for this tenant.

    Exactly ONE may be active per tenant in any given test: the buggy lookup is
    ``scalar_one_or_none()`` over ``Product.is_active``, so two active rows would
    raise ``MultipleResultsFound`` and the test would fail for the wrong reason.
    """
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
    """The task's own product decides where the promoted project lands."""

    @pytest.mark.asyncio
    async def test_conversion_lands_on_the_tasks_product_not_the_active_one(
        self,
        conversion_service: TaskConversionService,
        db_session,
        test_tenant_key: str,
    ):
        """THE regression: a conversion run while a DIFFERENT product is active
        lands on the task's product.

        RED before the fix -- the project is created on ``active`` (the ambient
        product) instead of ``owner`` (the task's own).
        """
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
        """BE-9411's contract: the response NAMES where the entity landed, so a
        caller can self-check the filing for the cost of one field read."""
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
        """Sites 2/3: a serial-less task draws its number from ITS OWN product's
        counter, not the active product's.

        ``series_number`` is one monotonic counter per ``(tenant_key,
        product_id)`` shared across tasks and projects (BE-6049b). Seeding the
        two products to different high-water marks makes the allocated number
        name which bucket was used -- an assertion on ``product_id`` alone would
        pass even with the serial drawn from the wrong namespace.
        """
        user = await _admin(db_session, test_tenant_key)
        owner = await _product(db_session, test_tenant_key, is_active=False)
        active = await _product(db_session, test_tenant_key, is_active=True)

        # Distinct high-water marks: owner -> next is 6, active -> next is 51.
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
        """The worst-case shape of the misfile: the active product ALREADY holds
        an untyped project at the serial the task is carrying.

        Binding to the task's own product is collision-free by construction --
        the shared ``(tenant_key, product_id)`` allocator (BE-6049b) gave that
        number to the task within that product, so nothing else there holds it.

        Deliberately NOT asserted here: that the pre-fix path *raises*. On a
        migrated database ``uq_project_taxonomy_active`` carries NULLS NOT
        DISTINCT, so two untyped projects at one serial in one product do
        collide -- but the pytest schema is built from the SQLAlchemy models,
        whose ``Index`` declaration omits ``postgresql_nulls_not_distinct``, and
        under standard SQL semantics NULL ``project_type_id`` rows never
        conflict. Measured, not assumed: ``giljo_mcp_test`` has the index WITHOUT
        the clause and ``giljo_mcp_ce`` (migration-built) WITH it. So the raise
        is unreproducible in this suite for a reason that has nothing to do with
        this fix; asserting it would pin an environment artefact. This test
        therefore pins the binding only, which IS red on the pre-fix path.
        """
        user = await _admin(db_session, test_tenant_key)
        owner = await _product(db_session, test_tenant_key, is_active=False)
        active = await _product(db_session, test_tenant_key, is_active=True)

        # The active product already holds an UNTYPED project at serial 42.
        occupant = Project(
            id=str(uuid4()),
            name="already here",
            description="untyped project squatting on serial 42",
            mission="",  # NOT NULL on projects
            tenant_key=test_tenant_key,
            product_id=active.id,
            status="inactive",
            project_type_id=None,
            series_number=42,
        )
        db_session.add(occupant)
        await db_session.commit()

        # A task in the OTHER product legitimately holding the same number.
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
        """A task whose product no longer resolves is REFUSED by name -- it never
        silently falls back to the active product.

        Soft-deleting the product is the reachable form of this: the FK is
        ON DELETE CASCADE, so a hard-deleted product takes its tasks with it,
        but a soft-deleted one leaves the task pointing at a row the
        tenant-scoped lookup excludes.
        """
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

        # Nothing written: no project, and the task row survives.
        projects = (
            (await db_session.execute(select(Project).where(Project.tenant_key == test_tenant_key))).scalars().all()
        )
        assert projects == []
        surviving = (await db_session.execute(select(Task).where(Task.id == task.id))).scalar_one_or_none()
        assert surviving is not None
