# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import asyncio

import asyncpg
import pytest

from api.websocket import WebSocketManager


class _FakeWS:

    def __init__(self, *, fail: bool = False, hang_seconds: float | None = None) -> None:
        self.fail = fail
        self.hang_seconds = hang_seconds
        self.sent: list[dict] = []
        self.closed = False

    async def send_json(self, data: dict) -> None:
        if self.hang_seconds is not None:
            await asyncio.sleep(self.hang_seconds)
        if self.fail:
            raise RuntimeError("simulated send failure")
        self.sent.append(data)

    async def send_text(self, data: str) -> None:
        if self.hang_seconds is not None:
            await asyncio.sleep(self.hang_seconds)
        if self.fail:
            raise RuntimeError("simulated send failure")
        self.sent.append(data)

    async def close(self, code: int = 1000, reason: str = "") -> None:
        self.closed = True


class _FakeBroker:

    def __init__(self, *, raise_postgres_error: bool = False) -> None:
        self.publish_count = 0
        self.raise_postgres_error = raise_postgres_error

    def subscribe(self, handler):
        def _unsubscribe() -> None:
            return None

        return _unsubscribe

    async def publish(self, message) -> None:
        self.publish_count += 1
        if self.raise_postgres_error:
            raise asyncpg.PostgresError("payload string too long")


def _wire_client(mgr: WebSocketManager, client_id: str, ws: _FakeWS, tenant_key: str) -> None:
    mgr.active_connections[client_id] = ws
    mgr.auth_contexts[client_id] = {"tenant_key": tenant_key}
    mgr._index_tenant_connection(client_id, tenant_key)


def _event(tenant_key: str) -> dict:
    return {"type": "test:event", "data": {"tenant_key": tenant_key, "n": 1}}




@pytest.mark.asyncio
async def test_broadcast_event_to_tenant_evicts_stalled_client(monkeypatch):
    import api.websocket as ws_mod

    monkeypatch.setattr(ws_mod, "_WS_SEND_TIMEOUT_SECONDS", 0.05)

    mgr = WebSocketManager()
    tenant = "tk_f4"
    wedged = _FakeWS(hang_seconds=5.0)
    healthy = _FakeWS()
    _wire_client(mgr, "c-wedged", wedged, tenant)
    _wire_client(mgr, "c-ok", healthy, tenant)

    sent_count = await asyncio.wait_for(
        mgr.broadcast_event_to_tenant(tenant_key=tenant, event=_event(tenant)),
        timeout=2,
    )

    assert sent_count == 1
    assert len(healthy.sent) == 1
    assert "c-ok" in mgr.active_connections
    assert "c-wedged" not in mgr.active_connections


@pytest.mark.asyncio
async def test_broadcast_event_to_tenant_happy_path_delivers_to_all(monkeypatch):
    import api.websocket as ws_mod

    monkeypatch.setattr(ws_mod, "_WS_SEND_TIMEOUT_SECONDS", 0.5)

    mgr = WebSocketManager()
    tenant = "tk_happy"
    clients = {f"c{i}": _FakeWS() for i in range(3)}
    for cid, ws in clients.items():
        _wire_client(mgr, cid, ws, tenant)

    sent_count = await mgr.broadcast_event_to_tenant(tenant_key=tenant, event=_event(tenant))

    assert sent_count == 3
    for ws in clients.values():
        assert len(ws.sent) == 1




@pytest.mark.asyncio
async def test_single_worker_skips_broker_publish(monkeypatch):
    monkeypatch.setattr("api.startup.database._worker_count", lambda: 1)

    mgr = WebSocketManager()
    broker = _FakeBroker()
    mgr.attach_broker(broker)
    assert mgr._publish_to_broker_enabled is False

    tenant = "tk_single"
    _wire_client(mgr, "c1", _FakeWS(), tenant)

    sent_count = await mgr.broadcast_event_to_tenant(tenant_key=tenant, event=_event(tenant))

    assert sent_count == 1
    assert broker.publish_count == 0


@pytest.mark.asyncio
async def test_multi_worker_still_publishes(monkeypatch):
    monkeypatch.setattr("api.startup.database._worker_count", lambda: 2)

    mgr = WebSocketManager()
    broker = _FakeBroker()
    mgr.attach_broker(broker)
    assert mgr._publish_to_broker_enabled is True

    tenant = "tk_multi"
    _wire_client(mgr, "c1", _FakeWS(), tenant)

    sent_count = await mgr.broadcast_event_to_tenant(tenant_key=tenant, event=_event(tenant))

    assert sent_count == 1
    assert broker.publish_count == 1


@pytest.mark.asyncio
async def test_broker_postgres_error_is_swallowed(monkeypatch):
    monkeypatch.setattr("api.startup.database._worker_count", lambda: 2)

    mgr = WebSocketManager()
    broker = _FakeBroker(raise_postgres_error=True)
    mgr.attach_broker(broker)

    tenant = "tk_pgerr"
    _wire_client(mgr, "c1", _FakeWS(), tenant)

    sent_count = await mgr.broadcast_event_to_tenant(tenant_key=tenant, event=_event(tenant))

    assert sent_count == 1
    assert broker.publish_count == 1


