# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from unittest.mock import AsyncMock, MagicMock, Mock

import pytest

from giljo_mcp.exceptions import (
    AuthorizationError,
    ResourceNotFoundError,
    ValidationError,
)
from giljo_mcp.services.task_conversion_service import TaskConversionService



TENANT_KEY = "test-tenant"
TASK_ID = "task-001"
USER_ID = "user-001"


def _make_session():
    session = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    session.execute = AsyncMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    session.add = Mock()
    session.delete = AsyncMock()
    session.flush = AsyncMock()
    session.info = {}
    return session


def _make_task(
    task_id=TASK_ID,
    title="Fix bug",
    description="Fix the critical bug",
    tenant_key=TENANT_KEY,
    converted_to_project_id=None,
    created_by_user_id=USER_ID,
    status="pending",
    product_id="prod-1",
    priority="medium",
):
    task = MagicMock()
    task.id = task_id
    task.title = title
    task.description = description
    task.tenant_key = tenant_key
    task.converted_to_project_id = converted_to_project_id
    task.created_by_user_id = created_by_user_id
    task.status = status
    task.product_id = product_id
    task.priority = priority
    task.parent_task_id = None
    return task


def _make_user(
    user_id=USER_ID,
    role="developer",
    tenant_key=TENANT_KEY,
):
    user = MagicMock()
    user.id = user_id
    user.role = role
    user.tenant_key = tenant_key
    return user


def _make_product(product_id="prod-1", tenant_key=TENANT_KEY):
    product = MagicMock()
    product.id = product_id
    product.tenant_key = tenant_key
    product.is_active = True
    return product


def _make_service(session, tenant_key=TENANT_KEY):
    db_manager = Mock()
    db_manager.get_session_async = Mock(return_value=session)
    tenant_manager = Mock()
    tenant_manager.get_current_tenant = Mock(return_value=tenant_key)
    return TaskConversionService(
        db_manager=db_manager,
        tenant_manager=tenant_manager,
        session=session,
    )




class TestConvertToProject:

    @pytest.mark.asyncio
    async def test_convert_no_tenant_raises(self):
        session = _make_session()
        service = _make_service(session)
        service.tenant_manager.get_current_tenant.return_value = None

        with pytest.raises(ValidationError, match="No tenant context"):
            await service.convert_to_project(TASK_ID, None, "create_new", include_subtasks=False, user_id=USER_ID)

    @pytest.mark.asyncio
    async def test_convert_task_not_found_raises(self):
        session = _make_session()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        session.execute = AsyncMock(return_value=mock_result)

        service = _make_service(session)
        with pytest.raises(ResourceNotFoundError, match="Task not found"):
            await service.convert_to_project(TASK_ID, None, "create_new", include_subtasks=False, user_id=USER_ID)

    @pytest.mark.asyncio
    async def test_convert_already_converted_raises(self):
        task = _make_task(converted_to_project_id="existing-proj")
        session = _make_session()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = task
        session.execute = AsyncMock(return_value=mock_result)

        service = _make_service(session)
        with pytest.raises(ValidationError, match="already converted"):
            await service.convert_to_project(TASK_ID, None, "create_new", include_subtasks=False, user_id=USER_ID)

    @pytest.mark.asyncio
    async def test_convert_user_not_found_raises(self):
        task = _make_task()
        session = _make_session()

        call_count = 0
        mock_task_result = MagicMock()
        mock_task_result.scalar_one_or_none.return_value = task
        mock_no_user = MagicMock()
        mock_no_user.scalar_one_or_none.return_value = None

        async def side_effect(stmt):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return mock_task_result
            return mock_no_user

        session.execute = AsyncMock(side_effect=side_effect)

        service = _make_service(session)
        with pytest.raises(ResourceNotFoundError, match="User not found"):
            await service.convert_to_project(TASK_ID, None, "create_new", include_subtasks=False, user_id="nonexistent")

    @pytest.mark.asyncio
    async def test_convert_unauthorized_developer_raises(self):
        task = _make_task(created_by_user_id="other-user")
        user = _make_user(role="developer")

        session = _make_session()

        call_count = 0
        mock_task_result = MagicMock()
        mock_task_result.scalar_one_or_none.return_value = task
        mock_user_result = MagicMock()
        mock_user_result.scalar_one_or_none.return_value = user

        async def side_effect(stmt):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return mock_task_result
            return mock_user_result

        session.execute = AsyncMock(side_effect=side_effect)

        service = _make_service(session)
        with pytest.raises(AuthorizationError, match="Not authorized"):
            await service.convert_to_project(TASK_ID, None, "create_new", include_subtasks=False, user_id=USER_ID)

    @pytest.mark.asyncio
    async def test_convert_unresolvable_task_product_raises(self):
        task = _make_task()
        user = _make_user(role="admin")

        session = _make_session()

        call_count = 0
        mock_task_result = MagicMock()
        mock_task_result.scalar_one_or_none.return_value = task
        mock_user_result = MagicMock()
        mock_user_result.scalar_one_or_none.return_value = user
        mock_no_product = MagicMock()
        mock_no_product.scalar_one_or_none.return_value = None

        async def side_effect(stmt):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return mock_task_result
            if call_count == 2:
                return mock_user_result
            return mock_no_product

        session.execute = AsyncMock(side_effect=side_effect)

        service = _make_service(session)
        with pytest.raises(ValidationError, match="was not found for your account"):
            await service.convert_to_project(TASK_ID, None, "create_new", include_subtasks=False, user_id=USER_ID)




