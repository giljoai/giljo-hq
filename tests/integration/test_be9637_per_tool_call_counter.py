# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest

from api.endpoints.mcp_tools import _base
from api.startup.metrics_flushers import flush_api_metrics_once




class _FakeAppState:
    def __init__(self) -> None:
        self.db_manager = None
        self.websocket_manager = None
        self.mcp_call_count: dict[str, int] = {}
        self.mcp_tool_call_count: dict[tuple[str, str, date], int] = {}
        self.tool_accessor = object()


@pytest.fixture
def boundary(monkeypatch):
    fake_state = _FakeAppState()

    async def _fake_tool(**kwargs: Any) -> dict[str, Any]:
        return {"ok": True}

    from api import app_state as app_state_module

    monkeypatch.setattr(app_state_module, "state", fake_state)
    monkeypatch.setattr(_base, "_resolve_tenant", lambda ctx: "tk-be9637")
    monkeypatch.setattr(_base, "_set_tenant_context", lambda tenant_key: None)
    accessor = object()
    monkeypatch.setattr(_base, "_get_tool_accessor", lambda: accessor)
    monkeypatch.setattr(_base, "_resolve_tool_func", lambda accessor, method_name: _fake_tool)
    monkeypatch.setattr(_base, "should_run", lambda *args, **kwargs: False)
    return fake_state


async def test_two_different_tools_increment_two_different_names(boundary):
    await _base._call_tool(object(), "health_check", {})
    await _base._call_tool(object(), "list_projects", {})
    await _base._call_tool(object(), "health_check", {})

    counted = {(tool, count) for (_tenant, tool, _day), count in boundary.mcp_tool_call_count.items()}

    assert counted == {("health_check", 2), ("list_projects", 1)}, (
        f"two different tools must accumulate under two different names, got {counted}"
    )
    assert boundary.mcp_call_count == {"tk-be9637": 3}


async def test_the_day_is_stamped_at_call_time(boundary):
    await _base._call_tool(object(), "health_check", {})
    ((_tenant, _tool, day),) = boundary.mcp_tool_call_count
    assert day == datetime.now(UTC).date()


async def test_tenants_do_not_share_a_counter(boundary, monkeypatch):
    await _base._call_tool(object(), "health_check", {})
    monkeypatch.setattr(_base, "_resolve_tenant", lambda ctx: "tk-other")
    await _base._call_tool(object(), "health_check", {})

    tenants = {tenant for (tenant, _tool, _day) in boundary.mcp_tool_call_count}
    assert tenants == {"tk-be9637", "tk-other"}




class _FakeResult:
    def __init__(self, values: list[str]) -> None:
        self._values = values

    def scalars(self) -> _FakeResult:
        return self

    def all(self) -> list[str]:
        return list(self._values)


def _bound_strings(stmt: object) -> list[str]:
    found: list[str] = []
    for value in stmt.compile().params.values():
        if isinstance(value, str):
            found.append(value)
        elif isinstance(value, (list, tuple, set, frozenset)):
            found.extend(item for item in value if isinstance(item, str))
    return found


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


class _FlushState:
    def __init__(self, session: _FakeSession, tool_counts: dict) -> None:
        self.db_manager = _FakeDbManager(session)
        self.api_call_count: dict[str, int] = {}
        self.mcp_call_count: dict[str, int] = {}
        self.mcp_tool_call_count = dict(tool_counts)


def _table_of(stmt: object) -> str:
    return stmt.table.name


async def test_the_flusher_writes_one_row_per_tool(monkeypatch):
    today = datetime.now(UTC).date()
    session = _FakeSession()
    state = _FlushState(
        session,
        {
            ("tk_alpha", "health_check", today): 2,
            ("tk_alpha", "list_projects", today): 5,
        },
    )

    await flush_api_metrics_once(state)

    tool_stmts = [s for s in session.executed if _table_of(s) == "mcp_tool_call_metrics"]
    written = {(s.compile().params["tool_name"], s.compile().params["call_count"]) for s in tool_stmts}

    assert written == {("health_check", 2), ("list_projects", 5)}, (
        f"each buffered tool name must reach its own row, got {written}"
    )
    assert session.commits == 1


async def test_the_same_tool_on_two_days_stays_two_rows(monkeypatch):
    today = datetime.now(UTC).date()
    yesterday = today - timedelta(days=1)
    session = _FakeSession()
    state = _FlushState(
        session,
        {
            ("tk_alpha", "health_check", today): 2,
            ("tk_alpha", "health_check", yesterday): 7,
        },
    )

    await flush_api_metrics_once(state)

    tool_stmts = [s for s in session.executed if _table_of(s) == "mcp_tool_call_metrics"]
    assert {s.compile().params["day"] for s in tool_stmts} == {today, yesterday}


async def test_per_tool_rows_do_not_disturb_the_be9520_tenant_order(monkeypatch):
    today = datetime.now(UTC).date()
    session = _FakeSession()
    state = _FlushState(
        session,
        {
            ("tk_zulu", "health_check", today): 1,
            ("tk_alpha", "health_check", today): 1,
            ("tk_mike", "list_projects", today): 1,
        },
    )

    await flush_api_metrics_once(state)

    tenant_sequence = [s.compile().params["tenant_key"] for s in session.executed]
    assert tenant_sequence == sorted(tenant_sequence), (
        f"tenant lock order must stay a stable total order, got {tenant_sequence}"
    )
    assert [s.compile().params["tenant_key"] for s in session.executed if _table_of(s) == "api_metrics"] == [
        "tk_alpha",
        "tk_mike",
        "tk_zulu",
    ]


async def test_a_failed_flush_puts_the_tool_counts_back(monkeypatch):
    today = datetime.now(UTC).date()
    buffered = {("tk_alpha", "health_check", today): 3}

    class _ExplodingSession(_FakeSession):
        async def execute(self, stmt: object) -> _FakeResult | None:
            if getattr(stmt, "is_select", False):
                return _FakeResult(_bound_strings(stmt))
            raise RuntimeError("transient DB error")

    session = _ExplodingSession()
    state = _FlushState(session, buffered)

    await flush_api_metrics_once(state)

    assert state.mcp_tool_call_count == buffered, (
        "a failed flush must restore the per-tool buffer so the window is retried"
    )


async def test_the_counter_guard_can_actually_fire():
    one_name = {("tk", "health_check", date(2026, 1, 1)): 3}
    counted = {tool for (_t, tool, _d) in one_name}
    assert counted != {"health_check", "list_projects"}, "the two-name assertion must not pass on a single name"
    assert asyncio.iscoroutinefunction(flush_api_metrics_once)
