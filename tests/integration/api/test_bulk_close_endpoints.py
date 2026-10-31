# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from api.endpoints.dependencies import get_task_service
from api.endpoints.tasks import router as tasks_router
from giljo_mcp.auth.dependencies import get_current_active_user
from giljo_mcp.models import Product, Project
from giljo_mcp.tenant import TenantManager
from tests.helpers.taxonomy_seeds import next_series_number
from tests.helpers.test_db_helper import purge_tenant_rows
from tests.integration.api.test_fe9708_board_keeps_unreviewed_completed import _app


pytestmark = pytest.mark.asyncio

PROJECTS = "/api/v1/projects/bulk"
TASKS = "/api/v1/tasks/bulk"


def _tasks_app() -> tuple[FastAPI, MagicMock]:
    from api.exception_handlers import register_exception_handlers

    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(tasks_router, prefix="/api/v1/tasks")
    service = MagicMock()
    service.bulk_close_tasks = AsyncMock(return_value={"done": [], "skipped": [], "failed": []})
    user = MagicMock(id=str(uuid.uuid4()), tenant_key="t")

    async def _user():
        return user

    async def _svc() -> AsyncIterator[MagicMock]:
        yield service

    app.dependency_overrides[get_current_active_user] = _user
    app.dependency_overrides[get_task_service] = _svc
    return app, service


@pytest_asyncio.fixture
async def tenant(db_manager):
    tenant_key = TenantManager.generate_tenant_key()
    yield tenant_key
    await purge_tenant_rows(db_manager, tenant_key)


@pytest.mark.parametrize(
    "body",
    [
        {"action": "explode", "ids": [str(uuid.uuid4())]},
        {"action": "archive", "ids": []},
        {"action": "archive", "ids": ["not-a-uuid"]},
        {"action": "archive", "ids": [str(uuid.uuid4()) for _ in range(501)]},
        {"ids": [str(uuid.uuid4())]},
    ],
)
async def test_bad_body_is_422_on_both_endpoints(db_manager, tenant, body):
    async with AsyncClient(transport=ASGITransport(app=_app(db_manager, tenant)), base_url="http://t") as client:
        assert (await client.post(PROJECTS, json=body)).status_code == 422
    app, service = _tasks_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        assert (await client.post(TASKS, json=body)).status_code == 422
    service.bulk_close_tasks.assert_not_awaited()


async def test_exactly_500_ids_is_accepted(db_manager, tenant):
    ids = [str(uuid.uuid4()) for _ in range(500)]
    async with AsyncClient(transport=ASGITransport(app=_app(db_manager, tenant)), base_url="http://t") as client:
        resp = await client.post(PROJECTS, json={"action": "archive", "ids": ids})
    assert resp.status_code == 200
    assert resp.json()["done"] == []
    assert len(resp.json()["skipped"]) == 500


async def test_tasks_endpoint_hands_ids_and_user_to_the_service():
    app, service = _tasks_app()
    tid = str(uuid.uuid4())
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        resp = await client.post(TASKS, json={"action": "delete", "ids": [tid, tid]})
    assert resp.status_code == 200
    kwargs = service.bulk_close_tasks.await_args.kwargs
    assert kwargs["action"] == "delete"
    assert kwargs["task_ids"] == [tid, tid]


async def test_projects_batch_reports_done_and_not_found(db_manager, tenant):
    async with db_manager.get_session_async(tenant_key=tenant) as session:
        product = Product(
            id=str(uuid.uuid4()),
            name=f"bulk {uuid.uuid4().hex[:6]}",
            description="d",
            tenant_key=tenant,
            is_active=True,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        session.add(product)
        await session.flush()
        project = Project(
            id=str(uuid.uuid4()),
            name="bulk",
            description="d",
            mission="m",
            status="inactive",
            tenant_key=tenant,
            product_id=product.id,
            series_number=next_series_number(),
            execution_mode="claude_code_cli",
            created_at=datetime.now(UTC),
        )
        session.add(project)
        await session.commit()
    ghost = str(uuid.uuid4())
    async with AsyncClient(transport=ASGITransport(app=_app(db_manager, tenant)), base_url="http://t") as client:
        resp = await client.post(PROJECTS, json={"action": "archive", "ids": [project.id, ghost]})
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"done": [project.id], "skipped": [{"id": ghost, "reason": "not found"}], "failed": []}
