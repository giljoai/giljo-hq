# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status

from api.endpoints._boundary_types import IdPath, IdQuery
from giljo_mcp.auth.dependencies import get_current_active_user
from giljo_mcp.exceptions import ProjectStateError, ResourceNotFoundError
from giljo_mcp.models import User
from giljo_mcp.models.schemas import ProjectLaunchResponse
from giljo_mcp.services.project_service import ProjectService
from giljo_mcp.utils.log_sanitizer import sanitize

from .dependencies import get_project_service
from .models import (
    ProjectDeleteResponse,
    ProjectPurgeResponse,
    ProjectResponse,
    ProjectReviewedResponse,
    PurgedProject,
)


logger = logging.getLogger(__name__)
router = APIRouter()


def _build_project_response(proj, agents=None) -> ProjectResponse:
    if agents is None:
        agents = []
    return ProjectResponse(
        id=proj.id,
        alias=proj.alias or "",
        name=proj.name,
        description=proj.description,
        mission=proj.mission or "",
        status=proj.status,
        product_id=proj.product_id,
        created_at=proj.created_at,
        updated_at=proj.updated_at,
        completed_at=proj.completed_at,
        implementation_launched_at=getattr(proj, "implementation_launched_at", None),
        agent_count=proj.agent_count,
        message_count=proj.message_count,
        agents=agents,
        hidden=getattr(proj, "hidden", False) is True,
    )


@router.post("/{project_id}/activate", response_model=ProjectResponse)
async def activate_project(
    project_id: IdPath,
    force: bool = False,
    current_user: User = Depends(get_current_active_user),
    project_service: ProjectService = Depends(get_project_service),
) -> ProjectResponse:
    """
    Activate a project (sets status to active).

    State Transitions:
    - staging → active (initial launch)
    - inactive → active (resume)

    Automatically deactivates other active projects in same product (Single Active Project constraint).

    Args:
        project_id: Project UUID
        force: Skip validation checks if True
        current_user: Authenticated user (from dependency)
        project_service: Project service (from dependency)

    Returns:
        ProjectResponse with activated project

    Raises:
        HTTPException 404: Project not found
        HTTPException 400: Activation failed
    """
    logger.info(
        "User %s activating project %s (force=%s)",
        sanitize(current_user.username),
        sanitize(project_id),
        sanitize(force),
    )

    await project_service.activate_project(project_id=project_id, force=force, tenant_key=current_user.tenant_key)

    logger.info("Activated project %s", sanitize(project_id))

    proj = await project_service.get_project(project_id=project_id, tenant_key=current_user.tenant_key)

    return _build_project_response(proj)


@router.post("/{project_id}/deactivate", response_model=ProjectResponse)
async def deactivate_project(
    project_id: IdPath,
    current_user: User = Depends(get_current_active_user),
    project_service: ProjectService = Depends(get_project_service),
) -> ProjectResponse:
    """
    Deactivate an active project.

    State Transition: active → inactive

    Args:
        project_id: Project UUID
        current_user: Authenticated user (from dependency)
        project_service: Project service (from dependency)

    Returns:
        ProjectResponse with inactive project

    Raises:
        HTTPException 404: Project not found
        HTTPException 400: Deactivation failed
    """
    logger.info("User %s deactivating project %s", sanitize(current_user.username), sanitize(project_id))

    await project_service.deactivate_project(project_id=project_id, tenant_key=current_user.tenant_key)

    logger.info("Deactivated project %s", sanitize(project_id))

    proj = await project_service.get_project(project_id=project_id, tenant_key=current_user.tenant_key)

    return _build_project_response(proj)


