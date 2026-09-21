# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from api.endpoints.dependencies import get_sequence_run_service
from giljo_mcp.auth.dependencies import get_current_active_user
from giljo_mcp.exceptions import ResourceNotFoundError, ValidationError
from giljo_mcp.models import User
from giljo_mcp.models.sequence_runs import (
    MAX_SEQUENCE_PROJECTS,
    VALID_EXECUTION_MODES,
    VALID_PROJECT_STATUSES,
    VALID_REVIEW_POLICIES,
    VALID_RUN_STATUSES,
)
from giljo_mcp.services.sequence_run_service import VALID_RELEASE_MODES, SequenceRunService
from giljo_mcp.utils.log_sanitizer import sanitize


logger = logging.getLogger(__name__)
router = APIRouter()

_PRODUCT_ID_QUERY = Query(
    None,
    max_length=64,
    description="Product to scope to (the viewed tab). Omitted: every product in the tenant.",
)




class CreateSequenceRunRequest(BaseModel):
    """Request body for POST /api/v1/sequence-runs."""

    project_ids: list[str] = Field(
        ...,
        min_length=1,
        max_length=MAX_SEQUENCE_PROJECTS,
        description="Ordered list of project_id strings (user-selected subset).",
    )
    resolved_order: list[str] = Field(
        ...,
        min_length=1,
        max_length=MAX_SEQUENCE_PROJECTS,
        description="Topologically/roadmap-resolved run order (list of project_id strings).",
    )
    execution_mode: str = Field(
        ...,
        description=f"Uniform execution mode. One of: {sorted(VALID_EXECUTION_MODES)}",
    )
    review_policy: str = Field(
        default="per_card",
        description=f"Review policy. One of: {sorted(VALID_REVIEW_POLICIES)}",
    )
    status: str = Field(
        default="pending",
        description=f"Initial run status. One of: {sorted(VALID_RUN_STATUSES)}",
    )
    current_index: int = Field(
        default=0,
        ge=0,
        description="0-based index of the project currently being processed.",
    )
    project_statuses: dict[str, str] = Field(
        default_factory=dict,
        description=(
            f"Per-project status map: {{project_id -> status}}. Valid status values: {sorted(VALID_PROJECT_STATUSES)}"
        ),
    )


class UpdateSequenceRunRequest(BaseModel):
    """Request body for PATCH /api/v1/sequence-runs/{run_id}.

    All fields are optional; only provided fields are updated.
    """

    current_index: int | None = Field(
        default=None,
        ge=0,
        description="New resume-from index.",
    )
    status: str | None = Field(
        default=None,
        description=f"New run status. One of: {sorted(VALID_RUN_STATUSES)}",
    )
    review_policy: str | None = Field(
        default=None,
        description=f"New review policy. One of: {sorted(VALID_REVIEW_POLICIES)}",
    )
    project_statuses: dict[str, str] | None = Field(
        default=None,
        description=(f"Replacement per-project status map. Valid status values: {sorted(VALID_PROJECT_STATUSES)}"),
    )
    execution_mode: str | None = Field(
        default=None,
        description=f"New uniform execution mode (cockpit picker). One of: {sorted(VALID_EXECUTION_MODES)}",
    )
    resolved_order: list[str] | None = Field(
        default=None,
        min_length=1,
        max_length=MAX_SEQUENCE_PROJECTS,
        description="Reordered run order (cockpit drag, pre-Stage). List of project_id strings.",
    )
    locked: bool | None = Field(
        default=None,
        description=(
            "Edit lock (FE-6171). Stage -> true (membership/tickboxes locked); Unstage -> false. "
            "Unstage (false) is refused with 422 once the run is staging-complete / running (ultralocked)."
        ),
    )
    chain_mission: str | None = Field(
        default=None,
        description=(
            "Conductor-owned cross-project chain plan (BE-6185). Editable via the FE pen pre-Implement; "
            "refused with 422 once the run is staging-complete / running (read-only after Implement)."
        ),
    )
    conductor_agent_id: str | None = Field(
        default=None,
        description="Conductor agent identity (written by the sequence driver's self-registration).",
    )
    conductor_project_id: str | None = Field(
        default=None,
        description="Conductor project_id (the head-of-order project).",
    )
    conductor_label: str | None = Field(
        default=None,
        description="Human-readable conductor label.",
    )




@router.post("", status_code=status.HTTP_201_CREATED)
async def create_sequence_run(
    request: CreateSequenceRunRequest,
    current_user: User = Depends(get_current_active_user),
    service: SequenceRunService = Depends(get_sequence_run_service),
) -> dict[str, Any]:
    """Create a new multi-project sequential run record.

    Returns the created run dict. 422 for invalid enum values or cap violations.
    """
    logger.info(
        "User %s creating sequence_run (mode=%s, projects=%d)",
        sanitize(current_user.username),
        sanitize(request.execution_mode),
        len(request.project_ids),
    )
    try:
        return await service.create(
            project_ids=request.project_ids,
            resolved_order=request.resolved_order,
            execution_mode=request.execution_mode,
            review_policy=request.review_policy,
            status=request.status,
            current_index=request.current_index,
            project_statuses=request.project_statuses,
            tenant_key=current_user.tenant_key,
        )
    except ValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=exc.message) from exc


