# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-9296a — the server wake signal, and the premise it had to be built against.

The project specified blocking on the PostgresNotifyBroker. That design is dead on
a default install and these tests pin why, so nobody rebuilds it:

* ``api/websocket.py`` only publishes to the broker when ``_publish_to_broker_enabled``,
  which is ``_worker_count() > 1``; ``WEB_CONCURRENCY`` defaults to 1.
* ``api/broker/__init__.py`` defaults the broker to ``in_memory``, and
  ``GILJO_WS_BROKER`` is set in no shipping config in this tree.

So on the install every CE self-hoster runs, the broker never sees the event and a
broker-backed wake would have returned empty at every timeout — silently, with the
whole suite green. ``test_wake_fires_on_a_default_single_worker_install`` is the
acceptance check the original design would have failed.

The rest cover the service side: which writes wake whom, and that the signal
fires only after the write commits. The registry primitive's own races live in
``test_agent_wake_registry.py``.

Parallel-safe: rollback-isolated ``db_session`` (TransactionalTestContext), no
module-level mutable state, each test owns its setup, every query tenant-scoped.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta

import pytest

from giljo_mcp.database import DatabaseManager, tenant_session_context
from giljo_mcp.services._comm_thread_wake_mixin import (
    DEFAULT_WAIT_SECONDS,
    LIVENESS_GONE_AFTER_MINUTES,
    LIVENESS_QUIET_AFTER_MINUTES,
    MAX_WAIT_SECONDS,
    POST_ADVICE,
    TIMEOUT_ADVICE,
)
from giljo_mcp.services.agent_wake_registry import get_wake_registry
from giljo_mcp.services.comm_thread_service import CommThreadService
from giljo_mcp.services.taxonomy_ops import ensure_default_types_seeded
from giljo_mcp.tenant import TenantManager
from tests.helpers.test_db_helper import PostgreSQLTestHelper, purge_tenant_rows


# No module-level ``pytest.mark.asyncio``: this file mixes async and plain sync
# assertions, and addopts already runs ``--asyncio-mode=auto``. Marking the module
# would apply the marker to the sync tests too (same reason INF-3000b notes it).

# A wake must be perceptibly instant, not "eventually". The DoD says under 2s;
# in-process delivery is sub-millisecond, so a generous ceiling still fails loudly
# if the signal is ever routed through something that polls.
WAKE_DEADLINE_SECONDS = 2.0


def _tk(suffix: str) -> str:
    return f"tk_be9296a_{suffix}_{uuid.uuid4().hex[:8]}"


def _service(db_manager, db_session) -> CommThreadService:
    return CommThreadService(db_manager, TenantManager(), session=db_session)


async def _seed(db_session, tenant: str) -> None:
    with tenant_session_context(db_session, tenant):
        await ensure_default_types_seeded(db_session, tenant)


async def _thread_with(svc: CommThreadService, tenant: str, *, creator: str, joiner: str) -> str:
    created = await svc.create_thread(subject="wake", creator_id=creator, tenant_key=tenant)
    thread_id = created["thread_id"]
    await svc.join_thread(thread_id=thread_id, participant_id=joiner, display_name="Worker", tenant_key=tenant)
    return thread_id


async def _park(svc: CommThreadService, tenant: str, agent_id: str, *, timeout_seconds: int = 5) -> asyncio.Task:
    """Start a waiter and return only once it is genuinely parked on its event.

    Waiting on a real sync point rather than a sleep, for two reasons. It is
    deterministic under load (a timed guess is the classic xdist flake), and more
    importantly these tests share ONE rollback-isolated session between the waiter
    and the writer. Returning while the waiter's own ``get_my_turn`` read is still
    in flight would interleave two coroutines on that single session and trip the
    tenant guard — a test-harness artifact, not a product defect, since every real
    request owns its session.

    Instrumenting the instance's ``get_my_turn`` gives the exact edge we need: when
    it has returned, the waiter runs synchronously on to ``wait_for`` and suspends
    there before this coroutine is rescheduled. So once ``read_done`` is set, the
    waiter is parked and holding nothing.
    """
    read_done = asyncio.Event()
    original = svc.get_my_turn

    async def _instrumented(**kwargs):
        result = await original(**kwargs)
        read_done.set()
        return result

    svc.get_my_turn = _instrumented  # type: ignore[method-assign]
    task = asyncio.create_task(svc.await_my_turn(agent_id=agent_id, timeout_seconds=timeout_seconds, tenant_key=tenant))
    await asyncio.wait_for(read_done.wait(), timeout=WAKE_DEADLINE_SECONDS)
    assert get_wake_registry().waiter_count(tenant) >= 1, "waiter read but never registered"
    return task


