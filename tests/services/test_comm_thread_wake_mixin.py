# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


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
    clamp = CommThreadService._resolve_wait_seconds
    assert clamp(None) == DEFAULT_WAIT_SECONDS
    assert clamp(0) == DEFAULT_WAIT_SECONDS
    assert clamp(10_000) == MAX_WAIT_SECONDS
    assert clamp(30) == 30




def test_wake_targets_match_what_get_my_turn_surfaces():
    targets = CommThreadService._wake_targets

    assert targets(to_participant="w1", requires_action=True, baton_to=None, participant_ids=[]) == ["w1"]
    assert targets(to_participant="w1", requires_action=False, baton_to=None, participant_ids=[]) == []
    assert targets(to_participant=None, requires_action=True, baton_to=None, participant_ids=["a", "b"]) == []
    assert targets(to_participant=None, requires_action=False, baton_to="w2", participant_ids=["a"]) == ["w2"]
    assert targets(to_participant=None, requires_action=False, baton_to="all", participant_ids=["a", "b"]) == ["a", "b"]
    assert targets(to_participant=None, requires_action=False, baton_to="none", participant_ids=["a"]) == []




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
    assert [d["thread_id"] for d in result["directed_action"]] == [thread_id]


async def test_auto_passed_baton_wakes_the_addressee(db_manager, db_session):
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
        pass_baton_to="worker-1",
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
    tenant = _tk("broadcast")
    await _seed(db_session, tenant)
    svc = _service(db_manager, db_session)
    thread_id = await _thread_with(svc, tenant, creator="em", joiner="worker-1")

    task = await _park(svc, tenant, "worker-1", timeout_seconds=1)
    await svc.post_to_thread(thread_id=thread_id, content="FYI all", from_agent="em", tenant_key=tenant)

    result = await asyncio.wait_for(task, timeout=5)
    assert result["woken"] is False
    assert result["wake_reason"] == "timeout"
    assert result["advice"] == TIMEOUT_ADVICE


async def test_post_reply_carries_the_hold_the_line_hint(db_manager, db_session):
    tenant = _tk("postadvice")
    await _seed(db_session, tenant)
    svc = _service(db_manager, db_session)
    thread_id = await _thread_with(svc, tenant, creator="em", joiner="worker-1")

    baton_post = await svc.post_to_thread(
        thread_id=thread_id, content="over to you", from_agent="em", pass_baton_to="worker-1", tenant_key=tenant
    )
    assert baton_post["advice"] == POST_ADVICE
    assert 'set_agent_status(status="idle")' in baton_post["advice"]

    action_post = await svc.post_to_thread(
        thread_id=thread_id,
        content="please run the suite",
        from_agent="em",
        to_participant="worker-1",
        requires_action=True,
        tenant_key=tenant,
    )
    assert action_post["advice"] == POST_ADVICE

    question_post = await svc.post_to_thread(thread_id=thread_id, content="status?", from_agent="em", tenant_key=tenant)
    assert question_post["advice"] == POST_ADVICE

    informational_post = await svc.post_to_thread(
        thread_id=thread_id, content="FYI: tests green, 12 passed.", from_agent="em", tenant_key=tenant
    )
    assert "advice" not in informational_post

    closing_post = await svc.post_to_thread(
        thread_id=thread_id, content="done, closing", from_agent="em", set_status="closed", tenant_key=tenant
    )
    assert "advice" not in closing_post

    reopened = await svc.post_to_thread(
        thread_id=thread_id, content="reopening", from_agent="em", set_status="open", tenant_key=tenant
    )
    assert "advice" not in reopened
    resolved_with_question = await svc.post_to_thread(
        thread_id=thread_id, content="all good?", from_agent="em", set_status="resolved", tenant_key=tenant
    )
    assert "advice" not in resolved_with_question


def test_wait_cap_stays_under_the_mcp_client_request_budget():
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

        task = await _park(svc, tenant, "worker-1", timeout_seconds=1)
        assert pool.checkedout() == 0, "await_my_turn held a pool connection while parked on the wait event"

        result = await asyncio.wait_for(task, timeout=WAKE_DEADLINE_SECONDS)
        assert result["wake_reason"] == "timeout"
        assert pool.checkedout() == 0, "await_my_turn left a connection checked out after returning"
    finally:
        await purge_tenant_rows(pool_db_manager, tenant)
        await pool_db_manager.close_async()




def test_default_install_never_publishes_to_the_broker():
    from api.websocket import WebSocketManager

    manager = WebSocketManager()
    assert manager._publish_to_broker_enabled is False


def test_default_broker_selection_is_in_memory(monkeypatch):
    from api.broker import create_websocket_event_broker
    from api.broker.in_memory import InMemoryWebSocketEventBroker

    monkeypatch.delenv("GILJO_WS_BROKER", raising=False)
    monkeypatch.delenv("GILJO_WEBSOCKET_BROKER", raising=False)
    assert isinstance(create_websocket_event_broker(), InMemoryWebSocketEventBroker)


async def test_wake_fires_on_a_default_single_worker_install(db_manager, db_session):
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




def test_liveness_bands_are_derived_from_the_agent_silence_threshold():
    from giljo_mcp.services.silence_detector import DEFAULT_SILENCE_THRESHOLD_MINUTES

    assert LIVENESS_QUIET_AFTER_MINUTES == DEFAULT_SILENCE_THRESHOLD_MINUTES
    assert LIVENESS_GONE_AFTER_MINUTES == DEFAULT_SILENCE_THRESHOLD_MINUTES * 3


def test_liveness_state_bands_each_boundary():
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
    now = datetime(2026, 8, 7, 12, 0, 0, tzinfo=UTC)
    assert CommThreadService._liveness_state(None, now) == ("unknown", None)


def test_a_malformed_timestamp_degrades_instead_of_failing_the_read():
    now = datetime(2026, 8, 7, 12, 0, 0, tzinfo=UTC)
    assert CommThreadService._liveness_state("not-a-date", now) == ("unknown", None)


def test_a_naive_timestamp_is_treated_as_utc():
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
        assert "harness" in row
        assert "last_seen_at" in row


async def test_a_participant_that_just_acted_reads_active(db_manager, db_session):
    tenant = _tk("active")
    await _seed(db_session, tenant)
    svc = _service(db_manager, db_session)
    thread_id = await _thread_with(svc, tenant, creator="em", joiner="worker-1")

    await svc.get_my_turn(agent_id="worker-1", tenant_key=tenant)

    result = await svc.get_participant_liveness(thread_id=thread_id, tenant_key=tenant)
    worker = next(p for p in result["participants"] if p["participant_id"] == "worker-1")
    assert worker["liveness"] == "active"
    assert worker["seconds_since_seen"] is not None
    assert worker["seconds_since_seen"] < 60


async def test_liveness_advertises_the_thresholds_it_used(db_manager, db_session):
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
    from giljo_mcp.exceptions import ResourceNotFoundError

    owner, intruder = _tk("owner"), _tk("intruder")
    await _seed(db_session, owner)
    await _seed(db_session, intruder)
    svc = _service(db_manager, db_session)
    thread_id = await _thread_with(svc, owner, creator="em", joiner="worker-1")

    with pytest.raises(ResourceNotFoundError):
        await svc.get_participant_liveness(thread_id=thread_id, tenant_key=intruder)