@router.get("")
async def list_sequence_runs(
    status_filter: str = Query(
        "pending,running,stalled",
        alias="status",
        description="Comma-separated run statuses to include. Default: active (pending,running,stalled).",
    ),
    include_review_pending: bool = Query(
        default=False,
        description=(
            "FE-9104: when true, ALSO include recent terminal runs that still have a "
            "completed-but-unreviewed member, so the chain review surface stays reachable "
            "after a cold refresh. Appended (deduped) to the status-filtered active set."
        ),
    ),
    product_id: str | None = _PRODUCT_ID_QUERY,
    current_user: User = Depends(get_current_active_user),
    service: SequenceRunService = Depends(get_sequence_run_service),
) -> list[dict[str, Any]]:
    """List this tenant's sequence runs filtered by status (BE-6165e).

    The durable-election read-back: the cockpit hydrates locked "In chain"
    checkboxes from here and detects an orphaned run for the reset hatch. 422 on
    an unknown status value. With ``include_review_pending=true`` the response also
    carries terminal runs awaiting review (FE-9104) — additive, tenant-scoped.

    ``product_id`` (FE-9627) narrows both halves to runs whose member projects
    belong to that product — the tab being viewed. Omitted, the response stays
    tenant-wide exactly as before. A product_id this tenant does not own is a
    422, never a silent tenant-wide fallback.
    """
    statuses = tuple(s.strip() for s in status_filter.split(",") if s.strip())
    logger.debug("User %s listing sequence_runs (status=%s)", sanitize(current_user.username), sanitize(status_filter))
    try:
        runs = await service.list_active(tenant_key=current_user.tenant_key, statuses=statuses, product_id=product_id)
        if include_review_pending:
            pending = await service.list_review_pending(tenant_key=current_user.tenant_key, product_id=product_id)
            seen = {r["id"] for r in runs}
            runs = runs + [r for r in pending if r["id"] not in seen]
        return runs
    except ValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=exc.message) from exc


@router.get("/{run_id}")
async def get_sequence_run(
    run_id: str,
    current_user: User = Depends(get_current_active_user),
    service: SequenceRunService = Depends(get_sequence_run_service),
) -> dict[str, Any]:
    """Fetch a sequence run by id (tenant-scoped).

    404 if the run does not exist or belongs to another tenant.
    """
    logger.debug("User %s fetching sequence_run %s", sanitize(current_user.username), sanitize(run_id))
    try:
        return await service.get(run_id=run_id, tenant_key=current_user.tenant_key)
    except ResourceNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="sequence_run not found") from exc


@router.patch("/{run_id}")
async def update_sequence_run(
    run_id: str,
    request: UpdateSequenceRunRequest,
    current_user: User = Depends(get_current_active_user),
    service: SequenceRunService = Depends(get_sequence_run_service),
) -> dict[str, Any]:
    """Partially update a sequence run.

    Only fields present in the request body are updated. Use this to advance
    current_index, flip status (e.g. running -> stalled), or write per-project
    status updates. 404 if run not found for this tenant; 422 for invalid values.
    """
    logger.info(
        "User %s patching sequence_run %s (status=%s, index=%s)",
        sanitize(current_user.username),
        sanitize(run_id),
        sanitize(str(request.status)),
        sanitize(str(request.current_index)),
    )
    try:
        return await service.update(
            run_id=run_id,
            tenant_key=current_user.tenant_key,
            current_index=request.current_index,
            status=request.status,
            review_policy=request.review_policy,
            project_statuses=request.project_statuses,
            execution_mode=request.execution_mode,
            resolved_order=request.resolved_order,
            locked=request.locked,
            chain_mission=request.chain_mission,
            conductor_agent_id=request.conductor_agent_id,
            conductor_project_id=request.conductor_project_id,
            conductor_label=request.conductor_label,
        )
    except ResourceNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="sequence_run not found") from exc
    except ValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=exc.message) from exc


@router.delete("/{run_id}/members/{project_id}")
async def remove_sequence_run_member(
    run_id: str,
    project_id: str,
    current_user: User = Depends(get_current_active_user),
    service: SequenceRunService = Depends(get_sequence_run_service),
) -> dict[str, Any]:
    """Remove ONE project from a run's membership (FE-6171 granular removal).

    Untick on /projects or /roadmap (Editing tier only) calls this to drop a member
    from ``project_ids`` / ``resolved_order``. When removal leaves exactly one
    project the run dissolves (status=cancelled); the lone project is NOT
    auto-activated (FE-6174b removed collapse-to-solo — reduce-to-1 is a warning,
    never an auto-flip). Refuses (422) when the run is staging-complete / running
    (ultralocked) — only Terminate/Release end such a run. 404 if the run is not
    found for this tenant. Returns the updated (or dissolved) run dict.
    """
    logger.info(
        "User %s removing project %s from sequence_run %s",
        sanitize(current_user.username),
        sanitize(project_id),
        sanitize(run_id),
    )
    try:
        return await service.remove_member(
            run_id=run_id,
            project_id=project_id,
            tenant_key=current_user.tenant_key,
        )
    except ResourceNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="sequence_run not found") from exc
    except ValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=exc.message) from exc


