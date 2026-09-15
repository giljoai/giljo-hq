# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import random
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch
from uuid import uuid4

import bcrypt
import pytest
import pytest_asyncio

from giljo_mcp.exceptions import (
    AuthorizationError,
    BaseGiljoError,
    ResourceNotFoundError,
    ValidationError,
)
from giljo_mcp.models.auth import User
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




@pytest.mark.asyncio
async def test_delete_task_raises_validation_error_no_tenant_context(db_manager, db_session):
    tenant_manager = MagicMock()
    tenant_manager.get_current_tenant.return_value = None

    service = TaskService(db_manager=db_manager, tenant_manager=tenant_manager, session=db_session)

    with pytest.raises(ValidationError) as exc_info:
        await service.delete_task(task_id=str(uuid4()), user_id=str(uuid4()))

    assert "No tenant context available" in str(exc_info.value)
    assert exc_info.value.context.get("operation") == "delete_task"


@pytest.mark.asyncio
async def test_delete_task_raises_not_found_on_nonexistent_task(task_service, test_user):
    nonexistent_task_id = str(uuid4())

    with pytest.raises(ResourceNotFoundError) as exc_info:
        await task_service.delete_task(task_id=nonexistent_task_id, user_id=test_user.id)

    assert "Task not found" in str(exc_info.value)


@pytest.mark.asyncio
async def test_delete_task_raises_not_found_on_nonexistent_user(task_service, test_task):
    nonexistent_user_id = str(uuid4())

    with pytest.raises(ResourceNotFoundError) as exc_info:
        await task_service.delete_task(task_id=test_task.id, user_id=nonexistent_user_id)

    assert "User not found" in str(exc_info.value)


@pytest.mark.asyncio
async def test_delete_task_raises_authorization_error_insufficient_permissions(
    task_service, test_task, db_session, test_tenant_key
):
    other_user = User(
        id=str(uuid4()),
        username=f"otheruser_{uuid4().hex[:6]}",
        email=f"other_{uuid4().hex[:6]}@example.com",
        password_hash=bcrypt.hashpw(b"OtherPassword123", bcrypt.gensalt()).decode("utf-8"),
        full_name="Other User",
        role="developer",
        tenant_key=test_tenant_key,
        is_active=True,
        created_at=datetime.now(UTC),
    )
    db_session.add(other_user)
    await db_session.commit()
    await db_session.refresh(other_user)

    with pytest.raises(AuthorizationError) as exc_info:
        await task_service.delete_task(task_id=test_task.id, user_id=other_user.id)

    assert "Not authorized to delete this task" in str(exc_info.value)


@pytest.mark.asyncio
async def test_delete_task_raises_exception_on_database_error(task_service):
    with patch.object(task_service, "_delete_task_impl", side_effect=Exception("DB error")):
        with pytest.raises(BaseGiljoError) as exc_info:
            await task_service.delete_task(task_id=str(uuid4()), user_id=str(uuid4()))

        assert "DB error" in str(exc_info.value)




@pytest.mark.asyncio
async def test_convert_to_project_raises_validation_error_no_tenant_context(db_manager, db_session):
    tenant_manager = MagicMock()
    tenant_manager.get_current_tenant.return_value = None

    service = TaskService(db_manager=db_manager, tenant_manager=tenant_manager, session=db_session)

    with pytest.raises(ValidationError) as exc_info:
        await service.convert_to_project(
            task_id=str(uuid4()),
            project_name="Test Project",
            strategy="create_new",
            include_subtasks=False,
            user_id=str(uuid4()),
        )

    assert "No tenant context available" in str(exc_info.value)
    assert exc_info.value.context.get("operation") == "convert_to_project"


@pytest.mark.asyncio
async def test_convert_to_project_raises_not_found_on_nonexistent_task(task_service, test_user):
    nonexistent_task_id = str(uuid4())

    with pytest.raises(ResourceNotFoundError) as exc_info:
        await task_service.convert_to_project(
            task_id=nonexistent_task_id,
            project_name="Test Project",
            strategy="create_new",
            include_subtasks=False,
            user_id=test_user.id,
        )

    assert "Task not found" in str(exc_info.value)


@pytest.mark.asyncio
async def test_convert_to_project_raises_validation_error_already_converted(
    task_service, test_task, test_user, db_session, test_product, test_tenant_key
):
    converted_project = Project(
        id=str(uuid4()),
        name=f"Converted Project {uuid4().hex[:6]}",
        description="Previously converted project",
        mission="Test mission",
        product_id=test_product.id,
        tenant_key=test_tenant_key,
        status="inactive",
        created_at=datetime.now(UTC),
        series_number=random.randint(1, 9000),
    )
    db_session.add(converted_project)
    await db_session.flush()

    test_task.converted_to_project_id = converted_project.id
    await db_session.flush()

    with pytest.raises(ValidationError) as exc_info:
        await task_service.convert_to_project(
            task_id=test_task.id,
            project_name="Test Project",
            strategy="create_new",
            include_subtasks=False,
            user_id=test_user.id,
        )

    assert f"Task already converted to project {test_task.converted_to_project_id}" in str(exc_info.value)


