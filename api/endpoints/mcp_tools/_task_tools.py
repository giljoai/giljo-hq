# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from typing import Annotated, Any, Literal

from mcp.server.mcpserver import Context
from pydantic import Field

from api.endpoints.mcp_tools import _base
from api.endpoints.mcp_tools._base import (
    CONSTRAINT_INVALID_CHOICE,
    CURSOR_DESC,
    MCP_DESCRIPTION_MAX,
    MCP_ID_MAX,
    MCP_NAME_MAX,
    MCP_SHORT_TEXT_MAX,
    READ_PRODUCT_ID_DESC,
    _call_tool,
    blank_text_rejection,
    mcp,
    validation_rejection,
)
from api.endpoints.mcp_tools._tool_annotations import _tool_hints
from giljo_mcp.exceptions import ValidationError
from giljo_mcp.services.handover_validation import (
    HANDOVER_CONTENT_CONSTRAINT,
    HANDOVER_SHAPE_CONSTRAINT,
    HANDOVER_TYPE_ABBR,
    handover_shape_error,
)
from giljo_mcp.services.task_service._mcp_read_layer import (
    LIST_TASKS_LIMIT_DEFAULT,
    LIST_TASKS_LIMIT_MAX,
)
from giljo_mcp.services.task_type_immutability import TaskTypeImmutableError
from giljo_mcp.services.taxonomy_ops import resolve_task_type_abbr


def _task_type_rejection(task_type: str) -> dict[str, Any] | None:
    try:
        resolve_task_type_abbr(task_type, operation="create_task")
    except ValidationError as exc:
        return validation_rejection(field="task_type", constraint=CONSTRAINT_INVALID_CHOICE, message=str(exc))
    return None


_HANDOVER_SHAPE_CONSTRAINTS = frozenset({HANDOVER_SHAPE_CONSTRAINT, HANDOVER_CONTENT_CONSTRAINT})


def _handover_shape_rejection(description: str) -> dict[str, Any] | None:
    error = handover_shape_error(description, operation="create_task")
    if error is None:
        return None
    return validation_rejection(
        field=error.context["field"],
        constraint=error.context["constraint"],
        message=error.message,
    )


def _handover_shape_rejection_from(exc: ValidationError) -> dict[str, Any] | None:
    if exc.context.get("constraint") not in _HANDOVER_SHAPE_CONSTRAINTS:
        return None
    return validation_rejection(
        field=exc.context["field"],
        constraint=exc.context["constraint"],
        message=exc.message,
    )