async def test_wait_seconds_are_clamped_not_rejected():
    """An overshoot is harmless plumbing; refusing it would fail a real call."""
    clamp = CommThreadService._resolve_wait_seconds
    assert clamp(None) == DEFAULT_WAIT_SECONDS
    assert clamp(0) == DEFAULT_WAIT_SECONDS
    assert clamp(10_000) == MAX_WAIT_SECONDS
    assert clamp(30) == 30


# ---------------------------------------------------------------------------
# The signal set: exactly what get_my_turn can report, nothing more
# ---------------------------------------------------------------------------


def test_wake_targets_match_what_get_my_turn_surfaces():
    """A wake with nothing to show would re-park the agent — pure noise.

    get_my_turn reports two things: holding the baton (including the 'all'
    baton), and an unresolved DIRECTED requires_action post. A plain broadcast is
    neither; it deliberately obligates nobody (BE-9197), so it wakes nobody.
    """
    targets = CommThreadService._wake_targets

    # Directed action-request -> its addressee.
    assert targets(to_participant="w1", requires_action=True, baton_to=None, participant_ids=[]) == ["w1"]
    # Directed but informational -> nobody (it never reaches get_my_turn).
    assert targets(to_participant="w1", requires_action=False, baton_to=None, participant_ids=[]) == []
    # Plain broadcast -> nobody.
    assert targets(to_participant=None, requires_action=True, baton_to=None, participant_ids=["a", "b"]) == []
    # Named baton -> that one agent.
    assert targets(to_participant=None, requires_action=False, baton_to="w2", participant_ids=["a"]) == ["w2"]
    # 'all' baton lands in EVERY participant's turn list.
    assert targets(to_participant=None, requires_action=False, baton_to="all", participant_ids=["a", "b"]) == ["a", "b"]
    # 'none' clears the baton and obligates nobody.
    assert targets(to_participant=None, requires_action=False, baton_to="none", participant_ids=["a"]) == []


# ---------------------------------------------------------------------------
# End to end through the owning service
# ---------------------------------------------------------------------------


async def test_directed_action_request_wakes_the_addressee(db_manager, db_session):
    tenant = _tk("directed")
    await _seed(db_session, tenant)
    svc = _service(db_manager, db_session)
    thread_id = await _thread_with(svc, tenant, creator="em", joiner="worker-1")

    task = await _park(svc, tenant, "worker-1")
    await svc.post_to_thread(
        thread_id=thread_id,
        content="please review",
        from_agent="em",
        to_participant="worker-1",
        requires_action=True,
        tenant_key=tenant,
    )

    result = await asyncio.wait_for(task, timeout=WAKE_DEADLINE_SECONDS)
    assert result["woken"] is True
    assert result["wake_reason"] == "signalled"
    assert result["waited_seconds"] < WAKE_DEADLINE_SECONDS
    # The woken agent can SEE the work — proving the signal fired post-commit.
    assert [d["thread_id"] for d in result["directed_action"]] == [thread_id]


async def test_auto_passed_baton_wakes_the_addressee(db_manager, db_session):
    """The BE-9292a lesson: the auto-pass IS the default, so it must wake too.

    The MCP wrapper resolves the auto-pass into an explicit ``pass_baton_to``
    before the service is called, so signalling on the resolved baton in the
    service covers the auto-pass path by construction rather than by a second
    branch that could rot independently.
    """
    tenant = _tk("autopass")
    await _seed(db_session, tenant)
    svc = _service(db_manager, db_session)
    thread_id = await _thread_with(svc, tenant, creator="em", joiner="worker-1")

    task = await _park(svc, tenant, "worker-1")
    posted = await svc.post_to_thread(
        thread_id=thread_id,
        content="your turn",
        from_agent="em",
        to_participant="worker-1",
        requires_action=True,
        pass_baton_to="worker-1",  # what _resolve_pass_baton_to produces
        tenant_key=tenant,
    )
    assert posted["baton_passed"] is True

    result = await asyncio.wait_for(task, timeout=WAKE_DEADLINE_SECONDS)
    assert result["woken"] is True
    assert thread_id in [t["thread_id"] for t in result["threads"]]


