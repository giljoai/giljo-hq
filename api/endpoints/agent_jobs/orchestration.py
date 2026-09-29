# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import logging
from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from api.dependencies.websocket import WebSocketDependency, get_websocket_dependency
from giljo_mcp.auth.dependencies import get_current_active_user, get_db_session
from giljo_mcp.exceptions import ResourceNotFoundError
from giljo_mcp.models import Project, User
from giljo_mcp.models.agent_identity import AgentExecution, AgentJob
from giljo_mcp.services.project_staging_service import ProjectStagingService
from giljo_mcp.utils.log_sanitizer import sanitize

from .dependencies import get_db_manager, get_tenant_manager


logger = logging.getLogger(__name__)
router = APIRouter()




class LaunchProjectRequest(BaseModel):
    """Request model for project launch."""

    project_id: UUID


class AgentInfo(BaseModel):
    """Agent information for launch response."""

    agent_id: str
    job_id: str
    agent_display_name: str
    agent_name: str | None
    status: str
    mission: str
    tool_type: str
    progress: int


class LaunchProjectResponse(BaseModel):
    """Response model for project launch."""

    success: bool
    project_id: str
    staging_status: str
    agent_count: int
    agents: list[AgentInfo]
    message: str | None = None




@router.post("/launch-project", response_model=LaunchProjectResponse)
async def launch_project(
    request: LaunchProjectRequest,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db_session),
    ws_dep: WebSocketDependency = Depends(get_websocket_dependency),
) -> LaunchProjectResponse:
    """
    Launch a staged project - transition from staging to execution phase.

    Called when user clicks "Launch Jobs" button after staging completes.
    Validates project has mission and agents, then transitions to 'launching' status.

    Handover 0109 Agent 1 - Project Launch Endpoint

    Args:
        request: LaunchProjectRequest with project_id
        current_user: Authenticated user (from dependency)
        db: Database session (from dependency)
        ws_dep: WebSocket dependency for broadcasting (from dependency)

    Returns:
        LaunchProjectResponse with agent data and updated status

    Raises:
        HTTPException 404: Project not found or soft-deleted
        HTTPException 400: Project missing mission or no agents spawned
    """
    project_id_str = str(request.project_id)
    logger.info("Launch project requested for %s by %s", sanitize(project_id_str), sanitize(current_user.username))

    stmt = select(Project).where(
        Project.id == project_id_str,
        Project.tenant_key == current_user.tenant_key,
    )
    result = await db.execute(stmt)
    project = result.scalar_one_or_none()

    if not project or project.deleted_at is not None:
        logger.warning(
            "Project %s not found for tenant %s", sanitize(project_id_str), sanitize(current_user.tenant_key)
        )
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")

    if not project.mission or project.mission.strip() == "":
        logger.error("Project %s has no mission", sanitize(project_id_str))
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Project mission has not been created. Please complete staging first.",
        )

    agent_stmt = (
        select(AgentExecution)
        .options(joinedload(AgentExecution.job))
        .join(AgentJob, AgentExecution.job_id == AgentJob.job_id)
        .where(
            AgentJob.project_id == project_id_str,
            AgentExecution.tenant_key == current_user.tenant_key,
        )
    )
    agent_result = await db.execute(agent_stmt)
    agents = agent_result.scalars().all()

    if not agents:
        logger.error("Project %s has no spawned agents", sanitize(project_id_str))
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No agents have been spawned for this project. Please complete staging first.",
        )

    project.updated_at = datetime.now(UTC)

    try:
        await db.commit()
        await db.refresh(project)
        logger.info("Project %s launching implementation (%d agents)", sanitize(project_id_str), len(agents))
    except Exception as e:
        await db.rollback()
        logger.exception("Failed to update project status")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to launch project due to database error"
        ) from e

    agent_info_list = [
        AgentInfo(
            agent_id=str(agent.agent_id),
            job_id=agent.job_id,
            agent_display_name=agent.agent_display_name,
            agent_name=agent.agent_name,
            status=agent.status,
            mission=agent.job.mission,
            tool_type=agent.tool_type,
            progress=agent.progress,
        )
        for agent in agents
    ]

    try:
        await ws_dep.broadcast_to_tenant(
            tenant_key=current_user.tenant_key,
            event_type="project:launched",
            data={
                "project_id": project_id_str,
                "staging_status": project.staging_status,
                "agent_count": len(agents),
                "timestamp": datetime.now(UTC).isoformat(),
                "launched_by": current_user.username,
            },
        )
        logger.info("WebSocket event 'project:launched' broadcasted for %s", sanitize(project_id_str))
    except Exception as _exc:
        logger.exception("Failed to broadcast WebSocket event")

    return LaunchProjectResponse(
        success=True,
        project_id=project_id_str,
        staging_status=project.staging_status,
        agent_count=len(agents),
        agents=agent_info_list,
        message=f"Project launched successfully with {len(agents)} agents",
    )




