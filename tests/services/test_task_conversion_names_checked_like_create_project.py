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
async def conversion_setup(db_manager, tenant_manager, db_session, test_tenant_key):
    tenant_manager.set_current_tenant(test_tenant_key)
    user = User(
        id=str(uuid4()),
        tenant_key=test_tenant_key,
        username=f"u_{uuid4().hex[:8]}",
        email=f"{uuid4().hex[:8]}@test.local",
        role="admin",
    )
    product = Product(id=str(uuid4()), name=f"Product {uuid4().hex[:6]}", tenant_key=test_tenant_key)
    db_session.add_all([user, product])
    await db_session.flush()
    task = Task(
        id=str(uuid4()),
        tenant_key=test_tenant_key,
        product_id=product.id,
        title="Task to convert",
        status="pending",
        priority="medium",
        created_by_user_id=user.id,
    )
    db_session.add(task)
    await db_session.flush()
    service = TaskConversionService(db_manager=db_manager, tenant_manager=tenant_manager, session=db_session)
    return {"service": service, "user": user, "product": product, "task": task}


@pytest.mark.asyncio
@pytest.mark.parametrize("bad_name", ["   ", "x" * 256], ids=["blank", "over_255"])
async def test_conversion_refuses_a_name_create_project_refuses(conversion_setup, db_session, bad_name):
    setup = conversion_setup

    with pytest.raises(ValidationError):
        await setup["service"].convert_to_project(
            task_id=setup["task"].id,
            project_name=bad_name,
            strategy="single",
            include_subtasks=False,
            user_id=setup["user"].id,
        )

    projects = (await db_session.execute(select(Project).where(Project.product_id == setup["product"].id))).all()
    assert projects == []
