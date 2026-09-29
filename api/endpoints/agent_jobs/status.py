# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import logging

from fastapi import APIRouter, Depends, Query

from giljo_mcp.auth.dependencies import get_current_active_user
from giljo_mcp.models import User
from giljo_mcp.services.orchestration_service import OrchestrationService
from giljo_mcp.utils.log_sanitizer import sanitize

from .dependencies import get_orchestration_service
from .models import (
    JobListResponse,
    JobResponse,
    TodoItemResponse,
)


logger = logging.getLogger(__name__)
router = APIRouter()


def job_to_response(job: dict) -> JobResponse:
    todo_items_raw = job.get("todo_items", [])
    todo_items = [
        TodoItemResponse(content=item.get("content", ""), status=item.get("status", "pending"))
        for item in todo_items_raw
        if isinstance(item, dict)
    ]

    return JobResponse(
        id=job.get("agent_id", job.get("id", "")),
        job_id=job["job_id"],
        agent_id=job.get("agent_id"),
        execution_id=job.get("execution_id"),
        tenant_key=job["tenant_key"],
        project_id=job.get("project_id"),
        chain_conductor=bool(job.get("chain_conductor", False)),
        agent_display_name=job["agent_display_name"],
        agent_name=job.get("agent_name"),
        mission=job["mission"],
        status=job["status"],
        progress=job.get("progress", 0),
        spawned_by=job.get("spawned_by"),
        tool_type=job.get("tool_type", "universal"),
        context_chunks=job.get("context_chunks", []),
        messages_sent_count=job.get("messages_sent_count", 0),
        messages_waiting_count=job.get("messages_waiting_count", 0),
        action_required_unread=job.get("action_required_unread", 0),
        messages_read_count=job.get("messages_read_count", 0),
        started_at=job.get("started_at"),
        completed_at=job.get("completed_at"),
        created_at=job["created_at"],
        updated_at=job.get("updated_at"),
        steps=job.get("steps"),
        todo_items=todo_items,
        phase=job.get("phase"),
        result=job.get("result"),
        accumulated_duration_seconds=job.get("accumulated_duration_seconds", 0.0),
        duration_seconds=job.get("duration_seconds"),
        reactivation_count=job.get("reactivation_count", 0),
        not_picked_up=job.get("not_picked_up", False),
        activity=job.get("activity") or job.get("status", ""),
    )


@router.get("/", response_model=JobListResponse)
async def list_jobs(
    project_id: str | None = Query(None, description="Filter by project ID"),
    status: str | None = Query(
        None, description="Filter by status (waiting, working, blocked, complete, silent, decommissioned)"
    ),
    agent_display_name: str | None = Query(
        None, description="Filter by agent display name (orchestrator, implementer, etc.)"
    ),
    limit: int = Query(100, ge=1, le=500, description="Maximum results (default 100, max 500)"),
    offset: int = Query(0, ge=0, description="Pagination offset (default 0)"),
    current_user: User = Depends(get_current_active_user),
    orchestration_service: OrchestrationService = Depends(get_orchestration_service),
) -> JobListResponse:
    """
    List agent jobs with flexible filtering.

    All jobs are automatically filtered by the authenticated user's tenant_key
    for multi-tenant isolation. Additional filters can be applied via query params.

    Supports pagination for large result sets. Use offset/limit for paging.

    Args:
        project_id: Filter by project UUID (optional)
        status: Filter by job status (optional)
        agent_display_name: Filter by agent display name (optional)
        limit: Maximum results (default 100)
        offset: Pagination offset (default 0)
        current_user: Authenticated user (from dependency)
        orchestration_service: Service for job operations (from dependency)

    Returns:
        JobListResponse with jobs list and pagination metadata

    Raises:
        HTTPException 500: Failed to list jobs

    Example:
        GET /api/agent-jobs/?project_id=abc123&status=active&limit=50
    """
    logger.debug(
        "User %s listing jobs (project=%s, status=%s, type=%s, limit=%s, offset=%s)",
        sanitize(current_user.username),
        sanitize(project_id) if project_id else None,
        sanitize(status) if status else None,
        sanitize(agent_display_name) if agent_display_name else None,
        sanitize(limit),
        sanitize(offset),
    )

    result = await orchestration_service.list_jobs(
        tenant_key=current_user.tenant_key,
        project_id=project_id,
        status_filter=status,
        agent_display_name=agent_display_name,
        limit=limit,
        offset=offset,
    )

    logger.info(
        "Found %d jobs for user %s (total=%d, offset=%s)",
        len(result.jobs),
        sanitize(current_user.username),
        result.total,
        sanitize(offset),
    )

    job_responses = [job_to_response(job) for job in result.jobs]

    return JobListResponse(
        jobs=job_responses,
        total=result.total,
        limit=result.limit,
        offset=result.offset,
    )


@router.get("/{job_id}", response_model=JobResponse)
async def get_job(
    job_id: str,
    current_user: User = Depends(get_current_active_user),
    orchestration_service: OrchestrationService = Depends(get_orchestration_service),
) -> JobResponse:
    """
    Get job details by job_id.

    BE-9330: reads the job/execution ROW (same producer as the list endpoint
    above), not ``get_agent_mission``. The mission call returns a protocol
    payload built for agent delivery, and two of its properties made it unfit
    to back a details read: on the implementation-launch gate's BLOCKED branch
    it carries only job_id + block wording (so the REQUIRED ``created_at``
    arrived None and this route 500'd on any staging orchestrator), and it
    rejects any job whose execution is not 'active' (so a COMPLETED job 404'd
    "wrong_state" out of a read-only endpoint). Reading the row also drops the
    hand-written dict bridge that hardcoded ``completed_at=None`` -- which had
    the API report every finished agent as never having completed.

    Args:
        job_id: Job ID to retrieve
        current_user: Authenticated user (from dependency)
        orchestration_service: Service for job operations (from dependency)

    Returns:
        JobResponse with job details

    Raises:
        HTTPException 404: Job not found (includes multi-tenant isolation)
    """
    logger.debug("User %s getting job %s", sanitize(current_user.username), sanitize(job_id))

    job = await orchestration_service.get_job_detail(job_id=job_id, tenant_key=current_user.tenant_key)

    logger.info("Retrieved job %s for tenant %s", sanitize(job_id), sanitize(current_user.tenant_key))

    return job_to_response(job)
