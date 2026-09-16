# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from typing import Annotated, Any, Literal

from mcp.server.mcpserver import Context
from pydantic import Field

from api.endpoints.mcp_tools import _base
from api.endpoints.mcp_tools._base import (
    CURSOR_DESC,
    MCP_DESCRIPTION_MAX,
    MCP_ID_MAX,
    MCP_NAME_MAX,
    MCP_SHORT_TEXT_MAX,
    READ_PRODUCT_ID_DESC,
    _call_tool,
    blank_text_rejection,
    mcp,
)
from api.endpoints.mcp_tools._tool_annotations import _tool_hints
from giljo_mcp.exceptions import ValidationError
from giljo_mcp.services.task_service._mcp_read_layer import (
    LIST_TASKS_LIMIT_DEFAULT,
    LIST_TASKS_LIMIT_MAX,
)


@mcp.tool(
    title="Create Task",
    description=(
        "Create a new task (technical debt/TODO/bug/small fix). PASS product_id: in a bound repo "
        "it is already in your boot context, and get_context(categories=['products']) resolves an "
        "unknown one. Omitting it falls back to the default product only for a single-product "
        "tenant; a tenant that owns more than one product gets a structured PRODUCT_AMBIGUOUS "
        "rejection instead (the product list is in the error) -- nothing is created on a bare "
        "guess. Every task is auto-tagged 'TSK' (task_type is accepted-but-ignored); the serial "
        "auto-assigns in the TSK-nnnn form. The response names the product the task landed on. "
        "Use create_project instead for actionable multi-step work. See get_giljo_guide for the "
        "full task-vs-project routing recipe."
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
    product_id: Annotated[
        str,
        Field(
            max_length=MCP_ID_MAX,
            description=(
                "Optional product UUID to bind the task to. PASS IT WHEN YOU KNOW YOUR PRODUCT -- "
                "a bound repo already carries it in your boot context. Omit only for a "
                "single-product tenant, where it falls back to the default product; a tenant with "
                "more than one product gets a structured PRODUCT_AMBIGUOUS rejection instead "
                "(carrying the full product list) rather than a silent guess at the active one, "
                "which is shared, mutable state another session or the user can change under you. "
                "A product_id that does not belong to your account is rejected and nothing is "
                "created; it never falls back to the active or default product."
            ),
        ),
    ] = "",
    ctx: Context = None,
) -> dict[str, Any]:
    if not title.strip():
        return blank_text_rejection("title", entity="Task")
    kwargs: dict[str, Any] = {"title": title, "description": description, "priority": priority}
    if task_type:
        kwargs["task_type"] = task_type
    if assigned_to:
        kwargs["assigned_to"] = assigned_to
    if product_id:
        kwargs["product_id"] = product_id
    return await _call_tool(ctx, "create_task", kwargs)


@mcp.tool(
    title="Update Task",
    description=(
        "Update task metadata (title, description, status, priority, due_date). Only provided "
        "fields are written. task_type is immutable ('TSK'). Pass status='completed' to complete "
        "it (stamps completed_at); pass completion_notes to append an audit note as it completes. "
        "Pass convert_to_project=true to PROMOTE the task to a project instead of editing it -- "
        "same conversion the dashboard wizard runs, and it DELETES the task row. Tenant-scoped."
    ),
    annotations=_tool_hints("update_task", destructive=True),
)
async def update_task(
    task_id: Annotated[str, Field(max_length=MCP_ID_MAX, description="Task UUID (required).")],
    title: Annotated[str | None, Field(max_length=MCP_NAME_MAX, description="New title; omit to keep it.")] = None,
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
    convert_to_project: Annotated[
        bool,
        Field(
            description=(
                "Promote this task to a project (default false). Runs the SAME conversion as the "
                "dashboard's task-to-project wizard, in one atomic step: a project is created from "
                "the task, subtasks and any roadmap card re-point to it (same roadmap position), and "
                "THE TASK ROW IS DELETED -- its task_id stops resolving, so do not reuse it. The new "
                "project is INACTIVE and UNTYPED; tag it with update_project(project_id, "
                "project_type=...). It lands on the TASK's own product -- not whichever product is "
                "active -- and the response names that product. Pass title alongside to name the "
                "project; NO other field may be "
                "combined (the task row is gone, so any other write would be discarded) -- a "
                "combined call is refused and changes nothing. Use this instead of hand-building a "
                "project and completing the task: that recipe leaves the roadmap card orphaned."
            )
        ),
    ] = False,
    ctx: Context = None,
) -> dict[str, Any]:
    params: dict[str, Any] = {"task_id": task_id}
    if title is not None:
        if not title.strip():
            return blank_text_rejection("title", entity="Task")
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
    if convert_to_project:
        params["convert_to_project"] = True
        params["user_id"] = _base._resolve_user_id(ctx)
    return await _call_tool(ctx, "update_task", params)


@mcp.tool(
    title="List Tasks",
    description=(
        "List tasks for your default product. mode='index' (leanest: id, alias, name, status, type, "
        "dates), 'summary' (default) or 'full' (all columns; description is untruncated unless "
        "memory_limit is passed). BOUNDED: at most `limit` rows and a response-size ceiling, and "
        "the response always carries `truncated` plus a `truncation` block naming which bound cut "
        "it -- treat a truncated list as INCOMPLETE. A cut response also carries "
        "`truncation.next_cursor`: pass it back as `cursor` with the SAME filters to walk the "
        "rest page by page until `truncated` is false, which is how you read every task without "
        "guessing at slices. Every response also carries `counts`: the "
        "totals for the WHOLE board (ignoring your filters), `matched` (rows your filters hit, "
        "constant across a walk -- ignores `cursor`), `remaining` (rows still ahead of `cursor` "
        "that match, only when walking; equals `matched` on the first page) and `returned` (rows "
        "here) -- so you can size a request before making it. Use `query` to "
        "find a task by a word in its title, description or TSK-nnnn alias. Every task is tagged "
        "'TSK' -- task_type accepts only 'TSK' (a harmless no-op filter) and refuses any other "
        "value rather than silently matching nothing; normally omit it. hidden is UI declutter "
        "only (does not affect default visibility). Defaults to your default product; pass "
        "product_id to list a specific product's tasks instead. See "
        "get_giljo_guide for read-vs-write routing."
    ),
    annotations=_tool_hints("list_tasks"),
)
async def list_tasks(
    mode: Annotated[
        Literal["", "index", "summary", "full"],
        Field(
            description=(
                "Projection mode. 'index' is the lean list-and-sort row, typically 35-40% smaller "
                "than 'summary' -- the exact saving depends on how long your task titles are, "
                "since the fields it drops are a fixed cost. 'full' carries every column. "
                "'' (default) = 'summary', unless summary_only says otherwise. When mode is passed "
                "explicitly (non-empty), it WINS over summary_only -- pass one or the other, not "
                "both, unless you deliberately want mode's answer."
            )
        ),
    ] = "",
    status: Annotated[str, Field(description="Filter by exact status (e.g. 'pending').")] = "",
    priority: Annotated[str, Field(description="Filter by priority (low/medium/high/critical).")] = "",
    task_type: Annotated[
        str,
        Field(
            description=(
                "Filter by taxonomy abbreviation. Only 'TSK' matches -- every task is tagged "
                "'TSK' and no other type is ever assigned to one, so 'TSK' is a harmless no-op "
                "filter and any other value is refused rather than silently matching nothing."
            )
        ),
    ] = "",
    due_before: Annotated[str, Field(description="ISO date; tasks with due_date < value.")] = "",
    hidden: Annotated[str, Field(description="'true'/'false'/'' (empty = no filter, default).")] = "",
    summary_only: Annotated[
        bool, Field(description="Alias for mode='summary'. Ignored when mode is also passed explicitly.")
    ] = False,
    memory_limit: Annotated[int, Field(description="Truncate description in 'full' mode.")] = 0,
    limit: Annotated[
        int,
        Field(
            ge=0,
            le=LIST_TASKS_LIMIT_MAX,
            description=(
                f"Max tasks to return (default {LIST_TASKS_LIMIT_DEFAULT}, max {LIST_TASKS_LIMIT_MAX}). "
                "0 = use the default. Raise it deliberately to ask for more; the response still says "
                "whether it was cut, and a response-size ceiling applies independently of this value."
            ),
        ),
    ] = 0,
    query: Annotated[
        str,
        Field(
            max_length=MCP_NAME_MAX,
            description=(
                "Case-insensitive substring to search title, description and taxonomy_alias "
                "(e.g. 'oauth', 'TSK-9438'). Empty = no search filter."
            ),
        ),
    ] = "",
    cursor: Annotated[
        str,
        Field(
            max_length=MCP_SHORT_TEXT_MAX,
            description=CURSOR_DESC,
        ),
    ] = "",
    product_id: Annotated[
        str,
        Field(
            max_length=MCP_ID_MAX,
            description=READ_PRODUCT_ID_DESC.format(what="list tasks for"),
        ),
    ] = "",
    ctx: Context = None,
) -> dict[str, Any]:
    kwargs: dict[str, Any] = {"mode": mode or None, "limit": limit}
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
        else:
            raise ValidationError(
                message=(
                    f"Unknown value {hidden!r} for hidden. Accepted: 'true'/'1'/'yes', "
                    "'false'/'0'/'no', or '' (empty = no filter)."
                ),
                context={"operation": "list_tasks", "hidden": hidden},
            )
    if summary_only:
        kwargs["summary_only"] = True
    if memory_limit:
        kwargs["memory_limit"] = memory_limit
    if query:
        kwargs["query"] = query
    if cursor:
        kwargs["cursor"] = cursor
    if product_id:
        kwargs["product_id"] = product_id
    return await _call_tool(ctx, "list_tasks", kwargs)
