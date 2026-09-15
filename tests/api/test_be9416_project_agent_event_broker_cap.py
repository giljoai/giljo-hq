# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import api.broker.postgres_notify as pn
from api.broker.postgres_notify import _MAX_NOTIFY_PAYLOAD_BYTES, PostgresNotifyWebSocketEventBroker
from api.dependencies.websocket import WebSocketDependency
from api.endpoints.agent_jobs.operations import update_agent_mission
from api.websocket import WebSocketManager
from giljo_mcp.events.schemas import BOUNDED_EVENT_FIELDS, MAX_EVENT_BYTES
from giljo_mcp.services.dto import BroadcastAgentCreatedContext
from giljo_mcp.services.job_lifecycle_service import JobLifecycleService


CHANNEL = "giljo_ws_events"
TENANT = "tk_be9416"

WORST_CHAR = "\U0001f600"

CJK_CHAR = "中"

_REQUIRED_HEADROOM_BYTES = 1_000




class _FakePostgresError(Exception):
    pass


class _ListenConn:
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

    def deliver(self, channel: str, payload: str) -> None:
        callback = self.listeners.get(channel)
        if callback is not None:
            callback(self, 12345, channel, payload)


class _RoutingPoolConn:
    def __init__(self, cluster: _RoutingFakeAsyncpg) -> None:
        self._cluster = cluster

    async def execute(self, sql: str, *args) -> None:
        channel, payload = args
        self._cluster.published.append(payload)
        for conn in list(self._cluster.listen_conns):
            if not conn.closed:
                conn.deliver(channel, payload)


class _RoutingPool:
    def __init__(self, cluster: _RoutingFakeAsyncpg) -> None:
        self._cluster = cluster
        self.closed = False

    def acquire(self) -> _RoutingPool._Ctx:
        return _RoutingPool._Ctx(self._cluster)

    async def close(self) -> None:
        self.closed = True

    class _Ctx:
        def __init__(self, cluster: _RoutingFakeAsyncpg) -> None:
            self._cluster = cluster

        async def __aenter__(self) -> _RoutingPoolConn:
            return _RoutingPoolConn(self._cluster)

        async def __aexit__(self, *exc_info) -> None:
            return None


class _RoutingFakeAsyncpg:
    PostgresError = _FakePostgresError

    def __init__(self) -> None:
        self.listen_conns: list[_ListenConn] = []
        self.published: list[str] = []

    async def connect(self, dsn: str) -> _ListenConn:
        conn = _ListenConn()
        self.listen_conns.append(conn)
        return conn

    async def create_pool(self, dsn: str, min_size: int, max_size: int) -> _RoutingPool:
        return _RoutingPool(self)


class _RecordingWS:

    def __init__(self) -> None:
        self.sent: list[str] = []

    async def send_text(self, data: str) -> None:
        self.sent.append(data)

    async def close(self, code: int = 1000, reason: str = "") -> None:
        return None


@pytest.fixture
def cluster(monkeypatch) -> _RoutingFakeAsyncpg:
    fake = _RoutingFakeAsyncpg()
    monkeypatch.setattr(pn, "asyncpg", fake)
    return fake


@pytest.fixture
def multiworker(monkeypatch) -> None:
    import api.startup.database as db_startup

    monkeypatch.setattr(db_startup, "_worker_count", lambda: 2)


async def _worker(cluster: _RoutingFakeAsyncpg) -> tuple[WebSocketManager, PostgresNotifyWebSocketEventBroker]:
    broker = PostgresNotifyWebSocketEventBroker(dsn="postgresql://fake/db")
    await broker.start()
    manager = WebSocketManager()
    manager.attach_broker(broker)
    return manager, broker


def _wire(manager: WebSocketManager, client_id: str, ws: _RecordingWS, tenant_key: str = TENANT) -> None:
    manager.active_connections[client_id] = ws
    manager.auth_contexts[client_id] = {"tenant_key": tenant_key}
    manager._index_tenant_connection(client_id, tenant_key)


async def _wait_until(condition, tries: int = 500) -> None:
    for _ in range(tries):
        if condition():
            return
        await asyncio.sleep(0)


@dataclass
class _Pair:

    manager_a: WebSocketManager
    manager_b: WebSocketManager
    broker_a: PostgresNotifyWebSocketEventBroker
    broker_b: PostgresNotifyWebSocketEventBroker
    ws_b: _RecordingWS


@pytest.fixture
async def pair(cluster, multiworker):
    manager_a, broker_a = await _worker(cluster)
    manager_b, broker_b = await _worker(cluster)
    ws_b = _RecordingWS()
    _wire(manager_b, "browser-on-worker-b", ws_b)
    try:
        yield _Pair(manager_a, manager_b, broker_a, broker_b, ws_b)
    finally:
        await broker_a.stop()
        await broker_b.stop()


async def _delivered(pair: _Pair) -> dict:
    await _wait_until(lambda: bool(pair.ws_b.sent))
    assert pair.ws_b.sent, (
        "the event never crossed the broker: a session on another worker received "
        "nothing, which is the prod symptom (visible only on refetch)"
    )
    return json.loads(pair.ws_b.sent[0])