class TestGetSummary:

    @pytest.mark.asyncio
    async def test_summary_no_tenant_raises(self):
        session = _make_session()
        service = _make_service(session)
        service.tenant_manager.get_current_tenant.return_value = None

        with pytest.raises(ValidationError, match="No tenant context"):
            await service.get_summary()

    @pytest.mark.asyncio
    async def test_summary_empty_returns_zeros(self):
        session = _make_session()
        mock_result = MagicMock()
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = []
        mock_result.scalars.return_value = mock_scalars
        session.execute = AsyncMock(return_value=mock_result)

        service = _make_service(session)
        result = await service.get_summary()

        assert result["total_tasks"] == 0
        assert result["total_products"] == 0
        assert result["summary"] == {}

    @pytest.mark.asyncio
    async def test_summary_aggregates_by_product(self):
        task1 = _make_task(task_id="t1", product_id="prod-A", status="pending", priority="high")
        task2 = _make_task(task_id="t2", product_id="prod-A", status="completed", priority="low")
        task3 = _make_task(task_id="t3", product_id="prod-B", status="pending", priority="critical")

        session = _make_session()
        mock_result = MagicMock()
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = [task1, task2, task3]
        mock_result.scalars.return_value = mock_scalars
        session.execute = AsyncMock(return_value=mock_result)

        service = _make_service(session)
        result = await service.get_summary()

        assert result["total_tasks"] == 3
        assert result["total_products"] == 2
        assert result["summary"]["prod-A"]["total"] == 2
        assert result["summary"]["prod-B"]["total"] == 1




class TestCanDeleteTask:

    def test_admin_can_delete_any_task_in_tenant(self):
        task = _make_task(created_by_user_id="other-user")
        user = _make_user(role="admin")
        service = _make_service(_make_session())
        assert service.can_delete_task(task, user) is True

    def test_admin_cannot_delete_other_tenant_task(self):
        task = _make_task(tenant_key="other-tenant")
        user = _make_user(role="admin")
        service = _make_service(_make_session())
        assert service.can_delete_task(task, user) is False

    def test_developer_can_delete_own_task(self):
        task = _make_task(created_by_user_id=USER_ID)
        user = _make_user(role="developer", user_id=USER_ID)
        service = _make_service(_make_session())
        assert service.can_delete_task(task, user) is True

    def test_developer_cannot_delete_others_task(self):
        task = _make_task(created_by_user_id="other-user")
        user = _make_user(role="developer", user_id=USER_ID)
        service = _make_service(_make_session())
        assert service.can_delete_task(task, user) is False

    def test_viewer_cannot_delete_any_task(self):
        task = _make_task(created_by_user_id=USER_ID)
        user = _make_user(role="viewer", user_id=USER_ID)
        service = _make_service(_make_session())
        assert service.can_delete_task(task, user) is True