@router.post("/{project_id}/cancel", response_model=ProjectResponse)
async def cancel_project(
    project_id: IdPath,
    reason: str | None = None,
    current_user: User = Depends(get_current_active_user),
    project_service: ProjectService = Depends(get_project_service),
) -> ProjectResponse:
    """
    Cancel a project.

    Args:
        project_id: Project UUID
        reason: Optional cancellation reason
        current_user: Authenticated user (from dependency)
        project_service: Project service (from dependency)

    Returns:
        ProjectResponse with cancelled project

    Raises:
        HTTPException 404: Project not found
        HTTPException 400: Cancellation failed
    """
    logger.info("User %s cancelling project %s", sanitize(current_user.username), sanitize(project_id))

    await project_service.lifecycle.cancel_project(
        project_id=project_id, tenant_key=current_user.tenant_key, reason=reason
    )

    logger.info("Cancelled project %s", sanitize(project_id))

    proj = await project_service.get_project(project_id=project_id, tenant_key=current_user.tenant_key)

    return _build_project_response(proj)


@router.post("/{project_id}/restore", response_model=ProjectResponse)
async def restore_project(
    project_id: IdPath,
    current_user: User = Depends(get_current_active_user),
    project_service: ProjectService = Depends(get_project_service),
) -> ProjectResponse:
    """
    Restore a cancelled project.

    Args:
        project_id: Project UUID
        current_user: Authenticated user (from dependency)
        project_service: Project service (from dependency)

    Returns:
        ProjectResponse with restored project

    Raises:
        HTTPException 404: Project not found
        HTTPException 400: Restore failed
    """
    logger.info("User %s restoring project %s", sanitize(current_user.username), sanitize(project_id))

    await project_service.deletion.restore_project(project_id=project_id, tenant_key=current_user.tenant_key)

    logger.info("Restored project %s", sanitize(project_id))

    proj = await project_service.get_project(project_id=project_id, tenant_key=current_user.tenant_key)

    return _build_project_response(proj)


@router.post("/{project_id}/cancel-staging", response_model=ProjectResponse)
async def cancel_project_staging(
    project_id: IdPath,
    current_user: User = Depends(get_current_active_user),
    project_service: ProjectService = Depends(get_project_service),
) -> ProjectResponse:
    """
    Cancel project staging and rollback.

    State Transition: staging → cancelled

    This endpoint cancels staging after orchestrator has spawned agents.
    Performs transactional rollback of staging changes.

    Args:
        project_id: Project UUID
        current_user: Authenticated user (from dependency)
        project_service: Project service (from dependency)

    Returns:
        ProjectResponse with cancelled project

    Raises:
        HTTPException 404: Project not found
        HTTPException 400: Cancellation failed
    """
    logger.info("User %s cancelling staging for project %s", sanitize(current_user.username), sanitize(project_id))

    await project_service.lifecycle.cancel_staging(project_id=project_id)

    logger.info("Cancelled staging for project %s", sanitize(project_id))

    proj = await project_service.get_project(project_id=project_id, tenant_key=current_user.tenant_key)

    return _build_project_response(proj)


@router.post("/{project_id}/restage")
async def restage_project(
    project_id: IdPath,
    current_user: User = Depends(get_current_active_user),
    project_service: ProjectService = Depends(get_project_service),
) -> dict:
    """
    Restage a project by resetting staging state and creating a fresh orchestrator.

    Guards:
        - Project must have staging_status in ('staging', 'staging_complete')
        - Recovery from 'staging_complete' is rejected once implementation is
          launched (implementation_launched_at set) -- restaging would strand
          already-spawned implementation jobs
        - Orchestrator execution must not be actively running ('working'/'blocked')

    Actions:
        - Resets staging_status to null
        - Clears mission, releasing the execution_mode lock
        - Preserves the project's chosen execution_mode (no longer
          force-reset to 'multi_terminal')
        - Clears implementation_launched_at
        - Decommissions existing orchestrator
        - Creates fresh orchestrator fixture

    Args:
        project_id: Project UUID
        current_user: Authenticated user (from dependency)
        project_service: Project service (from dependency)

    Returns:
        Dict with success message and project_id

    Raises:
        HTTPException 404: Project not found
        HTTPException 409: Invalid state for restage
    """
    logger.info(
        "Restage requested", extra={"user": sanitize(current_user.username), "project_id": sanitize(project_id)}
    )

    try:
        result = await project_service.lifecycle.restage(project_id=project_id)
    except ResourceNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        ) from e
    except ProjectStateError as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(e),
        ) from e

    logger.info("Restage completed", extra={"project_id": sanitize(project_id)})

    return {"message": result["message"], "project_id": result["project_id"]}


