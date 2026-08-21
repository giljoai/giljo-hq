# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-9414 — a long Hub message must still cross the cross-worker broker.

Edition Scope: Both (the emitter and the broker are CE code; multi-worker is the
SaaS deployment shape).

The defect, measured live on prod: ``broadcast_thread_message`` put the whole
message body on the wire, so any post over ~7 KB produced a NOTIFY payload past
the pg_notify 7999-byte cap. BE-3008c's guard raised (correctly), the caller
swallowed it as a WS006 warning (correctly — the local send already happened),
and every session on a DIFFERENT uvicorn worker silently never saw the message.
The guard was right; the emitter never adopted ids-not-blobs.

Tested AT THE FAILING LAYER: two real ``WebSocketManager`` + real
``PostgresNotifyWebSocketEventBroker`` pairs over one routing fake cluster, so a
publish on worker A has to survive the byte cap and reach a socket on worker B.
The assertion is on DELIVERY, not on "no exception raised" — the production
failure is swallowed, so an exception-based assertion would pass on the broken
code for the wrong reason.

Parallel-safe: no DB, no module-level mutable state; asyncpg is replaced with an
in-test fake via monkeypatch.
"""

from __future__ import annotations

import asyncio
import json

import pytest

import api.broker.postgres_notify as pn
from api.broker.postgres_notify import _MAX_NOTIFY_PAYLOAD_BYTES, PostgresNotifyWebSocketEventBroker
from api.endpoints._comm_ws import broadcast_thread_message
from api.websocket import WebSocketManager


CHANNEL = "giljo_ws_events"

# The most expensive character the 20,000-char content cap admits. json.dumps runs
# ensure_ascii=True, so an astral character is escaped as a SURROGATE PAIR —
# ``\udbxx\udcxx`` — 12 bytes on the wire for one source character. Measured, not
# assumed: this is why the bound is computed in bytes and never in characters.
WORST_CHAR = "\U0001f600"
CONTENT_CAP_CHARS = 20_000

# Headroom the boundary pin requires between the worst-case envelope and the cap.
# Everything above the emitter (ws wrapper + broker wrapper) measured 316 bytes at
# maximal ids; this leaves room for that to grow without silently re-approaching
# the cliff.
_REQUIRED_HEADROOM_BYTES = 1_000


# ---------------------------------------------------------------------------
# A fake asyncpg that ROUTES pg_notify between brokers (a one-node cluster)
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
        # The broker only ever issues SELECT pg_notify($1, $2).
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
    """asyncpg stand-in whose NOTIFY reaches every LISTEN connection.

    The BE-3008c harness records what a pool executed; it does not deliver it
    anywhere. Cross-worker delivery is the whole subject here, so this one
    actually routes: a publish from any worker's pool fans out to every other
    worker's listener, which is what a real single-node cluster does.
    """

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
    stayed green — so the failing shape only exists with this forced on.
    """
    import api.startup.database as db_startup

    monkeypatch.setattr(db_startup, "_worker_count", lambda: 2)


async def _worker(cluster: _RoutingFakeAsyncpg) -> tuple[WebSocketManager, PostgresNotifyWebSocketEventBroker]:
    broker = PostgresNotifyWebSocketEventBroker(dsn="postgresql://fake/db")
    await broker.start()
    manager = WebSocketManager()
    manager.attach_broker(broker)
    return manager, broker


def _wire(manager: WebSocketManager, client_id: str, ws: _RecordingWS, tenant_key: str) -> None:
    manager.active_connections[client_id] = ws
    manager.auth_contexts[client_id] = {"tenant_key": tenant_key}
    manager._index_tenant_connection(client_id, tenant_key)


async def _wait_until(condition, tries: int = 500) -> None:
    for _ in range(tries):
        if condition():
            return
        await asyncio.sleep(0)


async def _post(manager: WebSocketManager, content: str, **overrides) -> None:
    kwargs = {
        "thread_id": "11111111-1111-4111-8111-111111111111",
        "message_id": "22222222-2222-4222-8222-222222222222",
        "from_agent_id": "orchestrator",
        "from_display_name": "Coordinator",
        "content": content,
        "message_type": "broadcast",
        "priority": "normal",
        "requires_action": False,
        "project_id": None,
    }
    kwargs.update(overrides)
    await broadcast_thread_message(manager, "tk_be9414", **kwargs)


