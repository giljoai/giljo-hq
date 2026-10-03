# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import contextlib

import pytest
from sqlalchemy.exc import OperationalError

from api.endpoints.mcp_tools import _base
from giljo_mcp.services import debounce


pytestmark = pytest.mark.asyncio


class _FakeProgressService:
    async def report_progress(self, *, job_id=None, tenant_key=None, **kwargs):
        return {"ok": True}


class _FakeAccessor:
    def __init__(self) -> None:
        self._progress_service = _FakeProgressService()


class _Db:
    def get_session_async(self, tenant_key=None):
        @contextlib.asynccontextmanager
        async def _cm():
            yield object()

        return _cm()


@pytest.fixture
def harness(monkeypatch):
    from api import app_state
    from giljo_mcp.services import heartbeat, silence_detector

    debounce.reset("mcp_posthooks")
    state = app_state.state
    prior = (state.tool_accessor, state.db_manager, state.websocket_manager)
    state.tool_accessor = _FakeAccessor()
    state.db_manager = _Db()
    state.websocket_manager = None
    monkeypatch.setattr(_base, "_resolve_tenant", lambda ctx: "tk-test")
    monkeypatch.setattr(_base, "_set_tenant_context", lambda tenant_key: None)

    async def _silent_ok(db, job_id, ws_manager, tenant_key):
        return None

    monkeypatch.setattr(silence_detector, "auto_clear_silent", _silent_ok)

    def set_heartbeat(exc: Exception):
        async def _raise(db, job_id, tenant_key):
            raise exc

        monkeypatch.setattr(heartbeat, "touch_heartbeat", _raise)

    async def call():
        return await _base._call_tool(None, "report_progress", {"job_id": "job-F7"})

    try:
        yield call, set_heartbeat
    finally:
        state.tool_accessor, state.db_manager, state.websocket_manager = prior
        debounce.reset("mcp_posthooks")


async def test_a_database_error_in_the_heartbeat_hook_does_not_fail_the_committed_call(harness):
    call, set_heartbeat = harness
    set_heartbeat(OperationalError("UPDATE agent_jobs", {}, Exception("connection reset")))
    assert (await call())["ok"] is True


async def test_a_code_bug_in_the_heartbeat_hook_is_not_hidden(harness):
    call, set_heartbeat = harness
    set_heartbeat(TypeError("touch_heartbeat() got an unexpected keyword"))
    with pytest.raises(TypeError):
        await call()