async def test_explicit_pass_baton_wakes_the_new_owner(db_manager, db_session):
    tenant = _tk("baton")
    await _seed(db_session, tenant)
    svc = _service(db_manager, db_session)
    thread_id = await _thread_with(svc, tenant, creator="em", joiner="worker-1")

    task = await _park(svc, tenant, "worker-1")
    await svc.pass_baton(thread_id=thread_id, to="worker-1", tenant_key=tenant)

    result = await asyncio.wait_for(task, timeout=WAKE_DEADLINE_SECONDS)
    assert result["woken"] is True
    assert result["wake_reason"] == "signalled"


async def test_plain_broadcast_does_not_wake(db_manager, db_session):
    """A broadcast reaches get_my_turn for nobody, so waking on it is noise."""
    tenant = _tk("broadcast")
    await _seed(db_session, tenant)
    svc = _service(db_manager, db_session)
    thread_id = await _thread_with(svc, tenant, creator="em", joiner="worker-1")

    task = await _park(svc, tenant, "worker-1", timeout_seconds=1)
    await svc.post_to_thread(thread_id=thread_id, content="FYI all", from_agent="em", tenant_key=tenant)

    result = await asyncio.wait_for(task, timeout=5)
    assert result["woken"] is False
    assert result["wake_reason"] == "timeout"
    # The re-call instruction rides on the empty payload itself: the moment an
    # agent decides whether to keep holding the line is when a wait comes back
    # empty, not when it read the protocol prose hours earlier.
    assert result["advice"] == TIMEOUT_ADVICE


async def test_post_reply_carries_the_hold_the_line_hint(db_manager, db_session):
    """A post that leaves the thread open tells the poster to expect a response.

    The moment an agent decides whether to walk away is right after posting, so
    the stay-available rule rides on the post's own response (1CZA1D). A post
    that resolves or closes the thread IS the conversation ending — no hint.
    """
    tenant = _tk("postadvice")
    await _seed(db_session, tenant)
    svc = _service(db_manager, db_session)
    thread_id = await _thread_with(svc, tenant, creator="em", joiner="worker-1")

    open_post = await svc.post_to_thread(thread_id=thread_id, content="status?", from_agent="em", tenant_key=tenant)
    assert open_post["advice"] == POST_ADVICE

    closing_post = await svc.post_to_thread(
        thread_id=thread_id, content="done, closing", from_agent="em", set_status="closed", tenant_key=tenant
    )
    assert "advice" not in closing_post


def test_wait_cap_stays_under_the_mcp_client_request_budget():
    """The hold must return BEFORE the caller's own request timeout kills it.

    Standard MCP client SDKs abort any request at 60s by default, and FastMCP's
    ``json_response=True`` means no bytes hit the wire until the tool returns, so
    the whole hold counts against that budget. Measured live against production
    (2026-08-20, Claude Code CLI): a 57s hold returned normally, a 60s hold was
    killed by the client as a raw tool ERROR. With DEFAULT at 60 every default
    call failed and agents abandoned the stay-on-the-line loop (project 1CZA1D).
    The true failing layer is the client's HTTP timeout, which pytest cannot
    exercise — this guard pins the constants that keep us clear of it.
    """
    assert MAX_WAIT_SECONDS <= 55, "a hold at 60s+ is killed by the MCP client's default request timeout"
    assert DEFAULT_WAIT_SECONDS < MAX_WAIT_SECONDS


