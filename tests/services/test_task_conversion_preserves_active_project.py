# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-6033: Task → Project conversion must not deactivate the active project.

Regression: ``TaskConversionService`` previously deactivated the product's
currently-active project before creating the new (inactive) project, leaving the
product with ZERO active projects after a promotion. The new project is created
INACTIVE, so there is nothing to make room for regardless of how many other
projects in the product are active (BE-9525b dropped the one-active-per-product
limit; this was never index-enforced from conversion's side even before that —
only the user activates/deactivates a project, conversion never does).
"""

from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import select

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


async def _active_product(db_session, tenant_key: str) -> Product:
    p = Product(
        id=str(uuid4()),
        name=f"P {uuid4().hex[:6]}",
        description="conv test product",
        tenant_key=tenant_key,
        is_active=True,
    )
    db_session.add(p)
    await db_session.commit()
    await db_session.refresh(p)
    return p


@pytest.mark.asyncio
async def test_conversion_leaves_existing_active_project_active(
    conversion_service: TaskConversionService,
    db_session,
    test_tenant_key: str,
):
    """Promoting a task must NOT touch the product's currently-active project."""
    user = await _admin(db_session, test_tenant_key)
    product = await _active_product(db_session, test_tenant_key)

    # An existing ACTIVE project the user is working in.
    active_project = Project(
        id=str(uuid4()),
        tenant_key=test_tenant_key,
        product_id=product.id,
        name="Active work",
        description="user is mid-flight here",
        mission="keep me active",
        status="active",
        series_number=101,
    )
    db_session.add(active_project)

    task = Task(
        id=str(uuid4()),
        tenant_key=test_tenant_key,
        product_id=product.id,
        title="promote me",
        description="task to be converted",
        status="pending",
        priority="medium",
        created_by_user_id=user.id,
    )
    db_session.add(task)
    await db_session.commit()
    await db_session.refresh(task)
    await db_session.refresh(active_project)

    result = await conversion_service.convert_to_project(
        task_id=task.id,
        project_name=None,
        strategy="single",
        include_subtasks=False,
        user_id=user.id,
    )

    # The pre-existing active project is untouched.
    await db_session.refresh(active_project)
    assert active_project.status == "active", (
        f"Promoting a task must not deactivate the currently-active project; got status '{active_project.status}'"
    )

    # The new project is born inactive (user activates when ready).
    new_project = (await db_session.execute(select(Project).where(Project.id == result.project_id))).scalar_one()
    assert new_project.status == "inactive"

    # Product still has exactly one active project — the original.
    active_rows = (
        (
            await db_session.execute(
                select(Project).where(
                    Project.product_id == product.id,
                    Project.status == "active",
                    Project.tenant_key == test_tenant_key,
                )
            )
        )
        .scalars()
        .all()
    )
    assert [p.id for p in active_rows] == [active_project.id]
