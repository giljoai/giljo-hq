# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-9303 — the stalled-agent recovery hint must survive the orchestrator's own read.

The defect (carried forward from BE-9292b / 360 #913 with mechanical proof): the
``close_job`` recovery hint fires only while the execution reads literally
``'silent'``, and ``_base._call_tool``'s ``auto_clear_silent`` post-hook flipped that
flag on ANY successful MCP call carrying ``job_id`` — no caller identity, no tool
allowlist. So ``get_context(categories=['todos'], job_id=...)``, the read documented
FOR force-recovery and therefore the single most likely call from someone looking at
a stranded job, disarmed the hint before it could fire.

``tests/services/test_be9292b_silence_clear_disarms_hint.py`` proved no hint-layer
predicate can fix this: ``clear_silent_to_working`` also stamps
``last_progress_at = now()``, so after the disarming read the row is neither
``'silent'`` nor stale, and the bystander read leaves state byte-identical to a
genuine revival. The fix therefore has to live at the mutation layer, which is
load-bearing code — hence the tests below.

MUSEUM RULE. The incident ``auto_clear_silent`` exists for is on the record twice:
``f359afe09`` (0491 Phase 3) added it so an agent marked silent by the background
detector returns to 'working' on its next call, and ``dd306cb36`` is the REGRESSION
— "Re-wire auto_clear_silent() in _call_tool() after 0846 SDK migration dropped it"
— i.e. it has already been lost once, and a live-but-slow agent was left reading
'silent' forever. :func:`test_museum_a_live_agents_own_progress_report_clears_silence`
reproduces exactly that and is the guard this project must not break: it goes RED
when the hook is unreachable, which is the incident.

The fix is a scope on WHICH tools clear silence, not a removal:
  * a call that is the agent's OWN liveness signal still clears it;
  * a bystander INSPECTING or RECOVERING the job does not.

These drive ``_call_tool`` itself — the post-hook dispatch is the failing layer, per
CLAUDE.md's failing-layer mandate (the BE-5042 class: correct service-layer
behaviour, broken MCP-boundary wrapper). Pure/no-DB, no module-level mutable state,
parallel-safe under xdist.

