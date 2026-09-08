# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-9329: a periodic loop narrated every tick, including the empty ones.

Failing layer: ``sync_api_metrics_to_db`` logged its "Synced API metrics for N
tenants." line unconditionally at INFO on a 300-second loop. On an idle CE box
``N`` is permanently 0, so a self-hoster's log filled with 288 lines a day that
each report that nothing happened.

The house rule these tests pin: a periodic background task may log at INFO only
when it changed something; an idle tick logs at DEBUG. The predicate is the
edition difference expressed as data -- CE goes quiet because nothing happened,
SaaS keeps reporting because something did -- so there is no ``GILJO_MODE``
branch to test around.

Parallel-safe: no DB, no module-level mutable state; monkeypatch everywhere.
"""

from __future__ import annotations

import asyncio
import logging
from unittest.mock import MagicMock

import pytest

from api.startup import metrics_flushers
from api.startup.metrics_flushers import sync_api_metrics_to_db


_LOGGER_NAME = "api.startup.metrics_flushers"

# Pinned wording, not decoration: the message must scope its emptiness to the
# API counts. See test_mcp_only_window_does_not_claim_nothing_happened.
_IDLE_MESSAGE = "API metrics sync: no API call counts to flush"


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
    """Async session stand-in. A MagicMock cannot serve here: its ``commit`` is
    not awaitable, so the loop would land in its own ``except`` branch and the
    test would read a swallowed error as "correctly silent"."""

    def __init__(self) -> None:
        self.executed: list[object] = []
        self.commits = 0
        # BE-9582's liveness check opens a tenant_isolation_bypass, which stores
        # its state here. Without it the bypass raises and the loop swallows it.
        self.info: dict[str, object] = {}

    async def execute(self, stmt: object) -> _FakeResult | None:
        if getattr(stmt, "is_select", False):
            # BE-9582 liveness probe. Answer "every tenant you asked about still
            # exists" so these tests keep exercising log level and flush order
            # only, and keep it out of ``executed`` so the upsert assertions
            # below still index the statements they were written against.
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


async def _run_one_tick(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    api_counts: dict[str, int],
    mcp_counts: dict[str, int],
) -> tuple[list[logging.LogRecord], _FakeSession]:
    """Drive one flusher iteration; return its records and the session it used."""
    session = _FakeSession()
    state = MagicMock()
    state.api_call_count = dict(api_counts)
    state.mcp_call_count = dict(mcp_counts)
    state.db_manager = _FakeDbManager(session)

    _stop_after_one_tick(monkeypatch)

    with caplog.at_level(logging.DEBUG, logger=_LOGGER_NAME), pytest.raises(asyncio.CancelledError):
        await sync_api_metrics_to_db(state)

    return [rec for rec in caplog.records if rec.name == _LOGGER_NAME], session


async def test_idle_tick_emits_no_info_record(monkeypatch, caplog):
    """THE DEFECT: with nothing to flush, the tick must say nothing at INFO.

    The assertion is ``>= INFO`` rather than ``== INFO`` deliberately: if the
    fakes ever break, the loop's own catch logs at ERROR, and a narrower
    assertion would read that swallowed failure as a pass.
    """
    records, session = await _run_one_tick(monkeypatch, caplog, api_counts={}, mcp_counts={})

    noisy = [rec for rec in records if rec.levelno >= logging.INFO]
    assert noisy == [], f"idle tick must be silent at INFO, got: {[rec.getMessage() for rec in noisy]}"

    # The tick still did its work -- it went quiet, it did not go missing.
    assert session.commits == 1
    assert session.executed == []
    assert [rec.getMessage() for rec in records if rec.levelno == logging.DEBUG] == [_IDLE_MESSAGE]


async def test_mcp_only_window_does_not_claim_nothing_happened(monkeypatch, caplog):
    """An MCP-only window has empty API counts but non-empty MCP counts.

    ``/mcp`` is a public path, so auth early-returns without setting
    ``tenant_key`` and ``APIMetricsMiddleware`` never increments
    ``api_call_count``; ``mcp_call_count`` fills from ``_call_tool`` regardless.
    A headless MCP-only CE server therefore lands here on every tick, and a
    blanket "nothing to flush" would be a false statement -- actively
    misleading for someone debugging a zero MCP count.

    The predicate deliberately stays ``if api_counts``: widening it to
    ``or mcp_counts`` would restore the per-tick INFO noise this change exists
    to remove, so this test pins DEBUG here as well as the honest wording.
    """
    records, session = await _run_one_tick(
        monkeypatch,
        caplog,
        api_counts={},
        mcp_counts={"tk_alpha": 3},
    )

    noisy = [rec for rec in records if rec.levelno >= logging.INFO]
    assert noisy == [], f"an MCP-only window must not log at INFO, got: {[rec.getMessage() for rec in noisy]}"
    # BE-9329 pinned the log LEVEL and WORDING here, not persistence -- this
    # assertion originally read `== []`, which incidentally encoded the
    # since-fixed defect where an MCP-only tenant's row was never written.
    # The persistence contract now lives in
    # test_mcp_only_window_persists_the_mcp_count; here it's inverted only so
    # this test still proves the DEBUG line's honesty is not a lie about a
    # window that (correctly) did write something.
    assert len(session.executed) == 1

    rendered = [rec.getMessage() for rec in records if rec.levelno == logging.DEBUG]
    assert rendered == [_IDLE_MESSAGE]
    assert "nothing" not in rendered[0].lower(), (
        f"MCP counts were discarded in this window, so a blanket 'nothing' claim is false: {rendered[0]}"
    )


async def test_mcp_only_window_persists_the_mcp_count(monkeypatch, caplog):
    """THE DEFECT (differential-confirmed on master): a tenant with MCP calls
    but no API calls must still get its ``mcp_call_count`` written to the DB.

    The persistence loop iterates ``api_counts.items()`` only, so a tenant
    present in ``mcp_counts`` and absent from ``api_counts`` never triggers an
    upsert -- its MCP calls are silently dropped every tick, even though
    ``mcp_call_count`` was already cleared unconditionally before the DB
    round-trip. This is a real, first-class configuration: ``/mcp`` is a
    public path, so auth never sets ``tenant_key`` and an MCP-only CE
    self-hoster's dashboard MCP statistic permanently under-reports.
    """
    _records, session = await _run_one_tick(
        monkeypatch,
        caplog,
        api_counts={},
        mcp_counts={"tk_alpha": 3},
    )

    assert len(session.executed) == 1, f"the MCP-only tenant's count must reach the DB, got: {session.executed}"

    # A row existing is not enough -- this PR's whole subject is a count that
    # was silently dropped, so the row must carry the RIGHT numbers, not
    # merely exist. compile().params reads the actual bound values off the
    # Insert construct rather than re-deriving them.
    params = session.executed[0].compile().params
    assert params["tenant_key"] == "tk_alpha"
    assert params["total_api_calls"] == 0
    assert params["total_mcp_calls"] == 3


async def test_tick_with_work_emits_exactly_one_info_record(monkeypatch, caplog):
    """When there IS something to report, the line survives -- and still renders.

    Guards the f-string -> lazy ``%`` conversion: a dropped argument leaves the
    literal ``%d`` in the rendered message instead of the count.
    """
    records, session = await _run_one_tick(
        monkeypatch,
        caplog,
        api_counts={"tk_alpha": 7, "tk_beta": 2},
        mcp_counts={"tk_alpha": 3},
    )

    at_info = [rec for rec in records if rec.levelno >= logging.INFO]
    assert len(at_info) == 1, f"expected one INFO line, got: {[rec.getMessage() for rec in at_info]}"
    assert at_info[0].levelno == logging.INFO

    rendered = at_info[0].getMessage()
    assert "for 2 tenants" in rendered, rendered
    assert "%" not in rendered, f"lazy %-format left unrendered: {rendered}"
    assert len(session.executed) == 2


async def test_emitted_messages_survive_the_ce_noise_filter(monkeypatch, caplog):
    """Every message this loop emits must reach a CE log file.

    ``_NoiseFilter`` drops any record whose message contains "heartbeat" (among
    other substrings), so a future reword toward liveness vocabulary would be
    silently swallowed in CE while still appearing in SaaS. This drives the real
    filter over the real emitted text rather than restating the strings.
    """
    from api.run_api import _NoiseFilter

    idle_records, _ = await _run_one_tick(monkeypatch, caplog, api_counts={}, mcp_counts={})
    caplog.clear()
    busy_records, _ = await _run_one_tick(monkeypatch, caplog, api_counts={"tk_alpha": 1}, mcp_counts={})

    emitted = idle_records + busy_records
    assert emitted, "no records captured -- the guard would pass vacuously"

    noise_filter = _NoiseFilter()
    swallowed = [rec.getMessage() for rec in emitted if not noise_filter.filter(rec)]
    assert swallowed == [], f"CE's _NoiseFilter would drop these: {swallowed}"
