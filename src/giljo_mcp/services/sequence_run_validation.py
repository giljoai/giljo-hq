# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.exceptions import ValidationError
from giljo_mcp.models.projects import Project
from giljo_mcp.models.sequence_runs import (
    ACCEPTED_EXECUTION_MODES,
    MAX_SEQUENCE_PROJECTS,
    VALID_EXECUTION_MODES,
    VALID_PROJECT_STATUSES,
    VALID_REVIEW_POLICIES,
    VALID_RUN_STATUSES,
)
from giljo_mcp.schemas.jsonb_validators import (
    validate_sequence_run_project_ids,
    validate_sequence_run_project_statuses,
)


MAX_CHAIN_MISSION_CHARS: int = 100_000


def _validate_project_statuses(project_statuses: dict[str, str]) -> None:
    for pid, ps in project_statuses.items():
        if ps not in VALID_PROJECT_STATUSES:
            raise ValidationError(
                message=f"Invalid project status {ps!r} for project {pid!r}. Valid: {sorted(VALID_PROJECT_STATUSES)}",
                context={"field": "project_statuses", "project_id": pid, "valid": sorted(VALID_PROJECT_STATUSES)},
            )


def _require_member(field: str, value: str, valid: frozenset[str], shown: frozenset[str] | None = None) -> None:
    if value not in valid:
        names = sorted(shown if shown is not None else valid)
        raise ValidationError(
            message=f"Invalid {field} {value!r}. Valid: {names}", context={"field": field, "valid": names}
        )


def validate_create_fields(
    *,
    project_ids: list[str],
    execution_mode: str,
    status: str,
    review_policy: str,
    project_statuses: dict[str, str],
) -> None:
    if not project_ids:
        raise ValidationError(
            message="project_ids must be a non-empty list",
            context={"field": "project_ids"},
        )
    if len(project_ids) > MAX_SEQUENCE_PROJECTS:
        raise ValidationError(
            message=f"project_ids exceeds maximum of {MAX_SEQUENCE_PROJECTS} projects (got {len(project_ids)})",
            context={"field": "project_ids", "max": MAX_SEQUENCE_PROJECTS},
        )
    _require_member("execution_mode", execution_mode, ACCEPTED_EXECUTION_MODES, shown=VALID_EXECUTION_MODES)
    _require_member("status", status, VALID_RUN_STATUSES)
    _require_member("review_policy", review_policy, VALID_REVIEW_POLICIES)
    _validate_project_statuses(project_statuses)


def validate_update_fields(
    *,
    status: str | None,
    review_policy: str | None,
    current_index: int | None,
    execution_mode: str | None,
    chain_mission: str | None,
    resolved_order: list[str] | None,
    project_statuses: dict[str, str] | None,
) -> tuple[list[str] | None, dict[str, str] | None]:
    if status is not None:
        _require_member("status", status, VALID_RUN_STATUSES)
    if review_policy is not None:
        _require_member("review_policy", review_policy, VALID_REVIEW_POLICIES)
    if current_index is not None and current_index < 0:
        raise ValidationError(
            message="current_index must be >= 0",
            context={"field": "current_index"},
        )
    if execution_mode is not None:
        _require_member("execution_mode", execution_mode, ACCEPTED_EXECUTION_MODES, shown=VALID_EXECUTION_MODES)
    if chain_mission is not None:
        if not isinstance(chain_mission, str):
            raise ValidationError(
                message="chain_mission must be a string",
                context={"field": "chain_mission"},
            )
        if len(chain_mission) > MAX_CHAIN_MISSION_CHARS:
            raise ValidationError(
                message=(
                    f"chain_mission exceeds maximum of {MAX_CHAIN_MISSION_CHARS} characters (got {len(chain_mission)})"
                ),
                context={"field": "chain_mission", "max": MAX_CHAIN_MISSION_CHARS},
            )
    if resolved_order is not None:
        resolved_order = validate_sequence_run_project_ids(resolved_order)
    if project_statuses is not None:
        _validate_project_statuses(project_statuses)
        project_statuses = validate_sequence_run_project_statuses(project_statuses)
    return resolved_order, project_statuses


_RUNNING_STATUSES: frozenset[str] = frozenset({"running", "stalled"})


async def refuse_mode_change_if_live(session: AsyncSession, run, run_id: str, tenant_key: str) -> None:
    launched = await _launched_member_names(session, run, tenant_key)
    if launched:
        named = ", ".join(launched)
        raise ValidationError(
            message=(
                f"Cannot change the execution mode: implementation has already launched for {named}. "
                "Agents are live with prompts already rendered for the current mode. To change it you "
                "must Reset the launched project(s) first — that discards their agents and progress. "
                "(Re-staging is refused once implementation has launched.)"
            ),
            context={
                "field": "execution_mode",
                "run_id": run_id,
                "status": run.status,
                "launched_members": launched,
            },
        )
    if run.status in _RUNNING_STATUSES:
        raise ValidationError(
            message=("Cannot change the execution mode: the chain is already running. Re-stage it to change the mode."),
            context={"field": "execution_mode", "run_id": run_id, "status": run.status},
        )


async def _launched_member_names(session: AsyncSession, run, tenant_key: str) -> list[str]:
    member_ids = list(run.project_ids or [])
    if not member_ids:
        return []
    stmt = (
        select(Project.name)
        .where(
            Project.tenant_key == tenant_key,
            Project.id.in_(member_ids),
            Project.implementation_launched_at.isnot(None),
        )
        .order_by(Project.name)
    )
    result = await session.execute(stmt)
    return [row[0] for row in result.all()]
