# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-9582: the API-metrics flusher must not write rows for purged tenants.

Edition Scope: Both (the flusher is core).

``sync_api_metrics_to_db`` buffers per-tenant call counts in memory and flushes
them periodically. Buffered counts were flushed without checking that the tenant
still existed, so a tenant deleted between its last request and the next flush
could have a row recreated after erasure. The flusher now skips tenants with no
remaining user row.

Existence is checked against ``users`` rather than ``tenants``: this is CE code
and must never reference a SaaS-only table. The purge enumerates every
``tenant_key``-carrying table from ``Base.metadata``, so a purged tenant has no
``users`` row left either — which is what makes it a usable liveness signal in
both editions.

These tests drive one flush tick directly. The 300s loop is not exercised here;
the defect lives in what a single tick writes.
"""

from __future__ import annotations

import pytest
from sqlalchemy import delete, select

from api.startup.metrics_flushers import flush_api_metrics_once
from giljo_mcp.database import tenant_isolation_bypass
from giljo_mcp.models import ApiMetrics
from giljo_mcp.models.auth import User


class _FakeState:
    """The two attributes the flusher actually touches."""

    def __init__(self, db_manager, api_counts=None, mcp_counts=None):
        self.db_manager = db_manager
        self.api_call_count = dict(api_counts or {})
        self.mcp_call_count = dict(mcp_counts or {})


async def _make_user(db_manager, tenant_key: str) -> None:
    async with db_manager.get_session_async() as session:
        with tenant_isolation_bypass(session, reason="BE-9582 test setup", models=(User,)):
            session.add(
                User(
                    tenant_key=tenant_key,
                    username=f"user_{tenant_key}",
                    email=f"{tenant_key}@example.test",
                    password_hash="x",
                )
            )
            await session.commit()


async def _api_metrics_rows(db_manager, tenant_key: str) -> list[ApiMetrics]:
    async with db_manager.get_session_async() as session:
        with tenant_isolation_bypass(session, reason="BE-9582 test assertion", models=(ApiMetrics,)):
            result = await session.execute(select(ApiMetrics).where(ApiMetrics.tenant_key == tenant_key))
            return list(result.scalars().all())


async def _cleanup(db_manager, tenant_keys: list[str]) -> None:
    """These tests commit through the flusher's own sessions, so rollback cannot reach them."""
    async with db_manager.get_session_async() as session:
        with tenant_isolation_bypass(session, reason="BE-9582 test teardown", models=(ApiMetrics, User)):
            await session.execute(delete(ApiMetrics).where(ApiMetrics.tenant_key.in_(tenant_keys)))
            await session.execute(delete(User).where(User.tenant_key.in_(tenant_keys)))
            await session.commit()


@pytest.mark.asyncio
async def test_purged_tenant_gets_no_row(db_manager):
    """The defect: buffered counts for a tenant that no longer exists must not be written."""
    purged = "test_tenant_be9582_purged"
    await _cleanup(db_manager, [purged])
    state = _FakeState(db_manager, api_counts={purged: 7}, mcp_counts={purged: 3})

    try:
        await flush_api_metrics_once(state)

        rows = await _api_metrics_rows(db_manager, purged)
        assert rows == [], (
            f"api_metrics rows were written for a tenant with no users row: {rows}. "
            "A purged tenant's key must not reappear in the table after erasure."
        )
    finally:
        await _cleanup(db_manager, [purged])


@pytest.mark.asyncio
async def test_live_tenant_still_gets_its_row(db_manager):
    """Instrument check: the filter must not simply drop everything.

    Without this, a fix that skipped every tenant would pass the test above and
    silently stop all metrics collection.
    """
    live = "test_tenant_be9582_live"
    await _cleanup(db_manager, [live])
    await _make_user(db_manager, live)
    state = _FakeState(db_manager, api_counts={live: 5}, mcp_counts={live: 2})

    try:
        await flush_api_metrics_once(state)

        rows = await _api_metrics_rows(db_manager, live)
        assert len(rows) == 1
        assert rows[0].total_api_calls == 5
        assert rows[0].total_mcp_calls == 2
    finally:
        await _cleanup(db_manager, [live])


@pytest.mark.asyncio
async def test_mcp_only_counts_for_a_live_tenant_still_reach_the_db(db_manager):
    """/mcp is a public path, so a tenant can have MCP calls and no API calls.

    The union of both maps is load-bearing (a pre-existing fix); the existence
    filter must narrow that union without collapsing it back to api_counts.
    """
    live = "test_tenant_be9582_mcponly"
    await _cleanup(db_manager, [live])
    await _make_user(db_manager, live)
    state = _FakeState(db_manager, api_counts={}, mcp_counts={live: 4})

    try:
        await flush_api_metrics_once(state)

        rows = await _api_metrics_rows(db_manager, live)
        assert len(rows) == 1
        assert rows[0].total_mcp_calls == 4
    finally:
        await _cleanup(db_manager, [live])


@pytest.mark.asyncio
async def test_purged_tenant_counts_are_not_left_in_the_buffer(db_manager):
    """A dropped tenant must not linger in memory and be retried forever."""
    purged = "test_tenant_be9582_nobuffer"
    await _cleanup(db_manager, [purged])
    state = _FakeState(db_manager, api_counts={purged: 1}, mcp_counts={purged: 1})

    try:
        await flush_api_metrics_once(state)

        assert purged not in state.api_call_count
        assert purged not in state.mcp_call_count
    finally:
        await _cleanup(db_manager, [purged])


@pytest.mark.asyncio
async def test_mixed_batch_writes_only_the_live_tenant(db_manager):
    """One purged and one live tenant in the same tick: only the live one lands."""
    live = "test_tenant_be9582_mixed_live"
    purged = "test_tenant_be9582_mixed_purged"
    await _cleanup(db_manager, [live, purged])
    await _make_user(db_manager, live)
    state = _FakeState(db_manager, api_counts={live: 2, purged: 9}, mcp_counts={})

    try:
        await flush_api_metrics_once(state)

        assert len(await _api_metrics_rows(db_manager, live)) == 1
        assert await _api_metrics_rows(db_manager, purged) == []
    finally:
        await _cleanup(db_manager, [live, purged])
