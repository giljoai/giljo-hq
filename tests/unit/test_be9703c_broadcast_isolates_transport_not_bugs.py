# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import asyncpg
import pytest
from fastapi import WebSocketDisconnect

from api.websocket import WebSocketManager


def _manager_with_client(send_error: Exception) -> WebSocketManager:
    manager = WebSocketManager()
    socket = MagicMock()
    socket.send_text = AsyncMock(side_effect=send_error)
    manager.active_connections["c1"] = socket
    manager.tenant_connections["tk"] = {"c1"}
    return manager


def _event() -> dict:
    return {"type": "project:updated", "data": {"tenant_key": "tk", "project_id": "p1"}}


@pytest.mark.asyncio
async def test_a_dead_socket_does_not_escape_the_broadcast():
    manager = _manager_with_client(WebSocketDisconnect(code=1006))
    assert await manager.broadcast_event_to_tenant(tenant_key="tk", event=_event()) == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("error", [asyncpg.InterfaceError("connection is closed"), ConnectionResetError("reset")])
async def test_a_lost_broker_connection_does_not_escape_the_broadcast(error):
    manager = WebSocketManager()
    manager._event_broker = MagicMock()
    manager._event_broker.publish = AsyncMock(side_effect=error)
    manager._publish_to_broker_enabled = True
    await manager.broadcast_event_to_tenant(tenant_key="tk", event=_event())


@pytest.mark.asyncio
async def test_a_bug_in_a_service_broadcast_is_not_hidden():
    from giljo_mcp.services.product_service import ProductService

    ws = MagicMock()
    ws.broadcast_to_tenant = AsyncMock(side_effect=ValueError("event_type cannot be empty"))
    service = ProductService.__new__(ProductService)
    service._websocket_manager = ws
    service.tenant_key = "tk"
    service._logger = MagicMock()
    with pytest.raises(ValueError):
        await service._emit_websocket_event("", {"product_id": "p1"})
