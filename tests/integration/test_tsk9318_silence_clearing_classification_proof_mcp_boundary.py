# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any

import pytest

from api.endpoints.mcp_tools import _base, _silence_scope


CLASSIFIED_FROM_INTENT = ("set_agent_status", "get_staging_instructions", "request_approval")


class _Recorder:
    def __init__(self) -> None:
        self.silence_cleared_for: list[str] = []
        self.heartbeats_for: list[str] = []


@pytest.fixture
def boundary(monkeypatch):
    recorder = _Recorder()

    async def _fake_tool(**kwargs: Any) -> dict[str, Any]:
        return {"ok": True}

    async def _fake_auto_clear_silent(session, job_id, ws_manager, tenant_key):
        recorder.silence_cleared_for.append(job_id)

    async def _fake_touch_heartbeat(session, job_id, tenant_key):
        recorder.heartbeats_for.append(job_id)

    @asynccontextmanager
    async def _fake_session():
        yield object()

    class _FakeDbManager:
        def get_session_async(self):
            return _fake_session()

    class _FakeAppState:
        db_manager = _FakeDbManager()
        websocket_manager = None
        mcp_call_count: dict[str, int] = {}
        tool_accessor = object()

    from api import app_state as app_state_module
    from giljo_mcp.services import heartbeat as heartbeat_module
    from giljo_mcp.services import silence_detector as silence_module

    monkeypatch.setattr(app_state_module, "state", _FakeAppState())
    monkeypatch.setattr(_base, "_resolve_tenant", lambda ctx: "tk-tsk9318")
    monkeypatch.setattr(_base, "_set_tenant_context", lambda tenant_key: None)
    _accessor = object()
    monkeypatch.setattr(_base, "_get_tool_accessor", lambda: _accessor)
    monkeypatch.setattr(_base, "_resolve_tool_func", lambda accessor, method_name: _fake_tool)
    monkeypatch.setattr(_base, "should_run", lambda *args, **kwargs: True)
    monkeypatch.setattr(silence_module, "auto_clear_silent", _fake_auto_clear_silent)
    monkeypatch.setattr(heartbeat_module, "touch_heartbeat", _fake_touch_heartbeat)

    return recorder


async def _call(tool_name: str, job_id: str = "job-tsk9318") -> Any:
    return await _base._call_tool(object(), tool_name, {"job_id": job_id})




@pytest.mark.parametrize("tool_name", CLASSIFIED_FROM_INTENT)
async def test_the_three_unmeasured_names_do_clear_silence(boundary, tool_name):
    await _call(tool_name)
    assert boundary.silence_cleared_for == ["job-tsk9318"], (
        f"{tool_name} is classified as the caller's own liveness signal and must reach "
        f"auto_clear_silent; got {boundary.silence_cleared_for!r}"
    )


async def test_request_approval_reaches_the_hook_at_all(boundary):
    await _call("request_approval")
    assert boundary.silence_cleared_for == ["job-tsk9318"], (
        "request_approval forwards job_id into _call_tool, so its entry in "
        "SILENCE_CLEARING_TOOLS must be live rather than decorative"
    )
    assert boundary.heartbeats_for == ["job-tsk9318"], "the heartbeat post-hook must run for it too"


def test_every_classified_clearing_name_is_pinned_by_a_test():
    pinned = set(CLASSIFIED_FROM_INTENT) | {"report_progress", "get_job_mission"}
    unpinned = set(_silence_scope.SILENCE_CLEARING_TOOLS) - pinned
    assert not unpinned, (
        f"these silence-clearing names have no boundary test pinning them: {sorted(unpinned)}. "
        "Add one here (or to the BE-9303 museum set) rather than leaving the classification "
        "resting on a comment — that is the exact defect this file exists to close."
    )




@pytest.mark.parametrize("tool_name", ["get_staging_instructions", "set_agent_status"])
async def test_an_agent_whose_only_signal_is_these_tools_is_not_left_silent(boundary, tool_name):
    await _call(tool_name, job_id="job-5d57e77c")
    assert boundary.silence_cleared_for == ["job-5d57e77c"], (
        f"{tool_name} must keep clearing silence: a live agent was observed whose only "
        "job-carrying calls were these, and dropping them marks it silent and leaves it there"
    )


async def test_the_narrowing_still_holds_for_the_documented_disarm(boundary):
    await _call("get_context")
    assert boundary.silence_cleared_for == [], (
        "the orchestrator's force-recovery read must still never clear 'silent' — "
        "pinning the clearing names must not widen the gate"
    )




async def test_a_clearing_tool_cannot_tell_whose_job_the_job_id_is(boundary):
    await _call("set_agent_status", job_id="job-belonging-to-another-agent")
    assert boundary.silence_cleared_for == ["job-belonging-to-another-agent"], (
        "the hook has no caller identity and clears whatever job_id it is handed; this "
        "is the measured residual of the whose-job criterion, not a defect introduced here"
    )
