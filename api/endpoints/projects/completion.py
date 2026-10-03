# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import logging
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, status

from api.endpoints._boundary_types import IdPath
from api.schemas.prompt import (
    ProjectCompleteRequest,
    ProjectCompleteResponse,
)
from giljo_mcp.auth.dependencies import get_current_active_user
from giljo_mcp.exceptions import ProjectStateError
from giljo_mcp.models import User
from giljo_mcp.services.project_service import ProjectService
from giljo_mcp.utils.log_sanitizer import sanitize

from .dependencies import get_project_service
from .models import CloseoutWithoutSummaryRequest, CloseoutWithoutSummaryResponse, ContinueWorkingResponse


logger = logging.getLogger(__name__)
router = APIRouter()


@router.post(
    "/{project_id}/complete",
    response_model=ProjectCompleteResponse,
    summary="Complete project and update 360 Memory",
    tags=["Projects"],
)
async def complete_project(
    project_id: IdPath,
    request: ProjectCompleteRequest,
    current_user: User = Depends(get_current_active_user),
    project_service: ProjectService = Depends(get_project_service),
) -> ProjectCompleteResponse:
    """
    Complete project and update product's 360 Memory with learnings.
    """
    logger.info("User %s completing project %s", sanitize(current_user.username), sanitize(project_id))

    if not request.confirm_closeout:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Must confirm closeout (confirm_closeout=True)",
        )

    result = await project_service.complete_project(
        project_id=project_id,
        summary=request.summary,
        key_outcomes=request.key_outcomes,
        decisions_made=request.decisions_made,
        git_commits=request.git_commits,
        tenant_key=current_user.tenant_key,
    )

    return ProjectCompleteResponse(
        success=True,
        completed_at=datetime.now(UTC).isoformat(),
        memory_updated=result.memory_updated,
        sequence_number=result.sequence_number,
        git_commits_count=result.git_commits_count,
    )


@router.post("/{project_id}/continue-working", response_model=ContinueWorkingResponse)
async def continue_working(
    project_id: IdPath,
    current_user: User = Depends(get_current_active_user),
    project_service: ProjectService = Depends(get_project_service),
) -> ContinueWorkingResponse:
    """
    Resume work on project.

    Args:
        project_id: Project UUID
        current_user: Authenticated user (from dependency)
        project_service: Project service (from dependency)

    Returns:
        ContinueWorkingResponse with resume details

    Raises:
        HTTPException 404: Project not found
        HTTPException 400: Invalid state transition
    """
    logger.info("User %s resuming work on project %s", sanitize(current_user.username), sanitize(project_id))

    result = await project_service.lifecycle.continue_working(project_id=project_id, tenant_key=current_user.tenant_key)

    logger.info("Resumed work on project %s", sanitize(project_id))

    return ContinueWorkingResponse(
        success=True,
        message=result.message,
        agents_resumed=result.agents_resumed,
        resumed_agent_ids=result.resumed_agent_ids,
        project_status=result.project_status,
    )


@router.post("/{project_id}/closeout-without-summary", response_model=CloseoutWithoutSummaryResponse)
async def closeout_without_summary(
    project_id: IdPath,
    request: CloseoutWithoutSummaryRequest,
    current_user: User = Depends(get_current_active_user),
    project_service: ProjectService = Depends(get_project_service),
) -> CloseoutWithoutSummaryResponse:
    """Close out a project whose agents stopped without writing a closeout.

    Writes a short closeout entry to project memory with your reason, so the
    project can be reviewed and archived like any other. Refused while an agent
    is still working.
    """
    from giljo_mcp.tools.closeout_without_code_changes import close_project_without_code_changes

    logger.info(
        "User %s closing out project %s without an agent summary",
        sanitize(current_user.username),
        sanitize(project_id),
    )

    result = await close_project_without_code_changes(
        project_id,
        request.reason,
        tenant_key=current_user.tenant_key,
        db_manager=project_service.db_manager,
    )
    if result.get("success") is False:
        raise ProjectStateError(
            message=result.get("message") or "The closeout was refused.",
            error_code=result.get("error", "PROJECT_CLOSEOUT_REJECTED"),
            context={"project_id": project_id, "hint": result.get("hint")},
        )

    return CloseoutWithoutSummaryResponse(
        success=True,
        sequence_number=result.get("sequence_number"),
        message=result.get("message") or "",
    )