class LaunchImplementationResponse(BaseModel):
    """Response model for launch implementation."""

    success: bool = True
    implementation_launched_at: str | None = None
    already_launched: bool | None = None
    launched_at: str | None = None
    thread_id: str | None = Field(None, description="The project's coordination thread id")
    chat_id: str | None = Field(None, description="The coordination thread's short handle, for example CHT-0042")


@router.patch("/projects/{project_id}/launch-implementation", response_model=LaunchImplementationResponse)
async def launch_implementation(
    project_id: str,
    current_user: User = Depends(get_current_active_user),
    db_manager=Depends(get_db_manager),
    tenant_manager=Depends(get_tenant_manager),
    ws_dep: WebSocketDependency = Depends(get_websocket_dependency),
) -> LaunchImplementationResponse:
    """
    Set implementation_launched_at timestamp (phase gate release) — UI door.

    Called when the user clicks 'Implement' in the dashboard. Allows agents to
    receive their missions via get_job_mission().

    BE-6115a: this is the UI half of the two-door implement gate. It no longer
    raw-writes implementation_launched_at inline — both doors (this button and
    the launch_implementation MCP/CLI tool) flip the flag through the ONE shared
    single-writer ``ProjectStagingService.launch_implementation`` (no parallel
    write path). The human gate stays sacred; this endpoint IS the human
    authorization for the UI door.

    Handover 0709: Implementation phase gate.

    Args:
        project_id: Project ID to launch implementation for.
        current_user: Authenticated user (from dependency).

    Returns:
        LaunchImplementationResponse with timestamp.

    Raises:
        HTTPException 404: Project not found or tenant isolation violation.
    """
    logger.info(
        "Launch implementation requested for project %s by %s", sanitize(project_id), sanitize(current_user.username)
    )

    staging_service = ProjectStagingService(
        db_manager=db_manager,
        tenant_manager=tenant_manager,
        websocket_manager=ws_dep,
    )

    try:
        result = await staging_service.launch_implementation(
            project_id=project_id,
            tenant_key=current_user.tenant_key,
            launched_by=current_user.username,
            origin="ui",
        )
    except ResourceNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found") from exc

    if result["already_launched"]:
        logger.info("Project %s already launched at %s", sanitize(project_id), result["launched_at"])
        return LaunchImplementationResponse(
            already_launched=True,
            launched_at=result["launched_at"],
            implementation_launched_at=result["implementation_launched_at"],
            thread_id=result.get("thread_id"),
            chat_id=result.get("chat_id"),
        )

    logger.info(
        "Implementation launched for project %s at %s", sanitize(project_id), result["implementation_launched_at"]
    )
    return LaunchImplementationResponse(
        success=True,
        implementation_launched_at=result["implementation_launched_at"],
        launched_at=result["launched_at"],
        thread_id=result.get("thread_id"),
        chat_id=result.get("chat_id"),
    )