async def test_work_already_waiting_returns_without_parking(db_manager, db_session):
    tenant = _tk("pending")
    await _seed(db_session, tenant)
    svc = _service(db_manager, db_session)
    thread_id = await _thread_with(svc, tenant, creator="em", joiner="worker-1")

    await svc.pass_baton(thread_id=thread_id, to="worker-1", tenant_key=tenant)

    result = await asyncio.wait_for(
        svc.await_my_turn(agent_id="worker-1", timeout_seconds=30, tenant_key=tenant),
        timeout=WAKE_DEADLINE_SECONDS,
    )
    assert result["woken"] is True
    assert result["wake_reason"] == "already_pending"
    assert result["waited_seconds"] == 0


async def test_waiter_is_unregistered_after_every_exit_path(db_manager, db_session):
    tenant = _tk("cleanup")
    await _seed(db_session, tenant)
    svc = _service(db_manager, db_session)
    await _thread_with(svc, tenant, creator="em", joiner="worker-1")

    await svc.await_my_turn(agent_id="worker-1", timeout_seconds=1, tenant_key=tenant)
    assert get_wake_registry().waiter_count(tenant) == 0

    task = await _park(svc, tenant, "worker-1")
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert get_wake_registry().waiter_count(tenant) == 0


async def test_agent_id_is_required(db_manager, db_session):
    from giljo_mcp.exceptions import ValidationError

    svc = _service(db_manager, db_session)
    with pytest.raises(ValidationError):
        await svc.await_my_turn(agent_id="", tenant_key=_tk("noagent"))


async def test_over_the_waiter_cap_declines_to_park_and_says_to_poll(db_manager, db_session, monkeypatch):
    """A capacity ceiling is not an error — the caller has a working fallback."""
    tenant = _tk("cap")
    await _seed(db_session, tenant)
    svc = _service(db_manager, db_session)

    monkeypatch.setattr(
        "giljo_mcp.services._comm_thread_wake_mixin.MAX_WAITERS_PER_TENANT",
        0,
        raising=False,
    )
    result = await asyncio.wait_for(
        svc.await_my_turn(agent_id="worker-1", timeout_seconds=30, tenant_key=tenant),
        timeout=WAKE_DEADLINE_SECONDS,
    )
    assert result["woken"] is False
    assert result["wake_reason"] == "waiter_limit"
    assert result["count"] == 0


async def test_await_my_turn_holds_zero_pool_connections_while_parked():
    """BE-9558: locks in a claim the docstring makes but nothing tested.

    ``await_my_turn``'s docstring asserts it "Holds NO database session while
    parked ... proven under 40 concurrent waiters: pool checkedout stayed at 0
    throughout" -- found true by reading the code while root-causing the
    2026-09-01 prod long-poll slowdown (get_my_turn is called twice, straddling
    the wait, each time opening and closing its OWN session via
    _scoped_session), but with no regression test anywhere in the suite. This
    is that test.

    Needs a REAL QueuePool, not the ``db_manager`` fixture the rest of this
    file shares: that one runs NullPool (deliberately, so parallel xdist
    workers cannot exhaust Postgres's own max_connections) with ONE session
    injected into the service for the whole test, reused for every call --
    which can never show a connection actually returning to a pool. This test
    builds its own tiny (pool_size=2) QueuePool-backed manager against the same
    per-worker test database instead.
    """
    connection_string = PostgreSQLTestHelper.get_test_db_url()
    pool_db_manager = DatabaseManager(connection_string, is_async=True, pool_size=2, max_overflow=0)
    tenant = _tk("poolproof")
    try:
        async with pool_db_manager.get_session_async(tenant_key=tenant) as session:
            with tenant_session_context(session, tenant):
                await ensure_default_types_seeded(session, tenant)

        svc = CommThreadService(pool_db_manager, TenantManager(), session=None)
        await _thread_with(svc, tenant, creator="em", joiner="worker-1")

        pool = pool_db_manager.async_engine.pool
        assert pool.checkedout() == 0, "a connection was already checked out before parking"

        # _park only returns once the waiter's own get_my_turn read has
        # completed and it has moved on to suspend on the wait event -- the
        # exact window the docstring's claim is about.
        task = await _park(svc, tenant, "worker-1", timeout_seconds=1)
        assert pool.checkedout() == 0, "await_my_turn held a pool connection while parked on the wait event"

        result = await asyncio.wait_for(task, timeout=WAKE_DEADLINE_SECONDS)
        assert result["wake_reason"] == "timeout"
        assert pool.checkedout() == 0, "await_my_turn left a connection checked out after returning"
    finally:
        await purge_tenant_rows(pool_db_manager, tenant)
        await pool_db_manager.close_async()


