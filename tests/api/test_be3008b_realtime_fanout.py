# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import asyncio
import json
import time

import pytest

from api.websocket import WebSocketManager


class _FakeWS:

    def __init__(self, *, fail: bool = False, hang_seconds: float | None = None) -> None:
        self.fail = fail
        self.hang_seconds = hang_seconds
        self.sent: list[str] = []
        self.closed = False

    async def send_text(self, data: str) -> None:
        if self.hang_seconds is not None:
            await asyncio.sleep(self.hang_seconds)
        if self.fail:
            raise RuntimeError("simulated send failure")
        self.sent.append(data)

    async def send_json(self, data: dict) -> None:
        if self.hang_seconds is not None:
            await asyncio.sleep(self.hang_seconds)
        if self.fail:
            raise RuntimeError("simulated send failure")
        self.sent.append(json.dumps(data))

    async def close(self, code: int = 1000, reason: str = "") -> None:
        self.closed = True


def _wire(mgr: WebSocketManager, client_id: str, ws: _FakeWS, tenant_key: str) -> None:
    mgr.active_connections[client_id] = ws
    mgr.auth_contexts[client_id] = {"tenant_key": tenant_key}
    mgr._index_tenant_connection(client_id, tenant_key)


def _event(tenant_key: str, n: int = 1) -> dict:
    return {"type": "test:event", "data": {"tenant_key": tenant_key, "n": n}}




@pytest.mark.asyncio
async def test_event_for_tenant_a_never_reaches_tenant_b(monkeypatch):
    import api.websocket as ws_mod

    monkeypatch.setattr(ws_mod, "_WS_SEND_TIMEOUT_SECONDS", 0.5)

    mgr = WebSocketManager()
    a1, a2 = _FakeWS(), _FakeWS()
    b1 = _FakeWS()
    c1 = _FakeWS()
    _wire(mgr, "a1", a1, "tenant_A")
    _wire(mgr, "a2", a2, "tenant_A")
    _wire(mgr, "b1", b1, "tenant_B")
    _wire(mgr, "c1", c1, "tenant_C")

    sent = await mgr.broadcast_event_to_tenant(tenant_key="tenant_A", event=_event("tenant_A"))

    assert sent == 2
    assert len(a1.sent) == 1
    assert len(a2.sent) == 1
    assert b1.sent == []
    assert c1.sent == []


@pytest.mark.asyncio
async def test_broadcast_serializes_once_to_a_text_frame(monkeypatch):
    import api.websocket as ws_mod

    monkeypatch.setattr(ws_mod, "_WS_SEND_TIMEOUT_SECONDS", 0.5)

    mgr = WebSocketManager()
    a1, a2 = _FakeWS(), _FakeWS()
    _wire(mgr, "a1", a1, "tenant_A")
    _wire(mgr, "a2", a2, "tenant_A")

    await mgr.broadcast_event_to_tenant(tenant_key="tenant_A", event=_event("tenant_A", n=7))

    assert a1.sent == a2.sent
    decoded = json.loads(a1.sent[0])
    assert decoded["type"] == "test:event"
    assert decoded["data"]["tenant_key"] == "tenant_A"
    assert decoded["data"]["n"] == 7




@pytest.mark.asyncio
async def test_wedged_sockets_do_not_convoy_healthy_peers_at_load(monkeypatch):
    import api.websocket as ws_mod

    timeout = 0.3
    monkeypatch.setattr(ws_mod, "_WS_SEND_TIMEOUT_SECONDS", timeout)

    mgr = WebSocketManager()

    target = "tenant_target"
    healthy: list[_FakeWS] = []
    wedged: list[_FakeWS] = []

    for i in range(60):
        ws = _FakeWS()
        healthy.append(ws)
        _wire(mgr, f"t-ok-{i}", ws, target)
    for i in range(6):
        ws = _FakeWS(hang_seconds=2.0)
        wedged.append(ws)
        _wire(mgr, f"t-wedged-{i}", ws, target)

    others: list[_FakeWS] = []
    for i in range(67):
        ws = _FakeWS()
        others.append(ws)
        _wire(mgr, f"o1-{i}", ws, "tenant_other_1")
    for i in range(67):
        ws = _FakeWS()
        others.append(ws)
        _wire(mgr, f"o2-{i}", ws, "tenant_other_2")

    start = time.monotonic()
    sent = await mgr.broadcast_event_to_tenant(tenant_key=target, event=_event(target))
    elapsed = time.monotonic() - start

    assert elapsed < timeout * 3, f"fan-out convoyed: {elapsed:.3f}s for 6 wedged clients"

    assert sent == 60
    assert all(len(ws.sent) == 1 for ws in healthy)

    assert mgr.tenant_connections.get(target, set()) == {f"t-ok-{i}" for i in range(60)}
    for i in range(6):
        assert f"t-wedged-{i}" not in mgr.active_connections

    assert all(ws.sent == [] for ws in others)




