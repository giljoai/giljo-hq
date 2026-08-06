# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
Task Management Tools -- @mcp.tool wrappers (BE-6042d split of mcp_sdk_server.py).

Mechanically extracted verbatim from the pre-split ``mcp_sdk_server.py``. Each
wrapper registers against the shared ``mcp`` instance from ``_base`` as a decorator
side effect at import time. Behavior, signatures, names, and descriptions unchanged.
"""

from typing import Annotated, Any, Literal

from mcp.server.fastmcp import Context
from pydantic import Field

from api.endpoints.mcp_tools._base import (
    MCP_DESCRIPTION_MAX,
    MCP_ID_MAX,
    MCP_NAME_MAX,
    _call_tool,
    mcp,
)
from api.endpoints.mcp_tools._tool_annotations import _tool_hints
from giljo_mcp import branding


@mcp.tool(
    title="Create Task",
    description=(
        "Create a new task (technical debt/TODO/bug/small fix) bound to the active product. Every "
        "task is auto-tagged 'TSK' (task_type is accepted-but-ignored); the serial auto-assigns in "
        "the TSK-nnnn form. Requires an active product. Use create_project instead for actionable multi-step "
        "work. See get_giljo_guide for the full task-vs-project routing recipe. "
        f"{branding.TWO_HUB_DISAMBIGUATION}"
    ),
    annotations=_tool_hints("create_task"),
)
async def create_task(
    title: Annotated[
        str, Field(max_length=MCP_NAME_MAX, description="Task title (required). Short, actionable description.")
    ],
    description: Annotated[
        str, Field(max_length=MCP_DESCRIPTION_MAX, description="Detailed task description (required).")
    ],
    priority: Annotated[
        Literal["low", "medium", "high", "critical"],
        Field(description="Priority: 'low', 'medium', 'high', or 'critical'. Default: 'medium'."),
    ] = "medium",
    task_type: Annotated[
        str,
        Field(
            max_length=MCP_NAME_MAX,
            description=(
                "Ignored. Tasks are always tagged 'TSK' (auto-assigned). Kept for backward "
                "compatibility; any value passed has no effect."
            ),
        ),
    ] = "",
    assigned_to: Annotated[str, Field(max_length=MCP_NAME_MAX, description="Optional assignee name.")] = "",
    ctx: Context = None,
) -> dict[str, Any]:
    kwargs: dict[str, Any] = {"title": title, "description": description, "priority": priority}
    if task_type:
        kwargs["task_type"] = task_type
    if assigned_to:
        kwargs["assigned_to"] = assigned_to
    return await _call_tool(ctx, "create_task", kwargs)


@mcp.tool(
    title="Update Task",
    description=(
        "Update task metadata (title, description, status, priority, due_date). Only provided "
        "fields are written. task_type is immutable ('TSK'). Pass status='completed' to complete "
        "it (stamps completed_at); pass completion_notes to append an audit note as it completes. "
        "Tenant-scoped. "
        f"{branding.TWO_HUB_DISAMBIGUATION}"
    ),
    # BE-9251: status accepts terminal values (completed/cancelled) -- see _tool_hints docstring.
    annotations=_tool_hints("update_task", destructive=True),
)
async def update_task(
    task_id: Annotated[str, Field(max_length=MCP_ID_MAX, description="Task UUID (required).")],
    title: Annotated[str, Field(max_length=MCP_NAME_MAX, description="New title; empty string keeps current.")] = "",
    description: Annotated[
        str, Field(max_length=MCP_DESCRIPTION_MAX, description="New description; empty string keeps current.")
    ] = "",
    status: Annotated[
        Literal["", "pending", "in_progress", "completed", "blocked", "cancelled"],
        Field(description="New status: pending|in_progress|completed|blocked|cancelled. Empty string keeps current."),
    ] = "",
    priority: Annotated[
        Literal["", "low", "medium", "high", "critical"],
        Field(description="New priority: low|medium|high|critical. Empty string keeps current."),
    ] = "",
    task_type: Annotated[
        str,
        Field(
            max_length=MCP_NAME_MAX,
            description="Ignored -- the task type is immutable ('TSK'). Any value passed is not written.",
        ),
    ] = "",
    due_date: Annotated[
        str, Field(max_length=MCP_ID_MAX, description="ISO 8601 due date; empty string keeps current.")
    ] = "",
    hidden: Annotated[
        str, Field(max_length=8, description="Per-row UI declutter flag: 'true'/'false'/'' (empty keeps current).")
    ] = "",
    completion_notes: Annotated[
        str,
        Field(
            max_length=MCP_DESCRIPTION_MAX,
            description=(
                "Optional audit-trail note appended to the task description when the task is "
                "completed (status='completed'). Folds in the retired complete_task tool; a "
                "note without status='completed' is a no-op."
            ),
        ),
    ] = "",
    ctx: Context = None,
) -> dict[str, Any]:
    params: dict[str, Any] = {"task_id": task_id}
    if title:
        params["title"] = title
    if description:
        params["description"] = description
    if status:
        params["status"] = status
    if priority:
        params["priority"] = priority
    if task_type:
        params["task_type"] = task_type
    if due_date:
        params["due_date"] = due_date
    if hidden != "":
        h = str(hidden).lower()
        if h in ("true", "1", "yes"):
            params["hidden"] = True
        elif h in ("false", "0", "no"):
            params["hidden"] = False
    if completion_notes:
        params["completion_notes"] = completion_notes
    return await _call_tool(ctx, "update_task", params)


@mcp.tool(
    title="List Tasks",
    description=(
        "List tasks for the active product. mode='summary' (default, light fields) or 'full' (all "
        "columns). Every task is tagged 'TSK' -- a non-TSK task_type filter matches nothing, "
        "normally omit it. hidden is UI declutter only (does not affect default visibility). "
        "Requires an active product. See get_giljo_guide for read-vs-write routing. "
        f"{branding.TWO_HUB_DISAMBIGUATION}"
    ),
    annotations=_tool_hints("list_tasks"),
)
async def list_tasks(
    mode: Annotated[
        Literal["summary", "full"],
        Field(description="Projection mode. Default 'summary'."),
    ] = "summary",
    status: Annotated[str, Field(description="Filter by exact status (e.g. 'pending').")] = "",
    priority: Annotated[str, Field(description="Filter by priority (low/medium/high/critical).")] = "",
    task_type: Annotated[
        str,
        Field(
            description=(
                "Filter by taxonomy abbreviation. All tasks are 'TSK', so any other value "
                "matches nothing; normally omit this filter."
            )
        ),
    ] = "",
    due_before: Annotated[str, Field(description="ISO date; tasks with due_date < value.")] = "",
    hidden: Annotated[str, Field(description="'true'/'false'/'' (empty = no filter, default).")] = "",
    summary_only: Annotated[bool, Field(description="Alias for mode='summary'.")] = False,
    memory_limit: Annotated[int, Field(description="Truncate description in 'full' mode.")] = 0,
    ctx: Context = None,
) -> dict[str, Any]:
    kwargs: dict[str, Any] = {"mode": mode}
    if status:
        kwargs["status"] = status
    if priority:
        kwargs["priority"] = priority
    if task_type:
        kwargs["task_type"] = task_type
    if due_before:
        kwargs["due_before"] = due_before
    if hidden != "":
        h = str(hidden).lower()
        if h in ("true", "1", "yes"):
            kwargs["hidden"] = True
        elif h in ("false", "0", "no"):
            kwargs["hidden"] = False
    if summary_only:
        kwargs["summary_only"] = True
    if memory_limit:
        kwargs["memory_limit"] = memory_limit
    return await _call_tool(ctx, "list_tasks", kwargs)