async def test_a_long_project_description_reaches_a_session_on_another_worker(pair):
    await pair.manager_a.broadcast_project_update(
        project_id="11111111-1111-4111-8111-111111111111",
        update_type="updated",
        project_data={
            "name": "A project with a very long description",
            "description": "D" * 12_000,
            "status": "active",
            "mission": "M" * 4_000,
        },
        tenant_key=TENANT,
    )

    delivered = await _delivered(pair)
    assert delivered["type"] == "project_update"
    assert delivered["data"]["project_id"] == "11111111-1111-4111-8111-111111111111"
    assert delivered["data"]["update_type"] == "updated"


async def test_the_published_project_update_stays_under_the_pg_notify_cap(cluster, multiworker):
    manager_a, broker_a = await _worker(cluster)
    try:
        await manager_a.broadcast_project_update(
            project_id="x" * 36,
            update_type="updated",
            project_data={
                "name": "N" * 255,
                "description": WORST_CHAR * 20_000,
                "status": "active",
                "mission": WORST_CHAR * 20_000,
            },
            tenant_key=TENANT,
        )
        assert cluster.published, "nothing was published to the broker at all"
        size = len(cluster.published[0].encode("utf-8"))
        assert size <= _MAX_NOTIFY_PAYLOAD_BYTES, (
            f"published NOTIFY payload is {size} bytes, over the {_MAX_NOTIFY_PAYLOAD_BYTES}-byte pg_notify cap"
        )
    finally:
        await broker_a.stop()


async def test_a_truncated_project_update_says_so_and_states_the_full_length(pair):
    await pair.manager_a.broadcast_project_update(
        project_id="p" * 36,
        update_type="updated",
        project_data={"name": "n", "description": "D" * 12_000, "status": "active", "mission": None},
        tenant_key=TENANT,
    )

    data = (await _delivered(pair))["data"]
    assert data["description_truncated"] is True
    assert data["description_length"] == 12_000
    assert len(data["description"]) < 12_000


async def test_a_short_project_update_travels_whole_and_says_it_is_whole(pair):
    await pair.manager_a.broadcast_project_update(
        project_id="p" * 36,
        update_type="status_changed",
        project_data={
            "name": "Short project",
            "description": "a normal description",
            "status": "completed",
            "mission": "a normal mission",
        },
        tenant_key=TENANT,
    )

    data = (await _delivered(pair))["data"]
    assert data["description"] == "a normal description"
    assert data["description_truncated"] is False
    assert data["description_length"] == len("a normal description")
    assert data["mission"] == "a normal mission"
    assert data["mission_truncated"] is False




def _agent_created_ctx(mission: str) -> BroadcastAgentCreatedContext:
    return BroadcastAgentCreatedContext(
        tenant_key=TENANT,
        project_id="22222222-2222-4222-8222-222222222222",
        agent_execution=SimpleNamespace(id="33333333-3333-4333-8333-333333333333"),
        agent_id="44444444-4444-4444-8444-444444444444",
        job_id="55555555-5555-4555-8555-555555555555",
        agent_display_name="implementer",
        agent_name="implementer-backend",
        mission=mission,
        phase=1,
        created_at=datetime.now(UTC),
    )


async def test_an_oversized_agent_created_mission_reaches_another_worker(pair):
    service = JobLifecycleService(db_manager=None, tenant_manager=None, websocket_manager=pair.manager_a)

    await service._broadcast_agent_created(_agent_created_ctx("M" * 30_000))

    delivered = await _delivered(pair)
    assert delivered["type"] == "agent:created"
    assert delivered["data"]["job_id"] == "55555555-5555-4555-8555-555555555555"
    assert delivered["data"]["mission_truncated"] is True
    assert delivered["data"]["mission_length"] == 30_000


async def test_a_short_agent_created_mission_travels_whole(pair):
    service = JobLifecycleService(db_manager=None, tenant_manager=None, websocket_manager=pair.manager_a)

    await service._broadcast_agent_created(_agent_created_ctx("Do the thing."))

    data = (await _delivered(pair))["data"]
    assert data["mission"] == "Do the thing."
    assert data["mission_truncated"] is False




def _mission_update_deps(pair: _Pair):
    orchestration_service = AsyncMock()
    orchestration_service.update_agent_mission.return_value = SimpleNamespace(mission_length=1)

    job_query_service = AsyncMock()
    job_query_service.get_agent_job_by_job_id.return_value = SimpleNamespace(
        job_type="implementer", project_id="66666666-6666-4666-8666-666666666666"
    )
    job_query_service.get_latest_execution_for_job.return_value = SimpleNamespace(
        agent_display_name="implementer", agent_name="implementer-backend"
    )
    return orchestration_service, job_query_service


