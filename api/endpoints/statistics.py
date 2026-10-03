# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import logging
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel

from api.endpoints._boundary_types import ID_MAX
from giljo_mcp.auth.dependencies import get_current_active_user
from giljo_mcp.models import User
from giljo_mcp.services.statistics_service import StatisticsService


logger = logging.getLogger(__name__)


router = APIRouter()


def _tenant_and_stats(request: Request) -> tuple[str, StatisticsService]:
    from api.app_state import state

    tenant_key = getattr(request.state, "tenant_key", None)
    if not tenant_key:
        raise HTTPException(status_code=400, detail="Tenant key not found in request state")
    if not state.db_manager:
        raise HTTPException(status_code=503, detail="Database not available")
    return tenant_key, StatisticsService(state.db_manager)


class CallCountsResponse(BaseModel):
    total_api_calls: int
    total_mcp_calls: int


class McpToolCallCount(BaseModel):
    tool_name: str
    total_calls: int


class McpToolCallCountsResponse(BaseModel):
    window_days: int
    tools: list[McpToolCallCount]


class AgentRoleDistItem(BaseModel):
    """Single entry in the agent role distribution chart."""

    label: str
    count: int
    color: str
    is_active: bool


class DashboardStatsResponse(BaseModel):
    """Response model for the consolidated dashboard analytics endpoint."""

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
    product_id: str | None = Query(None, max_length=ID_MAX, description="Filter by product (None = all products)"),
    current_user: User = Depends(get_current_active_user),
):
    """
    Consolidated dashboard analytics endpoint.

    Returns project status distribution, taxonomy distribution, agent role
    distribution, recent projects, recent 360 memories, task status distribution,
    and per-product project counts -- all in a single request.

    All data is filtered by tenant_key for isolation. Optional product_id
    narrows results to a specific product.
    """
    tenant_key, stats_service = _tenant_and_stats(request)
    data = await stats_service.get_dashboard_stats(tenant_key, product_id=product_id)

    return DashboardStatsResponse(**data)


@router.get("/call-counts", response_model=CallCountsResponse)
async def get_call_counts(request: Request, current_user: User = Depends(get_current_active_user)):
    """Get total API and MCP call counts."""
    from api.app_state import state

    tenant_key, stats_service = _tenant_and_stats(request)
    db_api_calls = 0
    db_mcp_calls = 0
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


@router.get("/mcp-tool-calls", response_model=McpToolCallCountsResponse)
async def get_mcp_tool_call_counts(
    request: Request,
    days: int = Query(30, ge=1, le=365, description="Trailing window in days."),
    current_user: User = Depends(get_current_active_user),
):
    """How many times each MCP tool was called, over a trailing window.

    Read the bottom of the list: a tool with no calls over a long window is one
    nobody uses, and its description is costing every agent on every call.
    """
    from api.app_state import state

    tenant_key, stats_service = _tenant_and_stats(request)
    tools = {
        row["tool_name"]: row["total_calls"] for row in await stats_service.get_mcp_tool_call_counts(tenant_key, days)
    }

    cutoff = datetime.now(UTC).date() - timedelta(days=days - 1)
    for (buffered_tenant, tool_name, day), count in state.mcp_tool_call_count.items():
        if buffered_tenant == tenant_key and day >= cutoff:
            tools[tool_name] = tools.get(tool_name, 0) + count

    ordered = sorted(tools.items(), key=lambda item: (-item[1], item[0]))
    return McpToolCallCountsResponse(
        window_days=days,
        tools=[McpToolCallCount(tool_name=name, total_calls=count) for name, count in ordered],
    )
