# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from api.app_state import APIState
from api.startup.shutdown import shutdown


@pytest.mark.asyncio
async def test_graceful_shutdown_under_multiworker_web_posture(monkeypatch):
    monkeypatch.setenv("WEB_CONCURRENCY", "2")
    monkeypatch.setenv("GILJO_RUN_BACKGROUND_JOBS", "off")

    state = APIState()

    async def _forever():
        while True:
            await asyncio.sleep(1)

    state.heartbeat_task = asyncio.create_task(_forever())

    ws_a = MagicMock()
    ws_a.close = AsyncMock()
    ws_b = MagicMock()
    ws_b.close = AsyncMock()
    state.connections = {"a": ws_a, "b": ws_b}

    state.websocket_broker = MagicMock()
    state.websocket_broker.stop = AsyncMock()

    state.db_manager = MagicMock()
    state.db_manager.close_async = AsyncMock()

    await shutdown(state)

    ws_a.close.assert_awaited_once()
    ws_b.close.assert_awaited_once()
    state.websocket_broker.stop.assert_awaited_once()
    state.db_manager.close_async.assert_awaited_once()
    assert state.heartbeat_task.cancelled()
