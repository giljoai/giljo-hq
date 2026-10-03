# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import asyncio
import json

import pytest

import api.broker.postgres_notify as pn
from api.broker import ensure_broker_supports_worker_count
from api.broker.base import WebSocketBrokerMessage
from api.broker.in_memory import InMemoryWebSocketEventBroker
from api.broker.postgres_notify import PostgresNotifyWebSocketEventBroker
from api.startup.core_services import init_websocket_broker
from api.websocket import WebSocketManager




class _FakePostgresError(Exception):
    pass


class _FakeConn:

    def __init__(self) -> None:
        self.listeners: dict[str, object] = {}
        self.termination_listeners: list[object] = []
        self.closed = False

    async def add_listener(self, channel: str, callback) -> None:
        self.listeners[channel] = callback

    async def remove_listener(self, channel: str, callback) -> None:
        self.listeners.pop(channel, None)

    def add_termination_listener(self, callback) -> None:
        self.termination_listeners.append(callback)

    def remove_termination_listener(self, callback) -> None:
        if callback in self.termination_listeners:
            self.termination_listeners.remove(callback)

    def is_closed(self) -> bool:
        return self.closed

    async def close(self) -> None:
        self.closed = True
        for callback in list(self.termination_listeners):
            callback(self)

    def terminate_from_server(self) -> None:
        self.closed = True
        for callback in list(self.termination_listeners):
            callback(self)

    def deliver_notify(self, channel: str, payload: str) -> None:
        callback = self.listeners.get(channel)
        assert callback is not None, f"no LISTEN registered on {channel!r}"
        callback(self, 12345, channel, payload)


class _FakePoolConn:
    def __init__(self, pool: _FakePool) -> None:
        self._pool = pool

    async def execute(self, sql: str, *args) -> None:
        self._pool.executed.append((sql, *args))


class _FakePool:
    def __init__(self) -> None:
        self.executed: list[tuple] = []
        self.closed = False

    def acquire(self) -> _FakePool._Ctx:
        return _FakePool._Ctx(self)

    async def close(self) -> None:
        self.closed = True

    class _Ctx:
        def __init__(self, pool: _FakePool) -> None:
            self._pool = pool

        async def __aenter__(self) -> _FakePoolConn:
            return _FakePoolConn(self._pool)

        async def __aexit__(self, *exc_info) -> None:
            return None


class _FakeAsyncpg:

    PostgresError = _FakePostgresError

    def __init__(self) -> None:
        self.connections: list[_FakeConn] = []
        self.pools: list[_FakePool] = []
        self.connect_attempts = 0
        self.connect_failures_remaining = 0

    async def connect(self, dsn: str) -> _FakeConn:
        self.connect_attempts += 1
        if self.connect_failures_remaining > 0:
            self.connect_failures_remaining -= 1
            raise OSError("connection refused (fake)")
        conn = _FakeConn()
        self.connections.append(conn)
        return conn

    async def create_pool(self, dsn: str, min_size: int, max_size: int) -> _FakePool:
        pool = _FakePool()
        self.pools.append(pool)
        return pool


class _AsyncioShim:

    def __init__(self) -> None:
        self.sleep_delays: list[float] = []

    def __getattr__(self, name: str):
        return getattr(asyncio, name)

    async def sleep(self, delay: float) -> None:
        self.sleep_delays.append(delay)
        await asyncio.sleep(0)


@pytest.fixture
def fake_pg(monkeypatch) -> _FakeAsyncpg:
    fake = _FakeAsyncpg()
    monkeypatch.setattr(pn, "asyncpg", fake)
    return fake


@pytest.fixture
def sleep_shim(monkeypatch) -> _AsyncioShim:
    shim = _AsyncioShim()
    monkeypatch.setattr(pn, "asyncio", shim)
    return shim


async def _wait_until(condition, tries: int = 500) -> None:
    for _ in range(tries):
        if condition():
            return
        await asyncio.sleep(0)
    raise AssertionError("condition not reached within the yield budget")


def _message(**overrides) -> WebSocketBrokerMessage:
    fields = {"tenant_key": "tenant_A", "event": {"type": "ping", "data": {}}}
    fields.update(overrides)
    return WebSocketBrokerMessage(**fields)




async def test_start_awaits_listen_registration(fake_pg):
    broker = PostgresNotifyWebSocketEventBroker(dsn="postgresql://fake/db")
    await broker.start()
    try:
        conn = fake_pg.connections[0]
        assert "giljo_ws_events" in conn.listeners
        assert conn.termination_listeners, "termination listener must be registered"
    finally:
        await broker.stop()


async def test_notification_dispatches_to_subscribed_handler(fake_pg):
    broker = PostgresNotifyWebSocketEventBroker(dsn="postgresql://fake/db")
    await broker.start()
    received: list[WebSocketBrokerMessage] = []

    async def handler(message: WebSocketBrokerMessage) -> None:
        received.append(message)

    broker.subscribe(handler)
    try:
        payload = broker._serialize(_message(origin="peer-worker"))
        fake_pg.connections[0].deliver_notify("giljo_ws_events", payload)
        await _wait_until(lambda: received)
        assert received[0].tenant_key == "tenant_A"
        assert received[0].origin == "peer-worker"
    finally:
        await broker.stop()




