# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-9520: the metrics flusher's per-tenant upsert order must be deterministic.

Failing layer: ``sync_api_metrics_to_db`` iterated
``api_counts.keys() | mcp_counts.keys()`` -- a Python ``set``. Set iteration
order over ``str`` keys depends on per-process hash randomization (each worker
process gets its own random hash seed at startup), so two worker processes
flushing the same tenants in the same 300s window walk them in DIFFERENT
orders. Both open one transaction and issue one ``INSERT ... ON CONFLICT``
per tenant, so two processes taking the same set of per-tenant row locks in
opposite orders is a textbook deadlock -- and Postgres kills one of them
(Sentry GILJOAI-BACKEND-X, 3 events 2026-08-24; prod runs two services, so
concurrent flushers are steady state, not an edge case).

The fix replaces the bare set with ``sorted(...)``, a stable *total* order
that is identical in every process regardless of hash seed. This does not
prevent two processes from flushing the same tenant concurrently (that race
still exists and is fine -- Postgres serializes it), it only guarantees they
always visit the shared tenant set in the SAME order, which is what turns a
deadlock into ordinary lock contention.

This test does not simulate two processes (that would require a second
interpreter to get a second hash seed). Instead it pins the *contract*: the
sequence of ``tenant_key``s in the statements executed by ONE call must equal
``sorted()`` of the union, not whatever order ``set`` iteration happens to
produce. The five tenant keys below were confirmed (see project notes) to
iterate in a NON-sorted order under normal set iteration in this interpreter,
so this test fails against the unfixed code rather than passing by
coincidence.

Parallel-safe: no DB, no module-level mutable state; monkeypatch everywhere.
Fixture/mocking approach copied from
``test_be9329_idle_tick_logs_at_debug.py`` (``_FakeSession`` et al. -- a
MagicMock can't serve here since its ``commit`` isn't awaitable) and
``test_be9053_loop_resilience.py`` (bounded fake ``asyncio.sleep`` to stop the
infinite loop after one tick).
"""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import pytest

from api.startup import metrics_flushers
from api.startup.metrics_flushers import sync_api_metrics_to_db


def _bound_strings(stmt: object) -> list[str]:
    """Every string bound into ``stmt``, flattening expanding IN parameters.

    ``.in_(keys)`` compiles to a single expanding bindparam whose value is the
    whole LIST, so a plain ``isinstance(value, str)`` filter over
    ``compile().params`` silently returns nothing and the probe reads as "no
    tenant is live".
    """
    found: list[str] = []
    for value in stmt.compile().params.values():
        if isinstance(value, str):
            found.append(value)
        elif isinstance(value, (list, tuple, set, frozenset)):
            found.extend(item for item in value if isinstance(item, str))
    return found


class _FakeResult:
    """Minimal stand-in for a SQLAlchemy Result over a single scalar column."""

    def __init__(self, values: list[str]) -> None:
        self._values = values

    def scalars(self) -> _FakeResult:
        return self

    def all(self) -> list[str]:
        return list(self._values)


class _FakeSession:
    """Async session stand-in; records statements in EXECUTION order."""

    def __init__(self) -> None:
        self.executed: list[object] = []
        self.commits = 0
        # BE-9582's liveness check opens a tenant_isolation_bypass, which stores
        # its state here. Without it the bypass raises and the loop swallows it,
        # leaving ``executed`` empty and the order assertion unable to see
        # anything at all.
        self.info: dict[str, object] = {}

    async def execute(self, stmt: object) -> _FakeResult | None:
        if getattr(stmt, "is_select", False):
            # BE-9582 liveness probe. Answer "every tenant you asked about still
            # exists" so this test still measures ORDER, and keep it out of
            # ``executed`` so it cannot be mistaken for an upsert.
            return _FakeResult(_bound_strings(stmt))
        self.executed.append(stmt)
        return None

    async def commit(self) -> None:
        self.commits += 1


class _FakeSessionContext:
    def __init__(self, session: _FakeSession) -> None:
        self._session = session

    async def __aenter__(self) -> _FakeSession:
        return self._session

    async def __aexit__(self, *_exc: object) -> bool:
        return False


class _FakeDbManager:
    def __init__(self, session: _FakeSession) -> None:
        self._session = session

    def get_session_async(self) -> _FakeSessionContext:
        return _FakeSessionContext(self._session)


def _stop_after_one_tick(monkeypatch: pytest.MonkeyPatch) -> None:
    """Let the loop body run exactly once, then cancel it at the next sleep."""
    real_sleep = asyncio.sleep
    calls = {"n": 0}

    async def fake_sleep(_seconds: float) -> None:
        calls["n"] += 1
        if calls["n"] > 1:
            raise asyncio.CancelledError
        await real_sleep(0)

    monkeypatch.setattr(metrics_flushers.asyncio, "sleep", fake_sleep)


async def test_flush_order_matches_sorted_tenant_keys_not_set_iteration(monkeypatch):
    """THE DEFECT: the emitted upsert order must be a stable total order.

    Uses a mix of tenant keys present in ONLY api_counts, ONLY mcp_counts, and
    BOTH -- exercising the documented union requirement (a tenant with MCP
    calls but no API calls in the window must still be flushed) while also
    proving the ORDER is now independent of set-hash iteration.
    """
    api_counts = {"tk_zulu": 1, "tk_alpha": 2, "tk_mike": 3}
    mcp_counts = {"tk_bravo": 4, "tk_kilo": 5, "tk_alpha": 6}
    expected_union = {"tk_zulu", "tk_alpha", "tk_mike", "tk_bravo", "tk_kilo"}

    session = _FakeSession()
    state = MagicMock()
    state.api_call_count = dict(api_counts)
    state.mcp_call_count = dict(mcp_counts)
    state.db_manager = _FakeDbManager(session)

    _stop_after_one_tick(monkeypatch)

    with pytest.raises(asyncio.CancelledError):
        await sync_api_metrics_to_db(state)

    emitted_order = [stmt.compile().params["tenant_key"] for stmt in session.executed]

    # The union must be preserved regardless of ordering (pre-existing
    # requirement, not the thing this bug touches -- verified first so an
    # order-only assertion failure below can't be misread as a missing tenant).
    assert set(emitted_order) == expected_union

    # THE DEFECT: order must be the stable sort, not raw set-union iteration.
    assert emitted_order == sorted(expected_union), (
        f"flush order must be deterministic across processes (sorted), got: {emitted_order}"
    )
