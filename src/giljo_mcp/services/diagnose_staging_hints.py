# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-9499b: ``diagnose_project_state``'s stuck-conditions/suggested-actions
computation, including the staging-stuck recovery hint.

Split out of ``project_closeout_service.py`` (rather than inlined there) to
keep that file's Guardrail-1 800-line cap intact. Before the staging reverse
gear (``stage_project(action=...)``), a project stuck at ``staging_status``
'staged'/'staging' with zero agents got the bare ``no_agents_spawned`` stuck
condition and nothing an MCP agent could DO about it -- this names the new
recovery paths.
"""

from __future__ import annotations

from typing import Any

from giljo_mcp.domain.project_status import ProjectStatus


# Keyed by ``project.staging_status``. Empty tuple (via .get(..., ())) for
# every other value, including None -- a no-agents-spawned project is not
# "stuck in staging" unless staging_status says so.
#
# BE-9512: neither hint mentions ``cancel_staging`` inline anymore.
# ``ProjectStagingService.cancel_staging`` requires staging_status == 'staging'
# AND status == INACTIVE (project_staging_service.py:682) -- from 'staged' it
# is UNREACHABLE (staging_status alone rules it out), and from 'staging' it
# depends on ``status``, which this dict alone can't see. See
# ``_cancel_staging_hint`` below, which appends the suggestion only when it
# can actually succeed.
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
    """Only suggest ``cancel_staging`` when it can actually succeed.

    Mirrors ``ProjectStagingService.cancel_staging``'s precondition exactly:
    staging_status == 'staging' AND status == INACTIVE. From 'staged' it is
    unreachable no matter what status is -- never suggested there.
    """
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
    """The ``diagnose_project_state`` stuck/suggested computation -- pure
    relocation, behavior unchanged (BE-8003a's next_action-envelope note
    applies unchanged: this stays a multi-item list, not a single
    ``next_action``)."""
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
