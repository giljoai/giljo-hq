# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from typing import Any

from giljo_mcp.domain.project_status import ProjectStatus
from giljo_mcp.schemas.responses.orchestration import build_next_action


_TERMINAL_STATUSES: frozenset[str] = frozenset(
    {
        ProjectStatus.COMPLETED,
        ProjectStatus.CANCELLED,
        ProjectStatus.SUPERSEDED,
        ProjectStatus.TERMINATED,
        ProjectStatus.DELETED,
    }
)

_OPEN_TASK_STATUSES: frozenset[str] = frozenset({"pending", "in_progress"})

STAGING_COMPLETE = "staging_complete"

PROJECT_NOT_STAGED_HINT = (
    "To implement this project, call stage_project(project_id, mode). The server pauses "
    "you at staging for the user's go; then launch_implementation."
)
PROJECT_AWAITING_GO_HINT = "Staging is complete. Wait for the user's go, then call launch_implementation(project_id)."
PROJECT_IN_FLIGHT_HINT = "Implementation is in flight. Report with report_progress; finish with write_project_closeout."
PROJECT_AWAITING_USER_HINT = (
    "Blocked on a user decision. The user decides in the dashboard closeout modal or via decide_approval."
)
PROJECT_PARKED_HINT = "Parked by the user. Do not start work; ask before un-parking (update_project status='inactive')."
TASK_OPEN_HINT = (
    "Tasks are single-step. Do the work, then update_task(task_id, status='completed'). "
    "If it grows into multi-step work, create_project instead."
)


def project_next_action(
    *,
    status: Any,
    staging_status: str | None,
    implementation_launched_at: Any,
    awaiting_user: bool = False,
) -> dict[str, Any] | None:
    status_value = str(status or "")
    if status_value in _TERMINAL_STATUSES:
        return None
    if status_value == ProjectStatus.PARKED:
        return build_next_action(tool=None, why=PROJECT_PARKED_HINT)
    if awaiting_user:
        return build_next_action(tool=None, why=PROJECT_AWAITING_USER_HINT)
    if implementation_launched_at is not None:
        return build_next_action(tool="report_progress", why=PROJECT_IN_FLIGHT_HINT)
    if staging_status == STAGING_COMPLETE:
        return build_next_action(tool="launch_implementation", why=PROJECT_AWAITING_GO_HINT)
    return build_next_action(tool="stage_project", why=PROJECT_NOT_STAGED_HINT)


def project_next_action_for(project: Any, *, awaiting_user: bool = False) -> dict[str, Any] | None:
    return project_next_action(
        status=getattr(project, "status", None),
        staging_status=getattr(project, "staging_status", None),
        implementation_launched_at=getattr(project, "implementation_launched_at", None),
        awaiting_user=awaiting_user,
    )


def task_list_next_action_field(*, mode: str, statuses: Any) -> dict[str, Any]:
    if mode == "index":
        return {}
    hint = task_list_next_action(statuses)
    return {"next_action": hint} if hint is not None else {}


def task_list_next_action(statuses: Any) -> dict[str, Any] | None:
    for status in statuses:
        if str(status or "") in _OPEN_TASK_STATUSES:
            return build_next_action(tool="update_task", why=TASK_OPEN_HINT)
    return None