Edition Scope: Both.
"""

from __future__ import annotations

import ast
import pathlib
from contextlib import asynccontextmanager
from typing import Any

import pytest

from api.endpoints.mcp_tools import _base, _silence_scope


# No module-level asyncio mark: the suite runs --asyncio-mode=auto, and marking a
# module that also holds sync guard tests warns on every one of them.
REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
MCP_TOOLS_DIR = REPO_ROOT / "api" / "endpoints" / "mcp_tools"


class _Recorder:
    """Records whether each post-hook ran, and for which job."""

    def __init__(self) -> None:
        self.silence_cleared_for: list[str] = []
        self.heartbeats_for: list[str] = []


@pytest.fixture
def boundary(monkeypatch):
    """Drive ``_call_tool`` with both post-hooks spied and the debounce forced ON.

    Everything except the post-hook block is stubbed to the smallest thing that
    lets dispatch succeed — the post-hooks only run on a SUCCESSFUL call, which is
    the condition under test.
    """
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
    monkeypatch.setattr(_base, "_resolve_tenant", lambda ctx: "tk-be9303")
    monkeypatch.setattr(_base, "_set_tenant_context", lambda tenant_key: None)
    _accessor = object()
    monkeypatch.setattr(_base, "_get_tool_accessor", lambda: _accessor)
    monkeypatch.setattr(_base, "_resolve_tool_func", lambda accessor, method_name: _fake_tool)
    # Force the debounce OPEN so the post-hook block always runs — otherwise this
    # test would silently measure the debounce instead of the tool scope.
    monkeypatch.setattr(_base, "should_run", lambda *args, **kwargs: True)
    monkeypatch.setattr(silence_module, "auto_clear_silent", _fake_auto_clear_silent)
    monkeypatch.setattr(heartbeat_module, "touch_heartbeat", _fake_touch_heartbeat)

    return recorder


async def _call(tool_name: str, job_id: str = "job-be9303") -> Any:
    return await _base._call_tool(object(), tool_name, {"job_id": job_id})


# ---------------------------------------------------------------------------
# MUSEUM RULE — the incident auto_clear_silent exists for, reproduced.
# ---------------------------------------------------------------------------


async def test_museum_a_live_agents_own_progress_report_clears_silence(boundary):
    """THE INCIDENT (f359afe09, regressed and re-fixed by dd306cb36).

    A live-but-slow agent the detector marked 'silent' calls ``report_progress``.
    That call is the agent's own liveness signal and MUST still reach
    ``auto_clear_silent``, or the agent reads 'silent' forever while actively
    working — which is precisely what the 0846 SDK migration caused when it
    dropped this hook.

    This test goes RED whenever the hook becomes unreachable for the agent's own
    calls. It is the reason this project narrows the hook instead of removing it.
    """
    await _call("report_progress")
    assert boundary.silence_cleared_for == ["job-be9303"], (
        "report_progress is the agent's own proof of life — it must still clear "
        "'silent'. Losing this is the dd306cb36 incident: a live agent stuck "
        "reading 'silent' because the post-hook never ran."
    )


async def test_museum_b_agent_self_calls_that_stamp_liveness_still_clear_silence(boundary):
    """The narrowing must not be write-only.

    ``get_job_mission`` is a READ, but it is the agent's own boot/refresh call and
    ``mission_service`` already stamps ``last_progress_at`` on it. A strictly
    write-only allowlist would drop it, and an agent whose only job_id-carrying
    calls are mission refreshes would be marked silent and STAY silent — turning
    a live agent into a hint target, the exact over-fire DoD item 4 forbids.
    """
    await _call("get_job_mission")
    assert boundary.silence_cleared_for == ["job-be9303"]


# ---------------------------------------------------------------------------
# THE DEFECT — RED before the fix.
# ---------------------------------------------------------------------------


async def test_orchestrator_inspection_read_does_not_disarm_the_hint(boundary):
    """RED before fix: ``get_context(job_id=...)`` is the force-recovery TODO read.

    It is a bystander looking AT a stranded job, not the job's agent proving it is
    alive, so it must not mutate the agent's status. This is the whole defect: the
    orchestrator's own diagnostic read disarmed the hint it was about to need.

    Note the hook only ever fires when ``job_id`` is present, and ``get_context``
    takes ``job_id`` ONLY for the ``todos`` force-recovery category — so excluding
    it costs an agent's ordinary ``get_context`` calls nothing; they never carried
    a job_id and never reached this hook.
    """
    await _call("get_context")
    assert boundary.silence_cleared_for == [], (
        "an orchestrator's read ABOUT a stalled job must not clear that job's "
        "'silent' flag — clearing it disarms the close_job recovery hint before "
        "the orchestrator can reach it."
    )


@pytest.mark.parametrize(
    "tool_name",
    # NB these are dispatch names, not tool names — resolve_reactivation reaches
    # _call_tool as reactivate_job / dismiss_reactivation, so asserting on its own
    # name would have tested nothing.
    ["get_context", "get_agent_result", "close_job", "reactivate_job", "dismiss_reactivation", "complete_job"],
)
async def test_bystander_tools_never_clear_silence(boundary, tool_name):
    """Every tool an orchestrator uses to inspect or accept a stalled job.

    ``close_job`` matters most after ``get_context``: it is the call that RAISES
    the hint. If it cleared silence first, the hint could never fire on a retry.
    """
    await _call(tool_name)
    assert boundary.silence_cleared_for == [], f"{tool_name} is a bystander/recovery tool and must not clear 'silent'"


async def test_the_hint_survives_the_inspection_read_end_to_end(boundary):
    """Closes the loop: the read no longer fires the mutation, so the flag is still
    ``'silent'`` when ``close_job`` asks — and the recovery hint fires.

    BE-9292b pinned that the hint keys on the literal flag; the tests above pin
    that a bystander read no longer clears it. This asserts the composition, so
    neither half can be relaxed without a failure here.
    """
    from giljo_mcp.services._error_helpers import _wrong_state_next_action

    # The orchestrator inspects the stranded job — the call that used to disarm.
    await _call("get_context")
    assert boundary.silence_cleared_for == []

    # The execution therefore still reads 'silent' when close_job refuses.
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


# ---------------------------------------------------------------------------
# The narrowing must not take the heartbeat with it.
# ---------------------------------------------------------------------------


async def test_heartbeat_still_runs_for_a_tool_that_does_not_clear_silence(boundary):
    """``touch_heartbeat`` is unrelated to silence and must keep running for EVERY
    job-carrying call. Gating the whole post-hook block instead of just the
    silence hook would silently stop the server-side heartbeat — a regression that
    no silence test would catch.
    """
    await _call("get_context")
    assert boundary.heartbeats_for == ["job-be9303"], (
        "the BE-9303 scope applies to auto_clear_silent ONLY; last_activity_at "
        "must still be stamped on every authenticated job-carrying call."
    )


# ---------------------------------------------------------------------------
# Anti-drift: a new job_id tool must not default into clearing silence.
# ---------------------------------------------------------------------------


def _dispatch_targets(func: ast.AST) -> set[str]:
    """The ``method_name`` values this tool actually hands ``_call_tool``.

    Not the tool's own name: ``resolve_reactivation`` branches on ``action`` and
    dispatches to ``reactivate_job`` / ``dismiss_reactivation``, so those are what
    ``method_name`` holds inside the post-hook. Classifying the tool's own name
    there would never match anything — a negative that cannot fire.

    Resolves a literal second argument directly, and a variable second argument by
    collecting every string constant assigned to that name in the function
    (covers the ``target = "a" if cond else "b"`` form).
    """
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
    """String constants a value expression can EVALUATE to.

    For a conditional, only the branches — never the condition. ``target =
    "reactivate_job" if action == "resume" else "dismiss_reactivation"`` can only
    evaluate to the two target names; ``"resume"`` is the test and is not a
    dispatch name.
    """
    if isinstance(node, ast.Constant):
        return {node.value} if isinstance(node.value, str) else set()
    if isinstance(node, ast.IfExp):
        return _value_strings(node.body) | _value_strings(node.orelse)
    return set()


def _job_id_dispatch_names() -> set[str]:
    """Every ``method_name`` reachable from an agent-facing tool that takes job_id."""
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
    """No silent defaults.

    The defect existed because the hook applied to whatever happened to carry a
    ``job_id``. Every such tool must now be an explicit member of exactly one set,
    so adding a new job_id-carrying tool forces the author to decide whether it is
    the agent's own liveness signal — instead of inheriting 'yes' by accident.
    """
    classified = _base.SILENCE_CLEARING_TOOLS | _base.NON_SILENCE_CLEARING_TOOLS
    discovered = _job_id_dispatch_names()

    unclassified = discovered - classified
    assert not unclassified, (
        "these dispatch names are reachable from an MCP tool taking job_id but are in "
        f"neither BE-9303 set, so they would inherit a default: {sorted(unclassified)}. "
        "Add each to SILENCE_CLEARING_TOOLS (the caller's own proof of life) or "
        "NON_SILENCE_CLEARING_TOOLS (a bystander inspecting/recovering the job)."
    )

    # No decoration: a classified name that never reaches _call_tool is a rule the
    # gate can never apply. This is how "resolve_reactivation" was caught — the tool
    # dispatches under two OTHER names and its own never appears.
    stale = classified - discovered
    assert not stale, (
        f"classified but never reaches _call_tool as method_name: {sorted(stale)}. "
        "Check whether the tool dispatches under a different internal target name."
    )

    overlap = _base.SILENCE_CLEARING_TOOLS & _base.NON_SILENCE_CLEARING_TOOLS
    assert not overlap, f"a tool cannot be both: {sorted(overlap)}"


def test_the_documented_disarm_is_on_the_excluded_side():
    """Pins the specific call named in the project as the disarm."""
    assert "get_context" in _base.NON_SILENCE_CLEARING_TOOLS
    assert "get_context" not in _base.SILENCE_CLEARING_TOOLS
    assert "report_progress" in _base.SILENCE_CLEARING_TOOLS


def test_base_gates_on_the_owning_modules_set_by_identity():
    """Composition pinned BY IDENTITY, not by containment.

    ``_base`` must gate on the very object ``_silence_scope`` defines. An
    equal-looking set copied into ``_base`` would satisfy every containment
    assertion above while drifting from the documented classification on the next
    edit — the exact failure mode BE-9304 was cleaning up next door.
    """
    assert _base.SILENCE_CLEARING_TOOLS is _silence_scope.SILENCE_CLEARING_TOOLS
    assert _base.NON_SILENCE_CLEARING_TOOLS is _silence_scope.NON_SILENCE_CLEARING_TOOLS
