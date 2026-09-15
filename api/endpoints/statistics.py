# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import logging
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel

from giljo_mcp.auth.dependencies import get_current_active_user
from giljo_mcp.models import User
from giljo_mcp.services.statistics_service import StatisticsService


logger = logging.getLogger(__name__)


router = APIRouter()


class SystemStatsResponse(BaseModel):
    total_projects: int
    active_projects: int
    completed_projects: int
    total_agents: int
    active_agents: int
    total_messages: int
    pending_messages: int
    total_tasks: int
    completed_tasks: int
    database_size_mb: float
    uptime_seconds: float
    total_agents_spawned: int
    total_jobs_completed: int
    projects_finished: int
    projects_staged: int
    projects_cancelled: int


class CallCountsResponse(BaseModel):
    total_api_calls: int
    total_mcp_calls: int


startup_time = datetime.now(UTC)


class AgentRoleDistItem(BaseModel):
    """Single entry in the agent role distribution chart."""

    label: str
    count: int
    color: str
    is_active: bool


class DashboardStatsResponse(BaseModel):
    """Response model for the consolidated dashboard analytics endpoint (Handover 0839)."""

    project_status_dist: dict[str, int]
    taxonomy_dist: list[dict]
    agent_role_dist: list[AgentRoleDistItem]
    recent_projects: list[dict]
    recent_memories: list[dict]
    task_status_dist: dict[str, int]
    execution_mode_dist: dict[str, int]
    products: list[dict]
    total_commits: int = 0


@router.get("/dashboard", response_model=DashboardStatsResponse)
async def get_dashboard_stats(
    request: Request,
    product_id: str | None = Query(None, description="Filter by product (None = all products)"),
    current_user: User = Depends(get_current_active_user),
):
    """
    Consolidated dashboard analytics endpoint (Handover 0839).

    Returns project status distribution, taxonomy distribution, agent role
    distribution, recent projects, recent 360 memories, task status distribution,
    and per-product project counts -- all in a single request.

    All data is filtered by tenant_key for isolation. Optional product_id
    narrows results to a specific product.
    """
    from api.app_state import state

    tenant_key = getattr(request.state, "tenant_key", None)
    if not tenant_key:
        raise HTTPException(status_code=400, detail="Tenant key not found in request state")

    if not state.db_manager:
        raise HTTPException(status_code=503, detail="Database not available")

    stats_service = StatisticsService(state.db_manager)
    data = await stats_service.get_dashboard_stats(tenant_key, product_id=product_id)

    return DashboardStatsResponse(**data)


@router.get("/call-counts", response_model=CallCountsResponse)
async def get_call_counts(request: Request, current_user: User = Depends(get_current_active_user)):
    """Get total API and MCP call counts."""
    from api.app_state import state

    tenant_key = getattr(request.state, "tenant_key", None)
    if not tenant_key:
        raise HTTPException(status_code=400, detail="Tenant key not found in request state")

    db_api_calls = 0
    db_mcp_calls = 0

    if state.db_manager:
        stats_service = StatisticsService(state.db_manager)
        metrics = await stats_service.get_api_metrics(tenant_key)
        if metrics:
            db_api_calls = metrics.total_api_calls
            db_mcp_calls = metrics.total_mcp_calls

    in_memory_api_calls = state.api_call_count.get(tenant_key, 0)
    in_memory_mcp_calls = state.mcp_call_count.get(tenant_key, 0)

    return CallCountsResponse(
        total_api_calls=db_api_calls + in_memory_api_calls,
        total_mcp_calls=db_mcp_calls + in_memory_mcp_calls,
    )


@router.get("/system", response_model=SystemStatsResponse)
async def get_system_statistics(request: Request, current_user: User = Depends(get_current_active_user)):
    """Get overall system statistics"""
    from api.app_state import state

    tenant_key = getattr(request.state, "tenant_key", None)
    if not tenant_key:
        raise HTTPException(status_code=400, detail="Tenant key not found in request state")

    if not state.db_manager:
        raise HTTPException(status_code=503, detail="Database not available")

    stats_service = StatisticsService(state.db_manager)
    data = await stats_service.get_system_stats(tenant_key)

    uptime = (datetime.now(UTC) - startup_time).total_seconds()

    return SystemStatsResponse(
        total_projects=data["total_projects"],
        active_projects=data["active_projects"],
        completed_projects=data["completed_projects"],
        projects_finished=data["completed_projects"],
        projects_staged=data["projects_staged"],
        projects_cancelled=data["projects_cancelled"],
        total_agents=data["total_agents"],
        active_agents=data["active_agents"],
        total_messages=data["total_messages"],
        pending_messages=data["pending_messages"],
        total_tasks=data["total_tasks"],
        completed_tasks=data["completed_tasks"],
        database_size_mb=0,
        uptime_seconds=uptime,
        total_agents_spawned=data["total_agents_spawned"],
        total_jobs_completed=data["total_jobs_completed"],
    )