async def test_reconnects_with_backoff_and_delivery_resumes(fake_pg, sleep_shim):
    broker = PostgresNotifyWebSocketEventBroker(dsn="postgresql://fake/db")
    await broker.start()
    received: list[WebSocketBrokerMessage] = []

    async def handler(message: WebSocketBrokerMessage) -> None:
        received.append(message)

    broker.subscribe(handler)
    try:
        fake_pg.connect_failures_remaining = 2
        fake_pg.connections[0].terminate_from_server()

        await _wait_until(lambda: len(fake_pg.connections) == 2)
        assert fake_pg.connect_attempts == 4
        assert sleep_shim.sleep_delays == [0.5, 1.0]

        new_conn = fake_pg.connections[1]
        assert "giljo_ws_events" in new_conn.listeners, "LISTEN must be re-registered"
        new_conn.deliver_notify("giljo_ws_events", broker._serialize(_message(origin="peer")))
        await _wait_until(lambda: received)
    finally:
        await broker.stop()


async def test_backoff_delay_is_capped(fake_pg, sleep_shim):
    broker = PostgresNotifyWebSocketEventBroker(dsn="postgresql://fake/db")
    await broker.start()
    try:
        fake_pg.connect_failures_remaining = 8
        fake_pg.connections[0].terminate_from_server()
        await _wait_until(lambda: len(fake_pg.connections) == 2)
        assert sleep_shim.sleep_delays == [0.5, 1.0, 2.0, 4.0, 8.0, 16.0, 30.0, 30.0]
    finally:
        await broker.stop()


async def test_survives_repeated_connection_losses(fake_pg, sleep_shim):
    broker = PostgresNotifyWebSocketEventBroker(dsn="postgresql://fake/db")
    await broker.start()
    try:
        fake_pg.connections[0].terminate_from_server()
        await _wait_until(lambda: len(fake_pg.connections) == 2)
        fake_pg.connections[1].terminate_from_server()
        await _wait_until(lambda: len(fake_pg.connections) == 3)
        assert "giljo_ws_events" in fake_pg.connections[2].listeners
    finally:
        await broker.stop()


async def test_stop_does_not_reconnect(fake_pg):
    broker = PostgresNotifyWebSocketEventBroker(dsn="postgresql://fake/db")
    await broker.start()
    await broker.stop()

    assert fake_pg.connections[0].closed
    for _ in range(50):
        await asyncio.sleep(0)
    assert fake_pg.connect_attempts == 1, "a deliberate stop must not arm a reconnect"


async def test_start_failure_cleans_up_and_raises(fake_pg):
    fake_pg.connect_failures_remaining = 1
    broker = PostgresNotifyWebSocketEventBroker(dsn="postgresql://fake/db")
    with pytest.raises(OSError):
        await broker.start()
    assert broker._listen_conn is None
    assert broker._publish_pool is None




async def test_publish_sends_pg_notify(fake_pg):
    broker = PostgresNotifyWebSocketEventBroker(dsn="postgresql://fake/db")
    await broker.start()
    try:
        await broker.publish(_message(origin="me"))
        assert len(fake_pg.pools[0].executed) == 1
        sql, channel, payload = fake_pg.pools[0].executed[0]
        assert "pg_notify" in sql
        assert channel == "giljo_ws_events"
        assert json.loads(payload)["tenant_key"] == "tenant_A"
    finally:
        await broker.stop()


async def test_publish_rejects_oversized_payload_before_reaching_pg(fake_pg):
    broker = PostgresNotifyWebSocketEventBroker(dsn="postgresql://fake/db")
    await broker.start()
    try:
        oversized = _message(event={"type": "blob", "data": {"blob": "x" * 9000}})
        with pytest.raises(ValueError, match="pg_notify caps payloads"):
            await broker.publish(oversized)
        assert fake_pg.pools[0].executed == []
    finally:
        await broker.stop()




def test_deserialize_tolerates_legacy_payload_missing_optional_keys():
    legacy = json.dumps({"tenant_key": "tenant_A", "event": {"type": "ping", "data": {}}})
    message = PostgresNotifyWebSocketEventBroker._deserialize(legacy)
    assert message.tenant_key == "tenant_A"
    assert message.control is None
    assert message.origin is None
    assert message.exclude_client is None




class _FakeWS:
    def __init__(self) -> None:
        self.closed = False
        self.close_code: int | None = None

    async def send_text(self, data: str) -> None:
        return None

    async def close(self, code: int = 1000, reason: str = "") -> None:
        self.closed = True
        self.close_code = code