@pytest.mark.asyncio
async def test_schedule_returns_before_fanout_completes(monkeypatch):
    import api.websocket as ws_mod

    monkeypatch.setattr(ws_mod, "_WS_SEND_TIMEOUT_SECONDS", 0.5)

    mgr = WebSocketManager()
    slow = _FakeWS(hang_seconds=0.2)
    _wire(mgr, "slow", slow, "tenant_A")

    start = time.monotonic()
    mgr.schedule(mgr.broadcast_to_tenant(tenant_key="tenant_A", event_type="test:event", data={}))
    enqueue_elapsed = time.monotonic() - start

    assert enqueue_elapsed < 0.05
    assert slow.sent == []
    assert len(mgr._background_tasks) == 1

    await asyncio.sleep(0.3)
    assert len(slow.sent) == 1
    assert len(mgr._background_tasks) == 0


@pytest.mark.asyncio
async def test_schedule_swallows_broadcast_errors(monkeypatch):
    import api.websocket as ws_mod

    monkeypatch.setattr(ws_mod, "_WS_SEND_TIMEOUT_SECONDS", 0.5)

    mgr = WebSocketManager()
    failing = _FakeWS(fail=True)
    _wire(mgr, "boom", failing, "tenant_A")

    mgr.schedule(mgr.broadcast_to_tenant(tenant_key="tenant_A", event_type="test:event", data={}))
    await asyncio.sleep(0.1)
    assert "boom" not in mgr.active_connections
    assert len(mgr._background_tasks) == 0




@pytest.mark.asyncio
async def test_connect_disconnect_maintain_tenant_index():
    mgr = WebSocketManager()
    ws1, ws2 = _FakeWS(), _FakeWS()

    await mgr.connect(ws1, "c1", {"tenant_key": "tk_a"})
    await mgr.connect(ws2, "c2", {"tenant_key": "tk_a"})
    assert mgr.tenant_connections["tk_a"] == {"c1", "c2"}

    mgr.disconnect("c1")
    assert mgr.tenant_connections["tk_a"] == {"c2"}

    mgr.disconnect("c2")
    assert "tk_a" not in mgr.tenant_connections


@pytest.mark.asyncio
async def test_supersede_keeps_single_index_entry():
    mgr = WebSocketManager()
    ws1, ws2 = _FakeWS(), _FakeWS()

    await mgr.connect(ws1, "c1", {"tenant_key": "tk_a"})
    await mgr.connect(ws2, "c1", {"tenant_key": "tk_a"})

    assert mgr.tenant_connections["tk_a"] == {"c1"}
    assert mgr.active_connections["c1"] is ws2


@pytest.mark.asyncio
async def test_setup_context_socket_is_not_indexed():
    mgr = WebSocketManager()
    ws = _FakeWS()

    await mgr.connect(ws, "setup-1", {"tenant_key": None})

    assert mgr.tenant_connections == {}
    assert "setup-1" in mgr.active_connections


@pytest.mark.asyncio
async def test_reconnect_under_new_tenant_deindexes_old_tenant():
    mgr = WebSocketManager()
    ws_a, ws_b = _FakeWS(), _FakeWS()

    await mgr.connect(ws_a, "shared-id", {"tenant_key": "tk_a"})
    await mgr.connect(ws_b, "shared-id", {"tenant_key": "tk_b"})

    assert "shared-id" not in mgr.tenant_connections.get("tk_a", set())
    assert mgr.tenant_connections["tk_b"] == {"shared-id"}

    sent = await mgr.broadcast_event_to_tenant(tenant_key="tk_a", event=_event("tk_a"))
    assert sent == 0
    assert ws_b.sent == []


@pytest.mark.asyncio
async def test_stale_identity_disconnect_leaves_index_intact():
    mgr = WebSocketManager()
    ws1, ws2 = _FakeWS(), _FakeWS()

    await mgr.connect(ws1, "c1", {"tenant_key": "tk_a"})
    await mgr.connect(ws2, "c1", {"tenant_key": "tk_a"})

    mgr.disconnect("c1", ws1)

    assert mgr.tenant_connections["tk_a"] == {"c1"}
    assert mgr.active_connections["c1"] is ws2
