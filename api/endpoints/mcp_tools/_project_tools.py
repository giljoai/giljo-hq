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
    MCP_HEAVY_TOOL_META,
    MCP_ID_MAX,
    MCP_MISSION_MAX,
    MCP_NAME_MAX,
    MCP_SHORT_TEXT_MAX,
    READ_PRODUCT_ID_DESC,
    _call_tool,
    _detected_harness,
    _parse_iso_datetime_param,
    blank_text_rejection,
    mcp,
    validation_rejection,
)
from api.endpoints.mcp_tools._schema_helpers import enum_schema_without_default
from api.endpoints.mcp_tools._tool_annotations import _tool_hints
from giljo_mcp.services.project_service._mcp_list_bounds import (
    _QUERY_MAX_LENGTH,
    LIST_PROJECTS_LIMIT_DEFAULT,
    LIST_PROJECTS_LIMIT_MAX,
)


_UpdatableStatus = Literal["", "active", "cancelled", "completed", "inactive", "parked", "superseded"]


def _normalize_list_projects_filters(
    status: str, project_type: str, hidden: str
) -> tuple[list[str] | str | None, list[str] | str | None, bool | None]:
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

    hidden_arg: bool | None
    if hidden == "" or hidden is None:
        hidden_arg = None
    elif str(hidden).lower() in ("true", "1", "yes"):
        hidden_arg = True
    elif str(hidden).lower() in ("false", "0", "no"):
        hidden_arg = False
    else:
        raise ValueError(f"hidden must be 'true', 'false' or empty, got {hidden!r}")

    return status_arg, pt_arg, hidden_arg


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
        "Create a new project. PASS product_id: in a bound repo it is already in your boot context "
        "(giljo_setup wrote it), and resolve an unknown one via get_context(categories=['products']). "
        "Omitting it falls back to the default product only for a single-product tenant; a tenant "
        "that owns more than one product gets a structured PRODUCT_AMBIGUOUS rejection instead (the "
        "product list is in the error) -- nothing is created on a bare guess. project_type is a "
        "taxonomy abbreviation (e.g. FE, BE, INF); the reserved 'TSK' type is task-only and is never "
        "valid here. series_number is auto-assigned server-side -- omit it for a normal create. "
        "Project is created inactive. Launching its implementation makes it active; the launch "
        "gate is a separate, explicit step (either door -- see get_giljo_guide). The response names the "
        "product the project landed on and carries TWO aliases: alias is the short permanent "
        "share code (e.g. A1B2C3, never changes), taxonomy_alias is the human-readable serial "
        "(e.g. BE-0007) -- quote taxonomy_alias to people, use project_id in tool calls. See "
        "get_giljo_guide for chain creation (shared series_number + a/b/c suffix), taxonomy "
        "errors, and Edition Scope."
    ),
    annotations=_tool_hints("create_project"),
)
async def create_project(
    name: Annotated[str, Field(max_length=MCP_NAME_MAX, description="Project name (required).")],
    description: Annotated[
        str,
        Field(
            max_length=MCP_DESCRIPTION_MAX,
            description=(
                "What the project is for, in the user's own terms: the requirements, the "
                "definition of done, and what is out of scope. This is the INPUT brief -- the "
                "execution plan is written separately via update_project_mission."
            ),
        ),
    ],
    project_type: Annotated[
        str,
        Field(
            max_length=MCP_NAME_MAX,
            description=(
                "Taxonomy type abbreviation, e.g. 'FE', 'BE', 'INF'. Must match a type already "
                "configured for this account; an unknown value is rejected with the full valid "
                "list in the error, so re-map and retry. The reserved 'TSK' tag is task-only and "
                "never valid here. Omit to create an untyped project and tag it later."
            ),
        ),
    ] = "",
    series_number: Annotated[
        int,
        Field(
            description=(
                "Leave at 0 -- the serial is auto-assigned. Pass a number ONLY to place this "
                "project into an existing series slot alongside a suffix (see suffix)."
            )
        ),
    ] = 0,
    suffix: Annotated[
        str,
        Field(
            max_length=8,
            description=(
                "Single letter (a-z) marking this project's position in a multi-step series: "
                "the shared number says these belong together, the letter says which runs "
                "first. Empty for a normal standalone project."
            ),
        ),
    ] = "",
    bootstrap_template_vars: Annotated[
        dict[str, Any] | None,
        Field(
            description=(
                "Only used when project_type='CTX'; ignored for every other type. Keys: "
                "'new_documents' (optional list of {document_name, document_type}) plus any "
                "extra substitution variables the CTX bootstrap template consumes."
            )
        ),
    ] = None,
    product_id: Annotated[
        str,
        Field(
            max_length=MCP_ID_MAX,
            description=(
                "Product UUID to create this project under. PASS IT WHEN YOU KNOW YOUR PRODUCT: "
                "a bound repo already carries it, and get_context(categories=['products']) "
                "resolves a name to an id. Omitting it falls back to the default product only "
                "for a single-product account; an account with several gets a structured "
                "PRODUCT_AMBIGUOUS rejection listing them, and creates nothing. An id that is "
                "not one of your own products is rejected and creates nothing."
            ),
        ),
    ] = "",
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
        product_id: Optional product UUID to bind the project to. PASS IT WHEN YOU
            KNOW YOUR PRODUCT -- a bound repo already carries it in your boot
            context, and get_context(categories=['products']) resolves a name to
            an id otherwise. Omit only for a single-product tenant, where it falls
            back to the default product. A tenant with more than one product gets
            a structured PRODUCT_AMBIGUOUS rejection instead (carrying the full
            product list) rather than a silent guess at the active one -- the
            default product is shared, mutable state that another session or the
            user can change under you. A product_id that does not belong to your
            account is rejected and nothing is created; it never falls back to
            the active or default product.
    """
    if not name.strip():
        return blank_text_rejection("name", entity="Project")
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
        "List and SEARCH projects for your default product with server-side filtering. Default "
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
        "get_context(categories=['project']) for one project's full detail. Defaults to your "
        "default product; pass product_id to list a specific product's projects instead. See "
        "get_giljo_guide for read-vs-write routing."
    ),
    meta=MCP_HEAVY_TOOL_META,
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
            description=CURSOR_DESC,
        ),
    ] = "",
    product_id: Annotated[
        str,
        Field(
            max_length=MCP_ID_MAX,
            description=READ_PRODUCT_ID_DESC.format(what="list projects for"),
        ),
    ] = "",
    ctx: Context = None,
) -> dict[str, Any]:
    """List projects for your default product, or an explicit product_id (v1.2.1 server-side filtering).

    BE-9470: every parameter's contract now lives on its own Field description
    above (the wire an agent actually reads), not here -- FastMCP never
    serializes a docstring Args: block to the schema, so this stayed one
    source of truth instead of two that could disagree.
    """
    try:
        status_arg, pt_arg, hidden_arg = _normalize_list_projects_filters(status, project_type, hidden)
    except ValueError as exc:
        return validation_rejection(field="hidden", constraint=CONSTRAINT_INVALID_CHOICE, message=str(exc))

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
            "product_id": product_id or None,
        },
    )


@mcp.tool(
    title="Update Project",
    description=(
        "Update project metadata (name, description, status, project_type, series_number, suffix, "
        "successor_project_id). Only provided fields are updated. The reserved 'TSK' tag is not a "
        "selectable project_type. status='completed' on a solo project runs the FULL archive "
        "lifecycle (the same one the dashboard's Archive button runs): deactivate, terminal status "
        "with completion date stamped, and spawned agents moved from 'complete' to 'closed'. This "
        "is the supported way to finish a project over MCP. status='superseded' REQUIRES "
        "successor_project_id in the SAME call (a valid active/completed/inactive project) -- "
        "without one this returns a structured SUPERSEDE_REQUIRES_SUCCESSOR rejection, never a "
        "500. To find a project to update, call list_projects first. See get_giljo_guide for chain "
        "repositioning routing."
    ),
    annotations=_tool_hints("update_project", destructive=True),
)
async def update_project(
    project_id: Annotated[str, Field(max_length=MCP_ID_MAX, description="Project UUID to update (required).")],
    name: Annotated[
        str | None,
        Field(max_length=MCP_NAME_MAX, description="New project name; omit to keep it."),
    ] = None,
    description: Annotated[
        str,
        Field(max_length=MCP_DESCRIPTION_MAX, description="New description. Empty keeps the current one."),
    ] = "",
    status: Annotated[
        _UpdatableStatus,
        Field(
            description=(
                "New status. Empty keeps the current one. 'active' / 'inactive' start and pause "
                "work. 'parked' sets a project aside without cancelling it -- hidden from the "
                "roadmap, resumable by setting it back to 'active' or 'inactive'. 'cancelled' "
                "abandons it unfinished. 'completed' FINISHES a solo project and runs the whole "
                "archive lifecycle, so it needs a closeout written first (see force). "
                "'superseded' means another project replaced this work and REQUIRES "
                "successor_project_id in the same call. A project inside a running chain is "
                "finished by its conductor, not here."
            )
        ),
    ] = "",
    project_type: Annotated[
        str,
        Field(
            max_length=MCP_NAME_MAX,
            description=(
                "New taxonomy type abbreviation, e.g. 'FE', 'BE'. Empty keeps the current one. "
                "The reserved 'TSK' tag is task-only and never valid here."
            ),
        ),
    ] = "",
    series_number: Annotated[
        int, Field(description="Position in a multi-step series (1-9999). 0 keeps the current one.")
    ] = 0,
    suffix: Annotated[
        str,
        Field(max_length=8, description="Single letter (a-z) marking series position. Empty keeps the current one."),
    ] = "",
    successor_project_id: Annotated[
        str,
        Field(
            max_length=MCP_ID_MAX,
            description=(
                "The project that replaced this one's work. Required with status='superseded' "
                "and meaningless without it. Must be an active, completed, or inactive project."
            ),
        ),
    ] = "",
    force: Annotated[
        bool,
        Field(
            description=(
                "Only meaningful with status='completed'. Finishing a project normally requires "
                "a closeout entry first (write_project_closeout); without one this is refused "
                "with CLOSEOUT_BLOCKED naming what is outstanding. Pass true to finish it anyway, "
                "deliberately abandoning it without a closeout record."
            )
        ),
    ] = False,
    ctx: Context = None,
) -> dict[str, Any]:
    """Update project metadata fields.

    Args:
        project_id: Project UUID (required).
        name: New project name (max 200 chars). Omit it to keep the current one; supplying a
            blank one is refused.
        description: New description (max 20000 chars). Leave empty to keep current.
        status: New status — "inactive", "active", "completed", "cancelled", "parked", or
            "superseded". Leave empty to keep current. "parked" sets a project aside without
            cancelling it -- hidden from the roadmap but resumable; unpark by setting status back
            to "inactive" or "active". "completed" on a solo project is the supported completion
            path: it runs the whole archive lifecycle, not just the status write. The final status
            is derived, not taken literally -- a project the user terminated early lands on
            "terminated" instead, because the early-termination flag decides which terminal state
            is correct. "cancelled" is a different outcome (abandoned, not finished) and stays a
            plain status write. A member of a running chain also stays a plain status write; its
            conductor owns member completion. "superseded" marks this project's work as replaced by
            another and REQUIRES successor_project_id in this same call -- see that parameter. A
            completed project can be revived by setting status back to "inactive" or "active".
        project_type: Taxonomy type abbreviation (e.g. FE, BE). Leave empty to keep current.
            The reserved 'TSK' tag is not a selectable project type (tasks only).
        series_number: Sequential number within the type series (1-9999). Use 0 to keep current.
        suffix: Single-letter suffix (a-z). Leave empty to keep current.
        successor_project_id: The project this one's work was replaced by. Required, and only
            meaningful, together with status="superseded" — must be an active, completed, or
            inactive project (cancelled/terminated/deleted/superseded successors are rejected, the
            last to avoid looping the pointer chain). Leave empty otherwise.
        force: Only meaningful together with status="completed" on a solo project. The archive
            lifecycle refuses (CLOSEOUT_BLOCKED) when no closeout entry exists yet for this
            project — call write_project_closeout first. Pass force=true to archive anyway,
            deliberately abandoning without a closeout record.
    """
    params: dict = {"project_id": project_id, "force": force}
    if name is not None:
        if not name.strip():
            return blank_text_rejection("name", entity="Project")
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
    if successor_project_id:
        params["successor_project_id"] = successor_project_id
    return await _call_tool(ctx, "update_project_metadata", params)


@mcp.tool(
    title="Update Project Mission",
    description=(
        "Save the orchestrator's mission plan (the execution OUTPUT), distinct from "
        "Project.description (the user's INPUT requirements). Orchestrator-only, called after "
        "creating the execution strategy during staging. Triggers a WebSocket UI update."
    ),
    annotations=_tool_hints("update_project_mission", destructive=True),
)
async def update_project_mission(
    project_id: Annotated[str, Field(max_length=MCP_ID_MAX, description="Project id.")],
    mission: Annotated[str, Field(max_length=MCP_MISSION_MAX, description="The new mission text for the project.")],
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
        "Prepares a project in your own private Giljo HQ workspace and returns its staging plan. "
        "Staging always ends at a human approval gate: nothing is implemented until the user "
        "approves it with the Implement button in the dashboard or with launch_implementation. "
        "Approving also makes an inactive project active. "
        "Ask the user which `mode` to use (subagent or multi_terminal); if it is omitted and the "
        "account has no default, the call is refused with EXECUTION_MODE_REQUIRED and names both "
        "modes. Pass `mission` to set the project's goal at the same time; it is written through "
        "update_project_mission, which is also where you change a mission on its own. The `action` parameter "
        "can undo staging: 'unstage' reverts a staged project before the agent was contacted, "
        "'cancel_staging' abandons staging that is underway, and 'restage' clears the mission and "
        "the staging state, retires the earlier orchestrator and creates a fresh one so staging "
        "starts over (refused once implementation has launched). `mode` only applies to the "
        "default 'stage' action. No outside service is contacted."
    ),
    annotations=_tool_hints("stage_project", destructive=True),
)
async def stage_project(
    project_id: Annotated[str, Field(max_length=MCP_ID_MAX, description="The project to stage.")],
    mode: Annotated[
        str,
        Field(
            json_schema_extra=enum_schema_without_default(["multi_terminal", "subagent"]),
            description=(
                "How the work runs: 'subagent' (one session drives the worker agents itself) "
                "or 'multi_terminal' (a separate terminal per agent). This is the user's "
                "choice, so ask them. The coding tool in use is detected automatically. If "
                "omitted and the account has no default, the call is refused."
            ),
        ),
    ] = "",
    mission: Annotated[
        str,
        Field(
            max_length=MCP_MISSION_MAX,
            description=(
                "Optional goal-at-staging: write this as the project mission before staging. "
                "Routed through update_project_mission -- the same single writer the standalone "
                "tool uses. Omit to stage without touching an existing mission."
            ),
        ),
    ] = "",
    action: Annotated[
        Literal["stage", "unstage", "restage", "cancel_staging"],
        Field(description="'stage' (default) prepares the project; the other three undo staging, as described above."),
    ] = "stage",
    ctx: Context = None,
) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "project_id": project_id,
        "mode": mode,
        "action": action,
        "user_id": _base._resolve_user_id(ctx),
    }
    if mission:
        kwargs["mission"] = mission
    return await _call_tool(ctx, "stage_project", kwargs)


@mcp.tool(
    title="Get Implementation Prompt",
    description=(
        "Fetch the prompt that starts implementation on a project that is staged and has "
        "been approved to start. This RETURNS a prompt; it does not run anything. Two "
        "things must already be true: the project finished staging, and a human approved "
        "the start (the dashboard's Implement button, or launch_implementation). If they "
        "are not, you get a structured refusal naming the exact next step -- there is no "
        "bypass, the approval is deliberate."
    ),
    annotations=_tool_hints("get_implementation_prompt"),
)
async def get_implementation_prompt(
    project_id: Annotated[
        str, Field(max_length=MCP_ID_MAX, description="The project to fetch the implementation prompt for.")
    ],
    ctx: Context = None,
) -> dict[str, Any]:
    """Renamed from ``implement_project`` (BE-9554).

    The old name was half of the worst pair on the surface: ``implement_project`` and
    ``launch_implementation`` sat next to each other, neither implemented anything, and
    the order between them was not guessable from either name. This one FETCHES A PROMPT
    and the other AUTHORISES THE START, so the names now say which is which.
    """
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
        "Release the implementation phase gate for a STAGED project -- the second of the two "
        "human-authorized doors that flip implementation_launched_at (the first is the dashboard "
        "'Implement' button). Reachable from any MCP client, not CLI-only; admission is keyed on "
        "the tenant's Headless setting (off by default). Idempotent (a second call returns "
        "already_launched=true). NOT offered to a platform-spawned worker on a narrower toolset, so "
        "a worker cannot self-unlock. Turning Headless on signs your harness's own permission prompt "
        "for THIS call as your approval -- run that harness with a bypass/skip-permissions flag and "
        "nobody was actually asked. Launching also makes an inactive project active, so it shows in "
        "the dashboard Jobs view; `project_active` in the response confirms it. A project launched "
        "earlier, or one holding another status such as parked, is left as it is: `project_active` is "
        "then false and `next_action` names what to do. Optional `mission` writes the goal via "
        "update_project_mission (the same single writer the standalone tool uses) before the gate is "
        "stamped; omit to launch with the mission already authored during staging."
    ),
    annotations=_tool_hints("launch_implementation", destructive=True),
)
async def launch_implementation(
    project_id: Annotated[str, Field(max_length=MCP_ID_MAX, description="Project id.")],
    mission: Annotated[
        str,
        Field(
            max_length=MCP_MISSION_MAX,
            description=(
                "Optional goal-at-launch: write this as the project mission (via update_project_mission) "
                "before releasing the gate. Omit (or pass empty) to launch without touching the mission."
            ),
        ),
    ] = "",
    ctx: Context = None,
) -> dict[str, Any]:
    kwargs: dict[str, Any] = {"project_id": project_id, "user_id": _base._resolve_user_id(ctx)}
    if mission:
        kwargs["mission"] = mission
    return await _call_tool(ctx, "launch_implementation", kwargs)