@router.post("/{project_id}/reset")
async def reset_project(
    project_id: IdPath,
    current_user: User = Depends(get_current_active_user),
    project_service: ProjectService = Depends(get_project_service),
) -> dict:
    """Reset a project to its original pre-stage state (destructive rewind).

    The "Reset" escape hatch — unconditionally clears the staging artifacts
    (staging_status / mission / implementation_launched_at), sets status=inactive,
    and HARD-DELETES all agent jobs/executions for the project (no audit trail;
    Terminate is the audit-preserving graceful exit). Works on a launched project
    where /restage refuses. Idempotent. 404 if the project is not found.
    """
    logger.info("Reset requested", extra={"user": sanitize(current_user.username), "project_id": sanitize(project_id)})
    try:
        result = await project_service.lifecycle.reset_to_prestage(
            project_id=project_id, tenant_key=current_user.tenant_key
        )
    except ResourceNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e

    logger.info("Reset completed", extra={"project_id": sanitize(project_id), "deleted": result.get("deleted")})
    return {"message": result["message"], "project_id": result["project_id"], "deleted": result.get("deleted")}


@router.post("/{project_id}/unstage")
async def unstage_project(
    project_id: IdPath,
    current_user: User = Depends(get_current_active_user),
    project_service: ProjectService = Depends(get_project_service),
) -> dict:
    """
    Unstage a project — revert from 'staged' back to ready state.

    Only allowed when staging_status == 'staged' (prompt generated but agent
    has not yet been launched).  Once the agent is launched the status moves to
    'staging', which is handled by /restage instead of this endpoint.

    Clears mission, releasing the execution_mode lock so the user can
    re-pick the orchestration mode after unstaging.
    """
    logger.info(
        "Unstage requested", extra={"user": sanitize(current_user.username), "project_id": sanitize(project_id)}
    )

    try:
        result = await project_service.lifecycle.unstage(project_id=project_id)
    except ResourceNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e
    except ProjectStateError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e)) from e

    logger.info("Unstage completed", extra={"project_id": sanitize(project_id)})

    return {"message": result["message"], "project_id": result["project_id"]}


@router.delete("/deleted", response_model=ProjectPurgeResponse)
async def purge_all_deleted_projects(
    product_id: IdQuery = None,
    current_user: User = Depends(get_current_active_user),
    project_service: ProjectService = Depends(get_project_service),
) -> ProjectPurgeResponse:
    """
    Permanently delete all soft-deleted projects for the current tenant,
    optionally scoped to a product.
    """
    logger.info(
        "User %s purging all deleted projects (product=%s)",
        sanitize(current_user.username),
        sanitize(product_id),
    )

    result = await project_service.deletion.purge_all_deleted_projects(product_id=product_id)

    projects = [PurgedProject(**proj) for proj in result.projects]
    return ProjectPurgeResponse(
        success=True,
        purged_count=result.purged_count,
        projects=projects,
        message="Deleted projects purged successfully",
    )


@router.delete("/{project_id}/purge", response_model=ProjectPurgeResponse)
async def purge_deleted_project(
    project_id: IdPath,
    current_user: User = Depends(get_current_active_user),
    project_service: ProjectService = Depends(get_project_service),
) -> ProjectPurgeResponse:
    """
    Immediately perform nuclear delete on a specific soft-deleted project.

    This is triggered when user clicks the trash icon next to a deleted project.
    Performs complete removal of project and ALL associated data immediately.
    """
    logger.info(
        "User %s performing NUCLEAR PURGE on deleted project %s",
        sanitize(current_user.username),
        sanitize(project_id),
    )

    result = await project_service.deletion.nuclear_delete_project(project_id)

    project_info = {"id": project_id, "name": result.project_name, "tenant_key": current_user.tenant_key}

    return ProjectPurgeResponse(
        success=True,
        purged_count=1,
        projects=[PurgedProject(**project_info)],
        message=f"Project permanently deleted. Removed: {result.deleted_counts}",
    )


