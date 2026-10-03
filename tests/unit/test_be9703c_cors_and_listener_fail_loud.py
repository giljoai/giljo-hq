# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI


def test_malformed_cors_origins_json_raises_naming_the_variable(monkeypatch):
    from api.wiring.middleware import configure_middleware

    monkeypatch.setenv("CORS_ORIGINS", '["http://a.example"')
    monkeypatch.setattr("giljo_mcp._config_io.read_config", dict)
    with pytest.raises(ValueError, match="CORS_ORIGINS"):
        configure_middleware(FastAPI())


@pytest.mark.asyncio
async def test_listener_handler_lets_a_broadcast_failure_reach_the_event_bus():
    from api.websocket_event_listener import WebSocketEventListener

    ws_manager = MagicMock()
    ws_manager.broadcast_event_to_tenant = AsyncMock(side_effect=RuntimeError("socket gone"))
    listener = WebSocketEventListener(event_bus=MagicMock(), ws_manager=ws_manager)
    with pytest.raises(RuntimeError):
        await listener.handle_product_status_changed({"tenant_key": "tk", "product_id": "p1", "is_active": True})
