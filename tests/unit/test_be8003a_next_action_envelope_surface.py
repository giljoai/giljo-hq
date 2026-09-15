# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from api.endpoints.mcp_tools._base import SCOPE_AGENT, TOOL_SCOPES


NEXT_ACTION_COVERAGE: dict[str, str] = {
    "stage_project": "MIGRATED",
    "get_implementation_prompt": "MIGRATED",
    "link_projects": "MIGRATED",
    "unlink_projects": "MIGRATED",
    "complete_job": "MIGRATED",
    "get_workflow_status": "MIGRATED",
    "get_staging_instructions": "response body IS the staging protocol/prompt -- next_action would duplicate it",
    "get_job_mission": "response body IS the mission/implementation prompt -- next_action would duplicate it",
    "get_agent_result": "pure read of a stored result -- no forced next step",
    "update_project_mission": "metadata write, no natural next-step to advertise",
    "update_job_mission": "metadata write, no natural next-step to advertise",
    "create_thread": "fire-and-forget write, no natural next-step to advertise",
    "update_thread": "fire-and-forget write (retag/rename/status), no natural next-step to advertise",
    "join_thread": "fire-and-forget write, no natural next-step to advertise",
    "post_to_thread": "fire-and-forget write, no natural next-step to advertise",
    "set_next_actor": "fire-and-forget write, no natural next-step to advertise",
    "report_progress": "fire-and-forget write (heartbeat/todo update), no natural next-step to advertise",
    "finalize_job": "terminal write, no forced next step",
    "spawn_job": "returns SpawnResult identity; not in the BE-8003a evidence index -- candidate for a follow-up",
    "write_project_closeout": "terminal write; not in the BE-8003a evidence index -- candidate for a follow-up",
    "launch_implementation": "not in the BE-8003a evidence index -- candidate follow-up (natural next: get_implementation_prompt)",
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
    "decide_approval": "terminal write, no forced next step",
}


def test_next_action_coverage_roster_matches_live_agent_scope_set():
    live_agent_tools = {name for name, scope in TOOL_SCOPES.items() if scope == SCOPE_AGENT}
    roster_tools = set(NEXT_ACTION_COVERAGE)
    assert live_agent_tools == roster_tools, (
        f"mcp:agent next_action coverage drift. Missing decision for: "
        f"{sorted(live_agent_tools - roster_tools)}; stale roster entries for tools no longer "
        f"mcp:agent: {sorted(roster_tools - live_agent_tools)}"
    )


def test_every_coverage_entry_is_migrated_or_has_a_justification():
    for tool_name, decision in NEXT_ACTION_COVERAGE.items():
        assert decision == "MIGRATED" or (isinstance(decision, str) and len(decision) >= 10), (
            f"{tool_name}: coverage decision must be 'MIGRATED' or a real justification, got {decision!r}"
        )


def test_migrated_count_matches_this_pr_scope():
    migrated = [name for name, decision in NEXT_ACTION_COVERAGE.items() if decision == "MIGRATED"]
    assert sorted(migrated) == [
        "complete_job",
        "get_implementation_prompt",
        "get_workflow_status",
        "link_projects",
        "stage_project",
        "unlink_projects",
    ]
