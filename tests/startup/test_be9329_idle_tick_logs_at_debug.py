# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import asyncio
import logging
from unittest.mock import MagicMock

import pytest

from api.startup import metrics_flushers
from api.startup.metrics_flushers import sync_api_metrics_to_db


_LOGGER_NAME = "api.startup.metrics_flushers"

_IDLE_MESSAGE = "API metrics sync: no API call counts to flush"


def _bound_strings(stmt: object) -> list[str]:
    found: list[str] = []
    for value in stmt.compile().params.values():
        if isinstance(value, str):
            found.append(value)
        elif isinstance(value, (list, tuple, set, frozenset)):
            found.extend(item for item in value if isinstance(item, str))
    return found


class _FakeResult:

    def __init__(self, values: list[str]) -> None:
        self._values = values

    def scalars(self) -> _FakeResult:
        return self

    def all(self) -> list[str]:
        return list(self._values)


class _FakeSession:

    def __init__(self) -> None:
        self.executed: list[object] = []
        self.commits = 0
        self.info: dict[str, object] = {}

    async def execute(self, stmt: object) -> _FakeResult | None:
        if getattr(stmt, "is_select", False):
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
    records, session = await _run_one_tick(monkeypatch, caplog, api_counts={}, mcp_counts={})

    noisy = [rec for rec in records if rec.levelno >= logging.INFO]
    assert noisy == [], f"idle tick must be silent at INFO, got: {[rec.getMessage() for rec in noisy]}"

    assert session.commits == 1
    assert session.executed == []
    assert [rec.getMessage() for rec in records if rec.levelno == logging.DEBUG] == [_IDLE_MESSAGE]


async def test_mcp_only_window_does_not_claim_nothing_happened(monkeypatch, caplog):
    records, session = await _run_one_tick(
        monkeypatch,
        caplog,
        api_counts={},
        mcp_counts={"tk_alpha": 3},
    )

    noisy = [rec for rec in records if rec.levelno >= logging.INFO]
    assert noisy == [], f"an MCP-only window must not log at INFO, got: {[rec.getMessage() for rec in noisy]}"
    assert len(session.executed) == 1

    rendered = [rec.getMessage() for rec in records if rec.levelno == logging.DEBUG]
    assert rendered == [_IDLE_MESSAGE]
    assert "nothing" not in rendered[0].lower(), (
        f"MCP counts were discarded in this window, so a blanket 'nothing' claim is false: {rendered[0]}"
    )


async def test_mcp_only_window_persists_the_mcp_count(monkeypatch, caplog):
    _records, session = await _run_one_tick(
        monkeypatch,
        caplog,
        api_counts={},
        mcp_counts={"tk_alpha": 3},
    )

    assert len(session.executed) == 1, f"the MCP-only tenant's count must reach the DB, got: {session.executed}"

    params = session.executed[0].compile().params
    assert params["tenant_key"] == "tk_alpha"
    assert params["total_api_calls"] == 0
    assert params["total_mcp_calls"] == 3


async def test_tick_with_work_emits_exactly_one_info_record(monkeypatch, caplog):
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
    from api.run_api import _NoiseFilter

    idle_records, _ = await _run_one_tick(monkeypatch, caplog, api_counts={}, mcp_counts={})
    caplog.clear()
    busy_records, _ = await _run_one_tick(monkeypatch, caplog, api_counts={"tk_alpha": 1}, mcp_counts={})

    emitted = idle_records + busy_records
    assert emitted, "no records captured -- the guard would pass vacuously"

    noise_filter = _NoiseFilter()
    swallowed = [rec.getMessage() for rec in emitted if not noise_filter.filter(rec)]
    assert swallowed == [], f"CE's _NoiseFilter would drop these: {swallowed}"