async def _patch_mission(pair: _Pair, mission: str):
    orchestration_service, job_query_service = _mission_update_deps(pair)
    return await update_agent_mission(
        job_id="55555555-5555-4555-8555-555555555555",
        request=SimpleNamespace(mission=mission),
        current_user=SimpleNamespace(username="operator", tenant_key=TENANT),
        orchestration_service=orchestration_service,
        session=None,
        job_query_service=job_query_service,
        ws_dep=WebSocketDependency(manager=pair.manager_a),
    )


async def test_editing_a_mission_broadcasts_at_all(pair):
    await _patch_mission(pair, "A corrected mission.")

    delivered = await _delivered(pair)
    assert delivered["type"] == "agent:mission_updated"
    assert delivered["data"]["mission"] == "A corrected mission."
    assert delivered["data"]["job_id"] == "55555555-5555-4555-8555-555555555555"


async def test_an_oversized_mission_edit_reaches_another_worker(pair):
    await _patch_mission(pair, "M" * 50_000)

    data = (await _delivered(pair))["data"]
    assert data["mission_truncated"] is True
    assert data["mission_length"] == 50_000
    assert len(data["mission"]) < 50_000


async def test_a_websocket_outage_does_not_fail_a_committed_mission_write(pair):
    orchestration_service, job_query_service = _mission_update_deps(pair)

    result = await update_agent_mission(
        job_id="55555555-5555-4555-8555-555555555555",
        request=SimpleNamespace(mission="m"),
        current_user=SimpleNamespace(username="operator", tenant_key=TENANT),
        orchestration_service=orchestration_service,
        session=None,
        job_query_service=job_query_service,
        ws_dep=WebSocketDependency(manager=None),
    )

    assert result.success is True
    assert result.mission == "m"




async def test_worst_case_envelope_keeps_headroom_under_the_cap(cluster, multiworker):
    manager_a, broker_a = await _worker(cluster)
    try:
        await manager_a.broadcast_project_update(
            project_id="p" * 36,
            update_type="status_changed",
            project_data={
                "name": WORST_CHAR * 255,
                "description": WORST_CHAR * 50_000,
                "status": "active",
                "mission": WORST_CHAR * 50_000,
            },
            tenant_key="t" * 64,
        )
        size = len(cluster.published[0].encode("utf-8"))
        headroom = _MAX_NOTIFY_PAYLOAD_BYTES - size
        assert headroom >= _REQUIRED_HEADROOM_BYTES, (
            f"worst-case NOTIFY payload is {size} bytes, leaving only {headroom} bytes "
            f"under the {_MAX_NOTIFY_PAYLOAD_BYTES}-byte cap; {_REQUIRED_HEADROOM_BYTES} required"
        )
    finally:
        await broker_a.stop()


async def test_the_excerpt_is_valid_text_not_valid_looking_bytes(pair):
    await pair.manager_a.broadcast_project_update(
        project_id="p" * 36,
        update_type="updated",
        project_data={"name": "n", "description": CJK_CHAR * 5_000, "status": "active", "mission": None},
        tenant_key=TENANT,
    )

    data = (await _delivered(pair))["data"]
    assert data["description_truncated"] is True
    assert data["description"], "the excerpt is empty; nothing was preserved to check"
    assert "�" not in data["description"], "the excerpt contains U+FFFD -- a slice landed inside a code point"
    assert set(data["description"]) == {CJK_CHAR}, "the excerpt is not a clean prefix of the original"


async def test_an_absent_field_is_not_invented(pair):
    await pair.manager_a.broadcast_project_update(
        project_id="p" * 36,
        update_type="updated",
        project_data={"name": "n", "description": "short", "status": "active", "mission": None},
        tenant_key=TENANT,
    )

    data = (await _delivered(pair))["data"]
    assert data["mission"] is None
    assert "mission_truncated" not in data
    assert "mission_length" not in data
    assert data["description_truncated"] is False


async def test_a_rebound_never_overwrites_the_true_original_length(pair):
    service = JobLifecycleService(db_manager=None, tenant_manager=None, websocket_manager=pair.manager_a)
    await service._broadcast_agent_created(_agent_created_ctx("M" * 30_000))

    data = (await _delivered(pair))["data"]
    assert data["mission_length"] == 30_000, "the receiving worker recomputed the length from its own excerpt"
    assert data["mission_truncated"] is True
    assert len(data["mission"]) < 30_000


async def test_an_unregistered_event_type_is_passed_through_untouched(pair):
    assert "thread_message" not in BOUNDED_EVENT_FIELDS

    await pair.manager_a.broadcast_to_tenant(
        tenant_key=TENANT,
        event_type="some:other_event",
        data={"mission": "M" * 50, "description": "D" * 50},
    )

    data = (await _delivered(pair))["data"]
    assert data["mission"] == "M" * 50
    assert "mission_truncated" not in data
    assert "description_truncated" not in data


def test_the_budget_leaves_room_for_the_broker_envelope():
    assert MAX_EVENT_BYTES < _MAX_NOTIFY_PAYLOAD_BYTES
    assert _MAX_NOTIFY_PAYLOAD_BYTES - MAX_EVENT_BYTES >= _REQUIRED_HEADROOM_BYTES
