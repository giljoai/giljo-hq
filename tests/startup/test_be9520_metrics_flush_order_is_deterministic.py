# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import pytest

from api.startup import metrics_flushers
from api.startup.metrics_flushers import sync_api_metrics_to_db


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


async def test_flush_order_matches_sorted_tenant_keys_not_set_iteration(monkeypatch):
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

    assert set(emitted_order) == expected_union

    assert emitted_order == sorted(expected_union), (
        f"flush order must be deterministic across processes (sorted), got: {emitted_order}"
    )
