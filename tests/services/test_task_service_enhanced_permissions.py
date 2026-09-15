# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import random
from datetime import UTC, datetime
from uuid import uuid4

import bcrypt
import pytest
import pytest_asyncio

from giljo_mcp.models.auth import User
from giljo_mcp.models.projects import Project
from giljo_mcp.models.tasks import Task




@pytest_asyncio.fixture
async def test_project(db_session, test_tenant_key, test_product):
    project = Project(
        id=str(uuid4()),
        name=f"Test Project {uuid4().hex[:6]}",
        description="Test project for task tests",
        mission="Test mission",
        product_id=test_product.id,
        tenant_key=test_tenant_key,
        status="active",
        created_at=datetime.now(UTC),
        series_number=random.randint(1, 9000),
    )
    db_session.add(project)
    await db_session.commit()
    await db_session.refresh(project)
    return project


@pytest_asyncio.fixture
async def test_task(db_session, test_tenant_key, test_product, test_project, test_user):
    task = Task(
        id=str(uuid4()),
        tenant_key=test_tenant_key,
        product_id=test_product.id,
        project_id=test_project.id,
        title="Test Task",
        description="Test task description",
        status="waiting",
        priority="medium",
        created_by_user_id=test_user.id,
        created_at=datetime.now(UTC),
    )
    db_session.add(task)
    await db_session.commit()
    await db_session.refresh(task)
    return task




@pytest.mark.asyncio
async def test_can_delete_task_as_creator(task_service, test_task, test_user):
    can_delete = task_service._conversion.can_delete_task(test_task, test_user)
    assert can_delete is True


@pytest.mark.asyncio
async def test_can_delete_task_as_admin(task_service, test_task, admin_user):
    can_delete = task_service._conversion.can_delete_task(test_task, admin_user)
    assert can_delete is True


@pytest.mark.asyncio
async def test_can_delete_task_denied(task_service, test_task, db_session, test_tenant_key):
    other_user = User(
        id=str(uuid4()),
        username=f"otherdev_{uuid4().hex[:6]}",
        email=f"otherdev_{uuid4().hex[:6]}@example.com",
        password_hash=bcrypt.hashpw(b"Password123", bcrypt.gensalt()).decode("utf-8"),
        role="developer",
        tenant_key=test_tenant_key,
        is_active=True,
    )
    db_session.add(other_user)
    await db_session.commit()

    can_delete = task_service._conversion.can_delete_task(test_task, other_user)
    assert can_delete is False
