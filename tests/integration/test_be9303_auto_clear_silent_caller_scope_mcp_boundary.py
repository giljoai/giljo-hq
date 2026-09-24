# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import ast
import pathlib
from contextlib import asynccontextmanager
from typing import Any

import pytest

from api.endpoints.mcp_tools import _base, _silence_scope


REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
MCP_TOOLS_DIR = REPO_ROOT / "api" / "endpoints" / "mcp_tools"


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
        mcp_tool_call_count: dict[tuple[str, str, object], int] = {}
        tool_accessor = object()

    from api import app_state as app_state_module
    from giljo_mcp.services import heartbeat as heartbeat_module
    from giljo_mcp.services import silence_detector as silence_module

    monkeypatch.setattr(app_state_module, "state", _FakeAppState())
    monkeypatch.setattr(_base, "_resolve_tenant", lambda ctx: "tk-be9303")
    monkeypatch.setattr(_base, "_set_tenant_context", lambda tenant_key: None)
    _accessor = object()
    monkeypatch.setattr(_base, "_get_tool_accessor", lambda: _accessor)
    monkeypatch.setattr(_base, "_resolve_tool_func", lambda accessor, method_name: _fake_tool)
    monkeypatch.setattr(_base, "should_run", lambda *args, **kwargs: True)
    monkeypatch.setattr(silence_module, "auto_clear_silent", _fake_auto_clear_silent)
    monkeypatch.setattr(heartbeat_module, "touch_heartbeat", _fake_touch_heartbeat)

    return recorder


async def _call(tool_name: str, job_id: str = "job-be9303") -> Any:
    return await _base._call_tool(object(), tool_name, {"job_id": job_id})




async def test_museum_a_live_agents_own_progress_report_clears_silence(boundary):
    await _call("report_progress")
    assert boundary.silence_cleared_for == ["job-be9303"], (
        "report_progress is the agent's own proof of life — it must still clear "
        "'silent'. Losing this is the dd306cb36 incident: a live agent stuck "
        "reading 'silent' because the post-hook never ran."
    )


async def test_museum_b_agent_self_calls_that_stamp_liveness_still_clear_silence(boundary):
    await _call("get_job_mission")
    assert boundary.silence_cleared_for == ["job-be9303"]




async def test_orchestrator_inspection_read_does_not_disarm_the_hint(boundary):
    await _call("get_context")
    assert boundary.silence_cleared_for == [], (
        "an orchestrator's read ABOUT a stalled job must not clear that job's "
        "'silent' flag — clearing it disarms the finalize_job recovery hint before "
        "the orchestrator can reach it."
    )


@pytest.mark.parametrize(
    "tool_name",
    ["get_context", "get_agent_result", "finalize_job", "reactivate_job", "dismiss_reactivation", "complete_job"],
)
async def test_bystander_tools_never_clear_silence(boundary, tool_name):
    await _call(tool_name)
    assert boundary.silence_cleared_for == [], f"{tool_name} is a bystander/recovery tool and must not clear 'silent'"


async def test_the_hint_survives_the_inspection_read_end_to_end(boundary):
    from giljo_mcp.services._error_helpers import _wrong_state_next_action

    await _call("get_context")
    assert boundary.silence_cleared_for == []

    next_action = _wrong_state_next_action(
        job_id="job-be9303",
        project_id="proj-be9303",
        actual_status="silent",
        expected_status="complete",
    )
    assert next_action["tool"] == "complete_job", (
        "with the flag intact the refusal must name the complete_job recovery — that "
        f"is the whole point of not clearing it on a bystander read. Got: {next_action!r}"
    )




async def test_heartbeat_still_runs_for_a_tool_that_does_not_clear_silence(boundary):
    await _call("get_context")
    assert boundary.heartbeats_for == ["job-be9303"], (
        "the BE-9303 scope applies to auto_clear_silent ONLY; last_activity_at "
        "must still be stamped on every authenticated job-carrying call."
    )




def _dispatch_targets(func: ast.AST) -> set[str]:
    targets: set[str] = set()
    for node in ast.walk(func):
        if not (isinstance(node, ast.Call) and getattr(node.func, "id", None) == "_call_tool"):
            continue
        if len(node.args) < 2:
            continue
        second = node.args[1]
        if isinstance(second, ast.Constant) and isinstance(second.value, str):
            targets.add(second.value)
        elif isinstance(second, ast.Name):
            for assign in ast.walk(func):
                if not isinstance(assign, ast.Assign) or assign.value is None:
                    continue
                if not any(isinstance(t, ast.Name) and t.id == second.id for t in assign.targets):
                    continue
                targets |= _value_strings(assign.value)
    return targets


def _value_strings(node: ast.AST) -> set[str]:
    if isinstance(node, ast.Constant):
        return {node.value} if isinstance(node.value, str) else set()
    if isinstance(node, ast.IfExp):
        return _value_strings(node.body) | _value_strings(node.orelse)
    return set()


def _job_id_dispatch_names() -> set[str]:
    names: set[str] = set()
    for path in sorted(MCP_TOOLS_DIR.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)):
                continue
            args = [a.arg for a in node.args.args + node.args.kwonlyargs]
            if "job_id" in args and not node.name.startswith("_"):
                names |= _dispatch_targets(node)
    return names


def test_every_job_id_carrying_tool_is_deliberately_classified():
    classified = _base.SILENCE_CLEARING_TOOLS | _base.NON_SILENCE_CLEARING_TOOLS
    discovered = _job_id_dispatch_names()

    unclassified = discovered - classified
    assert not unclassified, (
        "these dispatch names are reachable from an MCP tool taking job_id but are in "
        f"neither BE-9303 set, so they would inherit a default: {sorted(unclassified)}. "
        "Add each to SILENCE_CLEARING_TOOLS (the caller's own proof of life) or "
        "NON_SILENCE_CLEARING_TOOLS (a bystander inspecting/recovering the job)."
    )

    stale = classified - discovered
    assert not stale, (
        f"classified but never reaches _call_tool as method_name: {sorted(stale)}. "
        "Check whether the tool dispatches under a different internal target name."
    )

    overlap = _base.SILENCE_CLEARING_TOOLS & _base.NON_SILENCE_CLEARING_TOOLS
    assert not overlap, f"a tool cannot be both: {sorted(overlap)}"


def test_the_documented_disarm_is_on_the_excluded_side():
    assert "get_context" in _base.NON_SILENCE_CLEARING_TOOLS
    assert "get_context" not in _base.SILENCE_CLEARING_TOOLS
    assert "report_progress" in _base.SILENCE_CLEARING_TOOLS


def test_base_gates_on_the_owning_modules_set_by_identity():
    assert _base.SILENCE_CLEARING_TOOLS is _silence_scope.SILENCE_CLEARING_TOOLS
    assert _base.NON_SILENCE_CLEARING_TOOLS is _silence_scope.NON_SILENCE_CLEARING_TOOLS
