# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
import pytest_asyncio

from giljo_mcp.models.tasks import Task
from giljo_mcp.services.task_service import TaskService


pytestmark = pytest.mark.asyncio


def _mock_ws() -> MagicMock:
    ws = MagicMock()
    ws.broadcast_to_tenant = AsyncMock()
    return ws


@pytest_asyncio.fixture
async def task_service_with_ws(db_manager, db_session, test_tenant_key):
    mock_tenant_manager = MagicMock()
    mock_tenant_manager.get_current_tenant.return_value = test_tenant_key
    mock_ws = _mock_ws()

    service = TaskService(
        db_manager=db_manager,
        tenant_manager=mock_tenant_manager,
        session=db_session,
        websocket_manager=mock_ws,
    )
    return service, mock_ws


@pytest_asyncio.fixture
async def test_task(db_session, test_tenant_key, test_product, test_user):
    task = Task(
        id=str(uuid4()),
        tenant_key=test_tenant_key,
        product_id=test_product.id,
        title="FE-9274 status broadcast test task",
        description="seed",
        status="pending",
        priority="medium",
        created_by_user_id=test_user.id,
    )
    db_session.add(task)
    await db_session.commit()
    await db_session.refresh(task)
    return task


class TestChangeStatusBroadcast:

    async def test_change_status_broadcasts_task_updated(self, task_service_with_ws, test_task):
        service, mock_ws = task_service_with_ws

        result = await service.change_status(str(test_task.id), "in_progress")

        assert result.status == "in_progress"
        mock_ws.broadcast_to_tenant.assert_awaited_once()
        call = mock_ws.broadcast_to_tenant.await_args
        assert call.kwargs["event_type"] == "task:updated"
        data = call.kwargs["data"]
        assert data["task_id"] == str(test_task.id)
        assert data["status"] == "in_progress"
        assert data["updated_fields"] == ["status"]
        assert data["product_id"] == test_task.product_id

    async def test_change_status_without_websocket_manager_does_not_raise(
        self, db_manager, db_session, test_tenant_key, test_task
    ):
        mock_tenant_manager = MagicMock()
        mock_tenant_manager.get_current_tenant.return_value = test_tenant_key
        service = TaskService(db_manager=db_manager, tenant_manager=mock_tenant_manager, session=db_session)

        result = await service.change_status(str(test_task.id), "completed")

        assert result.status == "completed"


class TestCreateTaskForRestBroadcast:
    async def test_create_task_for_rest_broadcasts_task_created(
        self, task_service_with_ws, test_tenant_key, test_product, test_user
    ):
        service, mock_ws = task_service_with_ws

        task = await service.create_task_for_rest(
            title="New REST task",
            description="created via REST",
            product_id=test_product.id,
            tenant_key=test_tenant_key,
            created_by_user_id=test_user.id,
        )

        mock_ws.broadcast_to_tenant.assert_awaited_once()
        call = mock_ws.broadcast_to_tenant.await_args
        assert call.kwargs["event_type"] == "task:created"
        data = call.kwargs["data"]
        assert data["task_id"] == task.id
        assert data["title"] == "New REST task"
        assert data["product_id"] == test_product.id


class TestGetTaskServiceDependencyWiring:

    async def test_get_task_service_wires_websocket_manager(self, db_manager):
        from api.endpoints.dependencies import get_task_service
        from giljo_mcp.tenant import TenantManager

        mock_ws = _mock_ws()
        tenant_manager = TenantManager()
        tenant_key = TenantManager.generate_tenant_key()

        service = await get_task_service(
            tenant_key=tenant_key,
            db_manager=db_manager,
            tenant_manager=tenant_manager,
            websocket_manager=mock_ws,
        )

        assert isinstance(service, TaskService)
        assert service._websocket_manager is mock_ws
