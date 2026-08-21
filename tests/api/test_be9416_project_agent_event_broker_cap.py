# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-9416 — project_update and agent:created/agent:mission_updated must cross the broker.

Edition Scope: Both (the emitters and the broker are CE code; multi-worker is the
SaaS deployment shape).

The defect, measured live on prod 2026-08-14 (WS006 at 06:57Z and 14:52Z): a
``project_update`` carrying a long project description serialized to 12,825 bytes
against the pg_notify 7999-byte cap, so ``PostgresNotifyWebSocketEventBroker.publish``
raised (BE-3008c's guard, working as designed), ``api/websocket.py`` swallowed it as
a WS006 warning (also correct -- the local send already happened), and every session
on a DIFFERENT uvicorn worker silently never saw the update. Same latent shape on
``agent:created`` and ``agent:mission_updated``, which ship the full agent mission.

Tested AT THE FAILING LAYER, reusing BE-9414's proven harness shape: two real
``WebSocketManager`` + real ``PostgresNotifyWebSocketEventBroker`` pairs over one
routing fake cluster, so a publish on worker A has to survive the byte cap and reach
a socket on worker B. Every assertion is on DELIVERY, not on "no exception raised" --
the production failure is SWALLOWED, so an exception-based assertion would pass on
the broken code for the wrong reason.

Parallel-safe: no DB, no module-level mutable state; asyncpg is replaced with an
in-test fake via monkeypatch.
"""

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

# The most expensive character json.dumps can emit. ensure_ascii=True escapes an
# ASTRAL character as a SURROGATE PAIR -- ``\udbxx\udcxx`` -- 12 bytes on the wire
# for one source character. Measured, not assumed: this is why the bound is
# computed in bytes and never in characters.
WORST_CHAR = "\U0001f600"

# A 3-byte-in-UTF-8 BMP character. Deliberately NOT the astral fixture: a byte
# slice of pure 4-byte astral text happens to land on character boundaries anyway,
# so it stays green under exactly the mutation the text-integrity test is written
# to catch. 3-byte characters do not divide evenly and expose it (BE-9414's finding).
CJK_CHAR = "中"

# Headroom the boundary pin requires between the worst-case envelope and the cap,
# so growth above the emitter (ws envelope + broker envelope) cannot silently
# re-approach the cliff.
_REQUIRED_HEADROOM_BYTES = 1_000


# ---------------------------------------------------------------------------
# A fake asyncpg that ROUTES pg_notify between brokers (a one-node cluster).
# Same shape as BE-9414's; cross-worker delivery is the whole subject, so the
# fake has to actually deliver rather than merely record what a pool executed.
# ---------------------------------------------------------------------------


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
    """A subscribed browser socket on the receiving worker."""

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
    """Cross-worker publishing is disabled at worker_count == 1 (m15).

    That is exactly why single-worker CE never hit this defect and every test
    stayed green -- so the failing shape only exists with this forced on. A test
    in this module that forgets this fixture passes VACUOUSLY on broken code.
    """
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
    """Two workers sharing one cluster, with a browser socket on worker B."""

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


# ---------------------------------------------------------------------------
# project_update — the event that is failing LIVE
# ---------------------------------------------------------------------------


async def test_a_long_project_description_reaches_a_session_on_another_worker(pair):
    """The prod defect, end to end: worker A updates a project, worker B's browser must see it.

    12,000 characters of description reproduces the size range prod recorded
    (12,825 bytes). Before the fix the publish raises, api/websocket.py swallows
    it as WS006, and this assertion fails with an empty socket -- the silent
    realtime gap itself.
    """
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
    """The guard must never be the thing that stops it -- the emitter fits first."""
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
    """ids-not-blobs: what does not fit must still be findable.

    Without the flags a client cannot tell a shortened description from a short
    one, and would render the excerpt forever. ``project_id`` + ``_length`` is
    everything a consumer needs to decide to re-fetch.
    """
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
    """Ordinary updates must be unaffected, and must SAY they are unaffected.

    "No flag" can never be allowed to mean "not truncated" -- a client reading an
    event from a worker that predates this field would guess wrong. So the flags
    are always present, including on the untouched path.
    """
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


# ---------------------------------------------------------------------------
# agent:created — the MCP spawn path's emitter
# ---------------------------------------------------------------------------


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
    """A spawn with a long mission must still put the agent row on every browser.

    SpawnAgentRequest.mission carries no max_length at all, so this is not a
    theoretical size -- an orchestrator mission of tens of KB is ordinary.
    """
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


# ---------------------------------------------------------------------------
# agent:mission_updated — the REPAIR path, which had never fired at all
# ---------------------------------------------------------------------------


def _mission_update_deps(pair: _Pair):
    """The handler's injectables, stubbed. No DB, no ASGI scope."""
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
    """RED ON MASTER for a reason that has nothing to do with byte caps.

    The handler did ``from api.websocket_manager import manager`` -- that shim has
    no ``manager`` -- and called ``emit_to_tenant``, which exists nowhere in the
    repo. So every mission edit raised ImportError AFTER the write had committed:
    the mission saved, the operator was shown a failure, and no session anywhere
    updated. Broken since Handover 0244b; invisible because the import is
    function-local and no test drove the route.
    """
    await _patch_mission(pair, "A corrected mission.")

    delivered = await _delivered(pair)
    assert delivered["type"] == "agent:mission_updated"
    assert delivered["data"]["mission"] == "A corrected mission."
    assert delivered["data"]["job_id"] == "55555555-5555-4555-8555-555555555555"


async def test_an_oversized_mission_edit_reaches_another_worker(pair):
    """The bound, on the path that repairs a mission.

    UpdateMissionRequest.mission caps at 50,000 characters -- 6x the pg_notify cap
    in the cheapest possible encoding.
    """
    await _patch_mission(pair, "M" * 50_000)

    data = (await _delivered(pair))["data"]
    assert data["mission_truncated"] is True
    assert data["mission_length"] == 50_000
    assert len(data["mission"]) < 50_000


async def test_a_websocket_outage_does_not_fail_a_committed_mission_write(pair):
    """Graceful degradation: the write already committed, so WS must never 500 it.

    This is the posture the broken code got wrong in the other direction -- it
    raised, on a write that had already succeeded.
    """
    orchestration_service, job_query_service = _mission_update_deps(pair)

    result = await update_agent_mission(
        job_id="55555555-5555-4555-8555-555555555555",
        request=SimpleNamespace(mission="m"),
        current_user=SimpleNamespace(username="operator", tenant_key=TENANT),
        orchestration_service=orchestration_service,
        session=None,
        job_query_service=job_query_service,
        ws_dep=WebSocketDependency(manager=None),  # WS unavailable
    )

    assert result.success is True
    assert result.mission == "m"


# ---------------------------------------------------------------------------
# Properties the bound quietly depends on
# ---------------------------------------------------------------------------


async def test_worst_case_envelope_keeps_headroom_under_the_cap(cluster, multiworker):
    """Pin the headroom by measurement rather than asserting it in a comment.

    Every bounded field at its maximum, in the most expensive encoding, with
    maximal ids. If a future field is added to any of these events, this fails
    before the cliff rather than after it.
    """
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
    """The bound searches CHARACTER prefixes, so a slice can never split a code point.

    The obvious optimisation -- slice the encoded bytes instead -- is faster and
    emits U+FFFD mid-word. Pinned with CJK content specifically: a byte slice of
    pure 4-byte astral text happens to land on character boundaries anyway and
    would stay GREEN under exactly the mutation this test exists to catch.
    """
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
    """A None field carries no bytes worth trimming, and must not gain flags.

    Stamping ``mission_truncated`` on an event whose emitter deliberately sent no
    mission would tell the consumer to re-fetch something that does not exist.
    """
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
    """Events arriving FROM the broker pass through this funnel a second time.

    They are already bounded, so recomputing ``mission_length`` on the receiving
    worker would overwrite the TRUE original length with the excerpt's -- telling the
    client its excerpt is the whole thing, which is the exact silent-truncation
    ambiguity the flags exist to prevent. ``setdefault`` is what stops it, and this
    is the test that fails if someone "simplifies" it to a plain assignment.
    """
    service = JobLifecycleService(db_manager=None, tenant_manager=None, websocket_manager=pair.manager_a)
    await service._broadcast_agent_created(_agent_created_ctx("M" * 30_000))

    data = (await _delivered(pair))["data"]
    assert data["mission_length"] == 30_000, "the receiving worker recomputed the length from its own excerpt"
    assert data["mission_truncated"] is True
    assert len(data["mission"]) < 30_000


async def test_an_unregistered_event_type_is_passed_through_untouched(pair):
    """The registry is the impact area. Only the three censused types are bounded.

    BE-9414's thread_message bounds itself in _comm_ws.py and must never be
    double-bounded here; nothing else should acquire flags it did not ask for.
    """
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
    """MAX_EVENT_BYTES must sit far enough below the hard cap to wrap the event."""
    assert MAX_EVENT_BYTES < _MAX_NOTIFY_PAYLOAD_BYTES
    assert _MAX_NOTIFY_PAYLOAD_BYTES - MAX_EVENT_BYTES >= _REQUIRED_HEADROOM_BYTES