# ---------------------------------------------------------------------------
# THE acceptance check: the default install the original design would have failed
# ---------------------------------------------------------------------------


def test_default_install_never_publishes_to_the_broker():
    """Pin the premise: on 1 worker the broker publish is gated OFF.

    This is the fact that killed "await the broker". If a future change makes
    ``_publish_to_broker_enabled`` true by default, this test fails and whoever
    made the change gets to reconsider the wake design deliberately rather than
    discover it in production.
    """
    from api.websocket import WebSocketManager

    manager = WebSocketManager()
    # Freshly constructed, before any attach_broker: publishing is off.
    assert manager._publish_to_broker_enabled is False


def test_default_broker_selection_is_in_memory(monkeypatch):
    """The second half of the premise: the default broker is per-process."""
    from api.broker import create_websocket_event_broker
    from api.broker.in_memory import InMemoryWebSocketEventBroker

    monkeypatch.delenv("GILJO_WS_BROKER", raising=False)
    monkeypatch.delenv("GILJO_WEBSOCKET_BROKER", raising=False)
    assert isinstance(create_websocket_event_broker(), InMemoryWebSocketEventBroker)


async def test_wake_fires_on_a_default_single_worker_install(db_manager, db_session):
    """THE acceptance check (DoD): the wake works with no broker in the picture.

    No broker is attached and no relay is installed — precisely the default CE
    posture (1 worker, in_memory). The waiter must still be woken by the write
    itself. A broker-backed design returns ``timeout`` here, every time.
    """
    tenant = _tk("default")
    await _seed(db_session, tenant)
    svc = _service(db_manager, db_session)
    thread_id = await _thread_with(svc, tenant, creator="em", joiner="worker-1")

    registry = get_wake_registry()
    assert registry._relay is None, "no cross-worker relay on a single-worker install"

    task = await _park(svc, tenant, "worker-1")
    await svc.post_to_thread(
        thread_id=thread_id,
        content="wake up",
        from_agent="em",
        to_participant="worker-1",
        requires_action=True,
        tenant_key=tenant,
    )

    result = await asyncio.wait_for(task, timeout=WAKE_DEADLINE_SECONDS)
    assert result["woken"] is True, "the wake must not depend on the broker"
    assert result["wake_reason"] == "signalled"


# ---------------------------------------------------------------------------
# Mechanism 2: liveness — is my orchestrator still there?
# ---------------------------------------------------------------------------


def test_liveness_bands_are_derived_from_the_agent_silence_threshold():
    """One definition of "quiet" in the product, not two.

    An operator who saw the Hub call a participant quiet while the job dashboard
    still called it working would be right to distrust both readings, so the band
    is pinned to the same constant the silence detector uses.
    """
    from giljo_mcp.services.silence_detector import DEFAULT_SILENCE_THRESHOLD_MINUTES

    assert LIVENESS_QUIET_AFTER_MINUTES == DEFAULT_SILENCE_THRESHOLD_MINUTES
    assert LIVENESS_GONE_AFTER_MINUTES == DEFAULT_SILENCE_THRESHOLD_MINUTES * 3


def test_liveness_state_bands_each_boundary():
    """Exact boundaries, because an off-by-one here silently mislabels an agent."""
    band = CommThreadService._liveness_state
    now = datetime(2026, 8, 7, 12, 0, 0, tzinfo=UTC)

    def at(seconds_ago: int) -> str:
        stamp = (now - timedelta(seconds=seconds_ago)).isoformat()
        return band(stamp, now)[0]

    quiet_at = LIVENESS_QUIET_AFTER_MINUTES * 60
    gone_at = LIVENESS_GONE_AFTER_MINUTES * 60

    assert at(0) == "active"
    assert at(quiet_at - 1) == "active"
    assert at(quiet_at) == "quiet", "the boundary second belongs to the slower band"
    assert at(gone_at - 1) == "quiet"
    assert at(gone_at) == "gone"