# ---------------------------------------------------------------------------
# DoD 1 — fail-first at the failing layer: delivery across workers
# ---------------------------------------------------------------------------


async def test_a_long_hub_message_reaches_a_session_on_another_worker(cluster, multiworker):
    """The prod defect, end to end: worker A posts, worker B's browser must see it.

    ~9 KB of content puts the envelope past the 7999-byte cap, which is the size
    range the prod logs recorded (8307 / 8701 / 9826 / 10286 bytes). Before the
    fix the publish raises, api/websocket.py swallows it as WS006, and this
    assertion fails with an empty socket — the silent realtime gap itself.
    """
    manager_a, broker_a = await _worker(cluster)
    manager_b, broker_b = await _worker(cluster)
    ws_b = _RecordingWS()
    _wire(manager_b, "browser-on-worker-b", ws_b, "tk_be9414")

    try:
        await _post(manager_a, "x" * 9_000)
        await _wait_until(lambda: bool(ws_b.sent))

        assert ws_b.sent, (
            "the message never crossed the broker: a session on another worker "
            "received nothing, which is the prod symptom (visible only on refetch)"
        )
        delivered = json.loads(ws_b.sent[0])
        assert delivered["type"] == "thread_message"
        assert delivered["data"]["message_id"] == "22222222-2222-4222-8222-222222222222"
        assert delivered["data"]["thread_id"] == "11111111-1111-4111-8111-111111111111"
    finally:
        await broker_a.stop()
        await broker_b.stop()


async def test_the_published_payload_stays_under_the_pg_notify_cap(cluster, multiworker):
    """The guard must never be the thing that stops it — the emitter fits first."""
    manager_a, broker_a = await _worker(cluster)
    try:
        await _post(manager_a, "x" * 9_000)
        assert cluster.published, "nothing was published to the broker at all"
        size = len(cluster.published[0].encode("utf-8"))
        assert size <= _MAX_NOTIFY_PAYLOAD_BYTES, (
            f"published NOTIFY payload is {size} bytes, over the {_MAX_NOTIFY_PAYLOAD_BYTES}-byte pg_notify cap"
        )
    finally:
        await broker_a.stop()


async def test_a_truncated_delivery_names_the_message_so_the_receiver_can_fetch_it(cluster, multiworker):
    """ids-not-blobs: what does not fit must still be findable.

    A receiver that gets an excerpt has to be able to say WHICH message it holds
    an excerpt of, and that it holds one at all. Without the flag the client
    cannot tell a shortened body from a short body, and would render the excerpt
    forever.
    """
    manager_a, broker_a = await _worker(cluster)
    manager_b, broker_b = await _worker(cluster)
    ws_b = _RecordingWS()
    _wire(manager_b, "browser-on-worker-b", ws_b, "tk_be9414")

    try:
        content = "y" * 12_000
        await _post(manager_a, content)
        await _wait_until(lambda: bool(ws_b.sent))
        assert ws_b.sent, "nothing crossed the broker"

        data = json.loads(ws_b.sent[0])["data"]
        assert data["content_truncated"] is True
        assert data["content_length"] == len(content)
        assert data["message_id"] and data["thread_id"]
        assert content.startswith(data["content"]), "the excerpt must be a real prefix of the message"
        assert data["content"], "an excerpt of nothing is not an excerpt"
    finally:
        await broker_a.stop()
        await broker_b.stop()


async def test_a_normal_length_message_is_delivered_whole_and_unflagged(cluster, multiworker):
    """Regression guard: the fix must not rewrite the 99% that already worked."""
    manager_a, broker_a = await _worker(cluster)
    manager_b, broker_b = await _worker(cluster)
    ws_b = _RecordingWS()
    _wire(manager_b, "browser-on-worker-b", ws_b, "tk_be9414")

    try:
        content = "a short coordination post, the ordinary case"
        await _post(manager_a, content)
        await _wait_until(lambda: bool(ws_b.sent))
        assert ws_b.sent, "nothing crossed the broker"

        data = json.loads(ws_b.sent[0])["data"]
        assert data["content"] == content
        assert data["content_truncated"] is False
        assert data["content_length"] == len(content)
    finally:
        await broker_a.stop()
        await broker_b.stop()