@mcp.tool(
    title="Create Task",
    description=(
        "Create a task (technical debt, a TODO, a bug, a small fix). Pass product_id when you know it (a "
        "bound repo carries it; get_context(categories=['products']) resolves a name); omitted, it falls "
        "back to the default product only for a single-product tenant, otherwise PRODUCT_AMBIGUOUS and "
        "nothing is created. task_type is 'TSK' (default) or 'HND' (a session handover). Serials "
        "auto-assign; the response names the product. Multi-step work is a project: use create_project. "
        "Routing: get_giljo_guide."
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
                "'TSK' (default) or 'HND' (session handover); any other value is refused. "
                "An HND description must carry the headings '## Verify before trusting', "
                "'## Waiting on the operator' and '## Cannot testify', or it is refused."
            ),
        ),
    ] = "",
    assigned_to: Annotated[str, Field(max_length=MCP_NAME_MAX, description="Optional assignee name.")] = "",
    product_id: Annotated[
        str,
        Field(
            max_length=MCP_ID_MAX,
            description=(
                "Product UUID to bind the task to. Pass it when you know your product; omitted, it falls back to "
                "the default product only for a single-product tenant, otherwise a PRODUCT_AMBIGUOUS rejection "
                "lists the products and nothing is created. An id that is not yours is rejected."
            ),
        ),
    ] = "",
    ctx: Context = None,
) -> dict[str, Any]:
    if not title.strip():
        return blank_text_rejection("title", entity="Task")
    if (rejection := _task_type_rejection(task_type)) is not None:
        return rejection
    if task_type.strip() == HANDOVER_TYPE_ABBR and ((rejection := _handover_shape_rejection(description)) is not None):
        return rejection
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
        "Update task metadata (title, description, status, priority). Only provided "
        "fields are written. task_type is fixed at creation: a different one is refused and "
        "nothing is written. Pass status='completed' to complete "
        "it (stamps completed_at); pass completion_notes to append an audit note as it completes. "
        "To turn a task into a project use promote_task_to_project. Tenant-scoped."
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
        Literal["", "pending", "in_progress", "on_hold", "completed", "blocked", "cancelled"],
        Field(
            description=(
                "New status: pending|in_progress|on_hold|completed|blocked|cancelled. on_hold parks an "
                "undecided task: it stays open and does not stamp started_at. Empty string keeps current."
            )
        ),
    ] = "",
    priority: Annotated[
        Literal["", "low", "medium", "high", "critical"],
        Field(description="New priority: low|medium|high|critical. Empty string keeps current."),
    ] = "",
    task_type: Annotated[
        str,
        Field(
            max_length=MCP_NAME_MAX,
            description=(
                "Fixed at creation. Passing the task's own current type is a no-op; a different "
                "type is refused and the whole call writes nothing -- create a new task instead."
            ),
        ),
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
    if hidden != "":
        h = str(hidden).lower()
        if h in ("true", "1", "yes"):
            params["hidden"] = True
        elif h in ("false", "0", "no"):
            params["hidden"] = False
        else:
            return validation_rejection(
                field="hidden", constraint=CONSTRAINT_INVALID_CHOICE, message="hidden must be 'true', 'false' or empty."
            )
    if completion_notes:
        params["completion_notes"] = completion_notes
    try:
        return await _call_tool(ctx, "update_task", params)
    except ValidationError as exc:
        if (rejection := _handover_shape_rejection_from(exc)) is not None:
            return rejection
        raise
    except TaskTypeImmutableError as exc:
        return validation_rejection(field=exc.field, constraint=exc.constraint, message=str(exc))


@mcp.tool(
    title="Promote Task To Project",
    description=(
        "Turns a task into a project in your own private Giljo HQ workspace, for a task that "
        "turned out to be bigger than one step. Creates a project from the task on the task's own "
        "product, moves its subtasks and any roadmap card to the project (same roadmap position), "
        "and DELETES the task: its task_id no longer resolves, so carry the returned project_id "
        "instead. The new project is inactive and untyped; give it a type with update_project, and "
        "the user activates it from the dashboard. Only the task's creator or an admin may promote "
        "it, and a handover task cannot be promoted. Tenant-scoped. No outside service is contacted."
    ),
    annotations=_tool_hints("promote_task_to_project", destructive=True),
)
async def promote_task_to_project(
    task_id: Annotated[str, Field(max_length=MCP_ID_MAX, description="UUID of the task to promote.")],
    title: Annotated[
        str | None,
        Field(
            max_length=MCP_NAME_MAX,
            description="Name for the new project; omit to keep the task's own title.",
        ),
    ] = None,
    ctx: Context = None,
) -> dict[str, Any]:
    if title is not None and not title.strip():
        return blank_text_rejection("title", entity="Project")
    params: dict[str, Any] = {"task_id": task_id, "user_id": _base._resolve_user_id(ctx)}
    if title is not None:
        params["title"] = title
    return await _call_tool(ctx, "promote_task_to_project", params)


@mcp.tool(
    title="List Tasks",
    description=(
        "List tasks for your default product (pass product_id for another). mode='index' (leanest), "
        "'summary' (default) or 'full'. query finds a task by a word in its title, description or alias; "
        "task_type filters 'TSK' (ordinary) or 'HND' (session handovers). Bounded: a cut response says so"
        " (truncated + truncation) and carries truncation.next_cursor to walk the rest; counts sizes the "
        "whole board, your match and this page. Details: get_giljo_guide."
    ),
    annotations=_tool_hints("list_tasks"),
)
async def list_tasks(
    mode: Annotated[
        Literal["", "index", "summary", "full"],
        Field(
            description=(
                "'index' is the lean list row (about a third smaller than 'summary'), 'full' carries every "
                "column, '' = 'summary'. An explicit mode wins over summary_only."
            )
        ),
    ] = "",
    status: Annotated[str, Field(description="Filter by exact status (e.g. 'pending').")] = "",
    priority: Annotated[str, Field(description="Filter by priority (low/medium/high/critical).")] = "",
    task_type: Annotated[
        str,
        Field(
            description=(
                "'TSK' (ordinary) or 'HND' (session handovers: how you find the one left for you). Any other "
                "value is refused."
            )
        ),
    ] = "",
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
                f"Max tasks to return (default {LIST_TASKS_LIMIT_DEFAULT}, max {LIST_TASKS_LIMIT_MAX}; 0 = "
                "default). A response-size ceiling applies as well; the response says whether it was cut."
            ),
        ),
    ] = 0,
    query: Annotated[
        str,
        Field(
            max_length=MCP_NAME_MAX,
            description=(
                "Case-insensitive substring over title, description and taxonomy_alias (e.g. 'oauth', 'TSK-9438')."
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