@router.post("/{run_id}/members/{project_id}/review")
async def mark_sequence_run_member_reviewed(
    run_id: str,
    project_id: str,
    current_user: User = Depends(get_current_active_user),
    service: SequenceRunService = Depends(get_sequence_run_service),
) -> dict[str, Any]:
    """Durably record that a chain member has been reviewed (BE-9098).

    The FE calls this when the user closes a member's review pane so the "Review"
    badge SURVIVES refresh/navigation (it was client-only before). Append-only +
    idempotent (re-marking is a no-op). NON-GATING: writes only
    ``reviewed_project_ids``, never ``project_statuses`` — chain advancement /
    purge_run are unaffected. 404 if the run is not found for this tenant; 422 if
    ``project_id`` is empty or not a member of the run. Returns the updated run dict.
    """
    logger.info(
        "User %s marking project %s reviewed on sequence_run %s",
        sanitize(current_user.username),
        sanitize(project_id),
        sanitize(run_id),
    )
    try:
        return await service.mark_member_reviewed(
            run_id=run_id,
            project_id=project_id,
            tenant_key=current_user.tenant_key,
        )
    except ResourceNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="sequence_run not found") from exc
    except ValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=exc.message) from exc


@router.post("/{run_id}/release")
async def release_sequence_run(
    run_id: str,
    mode: str = Query(
        ...,
        description=f"How to end the run. One of: {sorted(VALID_RELEASE_MODES)} "
        "(graceful = conductor closed out -> terminated; cancel = hard reset -> cancelled).",
    ),
    current_user: User = Depends(get_current_active_user),
    service: SequenceRunService = Depends(get_sequence_run_service),
) -> dict[str, Any]:
    """End a run and free its membership (BE-6165e convenience verb).

    ``mode=graceful`` -> terminated (requires the in-flight project already closed
    out; 422 otherwise). ``mode=cancel`` -> cancelled (the killed-terminals escape
    hatch, no precondition). Downstream members are freed by the run going terminal
    (no ProjectStatus mutation). 404 if not found; 422 for a bad mode/precondition.
    """
    logger.info(
        "User %s releasing sequence_run %s (mode=%s)",
        sanitize(current_user.username),
        sanitize(run_id),
        sanitize(mode),
    )
    try:
        return await service.release(run_id=run_id, mode=mode, tenant_key=current_user.tenant_key)
    except ResourceNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="sequence_run not found") from exc
    except ValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=exc.message) from exc


@router.post("/{run_id}/stop")
async def stop_sequence_run(
    run_id: str,
    current_user: User = Depends(get_current_active_user),
    service: SequenceRunService = Depends(get_sequence_run_service),
) -> dict[str, Any]:
    """Stop a running chain (FE-9632): end the run and stand its members down.

    The running-chain screen's Stop control, and the safe one: the work already done is
    never thrown away. A project that already finished stays finished. The project that
    was underway is marked terminated and its agents are stood down, with their history
    kept so you can still read what they did. Projects the chain never reached go back
    to inactive and need staging again, which clears the mission they had not started
    on. The run is then cancelled, releasing the group. 404 if the run is not found for
    this tenant. Returns the stopped run.
    """
    logger.info(
        "User %s stopping chain (sequence_run %s)",
        sanitize(current_user.username),
        sanitize(run_id),
    )
    try:
        return await service.stop_chain(run_id=run_id, tenant_key=current_user.tenant_key)
    except ResourceNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="sequence_run not found") from exc
    except ValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=exc.message) from exc


@router.post("/{run_id}/deactivate")
async def deactivate_sequence_run(
    run_id: str,
    current_user: User = Depends(get_current_active_user),
    service: SequenceRunService = Depends(get_sequence_run_service),
) -> dict[str, Any]:
    """Back out of a chain (FE-6178): rewind every member to its original state.

    The /projects "Deactivate Chain" escape hatch — the chain equivalent of solo
    Deactivate, and the DESTRUCTIVE one. Every member is returned to pre-staging: its
    staging state, mission and launch timestamp are cleared, it goes back to inactive,
    and its agent jobs and their history are DELETED — so the record of any work those
    agents did is gone. A hard-deleted member is skipped. The run is then cancelled,
    freeing membership (checkboxes unlock, the "In chain" pill clears).

    To stop a chain WITHOUT losing that history, use POST /{run_id}/stop instead.
    404 if the run is not found for this tenant. Returns the dissolved run.
    """
    logger.info(
        "User %s deactivating chain (sequence_run %s)",
        sanitize(current_user.username),
        sanitize(run_id),
    )
    try:
        return await service.deactivate_chain(run_id=run_id, tenant_key=current_user.tenant_key)
    except ResourceNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="sequence_run not found") from exc
    except ValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=exc.message) from exc
