# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
import pytest_asyncio

from giljo_mcp.models.products import Product
from giljo_mcp.models.projects import Project
from giljo_mcp.services.project_service import ProjectService
from giljo_mcp.tenant import TenantManager


pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def product(db_session, test_tenant_key) -> Product:
    row = Product(id=str(uuid4()), name=f"FE-0072c {uuid4().hex[:6]}", tenant_key=test_tenant_key, is_active=True)
    db_session.add(row)
    await db_session.commit()
    return row


@pytest_asyncio.fixture
async def ws() -> MagicMock:
    mock = MagicMock()
    mock.broadcast_project_update = AsyncMock()
    mock.broadcast_to_tenant = AsyncMock()
    return mock


@pytest_asyncio.fixture
async def service(db_manager, db_session, test_tenant_key, ws) -> ProjectService:
    tm = TenantManager()
    tm.set_current_tenant(test_tenant_key)
    return ProjectService(db_manager=db_manager, tenant_manager=tm, test_session=db_session, websocket_manager=ws)


async def _project(service: ProjectService, product: Product, tenant_key: str, name: str = "P") -> str:
    detail = await service.create_project(name=name, mission="m", product_id=product.id, tenant_key=tenant_key)
    return detail.id


def _update_types(ws: MagicMock, project_id: str) -> list[str]:
    return [
        call.kwargs["update_type"]
        for call in ws.broadcast_project_update.await_args_list
        if call.kwargs["project_id"] == project_id
    ]


def _tenants(ws: MagicMock) -> set[str]:
    return {call.kwargs["tenant_key"] for call in ws.broadcast_project_update.await_args_list}


async def test_the_rest_cancel_door_tells_the_dashboard(service, ws, product, test_tenant_key):
    project_id = await _project(service, product, test_tenant_key)
    ws.broadcast_project_update.reset_mock()

    await service.lifecycle.cancel_project(project_id, test_tenant_key, reason="no")

    assert _update_types(ws, project_id) == ["status_changed"]
    assert _tenants(ws) == {test_tenant_key}
    payload = ws.broadcast_project_update.await_args.kwargs["project_data"]
    assert payload["status"] == "cancelled"


async def test_the_rest_restore_door_tells_the_dashboard(service, ws, product, test_tenant_key):
    project_id = await _project(service, product, test_tenant_key)
    await service.deletion.delete_project(project_id)
    ws.broadcast_project_update.reset_mock()

    await service.deletion.restore_project(project_id, test_tenant_key)

    assert _update_types(ws, project_id) == ["status_changed"]
    assert ws.broadcast_project_update.await_args.kwargs["project_data"]["status"] == "inactive"


async def test_a_harness_revive_of_a_trashed_project_still_sends_exactly_one_event(
    service, ws, product, test_tenant_key
):
    project_id = await _project(service, product, test_tenant_key)
    await service.deletion.delete_project(project_id)
    ws.broadcast_project_update.reset_mock()

    await service.update_project(project_id=project_id, updates={"status": "inactive"})

    assert _update_types(ws, project_id) == ["status_changed"]


async def test_trashing_tells_the_dashboard(service, ws, product, test_tenant_key):
    project_id = await _project(service, product, test_tenant_key)
    ws.broadcast_project_update.reset_mock()

    await service.deletion.delete_project(project_id)

    assert _update_types(ws, project_id) == ["status_changed"]
    assert ws.broadcast_project_update.await_args.kwargs["project_data"]["status"] == "deleted"


async def test_terminating_tells_the_dashboard(service, ws, product, test_tenant_key, db_session):
    project_id = await _project(service, product, test_tenant_key)
    row = await db_session.get(Project, project_id)
    row.status = "active"
    await db_session.flush()
    ws.broadcast_project_update.reset_mock()

    await service.lifecycle.terminate_project(project_id, test_tenant_key)

    assert _update_types(ws, project_id) == ["status_changed"]


async def test_completing_tells_the_dashboard(service, ws, product, test_tenant_key):
    project_id = await _project(service, product, test_tenant_key)
    ws.broadcast_project_update.reset_mock()

    await service.complete_project(
        project_id=project_id,
        summary="done",
        key_outcomes=[],
        decisions_made=[],
        tenant_key=test_tenant_key,
        git_commits=[],
    )

    assert _update_types(ws, project_id) == ["status_changed"]


async def test_parking_tells_the_dashboard(service, ws, product, test_tenant_key):
    project_id = await _project(service, product, test_tenant_key)
    ws.broadcast_project_update.reset_mock()

    await service.update_project(project_id=project_id, updates={"status": "parked"})

    assert _update_types(ws, project_id) == ["updated"]
    assert ws.broadcast_project_update.await_args.kwargs["project_data"]["status"] == "parked"


async def test_superseding_tells_the_dashboard(service, ws, product, test_tenant_key):
    old_id = await _project(service, product, test_tenant_key, "Old")
    successor_id = await _project(service, product, test_tenant_key, "New")
    ws.broadcast_project_update.reset_mock()

    await service.update_project(
        project_id=old_id, updates={"status": "superseded", "successor_project_id": successor_id}
    )

    assert _update_types(ws, old_id) == ["updated"]
    assert ws.broadcast_project_update.await_args_list[-1].kwargs["project_data"]["status"] == "superseded"