# ---------------------------------------------------------------------------
# DoD 2 — boundary math, pinned as a test rather than asserted in a comment
# ---------------------------------------------------------------------------


async def test_worst_case_envelope_fits_the_cap_with_stated_headroom(cluster, multiworker):
    """The 20,000-char cap at 12 bytes/char, with maximal ids, still fits.

    Worst case on every axis the service's own caps permit: content at
    MCP_MESSAGE_MAX entirely in astral characters (surrogate-pair escaped, the
    most expensive encoding json.dumps can produce), a 64-char tenant_key,
    64-char ids, a 200-char display name, and requires_action True. This is the
    number that makes the fix a bound rather than a hope.
    """
    manager_a, broker_a = await _worker(cluster)
    try:
        await _post(
            manager_a,
            WORST_CHAR * CONTENT_CAP_CHARS,
            thread_id="i" * 64,
            message_id="m" * 64,
            from_agent_id="A" * 64,
            from_display_name="D" * 200,
            project_id="p" * 64,
            message_type="loop_directive",
            priority="urgent",
            requires_action=True,
        )
        assert cluster.published, "nothing was published to the broker at all"
        size = len(cluster.published[0].encode("utf-8"))
        headroom = _MAX_NOTIFY_PAYLOAD_BYTES - size
        assert size <= _MAX_NOTIFY_PAYLOAD_BYTES, (
            f"worst-case envelope is {size} bytes, over the {_MAX_NOTIFY_PAYLOAD_BYTES}-byte cap"
        )
        assert headroom >= _REQUIRED_HEADROOM_BYTES, (
            f"worst-case envelope is {size} bytes, leaving only {headroom} bytes of headroom "
            f"under the {_MAX_NOTIFY_PAYLOAD_BYTES}-byte cap "
            f"(at least {_REQUIRED_HEADROOM_BYTES} required)"
        )
    finally:
        await broker_a.stop()


async def test_the_excerpt_never_splits_a_character_in_half(cluster, multiworker):
    """The excerpt must be valid TEXT, not valid-looking bytes.

    The bound binary-searches CHARACTER prefixes, and a Python string slice cannot
    land inside a code point. The obvious "optimisation" — slicing the encoded
    bytes instead (``content.encode()[:n].decode(..., "replace")``) — is faster and
    silently emits U+FFFD mid-word.

    Deliberately CJK, not the emoji used elsewhere in this file. A byte slice of
    pure 4-byte astral text happens to land on character boundaries anyway, so an
    emoji fixture passes under that mutation and proves nothing; 3-byte characters
    do not divide evenly and expose it. Measured, not assumed: the emoji version of
    this test was written first, stayed green under the byte-slice mutation, and
    was replaced.
    """
    cjk = "中文" * (CONTENT_CAP_CHARS // 2)
    manager_a, broker_a = await _worker(cluster)
    manager_b, broker_b = await _worker(cluster)
    ws_b = _RecordingWS()
    _wire(manager_b, "browser-on-worker-b", ws_b, "tk_be9414")

    try:
        await _post(manager_a, cjk)
        await _wait_until(lambda: bool(ws_b.sent))
        assert ws_b.sent, "nothing crossed the broker"

        excerpt = json.loads(ws_b.sent[0])["data"]["content"]
        assert excerpt, "an excerpt of nothing is not an excerpt"
        assert cjk.startswith(excerpt), "the excerpt is not a character prefix of the message"
        assert "�" not in excerpt, "the excerpt was cut inside a character"
        assert excerpt.encode("utf-8").decode("utf-8") == excerpt, "the excerpt does not round-trip as text"
    finally:
        await broker_a.stop()
        await broker_b.stop()


async def test_the_worst_case_content_really_is_twelve_bytes_per_character(cluster):
    """Pins the premise the budget rests on, so it cannot rot silently.

    If json.dumps ever stopped escaping to ASCII, the per-character cost would
    drop and the budget would merely be conservative. If some future field made
    it WORSE than 12, the budget would be wrong and this fails first.
    """
    one = len(json.dumps({"c": WORST_CHAR}).encode("utf-8"))
    two = len(json.dumps({"c": WORST_CHAR * 2}).encode("utf-8"))
    assert two - one == 12, "an astral character must cost 12 bytes as an escaped surrogate pair"
