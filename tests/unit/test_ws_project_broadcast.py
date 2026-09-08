# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""Tests for WebSocket project broadcast fixes (WI-5 Gaps 1 & 2 of CE-OPT-003).

Covers:
- _build_ws_project_data includes description
- broadcast_project_update sends description in payload
- update_project uses self._websocket_manager (not method param)
"""

from unittest.mock import AsyncMock, MagicMock

import pytest


def test_build_ws_project_data_includes_description():
    """_build_ws_project_data should include description field."""
    from giljo_mcp.services.project_helpers import _build_ws_project_data

    project = MagicMock()
    project.name = "Test Project"
    project.description = "A test description"
    project.status = "active"
    project.mission = "Test mission"
    project.product_id = "prod-ws-1"

    data = _build_ws_project_data(project)

    assert data["name"] == "Test Project"
    assert data["description"] == "A test description"
    assert data["status"] == "active"
    assert data["mission"] == "Test mission"
    # BE-9518: single source of truth for the 6+ call sites routed through this
    # helper (project_launch_service, activate/deactivate_project,
    # project_service._mutation_mixin x2, project_staging_service).
    assert data["product_id"] == "prod-ws-1"


@pytest.mark.asyncio
async def test_broadcast_project_update_includes_description():
    """broadcast_project_update should include description in WebSocket payload."""
    from api.websocket import WebSocketManager

    ws = WebSocketManager.__new__(WebSocketManager)
    ws.broadcast_to_tenant = AsyncMock()

    await ws.broadcast_project_update(
        project_id="test-id",
        update_type="updated",
        project_data={
            "name": "P1",
            "description": "Desc1",
            "status": "active",
            "mission": "M1",
            "product_id": "prod-broadcast-1",
        },
        tenant_key="tk_test",
    )

    ws.broadcast_to_tenant.assert_called_once()
    call_kwargs = ws.broadcast_to_tenant.call_args.kwargs
    assert call_kwargs["data"]["description"] == "Desc1"
    assert call_kwargs["data"]["name"] == "P1"
    assert call_kwargs["data"]["mission"] == "M1"
    # BE-9518: additive envelope field.
    assert call_kwargs["data"]["product_id"] == "prod-broadcast-1"


@pytest.mark.asyncio
async def test_update_project_uses_constructor_websocket(db_session, test_tenant_key):
    """update_project should use self._websocket_manager, not the method parameter."""
    from giljo_mcp.database import DatabaseManager
    from giljo_mcp.services.project_service import ProjectService
    from giljo_mcp.tenant import TenantManager

    ws_mock = AsyncMock()
    ws_mock.broadcast_project_update = AsyncMock()

    db_manager = MagicMock(spec=DatabaseManager)
    tenant_manager = MagicMock(spec=TenantManager)
    tenant_manager.get_current_tenant.return_value = test_tenant_key

    service = ProjectService(
        db_manager=db_manager,
        tenant_manager=tenant_manager,
        test_session=db_session,
        websocket_manager=ws_mock,
    )

    # Create a test project
    from uuid import uuid4

    from giljo_mcp.models.products import Product
    from giljo_mcp.models.projects import Project

    # BE-9437: a project belongs to a product.
    product = Product(
        id=str(uuid4()),
        tenant_key=test_tenant_key,
        name=f"WS Product {uuid4().hex[:6]}",
        description="seeded",
        is_active=False,
    )
    db_session.add(product)
    await db_session.flush()

    project = Project(
        id=str(uuid4()),
        product_id=product.id,
        name="Original Name",
        description="Original Desc",
        mission="Original Mission",
        status="active",
        tenant_key=test_tenant_key,
        series_number=999999,
    )
    db_session.add(project)
    await db_session.commit()

    # Call update_project WITHOUT passing websocket_manager parameter
    await service.update_project(
        project_id=project.id,
        updates={"name": "Updated Name"},
    )

    # Verify the constructor-injected ws manager was used (not the deprecated param)
    ws_mock.broadcast_project_update.assert_called_once()
    call_kwargs = ws_mock.broadcast_project_update.call_args.kwargs
    assert call_kwargs["update_type"] == "updated"
    assert call_kwargs["project_data"]["name"] == "Updated Name"
