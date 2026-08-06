# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""SequenceRun write-boundary validation helpers (extracted from the service).

Pure, membership/length validation of the enum-like and capped fields before any
DB write, raising ValidationError (-> 422) rather than letting a DB constraint
produce a 500. Extracted to keep ``sequence_run_service.py`` under the 800-line CI
guardrail (BE-6185), mirroring the ``sequence_run_serialization.py`` extraction.
Internal; the owning service is the only caller.

Edition Scope: CE.
"""

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


# BE-6185: hard cap on the conductor-owned chain mission text, enforced at the
# write boundary so an over-cap value raises ValidationError (-> 422) rather than
# letting the DB produce a 500.
MAX_CHAIN_MISSION_CHARS: int = 100_000


def _validate_project_statuses(project_statuses: dict[str, str]) -> None:
    for pid, ps in project_statuses.items():
        if ps not in VALID_PROJECT_STATUSES:
            raise ValidationError(
                message=f"Invalid project status {ps!r} for project {pid!r}. Valid: {sorted(VALID_PROJECT_STATUSES)}",
                context={"field": "project_statuses", "project_id": pid, "valid": sorted(VALID_PROJECT_STATUSES)},
            )


def validate_create_fields(
    *,
    project_ids: list[str],
    execution_mode: str,
    status: str,
    review_policy: str,
    project_statuses: dict[str, str],
) -> None:
    """Membership-validate all enum-like fields before touching the DB (create path)."""
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
    if execution_mode not in ACCEPTED_EXECUTION_MODES:
        raise ValidationError(
            message=f"Invalid execution_mode {execution_mode!r}. Valid: {sorted(VALID_EXECUTION_MODES)}",
            context={"field": "execution_mode", "valid": sorted(VALID_EXECUTION_MODES)},
        )
    if status not in VALID_RUN_STATUSES:
        raise ValidationError(
            message=f"Invalid status {status!r}. Valid: {sorted(VALID_RUN_STATUSES)}",
            context={"field": "status", "valid": sorted(VALID_RUN_STATUSES)},
        )
    if review_policy not in VALID_REVIEW_POLICIES:
        raise ValidationError(
            message=f"Invalid review_policy {review_policy!r}. Valid: {sorted(VALID_REVIEW_POLICIES)}",
            context={"field": "review_policy", "valid": sorted(VALID_REVIEW_POLICIES)},
        )
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
    """Membership/length-validate the optional update fields (partial-update path).

    Returns the normalized ``(resolved_order, project_statuses)`` (JSONB-validated
    when provided, else passed through as None). Raises ValidationError (-> 422) on
    any invalid value.
    """
    if status is not None and status not in VALID_RUN_STATUSES:
        raise ValidationError(
            message=f"Invalid status {status!r}. Valid: {sorted(VALID_RUN_STATUSES)}",
            context={"field": "status", "valid": sorted(VALID_RUN_STATUSES)},
        )
    if review_policy is not None and review_policy not in VALID_REVIEW_POLICIES:
        raise ValidationError(
            message=f"Invalid review_policy {review_policy!r}. Valid: {sorted(VALID_REVIEW_POLICIES)}",
            context={"field": "review_policy", "valid": sorted(VALID_REVIEW_POLICIES)},
        )
    if current_index is not None and current_index < 0:
        raise ValidationError(
            message="current_index must be >= 0",
            context={"field": "current_index"},
        )
    if execution_mode is not None and execution_mode not in ACCEPTED_EXECUTION_MODES:
        raise ValidationError(
            message=f"Invalid execution_mode {execution_mode!r}. Valid: {sorted(VALID_EXECUTION_MODES)}",
            context={"field": "execution_mode", "valid": sorted(VALID_EXECUTION_MODES)},
        )
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


# Run statuses that mean implementation is in flight. Mirrors the service's own
# tier constant; kept here so the mode-freeze refusal is self-contained.
_RUNNING_STATUSES: frozenset[str] = frozenset({"running", "stalled"})


async def refuse_mode_change_if_live(session: AsyncSession, run, run_id: str, tenant_key: str) -> None:
    """Refuse an execution_mode change once the chain's agents are LIVE (BE-9335).

    The run's mode is what a chain member actually runs in, so changing it while
    agents already hold rendered prompts would re-point their harness mid-flight
    — exactly the desync ``projects.execution_mode`` refuses after launch. This
    is that same per-project lock at the tier that owns a chain, so it keys on
    the SAME signal: ``implementation_launched_at``.

    Deliberately NOT the ultralock tier. Ultralock means "the Implement button is
    available" (any member at ``staging_complete``), which is reached while every
    agent is still cold — refusing there took away a mode change the server had
    always allowed, and pointed at Unstage, which ultralock itself refuses. It
    also does not engage on the straight-to-implementation path this fixes:
    ``GET /prompts/chain-implementation`` is a pure read that sets neither
    ``status`` nor ``locked``, so a driven chain stays pending + unlocked while
    its members run. The launch gate is true in exactly that case.

    Re-staging clears ``implementation_launched_at``, so the remedy named in the
    message is one the user can actually carry out.
    """
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
    """Names of member projects that have crossed their launch gate. Tenant-scoped.

    Names rather than ids: this feeds a user-facing refusal, and a refusal that
    does not say which member froze the chain makes the user hunt for it.
    """
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
