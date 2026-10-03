# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import logging

from fastapi import APIRouter, Depends, HTTPException, status

from giljo_mcp.auth.dependencies import get_current_active_user
from giljo_mcp.models import User
from giljo_mcp.services.orchestration_service import OrchestrationService
from giljo_mcp.utils.log_sanitizer import sanitize

from .dependencies import get_orchestration_service
from .models import (
    SpawnAgentRequest,
    SpawnAgentResponse,
)


logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/spawn", response_model=SpawnAgentResponse, status_code=status.HTTP_201_CREATED)
async def spawn_job(
    request: SpawnAgentRequest,
    current_user: User = Depends(get_current_active_user),
    orchestration_service: OrchestrationService = Depends(get_orchestration_service),
) -> SpawnAgentResponse:
    """
    Spawn a new agent job.

    Uses OrchestrationService to create agent job with thin client architecture.
    The service broadcasts the one agent:created event for real-time UI updates.

    Args:
        request: Spawn request with agent details
        current_user: Authenticated user (from dependency)
        orchestration_service: Service for job operations (from dependency)

    Returns:
        SpawnAgentResponse with job ID and prompt

    Raises:
        HTTPException 403: User not authorized
        HTTPException 400: Invalid request or spawn failed
    """
    logger.debug(
        "User %s spawning agent job: %s", sanitize(current_user.username), sanitize(request.agent_display_name)
    )

    if current_user.role != "admin":
        logger.warning(
            "User %s (role=%s) attempted to spawn agent", sanitize(current_user.username), sanitize(current_user.role)
        )
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required to spawn agents")

    result = await orchestration_service.spawn_job(
        agent_display_name=request.agent_display_name,
        agent_name=request.agent_name or request.agent_display_name,
        mission=request.mission,
        project_id=request.project_id,
        tenant_key=current_user.tenant_key,
        parent_job_id=request.parent_job_id,
        context_chunks=request.context_chunks,
    )

    logger.info("Spawned agent job %s for tenant %s", sanitize(str(result.job_id)), sanitize(current_user.tenant_key))

    return SpawnAgentResponse(
        success=True,
        job_id=result.job_id,
        agent_prompt=result.agent_prompt,
        mission_stored=result.mission_stored,
        thin_client=result.thin_client,
    )
