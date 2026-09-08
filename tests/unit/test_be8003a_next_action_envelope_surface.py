# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
BE-8003a roster-lock — next_action envelope coverage over the mcp:agent surface.

Modeled on ``test_be6042d_mcp_tool_registry_surface.py``: a hand-authored roster
dict is compared against the LIVE ``TOOL_SCOPES`` mcp:agent set for exact
set-equality (drift lock — a new mcp:agent tool added later without an entry
here fails the test, forcing an explicit coverage decision rather than a silent
gap). This is a STATIC inventory lock, not a runtime functional test: whether
each MIGRATED tool's response actually carries next_action at runtime is
verified by the tool-specific suites (test_inf6049b_stage_implement_tools.py,
test_be6221a_start_chain_run.py, test_complete_job_mcp_boundary.py,
test_be6199_chain_prose_hygiene.py, test_be6198_cold_start_hardening.py).

Every entry is either "MIGRATED" (this tool's response carries the canonical
next_action envelope as of BE-8003a) or an ALLOWLIST justification string (why
it does not, one line). Per WO-8003a orchestrator delta #2, this PR's migrated
set is scoped to the strategy doc's evidence index (~4 files / ~8 sites) plus
get_workflow_status (DoD item 3) — NOT a forced next_action on all 26 mcp:agent
tools, which would exceed this PR's complexity budget. Every non-migrated entry
below is a conscious, documented deferral, not an oversight.
"""

from __future__ import annotations

from api.endpoints.mcp_tools._base import SCOPE_AGENT, TOOL_SCOPES


# tool_name -> "MIGRATED" | one-line allowlist justification.
NEXT_ACTION_COVERAGE: dict[str, str] = {
    # ------------------------------------------------------------------
    # MIGRATED in BE-8003a (evidence-index sites + DoD item 3).
    # ------------------------------------------------------------------
    "stage_project": "MIGRATED",
    # BE-9554 rename; same accessor, same migrated envelope.
    "get_implementation_prompt": "MIGRATED",
    # BE-9554: start_chain_run's start/terminate actions split into two named verbs.
    # Both route to the SAME accessor, so they inherit its migrated next_action envelope.
    "link_projects": "MIGRATED",
    "unlink_projects": "MIGRATED",
    "complete_job": "MIGRATED",
    "get_workflow_status": "MIGRATED",
    # ------------------------------------------------------------------
    # Allowlisted: response IS the next-step payload (a large protocol/prompt
    # blob) -- a next_action field would duplicate it, not add information.
    # ------------------------------------------------------------------
    "get_staging_instructions": "response body IS the staging protocol/prompt -- next_action would duplicate it",
    "get_job_mission": "response body IS the mission/implementation prompt -- next_action would duplicate it",
    # ------------------------------------------------------------------
    # Allowlisted: pure list/read, genuinely open-ended (0..N items, no single
    # forced next step) -- matches the documented null-envelope case.
    # ------------------------------------------------------------------
    "get_agent_result": "pure read of a stored result -- no forced next step",
    # ------------------------------------------------------------------
    # Allowlisted: plain writes/mutations with no natural single next-step to
    # advertise (fire-and-forget or metadata-only).
    # ------------------------------------------------------------------
    "update_project_mission": "metadata write, no natural next-step to advertise",
    "update_job_mission": "metadata write, no natural next-step to advertise",
    # BE-9012d: send_message / receive_messages hard-removed (bus retired).
    "create_thread": "fire-and-forget write, no natural next-step to advertise",
    "update_thread": "fire-and-forget write (retag/rename/status), no natural next-step to advertise",
    "join_thread": "fire-and-forget write, no natural next-step to advertise",
    "post_to_thread": "fire-and-forget write, no natural next-step to advertise",
    "set_next_actor": "fire-and-forget write, no natural next-step to advertise",
    "report_progress": "fire-and-forget write (heartbeat/todo update), no natural next-step to advertise",
    "finalize_job": "terminal write, no forced next step",
    "spawn_job": "returns SpawnResult identity; not in the BE-8003a evidence index -- candidate for a follow-up",
    "write_project_closeout": "terminal write; not in the BE-8003a evidence index -- candidate for a follow-up",
    # ------------------------------------------------------------------
    # Allowlisted: NOT in the evidence index this PR migrates. Carries an
    # analogous but differently-named field ("instruction" / "guidance") that
    # is a legitimate BE-8003a follow-up, not touched here to stay within this
    # PR's evidence-index scope (WO-8003a orchestrator delta #2/#3).
    # ------------------------------------------------------------------
    "launch_implementation": "not in the BE-8003a evidence index -- candidate follow-up (natural next: get_implementation_prompt)",
    # BE-9012b (BE-6225e): reactivate_job + dismiss_reactivation merged into one tool.
    # BE-9554 rename; same accessors, so the same analogous-instruction situation.
    "resume_or_dismiss_job": "carries Reactivation/DismissResult.instruction (analogous, differently-named) -- BE-8003a follow-up candidate",
    "set_agent_status": (
        "carries ErrorReportResult.guidance (analogous, differently-named); NOT in the evidence index "
        "-- BE-8003a follow-up candidate (WO-8003a KICKOFF)"
    ),
    "write_memory_entry": (
        "Tier-2 structured rejections (GIT_COMMITS_REQUIRED, CLOSEOUT_BLOCKED, ORCHESTRATOR_ONLY_ENTRY_TYPE) "
        "already carry actionable codes; not in the evidence index -- BE-8003a follow-up candidate"
    ),
    "request_approval": "sets awaiting_user (human gate, no MCP tool call applies) -- BE-8003a follow-up candidate",
    # BE-9499d: terminal write on the approval (decided is a terminal state for
    # that row) -- the agent's own next step is whatever it was already doing,
    # not something this tool can name.
    "decide_approval": "terminal write, no forced next step",
}


def test_next_action_coverage_roster_matches_live_agent_scope_set():
    """STRICT set-equality: every live mcp:agent tool has an explicit coverage decision.

    A new mcp:agent tool added later without a NEXT_ACTION_COVERAGE entry fails
    this test -- the author must add either "MIGRATED" or a one-line allowlist
    justification, mirroring test_be6042d's registry-drift lock.
    """
    live_agent_tools = {name for name, scope in TOOL_SCOPES.items() if scope == SCOPE_AGENT}
    roster_tools = set(NEXT_ACTION_COVERAGE)
    assert live_agent_tools == roster_tools, (
        f"mcp:agent next_action coverage drift. Missing decision for: "
        f"{sorted(live_agent_tools - roster_tools)}; stale roster entries for tools no longer "
        f"mcp:agent: {sorted(roster_tools - live_agent_tools)}"
    )


def test_every_coverage_entry_is_migrated_or_has_a_justification():
    """Every roster value is either the literal 'MIGRATED' marker or a non-empty,
    one-line justification string -- no blank/placeholder allowlist entries."""
    for tool_name, decision in NEXT_ACTION_COVERAGE.items():
        assert decision == "MIGRATED" or (isinstance(decision, str) and len(decision) >= 10), (
            f"{tool_name}: coverage decision must be 'MIGRATED' or a real justification, got {decision!r}"
        )


def test_migrated_count_matches_this_pr_scope():
    """Pins the MIGRATED count so a future accidental add/removal is visible in review."""
    migrated = [name for name, decision in NEXT_ACTION_COVERAGE.items() if decision == "MIGRATED"]
    assert sorted(migrated) == [
        "complete_job",
        # BE-9554 rename: same accessor, same migrated envelope, two names for one release.
        "get_implementation_prompt",
        "get_workflow_status",
        # BE-9554: link_projects/unlink_projects are start_chain_run's two verbs given
        # their own names. They route to the SAME accessor, so they carry the SAME
        # migrated envelope -- three entries for what is still one migrated code path.
        "link_projects",
        "stage_project",
        "unlink_projects",
    ]