def test_never_seen_is_unknown_not_gone():
    """A participant that joined but has not acted is starting up, not dark.

    Reporting it as gone would have a conductor reassign work from an agent that
    is merely booting.
    """
    now = datetime(2026, 8, 7, 12, 0, 0, tzinfo=UTC)
    assert CommThreadService._liveness_state(None, now) == ("unknown", None)


def test_a_malformed_timestamp_degrades_instead_of_failing_the_read():
    """The conductor is relying on this read; a bad stamp is a display concern."""
    now = datetime(2026, 8, 7, 12, 0, 0, tzinfo=UTC)
    assert CommThreadService._liveness_state("not-a-date", now) == ("unknown", None)


def test_a_naive_timestamp_is_treated_as_utc():
    """Postgres TIMESTAMPTZ round-trips aware, but a naive value must not raise."""
    now = datetime(2026, 8, 7, 12, 0, 0, tzinfo=UTC)
    state, age = CommThreadService._liveness_state("2026-08-07T11:59:30", now)
    assert state == "active"
    assert age == 30


async def test_liveness_reports_every_participant_with_a_band(db_manager, db_session):
    tenant = _tk("liveness")
    await _seed(db_session, tenant)
    svc = _service(db_manager, db_session)
    thread_id = await _thread_with(svc, tenant, creator="em", joiner="worker-1")

    result = await svc.get_participant_liveness(thread_id=thread_id, tenant_key=tenant)

    assert result["thread_id"] == thread_id
    assert result["count"] >= 2
    by_id = {p["participant_id"]: p for p in result["participants"]}
    assert {"em", "worker-1"} <= set(by_id)
    for row in result["participants"]:
        assert row["liveness"] in {"active", "quiet", "gone", "unknown"}
        # BE-9289a already stamps these; the liveness read must carry them through
        # rather than make a conductor issue a second call for identity.
        assert "harness" in row
        assert "last_seen_at" in row


async def test_a_participant_that_just_acted_reads_active(db_manager, db_session):
    tenant = _tk("active")
    await _seed(db_session, tenant)
    svc = _service(db_manager, db_session)
    thread_id = await _thread_with(svc, tenant, creator="em", joiner="worker-1")

    # A poll stamps last_seen_at (BE-9289a), which is exactly the signal of life.
    await svc.get_my_turn(agent_id="worker-1", tenant_key=tenant)

    result = await svc.get_participant_liveness(thread_id=thread_id, tenant_key=tenant)
    worker = next(p for p in result["participants"] if p["participant_id"] == "worker-1")
    assert worker["liveness"] == "active"
    assert worker["seconds_since_seen"] is not None
    assert worker["seconds_since_seen"] < 60


async def test_liveness_advertises_the_thresholds_it_used(db_manager, db_session):
    """A caller must never have to guess what "quiet" meant on this response."""
    tenant = _tk("thresholds")
    await _seed(db_session, tenant)
    svc = _service(db_manager, db_session)
    thread_id = await _thread_with(svc, tenant, creator="em", joiner="worker-1")

    result = await svc.get_participant_liveness(thread_id=thread_id, tenant_key=tenant)
    assert result["thresholds"] == {
        "quiet_after_minutes": LIVENESS_QUIET_AFTER_MINUTES,
        "gone_after_minutes": LIVENESS_GONE_AFTER_MINUTES,
    }


async def test_liveness_requires_a_thread_id(db_manager, db_session):
    from giljo_mcp.exceptions import ValidationError

    svc = _service(db_manager, db_session)
    with pytest.raises(ValidationError, match="thread_id"):
        await svc.get_participant_liveness(thread_id="", tenant_key=_tk("nothread"))


async def test_liveness_refuses_a_thread_from_another_tenant(db_manager, db_session):
    """Tenant isolation on the read a conductor uses to make routing decisions."""
    from giljo_mcp.exceptions import ResourceNotFoundError

    owner, intruder = _tk("owner"), _tk("intruder")
    await _seed(db_session, owner)
    await _seed(db_session, intruder)
    svc = _service(db_manager, db_session)
    thread_id = await _thread_with(svc, owner, creator="em", joiner="worker-1")

    with pytest.raises(ResourceNotFoundError):
        await svc.get_participant_liveness(thread_id=thread_id, tenant_key=intruder)
