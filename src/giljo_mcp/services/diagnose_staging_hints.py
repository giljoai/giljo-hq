# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from typing import Any

from giljo_mcp.domain.project_status import ProjectStatus


STAGING_STUCK_HINTS: dict[str, tuple[str, ...]] = {
    "staged": (
        "Staged but no agent has been launched yet — call "
        "stage_project(project_id, action='unstage') to revert to ready.",
    ),
    "staging": (
        "Staging is underway but no agents exist yet — call "
        "stage_project(project_id, action='restage') to reset staging and mint a "
        "fresh orchestrator.",
    ),
}

_CANCEL_STAGING_HINT = (
    "Project can also be abandoned entirely — call stage_project(project_id, action='cancel_staging')."
)


def _cancel_staging_hint(staging_status: str | None, status: str | None) -> tuple[str, ...]:
    if staging_status == "staging" and status == ProjectStatus.INACTIVE:
        return (_CANCEL_STAGING_HINT,)
    return ()


def compute_stuck_conditions(
    *,
    execution_mode: Any,
    is_terminal: bool,
    counts: dict[str, int],
    all_finished: bool,
    staging_status: str | None,
    any_awaiting_user: bool,
    status: str | None = None,
) -> tuple[list[str], list[str]]:
    stuck: list[str] = []
    suggested: list[str] = []
    if not execution_mode and not is_terminal:
        stuck.append("execution_mode_not_selected")
        suggested.append("Pick an execution mode in the dashboard, then stage the project.")
    if counts["total"] == 0 and not is_terminal:
        stuck.append("no_agents_spawned")
        suggested.extend(STAGING_STUCK_HINTS.get(staging_status, ()))
        suggested.extend(_cancel_staging_hint(staging_status, status))
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
