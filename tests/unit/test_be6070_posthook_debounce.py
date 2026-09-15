# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import contextlib

import pytest

from api.endpoints.mcp_tools import _base
from giljo_mcp.services import debounce


pytestmark = pytest.mark.asyncio


class _FakeProgressService:

    async def report_progress(self, *, job_id=None, tenant_key=None, **kwargs):
        return {"ok": True}


class _FakeAccessor:

    def __init__(self) -> None:
        self._progress_service = _FakeProgressService()


class _SessionCounter:

    def __init__(self) -> None:
        self.opens = 0

    def get_session_async(self, tenant_key=None):
        self.opens += 1

        @contextlib.asynccontextmanager
        async def _cm():
            yield object()

        return _cm()


@pytest.fixture
def posthook_harness(monkeypatch):
    from api import app_state
    from giljo_mcp.services import heartbeat, silence_detector

    debounce.reset("mcp_posthooks")

    state = app_state.state
    prior_accessor = state.tool_accessor
    prior_db = state.db_manager
    prior_ws = state.websocket_manager

    session_counter = _SessionCounter()
    state.tool_accessor = _FakeAccessor()
    state.db_manager = session_counter
    state.websocket_manager = None

    monkeypatch.setattr(_base, "_resolve_tenant", lambda ctx: "tk-test")
    monkeypatch.setattr(_base, "_set_tenant_context", lambda tenant_key: None)

    counters = {"silent": 0, "heartbeat": 0, "sessions": session_counter}

    async def _fake_auto_clear(db, job_id, ws_manager, tenant_key):
        counters["silent"] += 1

    async def _fake_heartbeat(db, job_id, tenant_key):
        counters["heartbeat"] += 1

    monkeypatch.setattr(silence_detector, "auto_clear_silent", _fake_auto_clear)
    monkeypatch.setattr(heartbeat, "touch_heartbeat", _fake_heartbeat)

    async def call(job_id="job-1"):
        return await _base._call_tool(None, "report_progress", {"job_id": job_id})

    try:
        yield call, counters
    finally:
        state.tool_accessor = prior_accessor
        state.db_manager = prior_db
        state.websocket_manager = prior_ws
        debounce.reset("mcp_posthooks")


async def test_first_call_runs_both_hooks_in_one_session(posthook_harness):
    call, counters = posthook_harness

    result = await call("job-A")

    assert result["ok"] is True
    assert counters["sessions"].opens == 1, "expected ONE shared session, not two"
    assert counters["silent"] == 1
    assert counters["heartbeat"] == 1


async def test_rapid_second_call_skips_both_hooks(posthook_harness):
    call, counters = posthook_harness

    await call("job-A")
    await call("job-A")

    assert counters["sessions"].opens == 1, "2nd rapid call must NOT open a session"
    assert counters["silent"] == 1, "2nd rapid call must NOT re-run silent-clear"
    assert counters["heartbeat"] == 1, "2nd rapid call must NOT re-run heartbeat"


async def test_n_rapid_calls_bounded_to_one_db_visit(posthook_harness):
    call, counters = posthook_harness

    for _ in range(25):
        await call("job-A")

    assert counters["sessions"].opens == 1
    assert counters["silent"] == 1
    assert counters["heartbeat"] == 1


async def test_window_elapsed_runs_hooks_again(posthook_harness):
    call, counters = posthook_harness

    await call("job-A")
    debounce.reset("mcp_posthooks")
    await call("job-A")

    assert counters["sessions"].opens == 2
    assert counters["silent"] == 2
    assert counters["heartbeat"] == 2


async def test_distinct_job_ids_each_get_first_write(posthook_harness):
    call, counters = posthook_harness

    await call("job-A")
    await call("job-B")

    assert counters["sessions"].opens == 2
    assert counters["silent"] == 2
    assert counters["heartbeat"] == 2


async def test_no_job_id_skips_posthooks_entirely(posthook_harness):
    _call, counters = posthook_harness

    await _base._call_tool(None, "report_progress", {})

    assert counters["sessions"].opens == 0
    assert counters["silent"] == 0
    assert counters["heartbeat"] == 0