@router.post("/{project_id}/archive", response_model=ProjectResponse)
async def archive_project(
    project_id: IdPath,
    current_user: User = Depends(get_current_active_user),
    project_service: ProjectService = Depends(get_project_service),
) -> ProjectResponse:
    """
    Archive a completed project.

    Marks project as 'completed' and sets completed_at timestamp.
    This is used when the user confirms project closeout and wants to archive it
    without continuing work.

    Args:
        project_id: Project UUID
        current_user: Authenticated user (from dependency)
        project_service: Project service (from dependency)

    Returns:
        ProjectResponse with archived project

    Raises:
        HTTPException 404: Project not found
        HTTPException 400: Archive failed
    """
    logger.info("User %s archiving project %s", sanitize(current_user.username), sanitize(project_id))

    await project_service.archive_project(project_id=project_id, tenant_key=current_user.tenant_key, force=True)

    logger.info("Archived project %s", sanitize(project_id))

    proj = await project_service.get_project(project_id=project_id, tenant_key=current_user.tenant_key)

    return _build_project_response(proj)


@router.post("/{project_id}/reviewed", response_model=ProjectReviewedResponse)
async def mark_project_reviewed(
    project_id: IdPath,
    current_user: User = Depends(get_current_active_user),
    project_service: ProjectService = Depends(get_project_service),
) -> ProjectReviewedResponse:
    """
    Record that you reviewed a finished project.

    The Review window's Close button calls this so the project leaves the Jobs
    board's "Done, not reviewed" group. Repeating the call keeps the first review
    time. A project that has not finished is refused with 409.
    """
    reviewed_at = await project_service.mark_project_reviewed(project_id=project_id, tenant_key=current_user.tenant_key)
    return ProjectReviewedResponse(id=project_id, reviewed_at=reviewed_at)


@router.delete("/{project_id}", response_model=ProjectDeleteResponse)
async def delete_project(
    project_id: IdPath,
    current_user: User = Depends(get_current_active_user),
    project_service: ProjectService = Depends(get_project_service),
) -> ProjectDeleteResponse:
    """
    Soft delete a project.

    Marks the project as status='deleted' and sets deleted_at. Purging after 10 days
    is handled by ProjectService.purge_expired_deleted_projects().
    """
    logger.info("User %s deleting project %s", sanitize(current_user.username), sanitize(project_id))

    result = await project_service.deletion.delete_project(project_id)

    return ProjectDeleteResponse(
        success=True,
        message=result.message,
        deleted_at=result.deleted_at,
    )


@router.post("/{project_id}/launch", response_model=ProjectLaunchResponse)
async def launch_project(
    project_id: IdPath,
    launch_config: dict[str, Any | None] = None,
    current_user: User = Depends(get_current_active_user),
    project_service: ProjectService = Depends(get_project_service),
) -> ProjectLaunchResponse:
    """
    Launch project orchestrator.

    Creates orchestrator agent job and generates thin-client launch prompt.
    Activates the project if not already active.

    Args:
        project_id: Project UUID
        launch_config: Optional launch configuration
        current_user: Authenticated user (from dependency)
        project_service: Project service (from dependency)

    Returns:
        ProjectLaunchResponse with orchestrator job ID and launch prompt

    Raises:
        HTTPException 404: Project not found
        HTTPException 400: Launch failed
    """
    logger.info("User %s launching project %s", sanitize(current_user.username), sanitize(project_id))

    launch_data = await project_service.launch_project(
        project_id=project_id, user_id=str(current_user.id), launch_config=launch_config
    )

    logger.info("Launched project %s", sanitize(project_id))

    return ProjectLaunchResponse(
        project_id=launch_data.project_id,
        orchestrator_job_id=launch_data.orchestrator_job_id,
        launch_prompt=launch_data.launch_prompt,
        status=launch_data.status,
    )
