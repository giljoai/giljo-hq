# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import pytest

from api.websocket import WebSocketManager


class _FakeWS:

    def __init__(self) -> None:
        self.closed = False
        self.close_code: int | None = None
        self.close_reason: str | None = None

    async def close(self, code: int = 1000, reason: str = "") -> None:
        self.closed = True
        self.close_code = code
        self.close_reason = reason


@pytest.mark.asyncio
async def test_reconnect_same_client_id_supersedes_and_closes_old_socket():
    mgr = WebSocketManager()
    ws1, ws2 = _FakeWS(), _FakeWS()

    await mgr.connect(ws1, "client-1", {"tenant_key": "tk_x"})
    assert mgr.active_connections["client-1"] is ws1

    await mgr.connect(ws2, "client-1", {"tenant_key": "tk_x"})

    assert mgr.active_connections["client-1"] is ws2
    assert ws1.closed is True
    assert ws1.close_code == 1012
    assert ws2.closed is False


@pytest.mark.asyncio
async def test_stale_socket_teardown_does_not_evict_the_live_socket():
    mgr = WebSocketManager()
    ws1, ws2 = _FakeWS(), _FakeWS()

    await mgr.connect(ws1, "client-1", {"tenant_key": "tk_x"})
    await mgr.connect(ws2, "client-1", {"tenant_key": "tk_x"})

    mgr.disconnect("client-1", ws1)

    assert mgr.active_connections.get("client-1") is ws2


@pytest.mark.asyncio
async def test_identity_disconnect_removes_the_matching_socket():
    mgr = WebSocketManager()
    ws1 = _FakeWS()

    await mgr.connect(ws1, "client-1", {"tenant_key": "tk_x"})
    mgr.disconnect("client-1", ws1)

    assert "client-1" not in mgr.active_connections


@pytest.mark.asyncio
async def test_legacy_disconnect_without_socket_removes_by_id():
    mgr = WebSocketManager()
    ws1 = _FakeWS()

    await mgr.connect(ws1, "client-1", {"tenant_key": "tk_x"})
    mgr.disconnect("client-1")

    assert "client-1" not in mgr.active_connections
