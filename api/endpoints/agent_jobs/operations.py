# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import logging

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies.websocket import WebSocketDependency, get_websocket_dependency
from api.endpoints._boundary_types import IdPath
from giljo_mcp.auth.dependencies import get_current_active_user, get_db_session
from giljo_mcp.models import User
from giljo_mcp.services.job_query_service import JobQueryService
from giljo_mcp.services.orchestration_service import OrchestrationService
from giljo_mcp.utils.log_sanitizer import sanitize

from .dependencies import get_job_query_service, get_orchestration_service
from .models import (
    UpdateMissionRequest,
    UpdateMissionResponse,
)


logger = logging.getLogger(__name__)
router = APIRouter()


@router.patch("/{job_id}/mission")
async def update_agent_mission(
    job_id: IdPath,
    request: UpdateMissionRequest,
    current_user: User = Depends(get_current_active_user),
    orchestration_service: OrchestrationService = Depends(get_orchestration_service),
    session: AsyncSession = Depends(get_db_session),
    job_query_service: JobQueryService = Depends(get_job_query_service),
    ws_dep: WebSocketDependency = Depends(get_websocket_dependency),
) -> UpdateMissionResponse:
    """
    Update agent mission with validation and WebSocket broadcast.

    Sprint 003c: Write routed through MissionService (no direct session.commit).

    Args:
        job_id: Job ID to update
        request: Update request with new mission text
        current_user: Authenticated user (from dependency)
        orchestration_service: Service for mission updates
        session: Database session (read-only, for WebSocket context)

    Returns:
        UpdateMissionResponse with success status and updated mission

    Raises:
        ResourceNotFoundError: Job not found
        HTTPException 422: Validation error (empty or too long)
    """
    logger.debug("User %s updating mission for job %s", sanitize(current_user.username), sanitize(job_id))

    result = await orchestration_service.update_agent_mission(
        job_id=job_id,
        tenant_key=current_user.tenant_key,
        mission=request.mission,
    )

    logger.info(
        "Mission updated for job %s by user %s. New length: %d chars",
        sanitize(job_id),
        sanitize(current_user.username),
        result.mission_length,
    )

    job = await job_query_service.get_agent_job_by_job_id(
        tenant_key=current_user.tenant_key,
        job_id=job_id,
        session=session,
    )
    current_execution = await job_query_service.get_latest_execution_for_job(
        tenant_key=current_user.tenant_key,
        job_id=job_id,
        session=session,
    )

    await ws_dep.broadcast_to_tenant(
        tenant_key=current_user.tenant_key,
        event_type="agent:mission_updated",
        data={
            "job_id": job_id,
            "agent_display_name": current_execution.agent_display_name
            if current_execution
            else (job.job_type if job else "unknown"),
            "agent_name": current_execution.agent_name if current_execution else None,
            "mission": request.mission,
            "project_id": str(job.project_id) if job and job.project_id else None,
        },
    )

    return UpdateMissionResponse(
        success=True,
        job_id=job_id,
        mission=request.mission,
    )
