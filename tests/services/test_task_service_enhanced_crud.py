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
from sqlalchemy import select

from giljo_mcp.exceptions import AuthorizationError, ResourceNotFoundError
from giljo_mcp.models.auth import User
from giljo_mcp.models.projects import Project
from giljo_mcp.models.tasks import Task
from giljo_mcp.schemas.service_responses import TaskUpdateResult




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
async def test_get_task_success(task_service, test_task):
    result = await task_service.get_task(task_id=str(test_task.id))

    assert isinstance(result, Task)
    assert str(result.id) == str(test_task.id)
    assert result.title == "Test Task"
    assert result.status == "waiting"


@pytest.mark.asyncio
async def test_get_task_not_found(task_service):
    fake_id = str(uuid4())

    with pytest.raises(ResourceNotFoundError) as exc_info:
        await task_service.get_task(task_id=fake_id)

    assert "not found" in str(exc_info.value).lower()


@pytest.mark.asyncio
async def test_get_task_tenant_isolation(task_service, other_tenant_task):
    with pytest.raises(ResourceNotFoundError) as exc_info:
        await task_service.get_task(task_id=str(other_tenant_task.id))

    assert "not found" in str(exc_info.value).lower()




@pytest.mark.asyncio
async def test_delete_task_success_as_creator(task_service, test_task, test_user, db_session):
    result = await task_service.delete_task(task_id=str(test_task.id), user_id=str(test_user.id))
    assert result is None

    stmt = select(Task).where(Task.id == test_task.id)
    db_result = await db_session.execute(stmt)
    soft_deleted = db_result.scalar_one_or_none()
    assert soft_deleted is not None
    assert soft_deleted.deleted_at is not None

    with pytest.raises(ResourceNotFoundError):
        await task_service.get_task(str(test_task.id))


@pytest.mark.asyncio
async def test_delete_task_success_as_admin(task_service, test_task, admin_user, db_session):
    result = await task_service.delete_task(task_id=str(test_task.id), user_id=str(admin_user.id))
    assert result is None

    stmt = select(Task).where(Task.id == test_task.id)
    db_result = await db_session.execute(stmt)
    soft_deleted = db_result.scalar_one_or_none()
    assert soft_deleted is not None
    assert soft_deleted.deleted_at is not None

    with pytest.raises(ResourceNotFoundError):
        await task_service.get_task(str(test_task.id))


@pytest.mark.asyncio
async def test_delete_task_permission_denied(task_service, test_task, db_session, test_tenant_key):
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

    with pytest.raises(AuthorizationError) as exc_info:
        await task_service.delete_task(task_id=str(test_task.id), user_id=str(other_user.id))

    assert "permission" in str(exc_info.value).lower() or "not authorized" in str(exc_info.value).lower()




@pytest.mark.asyncio
async def test_list_tasks_returns_task_list(task_service, test_task):
    result = await task_service.list_tasks()

    assert isinstance(result, list)
    assert len(result) >= 1
    assert all(isinstance(t, Task) for t in result)

    task_ids = [str(t.id) for t in result]
    assert str(test_task.id) in task_ids


@pytest.mark.asyncio
async def test_list_tasks_empty(task_service):
    result = await task_service.list_tasks()

    assert isinstance(result, list)
    assert len(result) == 0




@pytest.mark.asyncio
async def test_update_task_returns_typed_result(task_service, test_task):
    result = await task_service.update_task(task_id=str(test_task.id), status="in_progress", priority="high")

    assert isinstance(result, TaskUpdateResult)
    assert result.task_id == str(test_task.id)
    assert "status" in result.updated_fields
    assert "priority" in result.updated_fields




@pytest.mark.asyncio
async def test_create_task_returns_task_id(task_service, test_product, test_tenant_key):
    result = await task_service.create_task(
        title="New Task",
        description="A new task description",
        priority="high",
        product_id=test_product.id,
        tenant_key=test_tenant_key,
    )

    assert isinstance(result, str)
    assert len(result) > 0