def _wire(mgr: WebSocketManager, client_id: str, ws: _FakeWS, tenant_key: str) -> None:
    mgr.active_connections[client_id] = ws
    mgr.auth_contexts[client_id] = {"tenant_key": tenant_key}
    mgr._index_tenant_connection(client_id, tenant_key)


def _force_multiworker(monkeypatch) -> None:
    import api.startup.database as db_startup

    monkeypatch.setattr(db_startup, "_worker_count", lambda: 2)


async def test_peer_disconnect_tenant_notify_closes_sockets_without_republish(fake_pg, monkeypatch):
    _force_multiworker(monkeypatch)
    broker = PostgresNotifyWebSocketEventBroker(dsn="postgresql://fake/db")
    await broker.start()
    mgr = WebSocketManager()
    mgr.attach_broker(broker)
    ws = _FakeWS()
    _wire(mgr, "client-1", ws, "tenant_A")
    try:
        payload = broker._serialize(_message(event={}, origin="some-other-worker", control="disconnect_tenant"))
        fake_pg.connections[0].deliver_notify("giljo_ws_events", payload)
        await _wait_until(lambda: ws.closed)
        assert ws.close_code == 1008
        assert "client-1" not in mgr.active_connections
        assert fake_pg.pools[0].executed == [], "a received control must not be re-published (loop)"
    finally:
        await broker.stop()


async def test_own_origin_echo_is_ignored(fake_pg, monkeypatch):
    _force_multiworker(monkeypatch)
    broker = PostgresNotifyWebSocketEventBroker(dsn="postgresql://fake/db")
    await broker.start()
    mgr = WebSocketManager()
    mgr.attach_broker(broker)
    ws = _FakeWS()
    _wire(mgr, "client-1", ws, "tenant_A")
    try:
        payload = broker._serialize(_message(event={}, origin=mgr._broker_origin, control="disconnect_tenant"))
        fake_pg.connections[0].deliver_notify("giljo_ws_events", payload)
        for _ in range(50):
            await asyncio.sleep(0)
        assert not ws.closed, "a worker must ignore its own broker echo"
        assert "client-1" in mgr.active_connections
    finally:
        await broker.stop()




class _StubDBManager:
    database_url = "postgresql://fake-user:fake-pw@localhost:5432/fake_db"


class _StubState:
    def __init__(self) -> None:
        self.config = None
        self.db_manager = _StubDBManager()
        self.websocket_manager = WebSocketManager()
        self.websocket_broker = None
        self.degraded_services: list[str] = []


def _force_worker_count(monkeypatch, count: int) -> None:
    import api.startup.database as db_startup

    monkeypatch.setattr(db_startup, "_worker_count", lambda: count)


def test_guard_rejects_in_memory_with_multiple_workers():
    with pytest.raises(RuntimeError, match="in_memory"):
        ensure_broker_supports_worker_count(InMemoryWebSocketEventBroker(), worker_count=2)


def test_guard_allows_in_memory_single_worker_and_pg_multiworker():
    ensure_broker_supports_worker_count(InMemoryWebSocketEventBroker(), worker_count=1)
    ensure_broker_supports_worker_count(PostgresNotifyWebSocketEventBroker(dsn="postgresql://fake/db"), worker_count=2)


async def test_startup_fails_loud_on_multiworker_in_memory(monkeypatch):
    _force_worker_count(monkeypatch, 2)
    monkeypatch.setenv("GILJO_WS_BROKER", "in_memory")
    state = _StubState()
    with pytest.raises(RuntimeError, match="in_memory"):
        await init_websocket_broker(state)
    assert state.websocket_broker is None


async def test_startup_fails_loud_when_multiworker_broker_cannot_start(fake_pg, monkeypatch):
    _force_worker_count(monkeypatch, 2)
    monkeypatch.setenv("GILJO_WS_BROKER", "postgres_notify")
    fake_pg.connect_failures_remaining = 1
    state = _StubState()
    with pytest.raises(OSError):
        await init_websocket_broker(state)
    assert state.websocket_broker is None


async def test_startup_single_worker_degrades_gracefully_on_broker_failure(monkeypatch):
    _force_worker_count(monkeypatch, 1)
    monkeypatch.setenv("GILJO_WS_BROKER", "bogus_broker_type")
    state = _StubState()
    await init_websocket_broker(state)
    assert state.websocket_broker is None
    assert state.degraded_services == ["websocket_broker"], "the degraded broker is named on /health"


async def test_startup_attaches_postgres_broker_multiworker(fake_pg, monkeypatch):
    _force_worker_count(monkeypatch, 2)
    monkeypatch.setenv("GILJO_WS_BROKER", "postgres_notify")
    state = _StubState()
    await init_websocket_broker(state)
    try:
        assert isinstance(state.websocket_broker, PostgresNotifyWebSocketEventBroker)
        assert state.websocket_manager._event_broker is state.websocket_broker
        assert state.websocket_manager._publish_to_broker_enabled is True
    finally:
        await state.websocket_broker.stop()
