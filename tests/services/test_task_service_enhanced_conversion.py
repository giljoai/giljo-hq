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

from giljo_mcp.exceptions import AuthorizationError
from giljo_mcp.models.auth import User
from giljo_mcp.models.projects import Project
from giljo_mcp.models.tasks import Task
from giljo_mcp.schemas.service_responses import ConversionResult




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
async def test_convert_to_project_basic(task_service, test_task, test_user, db_session, test_product):
    result = await task_service.convert_to_project(
        task_id=str(test_task.id),
        project_name="New Project from Task",
        strategy="create_new",
        include_subtasks=False,
        user_id=str(test_user.id),
    )

    assert isinstance(result, ConversionResult)
    assert result.task_id == str(test_task.id)
    assert result.project_id is not None
    assert result.project_name == "New Project from Task"

    stmt = select(Project).where(Project.id == result.project_id)
    db_result = await db_session.execute(stmt)
    new_project = db_result.scalar_one_or_none()

    assert new_project is not None
    assert new_project.name == "New Project from Task"
    assert new_project.product_id == test_product.id


@pytest.mark.asyncio
async def test_convert_to_project_with_subtasks(
    task_service, test_task, test_user, db_session, test_tenant_key, test_product, test_project
):
    subtask1 = Task(
        id=str(uuid4()),
        tenant_key=test_tenant_key,
        product_id=test_product.id,
        project_id=test_project.id,
        parent_task_id=test_task.id,
        title="Subtask 1",
        description="First subtask",
        status="waiting",
        priority="low",
        created_by_user_id=test_user.id,
    )
    subtask2 = Task(
        id=str(uuid4()),
        tenant_key=test_tenant_key,
        product_id=test_product.id,
        project_id=test_project.id,
        parent_task_id=test_task.id,
        title="Subtask 2",
        description="Second subtask",
        status="waiting",
        priority="low",
        created_by_user_id=test_user.id,
    )
    db_session.add_all([subtask1, subtask2])
    await db_session.commit()

    result = await task_service.convert_to_project(
        task_id=str(test_task.id),
        project_name="Project with Subtasks",
        strategy="create_new",
        include_subtasks=True,
        user_id=str(test_user.id),
    )

    assert isinstance(result, ConversionResult)
    assert result.project_id is not None
    assert result.project_name == "Project with Subtasks"


@pytest.mark.asyncio
async def test_convert_to_project_permission_denied(task_service, test_task, db_session, test_tenant_key):
    other_user = User(
        id=str(uuid4()),
        username=f"unauthorized_{uuid4().hex[:6]}",
        email=f"unauth_{uuid4().hex[:6]}@example.com",
        password_hash=bcrypt.hashpw(b"Password123", bcrypt.gensalt()).decode("utf-8"),
        role="developer",
        tenant_key=test_tenant_key,
        is_active=True,
    )
    db_session.add(other_user)
    await db_session.commit()

    with pytest.raises(AuthorizationError) as exc_info:
        await task_service.convert_to_project(
            task_id=str(test_task.id),
            project_name="Unauthorized Project",
            strategy="create_new",
            include_subtasks=False,
            user_id=str(other_user.id),
        )

    assert "permission" in str(exc_info.value).lower() or "not authorized" in str(exc_info.value).lower()




@pytest.mark.asyncio
async def test_change_status_to_in_progress(task_service, test_task, db_session):
    assert test_task.started_at is None

    result = await task_service.change_status(task_id=str(test_task.id), new_status="in_progress")

    assert isinstance(result, Task)
    assert result.status == "in_progress"

    await db_session.refresh(test_task)
    assert test_task.started_at is not None


@pytest.mark.asyncio
async def test_change_status_to_completed(task_service, test_task, db_session):
    assert test_task.completed_at is None

    result = await task_service.change_status(task_id=str(test_task.id), new_status="completed")

    assert isinstance(result, Task)
    assert result.status == "completed"

    await db_session.refresh(test_task)
    assert test_task.completed_at is not None


@pytest.mark.asyncio
async def test_change_status_to_cancelled(task_service, test_task, db_session):
    assert test_task.completed_at is None

    result = await task_service.change_status(task_id=str(test_task.id), new_status="cancelled")

    assert isinstance(result, Task)
    assert result.status == "cancelled"

    await db_session.refresh(test_task)
    assert test_task.completed_at is not None


@pytest.mark.asyncio
async def test_change_status_invalid(task_service, test_task):
    result = await task_service.change_status(task_id=str(test_task.id), new_status="invalid_status_xyz")

    assert isinstance(result, Task)
    assert result.status == "invalid_status_xyz"




@pytest.mark.asyncio
async def test_get_summary_all_products(
    task_service, db_session, test_tenant_key, test_product, test_project, test_user
):
    tasks_data = [
        {"status": "pending", "priority": "high"},
        {"status": "in_progress", "priority": "medium"},
        {"status": "completed", "priority": "low"},
        {"status": "pending", "priority": "critical"},
    ]

    for task_data in tasks_data:
        task = Task(
            id=str(uuid4()),
            tenant_key=test_tenant_key,
            product_id=test_product.id,
            project_id=test_project.id,
            title=f"Task {task_data['status']}",
            description=f"Task with status {task_data['status']}",
            status=task_data["status"],
            priority=task_data["priority"],
            created_by_user_id=test_user.id,
        )
        db_session.add(task)

    await db_session.commit()

    summary = await task_service.get_summary(product_id=None)

    assert summary is not None
    assert "summary" in summary
    assert "total_products" in summary
    assert "total_tasks" in summary


@pytest.mark.asyncio
async def test_get_summary_filtered_by_product(
    task_service, db_session, test_tenant_key, test_product, test_project, test_user
):
    task1 = Task(
        id=str(uuid4()),
        tenant_key=test_tenant_key,
        product_id=test_product.id,
        project_id=test_project.id,
        title="Product Task",
        description="Task for specific product",
        status="waiting",
        priority="high",
        created_by_user_id=test_user.id,
    )
    db_session.add(task1)
    await db_session.commit()

    summary = await task_service.get_summary(product_id=str(test_product.id))

    assert summary is not None
    assert "summary" in summary
