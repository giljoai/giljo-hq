# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from typing import Any

from giljo_mcp.services.next_action import project_next_action_for


_ABANDON_HINT = "Project can also be abandoned entirely — call update_project(project_id, status='cancelled')."

STAGING_STUCK_HINTS: dict[str, tuple[str, ...]] = {
    "staged": (
        "Staged but no agent has been launched yet — call unstage_project(project_id) to revert to ready.",
        _ABANDON_HINT,
    ),
    "staging": (
        "Staging is underway but no agents exist yet — call "
        "unstage_project(project_id) to reset staging and mint a "
        "fresh orchestrator.",
        _ABANDON_HINT,
    ),
}


def compute_stuck_conditions(
    *,
    execution_mode: Any,
    is_terminal: bool,
    counts: dict[str, int],
    all_finished: bool,
    staging_status: str | None,
    any_awaiting_user: bool,
) -> tuple[list[str], list[str]]:
    stuck: list[str] = []
    suggested: list[str] = []
    if not execution_mode and not is_terminal:
        stuck.append("execution_mode_not_selected")
        suggested.append("Pick an execution mode in the dashboard, then stage the project.")
    if counts["total"] == 0 and not is_terminal:
        stuck.append("no_agents_spawned")
        suggested.extend(STAGING_STUCK_HINTS.get(staging_status, ()))
    if all_finished and not is_terminal:
        stuck.append("all_agents_finished_project_still_open")
        suggested.append("All agents are finished — run write_project_closeout to finalize, or review blockers.")
    if counts["blocked"] > 0:
        stuck.append("blocked_agents")
    if counts.get("silent", 0) > 0:
        stuck.append("silent_agents")
        suggested.append("Silent agents detected — message them or set_agent_status, then re-check.")
    if any_awaiting_user:
        stuck.append("awaiting_user_approval")
        suggested.append("Resolve pending user approvals (see blockers) via the dashboard.")
    return stuck, suggested


def lifecycle_next_action_field(project: Any, findings: Any) -> dict[str, Any]:
    hint = project_next_action_for(project, awaiting_user=any(f.awaiting_user for f in findings))
    return {"next_action": hint} if hint is not None else {}
