# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-9558 -- hard ceiling on held /mcp tool calls.

Regression: a tool dispatch that blocks indefinitely can hold a pooled
resource for the lifetime of the request, starving concurrent callers.
``_call_tool`` (the single dispatch chokepoint) now bounds every dispatch and
releases on cancellation.

This test reproduces the mechanism against a REAL, deliberately tiny
connection pool (pool_size=1, max_overflow=0): a tool dispatch that blocks
well past any reasonable budget while holding the pool's only connection,
concurrent with an ordinary caller that needs the same pool. Before the
chokepoint ceiling, the ordinary caller stalls for the full pool_timeout and
fails; after the fix, the chokepoint's ``asyncio.wait_for`` cancels the slow
dispatch, its ``async with`` releases the connection on that cancellation, and
the ordinary caller succeeds quickly. The pool is compressed to make
exhaustion deterministic.

The ceiling constant itself (``_base.HELD_TOOL_CEILING_SECONDS``) is
monkeypatched down to a fraction of a second so this test runs fast while
exercising the exact same code path -- see the comment on
``HELD_TOOL_CEILING_SECONDS`` for why it must stay strictly above
``MAX_WAIT_SECONDS``.

Transport: drives the REAL @mcp.tool wrapper / ``_call_tool`` chokepoint via
``create_connected_server_and_client_session``, matching the existing
MCP-boundary suites (test_be6081_mcp_boundary_contract.py et al) rather than
calling ``_call_tool`` directly -- this is the actual path a held prod request
travels.

