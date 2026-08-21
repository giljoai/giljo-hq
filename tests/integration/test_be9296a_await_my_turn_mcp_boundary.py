# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-9296a — ``await_my_turn`` across the MCP transport, not just the service.

The service suite (``tests/services/test_be9296a_wake_signal.py``) proves the wake
semantics. This file proves the thin glue an agent actually calls: the @mcp.tool
wrapper's dispatch string, the kwargs it builds, the scope mapping, and the shape
that reaches the wire.

That layer gets its own file because it is exactly where BE-5042 shipped broken
with ~1,392 unit tests green — the wrapper had no test, so a wrong dispatch name
or a dropped kwarg failed only at runtime. A wake tool that is registered but
mis-wired would look identical to one that simply never wakes.

Parallel-safe: fresh tenant_key per test, rolled-back db_session, no module-level
mutable state, no ordering dependencies.
"""

from __future__ import annotations

import asyncio
import json

import pytest_asyncio

from api.endpoints.mcp_sdk_server import mcp
from giljo_mcp.database import tenant_session_context
from giljo_mcp.services._comm_thread_wake_mixin import MAX_WAIT_SECONDS
from giljo_mcp.services.agent_wake_registry import get_wake_registry
from giljo_mcp.services.comm_thread_service import CommThreadService
from giljo_mcp.services.taxonomy_ops import ensure_default_types_seeded
from giljo_mcp.tenant import TenantManager
from giljo_mcp.tools.tool_accessor import ToolAccessor
from tests.helpers.mcp_session_fixture import create_connected_server_and_client_session


WAKE_DEADLINE_SECONDS = 2.0


def _payload(result) -> dict:
    """The tool's JSON body as a dict."""
    for block in result.content or []:
        text = getattr(block, "text", None)
        if text:
            return json.loads(text)
    raise AssertionError("tool returned no content")


@pytest_asyncio.fixture
async def wake_mcp_client(db_manager, db_session, monkeypatch):
    """(client_factory, tenant_key, service) with the real CommThreadService bound
    to the rolled-back test session.

    ``await_my_turn`` dispatches to ``acc._comm_thread_service.await_my_turn``
    (``_base.TOOL_DISPATCH``), so that one service is rebuilt on ``db_session`` and
    handed to the test as well — the test writes through the SAME instance the tool
    reads through, which is what makes the wake observable here.
    """
    from api import app_state
    from api.endpoints.mcp_tools import _base

    state = app_state.state
    prior_accessor, prior_tm, prior_dbm = state.tool_accessor, state.tenant_manager, state.db_manager

    if state.tenant_manager is None:
        state.tenant_manager = TenantManager()
    state.db_manager = db_manager

    # Generated, not hand-formatted: the MCP path runs the key through
    # TenantManager.set_current_tenant, which validates its shape.
    tenant_key = TenantManager.generate_tenant_key()
    accessor = ToolAccessor(db_manager=db_manager, tenant_manager=state.tenant_manager)
    service = CommThreadService(db_manager, state.tenant_manager, session=db_session)
    accessor._comm_thread_service = service
    state.tool_accessor = accessor

    monkeypatch.setattr(_base, "_resolve_tenant", lambda ctx: tenant_key)
    monkeypatch.setattr(_base, "_resolve_user_id", lambda ctx: None)
    monkeypatch.setattr(_base, "should_run", lambda *args, **kwargs: False)

    with tenant_session_context(db_session, tenant_key):
        await ensure_default_types_seeded(db_session, tenant_key)

    def _client():
        return create_connected_server_and_client_session(mcp)

    try:
        yield _client, tenant_key, service
    finally:
        state.tool_accessor, state.tenant_manager, state.db_manager = prior_accessor, prior_tm, prior_dbm


async def _thread_with_worker(service: CommThreadService, tenant_key: str) -> str:
    created = await service.create_thread(subject="wake-boundary", creator_id="em", tenant_key=tenant_key)
    thread_id = created["thread_id"]
    await service.join_thread(
        thread_id=thread_id, participant_id="worker-1", display_name="Worker", tenant_key=tenant_key
    )
    return thread_id


