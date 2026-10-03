# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from api.endpoints._boundary_types import IdPath
from giljo_mcp.auth.dependencies import get_current_active_user, get_db_session
from giljo_mcp.models import User
from giljo_mcp.models.schemas import ProjectSummaryResponse
from giljo_mcp.services.project_service import ProjectService
from giljo_mcp.utils.log_sanitizer import sanitize

from .dependencies import get_project_service
from .models import OrchestratorResponse


logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/{project_id}/summary", response_model=ProjectSummaryResponse)
async def get_project_summary(
    project_id: IdPath,
    current_user: User = Depends(get_current_active_user),
    project_service: ProjectService = Depends(get_project_service),
) -> ProjectSummaryResponse:
    """
    Get comprehensive project summary with metrics.

    Returns project overview including job statistics, completion metrics,
    and activity timestamps for dashboard display.

    Args:
        project_id: Project UUID
        current_user: Authenticated user (from dependency)
        project_service: Project service (from dependency)

    Returns:
        ProjectSummaryResponse with project metrics and status

    Raises:
        HTTPException 404: Project not found
        HTTPException 500: Internal server error
    """
    logger.debug("User %s getting summary for project %s", sanitize(current_user.username), sanitize(project_id))

    summary_data = await project_service.summary.get_project_summary(
        project_id=project_id, tenant_key=current_user.tenant_key
    )

    logger.info("Retrieved summary for project %s", sanitize(project_id))

    return ProjectSummaryResponse(
        id=summary_data.id,
        name=summary_data.name,
        status=summary_data.status,
        mission=summary_data.mission,
        total_jobs=summary_data.total_jobs,
        completed_jobs=summary_data.completed_jobs,
        blocked_jobs=summary_data.blocked_jobs,
        active_jobs=summary_data.active_jobs,
        pending_jobs=summary_data.pending_jobs,
        completion_percentage=summary_data.completion_percentage,
        created_at=summary_data.created_at,
        last_activity_at=summary_data.last_activity_at,
        product_id=summary_data.product_id,
        product_name=summary_data.product_name,
    )


@router.get("/{project_id}/orchestrator", response_model=OrchestratorResponse)
async def get_project_orchestrator(
    project_id: IdPath,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db_session),
) -> OrchestratorResponse:
    """
    Get the orchestrator job for a project.

    Returns the orchestrator AgentExecution (executor) with AgentJob (work order) data.
    Supports orchestrator succession - returns latest instance.
    If no orchestrator exists, creates one automatically using the dual-model pattern.

    Migration:
    - Queries AgentExecution joined with AgentJob (legacy model removed)
    - Creates BOTH AgentJob (work order) + AgentExecution (executor instance)
    - Response maps from AgentExecution fields + AgentJob.mission

    Args:
        project_id: Project UUID or alias
        current_user: Authenticated user (from dependency)
        db: Database session (from dependency)

    Returns:
        Orchestrator job data with full job_id/agent_id

    Raises:
        HTTPException 404: Project not found
        HTTPException 500: Database error

    Note:
        Removed auto-creation. Returns null orchestrator if none exists.
        Frontend shows "Re-launch Orchestrator" button when orchestrator is null.
    """
    from sqlalchemy import select
    from sqlalchemy.orm import joinedload

    from giljo_mcp.harness_resolver import _detected_harness_from_session
    from giljo_mcp.models import Project
    from giljo_mcp.models.agent_identity import AgentExecution, AgentJob
    from giljo_mcp.models.auth import MCPSession

    logger.debug("User %s getting orchestrator for project %s", sanitize(current_user.username), sanitize(project_id))

    project_stmt = select(Project).where(Project.id == project_id, Project.tenant_key == current_user.tenant_key)
    project_result = await db.execute(project_stmt)
    project = project_result.scalar_one_or_none()

    if not project:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Project not found: {project_id}")

    orch_stmt = (
        select(AgentExecution)
        .options(joinedload(AgentExecution.job))
        .join(AgentJob, AgentExecution.job_id == AgentJob.job_id)
        .where(
            AgentJob.project_id == project_id,
            AgentExecution.agent_display_name == "orchestrator",
            AgentExecution.tenant_key == current_user.tenant_key,
            AgentExecution.status.in_(["waiting", "working", "blocked", "complete", "handed_over"]),
        )
        .order_by(AgentExecution.started_at.desc())
    )
    orch_result = await db.execute(orch_stmt)
    orchestrator_execution = orch_result.scalars().first()

    if not orchestrator_execution:
        logger.info(
            "No orchestrator found for project %s (user: %s)", sanitize(project_id), sanitize(current_user.username)
        )
        return OrchestratorResponse(success=True, orchestrator=None)

    logger.info(
        "Retrieved orchestrator execution %s (job: %s) for project %s",
        sanitize(str(orchestrator_execution.agent_id)),
        sanitize(str(orchestrator_execution.job_id)),
        sanitize(project_id),
    )

    session_stmt = (
        select(MCPSession)
        .where(MCPSession.project_id == project_id, MCPSession.tenant_key == current_user.tenant_key)
        .order_by(MCPSession.last_accessed.desc())
    )
    session_result = await db.execute(session_stmt)
    mcp_session = session_result.scalars().first()
    detected_harness = _detected_harness_from_session(mcp_session)

    from .models import OrchestratorJobResponse

    return OrchestratorResponse(
        success=True,
        orchestrator=OrchestratorJobResponse(
            job_id=orchestrator_execution.job_id,
            agent_id=orchestrator_execution.agent_id,
            agent_display_name=orchestrator_execution.agent_display_name,
            agent_name=orchestrator_execution.agent_name,
            mission=orchestrator_execution.job.mission,
            status=orchestrator_execution.status,
            progress=orchestrator_execution.progress,
            tool_type=orchestrator_execution.tool_type,
            created_at=orchestrator_execution.started_at or orchestrator_execution.job.created_at,
            started_at=orchestrator_execution.started_at,
            completed_at=orchestrator_execution.completed_at,
            detected_harness=detected_harness,
        ),
    )