Parallel-safe: each test builds its OWN raw asyncpg engine against the shared
per-worker test database (no schema writes, so no TransactionalTestContext
needed) and disposes it in a fixture teardown; no module-level mutable state.
"""

from __future__ import annotations

import asyncio
import json
import time

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.exc import TimeoutError as SATimeoutError
from sqlalchemy.ext.asyncio import create_async_engine

from api.endpoints.mcp_sdk_server import mcp
from api.endpoints.mcp_tools import _base
from giljo_mcp.tenant import TenantManager
from tests.helpers.mcp_session_fixture import create_connected_server_and_client_session
from tests.helpers.test_db_helper import PostgreSQLTestHelper

# Reused, not duplicated (precedent already set by test_be9388_stale_baton_park_
# mcp_boundary.py importing the same fixture): the real CommThreadService bound
# to the rolled-back test session, wired into the in-memory MCP transport.
from tests.integration.test_be9296a_await_my_turn_mcp_boundary import wake_mcp_client  # noqa: F401


# The shipped pool timeout and pool size are both shrunk here so the exhaustion
# is immediate and the test fast, not to change the mechanism under test.
_POOL_TIMEOUT_SECONDS = 2.0
# The stand-in slow tool's OWN (unaware) sleep -- longer than the monkeypatched
# ceiling below so the fix actually has something to cancel, but also longer
# than _POOL_TIMEOUT_SECONDS so an UNcancelled hold reliably starves the
# ordinary caller (proving the repro fails on unfixed code, not by accident).
_SLOW_TOOL_HOLD_SECONDS = 3.0
# The chokepoint ceiling, shrunk to a fraction of a second.
_TEST_CEILING_SECONDS = 0.3


@pytest_asyncio.fixture
async def tiny_pool_engine():
    """A real 1-connection, 0-overflow asyncpg engine against the test DB.

    Deliberately NOT the shared ``db_manager`` fixture -- that one runs
    NullPool (unlimited, unpooled connections) specifically so parallel xdist
    workers cannot exhaust Postgres's own ``max_connections``, which means
    pool exhaustion can never be observed through it. This engine is the one
    piece of test infrastructure that needs a REAL QueuePool to prove the bug.
    """
    engine = create_async_engine(
        PostgreSQLTestHelper.get_test_db_url(),
        pool_size=1,
        max_overflow=0,
        pool_timeout=_POOL_TIMEOUT_SECONDS,
    )
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def slow_tool_client(tiny_pool_engine, monkeypatch):
    """Wire ``get_workflow_status`` (an arbitrary existing pure tool -- its
    accessor dispatch target is monkeypatched, not its behavior) to a stand-in
    handler that holds ``tiny_pool_engine``'s only connection and sleeps past
    any reasonable budget: the mechanism gap BE-9558 closes, independent of
    which literal handler tripped it in production.
    """
    from api import app_state

    state = app_state.state
    prior_tool_accessor = state.tool_accessor
    prior_tenant_manager = state.tenant_manager
    if state.tenant_manager is None:
        state.tenant_manager = TenantManager()
    tenant_key = TenantManager.generate_tenant_key()
    # Never actually consulted: TOOL_DISPATCH is monkeypatched below to bypass
    # the real accessor entirely, but _get_tool_accessor() requires a truthy
    # value before dispatch is even attempted.
    state.tool_accessor = object()

    async def _slow_workflow_status(*, project_id: str, tenant_key: str, exclude_job_id: str | None = None):
        async with tiny_pool_engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
            await asyncio.sleep(_SLOW_TOOL_HOLD_SECONDS)
        return {"never": "reached in this test -- the ceiling must cancel first"}

    monkeypatch.setitem(_base.TOOL_DISPATCH, "get_workflow_status", lambda acc: _slow_workflow_status)
    monkeypatch.setattr(_base, "_resolve_tenant", lambda ctx: tenant_key)
    # raising=False: on pre-fix code this attribute does not exist yet -- the
    # repro must still run (and fail on the actual pool-exhaustion assertion
    # below, not on a missing-attribute setup error) so it proves the bug, not
    # just the absence of the fix.
    monkeypatch.setattr(_base, "HELD_TOOL_CEILING_SECONDS", _TEST_CEILING_SECONDS, raising=False)

    yield

    state.tool_accessor = prior_tool_accessor
    state.tenant_manager = prior_tenant_manager


@pytest.mark.asyncio
async def test_ceiling_cancels_slow_tool_call_and_frees_its_pool_connection(slow_tool_client, tiny_pool_engine):
    """The regression this project exists to fix.

    Before the chokepoint ceiling: the slow tool holds the pool's only
    connection for the full ``_SLOW_TOOL_HOLD_SECONDS`` (nothing cancels it),
    so the concurrent ordinary caller below -- the shape Railway's HTTP logs
    showed in prod, a single long-held request starving every other /mcp
    caller against the same pool -- stalls for the full pool_timeout and then
    raises. This assertion FAILS on unfixed code.

    After the fix: ``_call_tool``'s watchdog cancels the slow dispatch at
    ``_TEST_CEILING_SECONDS``, its ``async with`` releases the connection on
    that cancellation, and the ordinary caller succeeds quickly.
    """

    async def _hold_it():
        async with create_connected_server_and_client_session(mcp) as session:
            return await session.call_tool("get_workflow_status", {"project_id": "p1"})

    holder_task = asyncio.create_task(_hold_it())
    # Let the slow tool actually check out the pool's only connection first.
    await asyncio.sleep(0.1)

    started = time.monotonic()
    ordinary_call_failed = False
    try:
        async with tiny_pool_engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    except SATimeoutError:
        ordinary_call_failed = True
    waited = time.monotonic() - started

    assert not ordinary_call_failed, (
        f"a concurrent ordinary caller was starved of the pool's only connection for "
        f"{waited:.2f}s and timed out -- the held tool call was never cancelled"
    )
    assert waited < _POOL_TIMEOUT_SECONDS, (
        f"ordinary caller waited {waited:.2f}s for a pool connection (pool_timeout="
        f"{_POOL_TIMEOUT_SECONDS}s) -- the held tool call was cancelled too late to help it"
    )

    holder_result = await holder_task
    assert holder_result.is_error is False, (
        f"the ceiling-exceeded response must be a Tier-2 structured rejection, not isError: {holder_result}"
    )
    payload = json.loads(holder_result.content[0].text)
    assert payload.get("error") == _base.TOOL_CEILING_ERROR, payload


@pytest.mark.asyncio
async def test_ceiling_does_not_clobber_get_my_turns_own_graceful_timeout(wake_mcp_client):  # noqa: F811
    """Anti-regression, at the SHIPPED constants (no monkeypatching).

    The global dispatch ceiling must sit strictly above any tool's own
    self-clamp, or the outer timeout would pre-empt the tool's graceful
    response. This pins that margin at the shipped values -- a short, real park
    still returns get_my_turn's OWN timeout shape, not the ceiling's.
    """
    client_factory, _tenant_key, _service = wake_mcp_client

    async with client_factory() as client:
        result = await client.call_tool("get_my_turn", {"agent_id": "worker-1", "wait_seconds": 1})

    assert result.is_error is False
    payload = json.loads(result.content[0].text)
    assert payload.get("wake_reason") == "timeout", payload
    assert payload.get("error") != _base.TOOL_CEILING_ERROR, payload