async def test_tool_is_advertised_with_its_documented_shape(wake_mcp_client):
    """The wrapper reaches the wire at all, with the params agents are told about."""
    client_factory, _tenant, _svc = wake_mcp_client
    async with client_factory() as client:
        tools = {t.name: t for t in (await client.list_tools()).tools}

    assert "await_my_turn" in tools, "the wake tool must be advertised"
    schema = tools["await_my_turn"].input_schema
    assert sorted(schema["properties"]) == ["agent_id", "timeout_seconds"]
    assert schema["required"] == ["agent_id"]
    # The cap is advertised as a bound, so a client cannot request a wait the
    # edge would kill.
    assert schema["properties"]["timeout_seconds"]["maximum"] == MAX_WAIT_SECONDS


async def test_dispatch_reaches_the_service_and_returns_the_wake_envelope(wake_mcp_client):
    """The dispatch string and kwargs are right — the BE-5042 failure mode."""
    client_factory, tenant_key, service = wake_mcp_client
    await _thread_with_worker(service, tenant_key)

    async with client_factory() as client:
        result = await client.call_tool("await_my_turn", {"agent_id": "worker-1", "timeout_seconds": 1})

    assert result.is_error is False
    body = _payload(result)
    # The envelope agents branch on.
    assert body["agent_id"] == "worker-1"
    assert body["woken"] is False
    assert body["wake_reason"] == "timeout"
    assert body["count"] == 0


async def test_pending_work_returns_immediately_over_the_transport(wake_mcp_client):
    client_factory, tenant_key, service = wake_mcp_client
    thread_id = await _thread_with_worker(service, tenant_key)
    await service.pass_baton(thread_id=thread_id, to="worker-1", tenant_key=tenant_key)

    async with client_factory() as client:
        result = await asyncio.wait_for(
            client.call_tool("await_my_turn", {"agent_id": "worker-1", "timeout_seconds": 30}),
            timeout=WAKE_DEADLINE_SECONDS,
        )

    body = _payload(result)
    assert body["woken"] is True
    assert body["wake_reason"] == "already_pending"
    assert thread_id in [t["thread_id"] for t in body["threads"]]


async def test_a_write_wakes_a_waiter_that_is_blocked_on_the_transport(wake_mcp_client):
    """The end-to-end claim, across the MCP boundary: park on the wire, write, wake.

    This is the DoD's 'observably wakes in under 2s' with the tool call genuinely
    in flight rather than the service method awaited directly.
    """
    client_factory, tenant_key, service = wake_mcp_client
    thread_id = await _thread_with_worker(service, tenant_key)

    async with client_factory() as client:
        # Park first, then write — otherwise the test exercises already_pending.
        #
        # Waiting on the waiter's own read to FINISH (not merely on its
        # registration) is load-bearing here: this fixture shares one
        # rollback-isolated session between the in-flight tool call and the write
        # below, and two coroutines using one session interleave the tenant guard's
        # context. A harness artifact — every real request owns its session — but
        # it would surface as a confusing isolation error rather than a wake bug.
        # Once get_my_turn has returned, the waiter runs on to its await and
        # suspends there holding nothing, before this coroutine resumes.
        read_done = asyncio.Event()
        original_get_my_turn = service.get_my_turn

        async def _instrumented(**kwargs):
            result = await original_get_my_turn(**kwargs)
            read_done.set()
            return result

        service.get_my_turn = _instrumented  # type: ignore[method-assign]
        call = asyncio.create_task(client.call_tool("await_my_turn", {"agent_id": "worker-1", "timeout_seconds": 10}))
        await asyncio.wait_for(read_done.wait(), timeout=WAKE_DEADLINE_SECONDS)
        assert get_wake_registry().waiter_count(tenant_key) >= 1, "waiter read but never parked"

        await service.post_to_thread(
            thread_id=thread_id,
            content="your turn",
            from_agent="em",
            to_participant="worker-1",
            requires_action=True,
            tenant_key=tenant_key,
        )
        result = await asyncio.wait_for(call, timeout=WAKE_DEADLINE_SECONDS)

    body = _payload(result)
    assert body["woken"] is True
    assert body["wake_reason"] == "signalled"
    assert [d["thread_id"] for d in body["directed_action"]] == [thread_id]