@pytest.mark.asyncio
async def test_convert_to_project_raises_not_found_on_nonexistent_user(task_service, test_task):
    nonexistent_user_id = str(uuid4())

    with pytest.raises(ResourceNotFoundError) as exc_info:
        await task_service.convert_to_project(
            task_id=test_task.id,
            project_name="Test Project",
            strategy="create_new",
            include_subtasks=False,
            user_id=nonexistent_user_id,
        )

    assert "User not found" in str(exc_info.value)


@pytest.mark.asyncio
async def test_convert_to_project_raises_authorization_error_insufficient_permissions(
    task_service, test_task, db_session, test_tenant_key
):
    other_user = User(
        id=str(uuid4()),
        username=f"otheruser_{uuid4().hex[:6]}",
        email=f"other_{uuid4().hex[:6]}@example.com",
        password_hash=bcrypt.hashpw(b"OtherPassword123", bcrypt.gensalt()).decode("utf-8"),
        full_name="Other User",
        role="developer",
        tenant_key=test_tenant_key,
        is_active=True,
        created_at=datetime.now(UTC),
    )
    db_session.add(other_user)
    await db_session.commit()
    await db_session.refresh(other_user)

    with pytest.raises(AuthorizationError) as exc_info:
        await task_service.convert_to_project(
            task_id=test_task.id,
            project_name="Test Project",
            strategy="create_new",
            include_subtasks=False,
            user_id=other_user.id,
        )

    assert "Not authorized to convert this task" in str(exc_info.value)


@pytest.mark.asyncio
async def test_convert_to_project_succeeds_onto_an_inactive_product(
    task_service, test_task, test_user, test_product, db_session
):
    test_product.is_active = False
    await db_session.commit()

    result = await task_service.convert_to_project(
        task_id=test_task.id,
        project_name="Test Project",
        strategy="create_new",
        include_subtasks=False,
        user_id=test_user.id,
    )

    assert result.product_id == test_product.id
    assert result.product_name == test_product.name


@pytest.mark.asyncio
async def test_convert_to_project_raises_exception_on_database_error(task_service):
    with patch.object(task_service._conversion, "_convert_to_project_impl", side_effect=Exception("DB error")):
        with pytest.raises(BaseGiljoError) as exc_info:
            await task_service.convert_to_project(
                task_id=str(uuid4()),
                project_name="Test",
                strategy="create_new",
                include_subtasks=False,
                user_id=str(uuid4()),
            )

        assert "DB error" in str(exc_info.value)




@pytest.mark.asyncio
async def test_change_status_raises_validation_error_no_tenant_context(db_manager, db_session):
    tenant_manager = MagicMock()
    tenant_manager.get_current_tenant.return_value = None

    service = TaskService(db_manager=db_manager, tenant_manager=tenant_manager, session=db_session)

    with pytest.raises(ValidationError) as exc_info:
        await service.change_status(task_id=str(uuid4()), new_status="completed")

    assert "No tenant context available" in str(exc_info.value)
    assert exc_info.value.context.get("operation") == "change_status"


@pytest.mark.asyncio
async def test_change_status_raises_not_found_on_nonexistent_task(task_service):
    nonexistent_task_id = str(uuid4())

    with pytest.raises(ResourceNotFoundError) as exc_info:
        await task_service.change_status(task_id=nonexistent_task_id, new_status="completed")

    assert "Task not found" in str(exc_info.value)
    assert exc_info.value.context.get("task_id") == nonexistent_task_id


@pytest.mark.asyncio
async def test_change_status_raises_exception_on_database_error(task_service):
    with patch.object(task_service, "_change_status_impl", side_effect=Exception("DB error")):
        with pytest.raises(BaseGiljoError) as exc_info:
            await task_service.change_status(task_id=str(uuid4()), new_status="completed")

        assert "DB error" in str(exc_info.value)




@pytest.mark.asyncio
async def test_get_summary_raises_validation_error_no_tenant_context(db_manager, db_session):
    tenant_manager = MagicMock()
    tenant_manager.get_current_tenant.return_value = None

    service = TaskService(db_manager=db_manager, tenant_manager=tenant_manager, session=db_session)

    with pytest.raises(ValidationError) as exc_info:
        await service.get_summary()

    assert "No tenant context available" in str(exc_info.value)
    assert exc_info.value.context.get("operation") == "get_summary"


@pytest.mark.asyncio
async def test_get_summary_raises_exception_on_database_error(task_service):
    with patch.object(task_service._conversion, "_get_summary_impl", side_effect=Exception("DB error")):
        with pytest.raises(BaseGiljoError) as exc_info:
            await task_service.get_summary()

        assert "DB error" in str(exc_info.value)
