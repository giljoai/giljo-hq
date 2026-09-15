# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import random
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
import pytest_asyncio

from giljo_mcp.exceptions import (
    BaseGiljoError,
    ResourceNotFoundError,
    ValidationError,
)
from giljo_mcp.models.projects import Project
from giljo_mcp.models.tasks import Task
from giljo_mcp.services.task_service import TaskService




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
        created_by_user_id=test_user.id,
        title="Test Task",
        description="Test task description",
        status="pending",
        priority="medium",
        created_at=datetime.now(UTC),
    )
    db_session.add(task)
    await db_session.commit()
    await db_session.refresh(task)
    return task


@pytest_asyncio.fixture
async def tenant_manager(test_tenant_key):
    manager = MagicMock()
    manager.get_current_tenant.return_value = test_tenant_key
    return manager




@pytest.mark.asyncio
async def test_log_task_raises_exception_on_database_error(task_service, tenant_manager):
    with patch.object(task_service, "_log_task_impl", side_effect=Exception("Database connection failed")):
        with pytest.raises(BaseGiljoError) as exc_info:
            await task_service.log_task(content="Test task")

        assert "Database connection failed" in str(exc_info.value)
        assert exc_info.value.context.get("operation") == "log_task"


@pytest.mark.asyncio
async def test_log_task_impl_raises_not_found_on_nonexistent_project(task_service, test_tenant_key, test_product):
    nonexistent_project_id = str(uuid4())

    with pytest.raises(ResourceNotFoundError) as exc_info:
        await task_service.log_task(
            content="Test task",
            project_id=nonexistent_project_id,
            product_id=test_product.id,
            tenant_key=test_tenant_key,
        )

    assert f"Project {nonexistent_project_id} not found" in str(exc_info.value)




@pytest.mark.asyncio
async def test_list_tasks_raises_validation_error_no_tenant_context(db_manager):
    tenant_manager = MagicMock()
    tenant_manager.get_current_tenant.return_value = None

    service = TaskService(db_manager=db_manager, tenant_manager=tenant_manager)

    with pytest.raises(ValidationError) as exc_info:
        await service.list_tasks()

    assert "No tenant context available" in str(exc_info.value)
    assert exc_info.value.context.get("operation") == "list_tasks"


@pytest.mark.asyncio
async def test_list_tasks_raises_exception_on_database_error(task_service):
    with patch.object(task_service, "_list_tasks_impl", side_effect=Exception("DB error")):
        with pytest.raises(BaseGiljoError) as exc_info:
            await task_service.list_tasks()

        assert "DB error" in str(exc_info.value)




@pytest.mark.asyncio
async def test_update_task_raises_not_found_on_nonexistent_task(task_service):
    nonexistent_task_id = str(uuid4())

    with pytest.raises(ResourceNotFoundError) as exc_info:
        await task_service.update_task(task_id=nonexistent_task_id, status="completed")

    assert "not found" in str(exc_info.value).lower() or "access denied" in str(exc_info.value).lower()


@pytest.mark.asyncio
async def test_update_task_raises_exception_on_database_error(task_service):
    with patch.object(task_service, "_update_task_impl", side_effect=Exception("DB error")):
        with pytest.raises(BaseGiljoError) as exc_info:
            await task_service.update_task(task_id=str(uuid4()), status="completed")

        assert "DB error" in str(exc_info.value)




@pytest.mark.asyncio
async def test_get_task_raises_validation_error_no_tenant_context(db_manager, db_session):
    tenant_manager = MagicMock()
    tenant_manager.get_current_tenant.return_value = None

    service = TaskService(db_manager=db_manager, tenant_manager=tenant_manager, session=db_session)

    with pytest.raises(ValidationError) as exc_info:
        await service.get_task(task_id=str(uuid4()))

    assert "No tenant context available" in str(exc_info.value)
    assert exc_info.value.context.get("operation") == "get_task"


@pytest.mark.asyncio
async def test_get_task_raises_not_found_on_nonexistent_task(task_service):
    nonexistent_task_id = str(uuid4())

    with pytest.raises(ResourceNotFoundError) as exc_info:
        await task_service.get_task(task_id=nonexistent_task_id)

    assert "Task not found" in str(exc_info.value)
    assert exc_info.value.context.get("task_id") == nonexistent_task_id


@pytest.mark.asyncio
async def test_get_task_raises_exception_on_database_error(task_service):
    with patch.object(task_service, "_get_task_impl", side_effect=Exception("DB error")):
        with pytest.raises(BaseGiljoError) as exc_info:
            await task_service.get_task(task_id=str(uuid4()))

        assert "DB error" in str(exc_info.value)
