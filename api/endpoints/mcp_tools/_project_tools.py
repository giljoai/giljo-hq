# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
Project Management Tools -- @mcp.tool wrappers (BE-6042d split of mcp_sdk_server.py).

Mechanically extracted verbatim from the pre-split ``mcp_sdk_server.py``. Each
wrapper registers against the shared ``mcp`` instance from ``_base`` as a decorator
side effect at import time. Behavior, signatures, names, and descriptions unchanged.
"""

from typing import Annotated, Any, Literal

from mcp.server.mcpserver import Context
from pydantic import Field

from api.endpoints.mcp_tools import _base
from api.endpoints.mcp_tools._base import (
    MCP_DESCRIPTION_MAX,
    MCP_HEAVY_TOOL_META,
    MCP_ID_MAX,
    MCP_MISSION_MAX,
    MCP_NAME_MAX,
    MCP_SHORT_TEXT_MAX,
    _call_tool,
    _detected_harness,
    _parse_iso_datetime_param,
    mcp,
)
from api.endpoints.mcp_tools._tool_annotations import _tool_hints
from giljo_mcp.services.project_service._mcp_list_bounds import (
    _QUERY_MAX_LENGTH,
    LIST_PROJECTS_LIMIT_DEFAULT,
    LIST_PROJECTS_LIMIT_MAX,
)


@mcp.tool(
    title="Diagnose Project State",
    description=(
        "Diagnose a project's lifecycle state for orchestrator self-healing. READ-ONLY: reports "
        "status, gates, agent/job counts, closeout readiness, and stuck_conditions with "
        "suggested_actions. Call when a project looks wedged, instead of guessing. Tenant-scoped. "
        "See get_giljo_guide for the full stuck_conditions list and recovery routing."
    ),
    annotations=_tool_hints("diagnose_project_state"),
)
async def diagnose_project_state(
    project_id: Annotated[str, Field(max_length=MCP_ID_MAX, description="Project UUID to diagnose.")],
    ctx: Context = None,
) -> dict[str, Any]:
    return await _call_tool(ctx, "diagnose_project_state", {"project_id": project_id})


@mcp.tool(
    title="Create Project",
    description=(
        "Create a new project. Pass product_id to bind it to a specific product; omit it and the "
        "project binds to the active product, which another session or the user can change under "
        "you. project_type is a taxonomy abbreviation (e.g. FE, BE, INF); the reserved 'TSK' type "
        "is task-only and is never valid here. series_number is auto-assigned server-side -- omit "
        "it for a normal create. Project is created inactive; the user activates/launches from the "
        "dashboard. The response names the product the project landed on. See get_giljo_guide for "
        "chain creation (shared series_number + a/b/c suffix), taxonomy errors, and Edition Scope."
    ),
    annotations=_tool_hints("create_project"),
)
async def create_project(
    name: Annotated[str, Field(max_length=MCP_NAME_MAX)],
    description: Annotated[str, Field(max_length=MCP_DESCRIPTION_MAX)],
    project_type: Annotated[str, Field(max_length=MCP_NAME_MAX)] = "",
    series_number: int = 0,
    suffix: Annotated[str, Field(max_length=8)] = "",
    bootstrap_template_vars: dict[str, Any] | None = None,
    product_id: Annotated[str, Field(max_length=MCP_ID_MAX)] = "",
    ctx: Context = None,
) -> dict[str, Any]:
    """Create a new project bound to a product.

    Args:
        name: Project name (required)
        description: Human-written project description
        project_type: Taxonomy type abbreviation (e.g. FE, BE, INFRA, DOCS).
            Must match a pre-existing category configured in the dashboard.
            Unknown values are rejected with a ValidationError whose context lists
            valid_types (the reserved 'TSK' task tag is excluded -- it is never a
            valid project type). Combined with the auto-assigned series_number to
            form the project serial (e.g. FE-0001).
        series_number: Leave at 0. The serial is auto-assigned (continue-upward,
            global across all types AND tasks in this tenant+product) -- you do NOT
            pick the number. A non-zero value is only for deliberately injecting a
            project into an existing series slot; normal creates omit it.
        suffix: Single-letter suffix (a-z) for injecting projects into an existing
            series. E.g. series_number=5 + suffix="b" creates FE-0005b.
            Leave empty for no suffix.
        bootstrap_template_vars: Required when project_type='CTX' (BE-5122). Dict
            with keys 'new_documents' (optional list of {document_name, document_type})
            and any extra substitution vars consumed by the CTX bootstrap template.
            For non-CTX project types, this parameter is ignored.
        product_id: Optional product UUID to bind the project to. Omit to use the
            active product (the default, and what every existing caller gets).
            PASS IT WHEN YOU KNOW YOUR PRODUCT: the active product is shared,
            mutable state -- another session or the user switching products in the
            dashboard changes it mid-session, and an omitted product_id follows
            that change. A product_id that does not belong to your account is
            rejected and nothing is created; it never falls back to the active
            product.
    """
    params = {
        "name": name,
        "description": description,
        "project_type": project_type,
    }
    if series_number > 0:
        params["series_number"] = series_number
    if suffix:
        params["subseries"] = suffix
    if bootstrap_template_vars is not None:
        params["bootstrap_template_vars"] = bootstrap_template_vars
    if product_id:
        params["product_id"] = product_id
    return await _call_tool(ctx, "create_project", params)


@mcp.tool(
    title="List Projects",
    description=(
        "List and SEARCH projects for the active product with server-side filtering. Default "
        "returns only active-lifecycle projects (excludes completed/cancelled/terminated/"
        "deleted); pass include_completed=true or an explicit status to change that. EVERY "
        "response carries a counts block describing the WHOLE board (totals by status and type, "
        "the date span) so you can size it before choosing what to ask for. counts.matched is "
        "your filters' full hit count and stays constant across a walk; counts.remaining (only "
        "while walking, via cursor) is the part still ahead of you and shrinks each page. If your "
        "default-view result looks emptier than expected, counts.advice explains why and names "
        "the true count for YOUR filters (not a whole-board number) and how to see the rest -- "
        "this is NOT a truncation, just an explicit note. Use query "
        "to find a project by name, serial, or a word from its description without listing the "
        "board. Results are bounded by "
        f"limit (default {LIST_PROJECTS_LIMIT_DEFAULT}, max {LIST_PROJECTS_LIMIT_MAX}); a cut "
        "response says so via truncated + truncation, and carries truncation.next_cursor -- pass "
        "it back as cursor with the SAME filters to walk the rest, page by page, until truncated "
        "is false. That is how you list EVERYTHING without guessing at slices. "
        "Prefer mode=triage|planning|audit|forensic "
        "over numeric depth. Cheap-first: mode=triage to find a project_id, then "
        "get_context(categories=['project']) for one project's full detail. Requires an active "
        "product. See get_giljo_guide for read-vs-write routing."
    ),
    meta=MCP_HEAVY_TOOL_META,  # BE-9083c: raise Claude Code's inline-truncation ceiling
    annotations=_tool_hints("list_projects"),
)
async def list_projects(
    status: Annotated[
        str,
        Field(
            description=(
                "Filter by status. Single value or comma-separated list. Valid values: "
                "active, cancelled, completed, deleted, inactive, parked, superseded, "
                "terminated. When set, include_completed is ignored. status='deleted' "
                "reaches soft-deleted rows (the default hides them). If status_filter is "
                "ALSO passed with a different effective meaning, the call is refused "
                "(conflict) naming both values and the remedy; identical values pass."
            )
        ),
    ] = "",
    project_type: Annotated[
        str,
        Field(
            description="Filter by taxonomy type abbreviation. Single value ('BE') or comma-separated list "
            "('BE,FE,INF'). Must match a configured type."
        ),
    ] = "",
    taxonomy_alias_prefix: Annotated[
        str,
        Field(
            description="Prefix-match against taxonomy_alias (e.g. 'BE-50' matches BE-5001..BE-5099 but not "
            "BE-5100; 'BE-5036' exact-matches one)."
        ),
    ] = "",
    created_after: Annotated[
        str, Field(description="ISO-8601 datetime (e.g. '2026-01-01T00:00:00Z'); only rows created at/after this.")
    ] = "",
    created_before: Annotated[
        str, Field(description="ISO-8601 datetime (e.g. '2026-01-01T00:00:00Z'); only rows created before this.")
    ] = "",
    completed_after: Annotated[
        str,
        Field(description="ISO-8601 datetime (e.g. '2026-01-01T00:00:00Z'); only rows completed at/after this."),
    ] = "",
    completed_before: Annotated[
        str,
        Field(description="ISO-8601 datetime (e.g. '2026-01-01T00:00:00Z'); only rows completed before this."),
    ] = "",
    include_completed: Annotated[
        bool,
        Field(
            description="When True, archived projects (completed, cancelled, terminated, deleted) are "
            "included. Ignored when status is explicitly set."
        ),
    ] = False,
    include_superseded: Annotated[
        bool,
        Field(
            description="When True, superseded projects (work replaced by a successor) are included. Hidden "
            "by default even under include_completed=True. An explicit status='superseded' also surfaces them."
        ),
    ] = False,
    hidden: Annotated[str, Field(description="'true' / 'false' / '' (empty = no filter, default).")] = "",
    summary_only: Annotated[
        bool,
        Field(
            description="When True (default), return only summary fields to minimize payload. An explicit "
            "nonzero depth overrides this default (see depth); mode always wins over both when passed."
        ),
    ] = True,
    depth: Annotated[
        int,
        Field(
            description="Detail level 0-3: 0 = summary fields only. 1 = + description, mission, agent job "
            "summary. 2 = + 360 memory entries, agent job details. 3 = + message history, git commits from 360 "
            "memory. An explicit nonzero depth overrides the summary_only=True default (same precedence mode "
            "already has); mode still wins over depth when both are passed."
        ),
    ] = 0,
    status_filter: Annotated[
        str,
        Field(
            description="Legacy -- prefer `status`. Used when `status` is unset. Valid values: active, all, "
            "cancelled, completed, inactive, parked. When BOTH `status` and `status_filter` are passed, a "
            "genuine disagreement is refused (conflict) naming both values; identical/compatible values pass."
        ),
    ] = "",
    mode: Annotated[
        Literal["", "triage", "planning", "audit", "forensic"],
        Field(
            description="Agent-facing projection depth, preferred over numeric depth. 'triage' = "
            "id+name+status+dates (cheapest). 'planning' = + description, mission, agent counts. 'audit' = + "
            "memory headlines + agent summaries. 'forensic' = + full memory bodies, agent results (no cap). "
            "'' (default) = use numeric depth instead."
        ),
    ] = "",
    memory_limit: Annotated[
        int,
        Field(
            description="Cap memory entries returned (audit mode default 5, max 50). 0 = use mode default. "
            "Forensic ignores the cap unless explicitly set."
        ),
    ] = 0,
    query: Annotated[
        str,
        Field(
            max_length=_QUERY_MAX_LENGTH,
            description=(
                "Case-insensitive substring to search project name, id, description, "
                "project_alias and taxonomy_alias (e.g. 'oauth', 'BE-1042'). Empty = no search. "
                "The cheapest path from a half-remembered name -- or a phrase you recall from the "
                "description -- to one project_id."
            ),
        ),
    ] = "",
    limit: Annotated[
        int,
        Field(
            ge=0,
            le=LIST_PROJECTS_LIMIT_MAX,
            description=(
                f"Max projects to return (default {LIST_PROJECTS_LIMIT_DEFAULT}, max "
                f"{LIST_PROJECTS_LIMIT_MAX}). 0 = use the default. Values above the max are "
                "REJECTED with a validation error, not clamped. A response cut by this bound "
                "sets truncated=true and carries a truncation block naming it; read "
                "counts.matched to see how many rows your filters actually match."
            ),
        ),
    ] = 0,
    cursor: Annotated[
        str,
        Field(
            max_length=MCP_SHORT_TEXT_MAX,
            description=(
                "Continue a previous list from where it stopped. Pass back the opaque token from "
                "that response's truncation.next_cursor, WITH THE SAME FILTERS. Empty = start at "
                "the first page. Walking is the only way to read a set larger than one page: keep "
                "passing the newest next_cursor until a response comes back with truncated=false, "
                "and every project will have been returned exactly once. Changing any filter "
                "mid-walk is REFUSED rather than silently answered from the wrong set -- restart "
                "without cursor if you want different filters. Changing limit or mode mid-walk is "
                "fine."
            ),
        ),
    ] = "",
    ctx: Context = None,
) -> dict[str, Any]:
    """List projects for the active product (v1.2.1 server-side filtering).

    BE-9470: every parameter's contract now lives on its own Field description
    above (the wire an agent actually reads), not here -- FastMCP never
    serializes a docstring Args: block to the schema, so this stayed one
    source of truth instead of two that could disagree.
    """
    # Normalize status -> list[str] | None
    status_arg: list[str] | str | None
    if not status:
        status_arg = None
    elif "," in status:
        status_arg = [s.strip() for s in status.split(",") if s.strip()]
    else:
        status_arg = status.strip()

    pt_arg: list[str] | str | None
    if not project_type:
        pt_arg = None
    elif "," in project_type:
        pt_arg = [s.strip() for s in project_type.split(",") if s.strip()]
    else:
        pt_arg = project_type.strip()

    # Parse hidden tri-state
    hidden_arg: bool | None
    if hidden == "" or hidden is None:
        hidden_arg = None
    elif str(hidden).lower() in ("true", "1", "yes"):
        hidden_arg = True
    elif str(hidden).lower() in ("false", "0", "no"):
        hidden_arg = False
    else:
        hidden_arg = None

    return await _call_tool(
        ctx,
        "list_projects",
        {
            "status_filter": status_filter or None,
            "summary_only": summary_only,
            "depth": depth,
            "status": status_arg,
            "project_type": pt_arg,
            "taxonomy_alias_prefix": taxonomy_alias_prefix or None,
            "created_after": _parse_iso_datetime_param(created_after),
            "created_before": _parse_iso_datetime_param(created_before),
            "completed_after": _parse_iso_datetime_param(completed_after),
            "completed_before": _parse_iso_datetime_param(completed_before),
            "include_completed": include_completed,
            "include_superseded": include_superseded,
            "hidden": hidden_arg,
            "mode": mode or None,
            "memory_limit": memory_limit or None,
            "query": query or None,
            "limit": limit or None,
            "cursor": cursor or None,
        },
    )


@mcp.tool(
    title="Update Project",
    description=(
        "Update project metadata (name, description, status, project_type, series_number, suffix). "
        "Only provided fields are updated. The reserved 'TSK' tag is not a selectable project_type. "
        "status='completed' on a solo project runs the FULL archive lifecycle (the same one the "
        "dashboard's Archive button runs): deactivate, terminal status with completion date stamped, "
        "and spawned agents moved from 'complete' to 'closed'. This is the supported way to finish a "
        "project over MCP. To find a project to update, call list_projects first. See get_giljo_guide "
        "for chain repositioning routing."
    ),
    # BE-9251: status accepts terminal values (completed/cancelled) -- a general
    # editor tool that CAN produce a terminal transition, not just rename/redescribe.
    annotations=_tool_hints("update_project", destructive=True),
)
async def update_project(
    project_id: Annotated[str, Field(max_length=MCP_ID_MAX)],
    name: Annotated[str, Field(max_length=MCP_NAME_MAX)] = "",
    description: Annotated[str, Field(max_length=MCP_DESCRIPTION_MAX)] = "",
    status: Annotated[str, Field(max_length=MCP_NAME_MAX)] = "",
    project_type: Annotated[str, Field(max_length=MCP_NAME_MAX)] = "",
    series_number: int = 0,
    suffix: Annotated[str, Field(max_length=8)] = "",
    ctx: Context = None,
) -> dict[str, Any]:
    """Update project metadata fields.

    Args:
        project_id: Project UUID (required).
        name: New project name (max 200 chars). Leave empty to keep current.
        description: New description (max 20000 chars). Leave empty to keep current.
        status: New status — "inactive", "active", "completed", "cancelled", or "parked". Leave
            empty to keep current. "parked" sets a project aside without cancelling it -- hidden
            from the roadmap but resumable; unpark by setting status back to "inactive" or "active".
            "completed" on a solo project is the supported completion path: it runs the whole
            archive lifecycle, not just the status write. The final status is derived, not taken
            literally -- a project the user terminated early lands on "terminated" instead, because
            the early-termination flag decides which terminal state is correct. "cancelled" is a
            different outcome (abandoned, not finished) and stays a plain status write. A member of
            a running chain also stays a plain status write; its conductor owns member completion.
        project_type: Taxonomy type abbreviation (e.g. FE, BE). Leave empty to keep current.
            The reserved 'TSK' tag is not a selectable project type (tasks only).
        series_number: Sequential number within the type series (1-9999). Use 0 to keep current.
        suffix: Single-letter suffix (a-z). Leave empty to keep current.
    """
    params: dict = {"project_id": project_id}
    if name:
        params["name"] = name
    if description:
        params["description"] = description
    if status:
        params["status"] = status
    if project_type:
        params["project_type"] = project_type
    if series_number > 0:
        params["series_number"] = series_number
    if suffix:
        params["subseries"] = suffix
    return await _call_tool(ctx, "update_project_metadata", params)


@mcp.tool(
    title="Update Project Mission",
    description=(
        "Save the orchestrator's mission plan (the execution OUTPUT), distinct from "
        "Project.description (the user's INPUT requirements). Orchestrator-only, called after "
        "creating the execution strategy during staging. Triggers a WebSocket UI update."
    ),
    annotations=_tool_hints("update_project_mission"),
)
async def update_project_mission(
    project_id: Annotated[str, Field(max_length=MCP_ID_MAX)],
    mission: Annotated[str, Field(max_length=MCP_MISSION_MAX)],
    ctx: Context = None,
) -> dict[str, Any]:
    return await _call_tool(
        ctx,
        "update_project_mission",
        {
            "project_id": project_id,
            "mission": mission,
        },
    )


@mcp.tool(
    title="Stage Project",
    description=(
        "Stage a project: drive the staging endpoint and return the orchestrator staging prompt for "
        "the chosen mode (execution harness: multi_terminal|subagent|claude|codex|gemini|antigravity). MCP "
        "equivalent of the dashboard 'copy staging prompt' button. HUMAN GATE: after staging, STOP "
        "-- the user must press Implement in the dashboard before implement_project can run. See "
        "get_giljo_guide for the staging -> human-gate -> implement lifecycle."
    ),
    annotations=_tool_hints("stage_project"),
)
async def stage_project(
    project_id: str,
    mode: Literal["multi_terminal", "subagent", "claude", "codex", "gemini", "antigravity"] = "multi_terminal",
    ctx: Context = None,
) -> dict[str, Any]:
    return await _call_tool(
        ctx,
        "stage_project",
        {"project_id": project_id, "mode": mode, "user_id": _base._resolve_user_id(ctx)},
    )


@mcp.tool(
    title="Implement Project",
    description=(
        "Return the implementation prompt for an already-staged project. Preconditions: "
        "staging_status='staging_complete' AND the user has pressed Implement in the dashboard. If "
        "the gate hasn't cleared, returns a structured error (status='gate_not_passed') with a "
        "next_action naming the exact next step. No bypass -- the human gate is intentional."
    ),
    annotations=_tool_hints("implement_project"),
)
async def implement_project(
    project_id: str,
    ctx: Context = None,
) -> dict[str, Any]:
    # BE-9099: resolve the session's detected harness (claude-code / codex / gemini /
    # antigravity / opencode / generic) from clientInfo and thread it down so a subagent
    # orchestrator gets its harness's native spawn render — never the multi_terminal seed.
    return await _call_tool(
        ctx,
        "implement_project",
        {
            "project_id": project_id,
            "user_id": _base._resolve_user_id(ctx),
            "detected_harness": _detected_harness(ctx),
        },
    )


@mcp.tool(
    title="Launch Implementation",
    description=(
        "Release the implementation phase gate for a STAGED project from the CLI -- the second of the "
        "two human-authorized doors that flip implementation_launched_at (the first is the dashboard "
        "'Implement' button). Idempotent (a second call returns already_launched=true). NOT in the "
        "orchestrator's auto-loaded tool bundle -- a spawned agent cannot self-unlock; its MCP "
        "permission prompt IS the human authorization. Use for headless/CLI operation with no "
        "dashboard user to press Implement."
    ),
    # BE-9251 audit F3: stamps project.implementation_launched_at -- a
    # one-way phase gate set once and never reset, the same terminal-transition
    # class as update_project/update_task/complete_job/close_job/
    # write_project_closeout.
    annotations=_tool_hints("launch_implementation", destructive=True),
)
async def launch_implementation(
    project_id: str,
    ctx: Context = None,
) -> dict[str, Any]:
    return await _call_tool(
        ctx,
        "launch_implementation",
        {"project_id": project_id, "user_id": _base._resolve_user_id(ctx)},
    )