async def test_missing_agent_id_is_a_clean_boundary_rejection(wake_mcp_client):
    """A required-arg omission must be a 422-style tool error, never a 500."""
    client_factory, _tenant, _svc = wake_mcp_client
    async with client_factory() as client:
        result = await client.call_tool("await_my_turn", {})

    assert result.is_error is True
    text = "\n".join(b.text for b in result.content if getattr(b, "text", None))
    assert "agent_id" in text


async def test_an_over_long_wait_is_refused_at_the_boundary(wake_mcp_client):
    """The advertised maximum is enforced, not merely documented."""
    client_factory, _tenant, _svc = wake_mcp_client
    async with client_factory() as client:
        result = await client.call_tool("await_my_turn", {"agent_id": "w", "timeout_seconds": 100_000})

    assert result.is_error is True


def test_wake_tool_is_read_scoped_and_dispatch_mapped():
    """Fail-closed registries must both know the tool (SEC-9126)."""
    from api.endpoints.mcp_tools._base import TOOL_DISPATCH, TOOL_SCOPES

    assert TOOL_SCOPES["await_my_turn"] == "mcp:read"
    assert "await_my_turn" in TOOL_DISPATCH


def test_wake_tool_is_reachable_from_the_standard_profile():
    """An agent on the standard tier must be able to wait its turn.

    ``get_my_turn`` is standard-tier, and a blocking form that were full-only would
    leave exactly the mid-tier sessions that poll hardest unable to stop polling.
    """
    from api.endpoints.mcp_tools._base import _STANDARD_PROFILE_TOOLS

    assert "await_my_turn" in _STANDARD_PROFILE_TOOLS
    assert "get_my_turn" in _STANDARD_PROFILE_TOOLS


# ---------------------------------------------------------------------------
# Mechanism 2: the liveness read across the same boundary
# ---------------------------------------------------------------------------


async def test_liveness_tool_dispatches_and_returns_bands(wake_mcp_client):
    """The conductor's who-is-still-there read, over the wire."""
    client_factory, tenant_key, service = wake_mcp_client
    thread_id = await _thread_with_worker(service, tenant_key)

    async with client_factory() as client:
        result = await client.call_tool("get_participant_liveness", {"thread_id": thread_id})

    assert result.is_error is False
    body = _payload(result)
    assert body["thread_id"] == thread_id
    assert body["count"] >= 2
    by_id = {p["participant_id"]: p for p in body["participants"]}
    assert {"em", "worker-1"} <= set(by_id)
    for row in body["participants"]:
        assert row["liveness"] in {"active", "quiet", "gone", "unknown"}
    # The bands are self-describing, so a reader never guesses what quiet meant.
    assert set(body["thresholds"]) == {"quiet_after_minutes", "gone_after_minutes"}


async def test_liveness_needs_no_filesystem_access(wake_mcp_client):
    """The whole point of mechanism 2: a conductor answers this from the server.

    Before it, distinguishing "mid-work" from "finished and waiting" from "dead"
    meant inspecting the agent's working directory. The payload must therefore be
    self-sufficient — identity AND recency in one call.
    """
    client_factory, tenant_key, service = wake_mcp_client
    thread_id = await _thread_with_worker(service, tenant_key)

    async with client_factory() as client:
        body = _payload(await client.call_tool("get_participant_liveness", {"thread_id": thread_id}))

    worker = next(p for p in body["participants"] if p["participant_id"] == "worker-1")
    assert worker["display_name"] == "Worker"
    assert "harness" in worker
    assert "last_seen_at" in worker
    assert "seconds_since_seen" in worker


async def test_liveness_missing_thread_id_is_a_clean_rejection(wake_mcp_client):
    client_factory, _tenant, _svc = wake_mcp_client
    async with client_factory() as client:
        result = await client.call_tool("get_participant_liveness", {})

    assert result.is_error is True
    text = "\n".join(b.text for b in result.content if getattr(b, "text", None))
    assert "thread_id" in text


def test_liveness_tool_is_read_scoped_dispatch_mapped_and_standard_tier():
    from api.endpoints.mcp_tools._base import _STANDARD_PROFILE_TOOLS, TOOL_DISPATCH, TOOL_SCOPES

    assert TOOL_SCOPES["get_participant_liveness"] == "mcp:read"
    assert "get_participant_liveness" in TOOL_DISPATCH
    assert "get_participant_liveness" in _STANDARD_PROFILE_TOOLS
