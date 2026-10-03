# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import pytest

import api.wiring.websocket as ws_wiring
from api.app_state import state
from api.websocket import WebSocketManager


pytestmark = pytest.mark.asyncio


class _FakeWS:
    def __init__(self) -> None:
        self.accepted = False
        self.closed_with: tuple[int, str] | None = None

    async def accept(self) -> None:
        self.accepted = True

    async def close(self, code: int = 1000, reason: str = "") -> None:
        self.closed_with = (code, reason)


def _auth_as(tenant_key: str):
    async def _authenticate(websocket, db=None):
        return {"user": {"tenant_key": tenant_key}, "context": "normal"}

    return _authenticate


@pytest.fixture
def manager(monkeypatch):
    mgr = WebSocketManager()
    monkeypatch.setattr(state, "websocket_manager", mgr)
    monkeypatch.setattr(state, "db_manager", None)
    monkeypatch.setattr(state, "connections", {})
    return mgr


async def _connect(monkeypatch, tenant_key: str, client_id: str) -> tuple[_FakeWS, dict | None]:
    monkeypatch.setattr(ws_wiring, "authenticate_websocket", _auth_as(tenant_key))
    ws = _FakeWS()
    ctx = await ws_wiring.authenticate_ws_connection(ws, client_id, api_key=None, token="jwt")
    return ws, ctx


async def test_another_tenant_reusing_a_live_client_id_does_not_close_the_first_socket(monkeypatch, manager):
    ws_a, ctx_a = await _connect(monkeypatch, "tk_owner", "shared-id")
    assert ctx_a is not None

    ws_b, ctx_b = await _connect(monkeypatch, "tk_intruder", "shared-id")

    assert ws_a.closed_with is None, "the owner's socket was closed by another tenant"
    assert manager.active_connections["shared-id"] is ws_a
    assert manager.tenant_connections.get("tk_owner") == {"shared-id"}
    assert ctx_b is None
    assert ws_b.closed_with is not None and ws_b.closed_with[0] == 1008


async def test_same_tenant_reconnect_still_supersedes(monkeypatch, manager):
    ws_1, _ = await _connect(monkeypatch, "tk_owner", "c1")
    ws_2, ctx = await _connect(monkeypatch, "tk_owner", "c1")

    assert ctx is not None
    assert manager.active_connections["c1"] is ws_2
    assert ws_1.closed_with is not None and ws_1.closed_with[0] == 1012


async def test_an_oversized_client_id_is_refused(monkeypatch, manager):
    ws, ctx = await _connect(monkeypatch, "tk_owner", "x" * 200)

    assert ctx is None
    assert ws.closed_with is not None and ws.closed_with[0] == 1008
    assert manager.active_connections == {}
