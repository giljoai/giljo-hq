# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""TSK-9318 — the three silence-clearing names that were classified, not measured.

BE-9303 scoped ``auto_clear_silent`` by WHOSE JOB the ``job_id`` is. Twelve dispatch
names reach that gate. Nine were classified against observed behaviour; three were
classified from design reading alone — ``set_agent_status``,
``get_staging_instructions`` and ``request_approval``. Being unmeasured, none of the
three had a test either, so the BE-9303 suite would stay green if one were quietly
moved to the other side. This file supplies the measurement and the pins.

WHAT WAS OBSERVED (530 local session transcripts; a job is OWNED by the session that
heartbeats it via ``report_progress``, and a job a session got back from ``spawn_job``
is provably another agent's):

* ``set_agent_status`` — 47 calls, 47 on the caller's own job, zero cross-agent uses.
  The classification is confirmed by observation.
* ``get_staging_instructions`` — 20 calls: 12 on the caller's own job, 7 on jobs never
  heartbeat anywhere, and 1 AMBIGUOUS (session 46cc210d called it on job c79c8327,
  which a different session first heartbeat ten hours later). That single instance
  reads equally well as a staging orchestrator acting on a job it does not own OR as
  one agent carrying a second job across two sessions, and the transcripts cannot
  separate the two. It is recorded here as unresolved rather than counted as a
  counter-example, because it does not establish one.
* ``request_approval`` — ZERO calls in 530 sessions. Its classification cannot be
  established by observation at all; what CAN be established is that it does reach the
  hook, since its wrapper forwards ``job_id`` into ``_call_tool``. That is pinned below
  so the name is not merely decorative the way ``resolve_reactivation`` would have been.

NOTHING IS RECLASSIFIED, and the evidence for leaving it alone is the load-bearing
half: session 625057eb's only job-carrying calls on job 5d57e77c are
``get_staging_instructions`` and ``set_agent_status`` — no ``report_progress`` at all.
Moving either name to the non-clearing side would mark that live agent silent and
leave it silent, which is the over-fire BE-9303 DoD item 4 forbids and the reason a
write-only allowlist was already refused. :func:`test_an_agent_whose_only_signal_is_
these_tools_is_not_left_silent` encodes that refusal as a test instead of prose.

THE RESIDUAL, pinned rather than assumed: this boundary has no caller identity, so
the hook clears whatever ``job_id`` it is handed. "Whose job" is a usage convention
these names satisfy in practice, not an invariant the code can enforce. That is
exactly what TSK-9318 was raised to stop taking on faith, so it is characterized
below rather than left to be rediscovered.

Drives ``_call_tool`` itself — the post-hook dispatch is the failing layer. Pure/no-DB,
no module-level mutable state, parallel-safe under xdist.

Edition Scope: Both.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any

import pytest

from api.endpoints.mcp_tools import _base, _silence_scope


# The three names TSK-9318 says were classified from intent rather than proof.
CLASSIFIED_FROM_INTENT = ("set_agent_status", "get_staging_instructions", "request_approval")


class _Recorder:
    def __init__(self) -> None:
        self.silence_cleared_for: list[str] = []
        self.heartbeats_for: list[str] = []


@pytest.fixture
def boundary(monkeypatch):
    """``_call_tool`` with both post-hooks spied and the debounce forced open.

    Mirrors the BE-9303 fixture deliberately: that file is the characterization set
    for this mechanism and stays unmodified, so this one carries its own double
    rather than reaching into it.
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
    monkeypatch.setattr(_base, "_resolve_tenant", lambda ctx: "tk-tsk9318")
    monkeypatch.setattr(_base, "_set_tenant_context", lambda tenant_key: None)
    _accessor = object()
    monkeypatch.setattr(_base, "_get_tool_accessor", lambda: _accessor)
    monkeypatch.setattr(_base, "_resolve_tool_func", lambda accessor, method_name: _fake_tool)
    # Force the debounce open, or this file would measure the debounce rather than
    # the tool scope it claims to measure.
    monkeypatch.setattr(_base, "should_run", lambda *args, **kwargs: True)
    monkeypatch.setattr(silence_module, "auto_clear_silent", _fake_auto_clear_silent)
    monkeypatch.setattr(heartbeat_module, "touch_heartbeat", _fake_touch_heartbeat)

    return recorder


async def _call(tool_name: str, job_id: str = "job-tsk9318") -> Any:
    return await _base._call_tool(object(), tool_name, {"job_id": job_id})


# ---------------------------------------------------------------------------
# DoD 2 — where behaviour matches the classification, pin it.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("tool_name", CLASSIFIED_FROM_INTENT)
async def test_the_three_unmeasured_names_do_clear_silence(boundary, tool_name):
    """Each of the three reaches ``auto_clear_silent`` for the job it carries.

    Before this file none of the three had any test, so the classification was an
    assumption in both directions: nothing proved they cleared silence, and nothing
    would have gone red if a future edit moved one to the excluded side. The
    consequence of that silent move is concrete — an agent whose liveness signal is
    one of these names would be marked silent and stay silent.
    """
    await _call(tool_name)
    assert boundary.silence_cleared_for == ["job-tsk9318"], (
        f"{tool_name} is classified as the caller's own liveness signal and must reach "
        f"auto_clear_silent; got {boundary.silence_cleared_for!r}"
    )


async def test_request_approval_reaches_the_hook_at_all(boundary):
    """``request_approval`` has ZERO observed calls, so this is the only property
    about it that can be established rather than assumed.

    It matters because a classified name that never reaches ``_call_tool`` under that
    dispatch string is decoration — the trap ``_silence_scope`` documents for
    ``resolve_reactivation``, which arrives as ``reactivate_job`` /
    ``dismiss_reactivation`` and would have been classified under a name that never
    matches. Its wrapper forwards ``job_id`` into the dispatch kwargs, so the hook is
    genuinely live for it, and this pins that it stays so.
    """
    await _call("request_approval")
    assert boundary.silence_cleared_for == ["job-tsk9318"], (
        "request_approval forwards job_id into _call_tool, so its entry in "
        "SILENCE_CLEARING_TOOLS must be live rather than decorative"
    )
    assert boundary.heartbeats_for == ["job-tsk9318"], "the heartbeat post-hook must run for it too"


def test_every_classified_clearing_name_is_pinned_by_a_test():
    """Completeness: no name may sit in ``SILENCE_CLEARING_TOOLS`` unexercised.

    The whole defect TSK-9318 names is a classification carried by nothing but a
    comment. This fails when a new clearing name is added without a pin here, so the
    unmeasured-classification state cannot silently return.
    """
    pinned = set(CLASSIFIED_FROM_INTENT) | {"report_progress", "get_job_mission"}
    unpinned = set(_silence_scope.SILENCE_CLEARING_TOOLS) - pinned
    assert not unpinned, (
        f"these silence-clearing names have no boundary test pinning them: {sorted(unpinned)}. "
        "Add one here (or to the BE-9303 museum set) rather than leaving the classification "
        "resting on a comment — that is the exact defect this file exists to close."
    )


# ---------------------------------------------------------------------------
# The load-bearing half — why NOTHING was reclassified.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("tool_name", ["get_staging_instructions", "set_agent_status"])
async def test_an_agent_whose_only_signal_is_these_tools_is_not_left_silent(boundary, tool_name):
    """Observed, not hypothetical: session 625057eb's only job-carrying calls on job
    5d57e77c were ``get_staging_instructions`` (x4) and ``set_agent_status``, with no
    ``report_progress`` anywhere.

    So for a real agent these names WERE the only liveness signal. Moving either to
    the non-clearing side — the write-only-allowlist shape already refused with
    evidence — would leave that agent silent while it was working, reintroducing the
    over-fire the original project existed to prevent. This test is that refusal made
    enforceable.
    """
    await _call(tool_name, job_id="job-5d57e77c")
    assert boundary.silence_cleared_for == ["job-5d57e77c"], (
        f"{tool_name} must keep clearing silence: a live agent was observed whose only "
        "job-carrying calls were these, and dropping them marks it silent and leaves it there"
    )


async def test_the_narrowing_still_holds_for_the_documented_disarm(boundary):
    """Two-sided anchor: pinning the three positives must not have widened the gate.

    ``get_context`` is the read BE-9303 was raised for. If a future edit relaxed the
    scope check itself rather than the roster, every test above would still pass while
    the original defect returned — so the excluded side is asserted here too.
    """
    await _call("get_context")
    assert boundary.silence_cleared_for == [], (
        "the orchestrator's force-recovery read must still never clear 'silent' — "
        "pinning the clearing names must not widen the gate"
    )


# ---------------------------------------------------------------------------
# THE RESIDUAL — characterized, so it stops being an assumption.
# ---------------------------------------------------------------------------


async def test_a_clearing_tool_cannot_tell_whose_job_the_job_id_is(boundary):
    """The honest limit of the BE-9303 criterion, pinned as behaviour.

    "Whose job is the job_id" is the criterion, but this boundary carries no caller
    job identity — only ``tenant_key`` and ``user_id``. So the hook clears whatever
    ``job_id`` it is handed, and an orchestrator calling ``set_agent_status`` on a
    WORKER's job_id would clear that worker's silent flag exactly as the worker's own
    call would.

    Observation says this does not happen in practice: 47 of 47 ``set_agent_status``
    calls across 530 sessions were on the caller's own job. So the name stays on the
    clearing side. But "does not happen" is a usage convention, not an invariant, and
    closing it would need a caller-identity signal that does not exist at this layer —
    a new mechanism, which is not this item's to introduce.

    This test states the residual in the only terms that cannot rot: the observed
    behaviour. If a caller-identity signal is ever added, this test is the one that
    must change, and its failure is the prompt to revisit the roster.
    """
    await _call("set_agent_status", job_id="job-belonging-to-another-agent")
    assert boundary.silence_cleared_for == ["job-belonging-to-another-agent"], (
        "the hook has no caller identity and clears whatever job_id it is handed; this "
        "is the measured residual of the whose-job criterion, not a defect introduced here"
    )
