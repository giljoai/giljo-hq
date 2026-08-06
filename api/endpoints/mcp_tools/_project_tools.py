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

from mcp.server.fastmcp import Context
from pydantic import Field

from api.endpoints.mcp_tools import _base
from api.endpoints.mcp_tools._base import (
    MCP_DESCRIPTION_MAX,
    MCP_HEAVY_TOOL_META,
    MCP_ID_MAX,
    MCP_MISSION_MAX,
    MCP_NAME_MAX,
    _call_tool,
    _detected_harness,
    _parse_iso_datetime_param,
    mcp,
)
from api.endpoints.mcp_tools._tool_annotations import _tool_hints


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
        "Create a new project bound to the active product. project_type is a taxonomy abbreviation "
        "(e.g. FE, BE, INF); the reserved 'TSK' type is task-only and is never valid here. "
        "series_number is auto-assigned server-side -- omit it for a normal create. Project is "
        "created inactive; the user activates/launches from the dashboard. See get_giljo_guide for "
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
    ctx: Context = None,
) -> dict[str, Any]:
    """Create a new project bound to the active product.

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
    return await _call_tool(ctx, "create_project", params)


@mcp.tool(
    title="List Projects",
    description=(
        "List projects for the active product with server-side filtering. Default returns only "
        "active-lifecycle projects (excludes completed/cancelled/terminated/deleted); pass "
        "include_completed=true or an explicit status to change that. Prefer mode=triage|planning|"
        "audit|forensic over numeric depth. Cheap-first: summary_only/mode=triage to find a "
        "project_id, then get_context(categories=['project']) for one project's full detail. "
        "Requires an active product. See get_giljo_guide for read-vs-write routing."
    ),
    meta=MCP_HEAVY_TOOL_META,  # BE-9083c: raise Claude Code's inline-truncation ceiling
    annotations=_tool_hints("list_projects"),
)
async def list_projects(
    status: str = "",
    project_type: str = "",
    taxonomy_alias_prefix: str = "",
    created_after: str = "",
    created_before: str = "",
    completed_after: str = "",
    completed_before: str = "",
    include_completed: bool = False,
    include_superseded: bool = False,
    hidden: str = "",
    summary_only: bool = True,
    depth: int = 0,
    status_filter: str = "",
    mode: str = "",
    memory_limit: int = 0,
    ctx: Context = None,
) -> dict[str, Any]:
    """List projects for the active product (v1.2.1 server-side filtering).

    Default returns only projects in active lifecycle. Four statuses are
    auto-excluded from the default response: completed, cancelled, terminated,
    deleted. The two returned by default are: active, inactive. The hidden
    column is per-row UI declutter and does NOT affect default visibility --
    agent sees hidden and non-hidden alike. Pass include_completed=true to
    retrieve archived projects. Pass hidden=true|false to filter explicitly
    when needed (rare).

    NOTE: status="deleted" returns soft-deleted rows. The default response
    hides soft-deleted projects (deleted_at IS NULL), but explicitly passing
    status="deleted" flips the soft-delete filter to deleted_at IS NOT NULL,
    so soft-deleted projects are reachable when the agent asks for them by
    status. Frontend StatusBadge enum parity is preserved either way.

    Args:
        status: Filter by status. Single value ("active") or comma-separated list
            ("active,inactive"). Valid values: active, inactive, completed,
            cancelled, terminated, deleted. When set, include_completed is
            ignored -- explicit status arg overrides the default exclusion.
        project_type: Filter by taxonomy type abbreviation. Single value ("BE")
            or comma-separated list ("BE,FE,INF"). Must match a configured type.
        taxonomy_alias_prefix: Prefix-match against taxonomy alias (e.g. "BE-50"
            matches BE-5001..BE-5099 but not BE-5100; "BE-5036" exact-matches one).
        created_after / created_before: ISO-8601 datetimes (e.g. "2026-01-01T00:00:00Z").
        completed_after / completed_before: ISO-8601 datetimes for completion window.
        include_completed: When True, archived projects (completed, cancelled,
            terminated, deleted) are included. Ignored when `status` is explicitly set.
        include_superseded: When True, superseded projects (work replaced by a
            successor) are included. Hidden by default even under
            include_completed=True. An explicit status="superseded" also surfaces them.
        hidden: "true" / "false" / "" (empty = no filter, default).
        summary_only: When True (default), return only summary fields to minimize payload.
        depth: Detail level 0-3 when summary_only=False:
            0 = summary fields only.
            1 = + description, mission, agent job summary.
            2 = + 360 memory entries, agent job details.
            3 = + message history, git commits from 360 memory.
        status_filter: Legacy parameter -- prefer `status`. Accepts "all" or a single
            status string. Honored only when `status` is unset.
        mode: BE-5042 agent-facing projection (preferred over numeric depth).
            "triage"   = id+name+status+dates (cheapest).
            "planning" = + description, mission, agent counts.
            "audit"    = + memory headlines + agent summaries (default last 5
                         memory entries).
            "forensic" = + full memory bodies, agent results (no cap).
            When set, mode wins over numeric `depth`. Empty string = use depth.
        memory_limit: Cap memory entries returned (audit mode default 5, max 50).
            0 = use mode default. Forensic ignores the cap unless explicitly set.
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
        },
    )


@mcp.tool(
    title="Update Project",
    description=(
        "Update project metadata (name, description, status, project_type, series_number, suffix). "
        "Only provided fields are updated. The reserved 'TSK' tag is not a selectable project_type. "
        "To find a project to update, call list_projects first. See get_giljo_guide for chain "
        "repositioning routing."
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
