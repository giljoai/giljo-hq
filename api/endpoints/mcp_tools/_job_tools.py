# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from typing import Annotated, Any, Literal

from mcp.server.mcpserver import Context
from pydantic import Field

from api.endpoints.mcp_tools._base import (
    _HARNESS_PARAM_DESCRIPTION,
    MCP_HEAVY_TOOL_META,
    MCP_ID_MAX,
    MCP_MISSION_MAX,
    MCP_NAME_MAX,
    MCP_SHORT_TEXT_MAX,
    _call_tool,
    _detected_harness,
    _resolve_preset_name,
    mcp,
)
from api.endpoints.mcp_tools._tool_annotations import _tool_hints
from giljo_mcp.exceptions import ValidationError
from giljo_mcp.services.orchestrator_caller_guard import ORCHESTRATOR_ONLY


@mcp.tool(
    title="Get Staging Instructions",
    description=(
        "Fetch context for the orchestrator to CREATE a mission plan (near the start of staging, "
        "or during implementation to refresh context). Returns project description (user "
        "requirements), prioritized context fields, and agent_templates for discovering "
        "specialists. Orchestrator-only; analyzes this INPUT, does NOT execute work."
    ),
    meta=MCP_HEAVY_TOOL_META,
    annotations=_tool_hints("get_staging_instructions", destructive=True),
)
async def get_staging_instructions(
    job_id: Annotated[str, Field(max_length=MCP_ID_MAX)],
    harness: Annotated[str, Field(max_length=MCP_ID_MAX, description=_HARNESS_PARAM_DESCRIPTION)] = "",
    ctx: Context = None,
) -> dict[str, Any]:
    preset_name = _resolve_preset_name(harness, ctx)
    detected_harness = _detected_harness(ctx)
    return await _call_tool(
        ctx,
        "get_staging_instructions",
        {"job_id": job_id, "preset_name": preset_name, "detected_harness": detected_harness},
    )


@mcp.tool(
    title="Update Job Mission",
    description=(
        "Persist an agent's mission/execution plan. Orchestrator-only, called during staging so a "
        "fresh-session orchestrator can retrieve it later via get_job_mission() during implementation."
    ),
    annotations=_tool_hints("update_job_mission"),
)
async def update_job_mission(
    job_id: Annotated[str, Field(max_length=MCP_ID_MAX)],
    mission: Annotated[str, Field(max_length=MCP_MISSION_MAX)],
    ctx: Context = None,
) -> dict[str, Any]:
    return await _call_tool(
        ctx,
        "update_job_mission",
        {
            "job_id": job_id,
            "mission": mission,
        },
    )


@mcp.tool(
    title="Report Progress",
    description=(
        "Report incremental progress with TODO items. Backend auto-calculates "
        "percent and step counts. Also auto-wakes idle/sleeping/blocked agents "
        "back to 'working' status."
    ),
    annotations=_tool_hints("report_progress", destructive=True),
)
async def report_progress(
    job_id: Annotated[str, Field(max_length=MCP_ID_MAX)],
    todo_items: Annotated[
        list[dict] | None,
        Field(
            description="FULL TODO list (replaces existing). Each item: {content: str, status: 'pending'|'in_progress'|'completed'}. Include ALL items — completed + in_progress + pending. Never a partial list."
        ),
    ] = None,
    todo_append: Annotated[
        list[dict] | None,
        Field(
            description="NEW items to append (does not replace). Same format as todo_items. Use this to add tasks discovered during work without overwriting existing list."
        ),
    ] = None,
    replace: Annotated[
        bool,
        Field(
            description="A todo_items list SHORTER than the stored one REQUIRES replace=True, or it is rejected (it would silently drop items). Use todo_append to add items without replacing. Default False."
        ),
    ] = False,
    ctx: Context = None,
) -> dict[str, Any]:
    kwargs: dict[str, Any] = {"job_id": job_id, "replace": replace}
    if todo_items is not None:
        kwargs["todo_items"] = todo_items
    if todo_append is not None:
        kwargs["todo_append"] = todo_append
    result = await _call_tool(ctx, "report_progress", kwargs)
    if isinstance(result, dict) and not result.get("warnings"):
        result.pop("warnings", None)
    return result


@mcp.tool(
    title="Complete Job",
    description=(
        "Mark a job as completed with results. Any agent, when all assigned work is done. "
        "Rejected if action-required Hub messages or incomplete TODOs remain -- there is no "
        "bypass. See get_giljo_guide for the three-phase completion contract "
        "(staging_end / closeout / deliverable)."
    ),
    annotations=_tool_hints("complete_job", destructive=True),
)
async def complete_job(
    job_id: Annotated[str, Field(max_length=MCP_ID_MAX)],
    result: Annotated[
        dict,
        Field(
            description="Completion result dict (validator-canonical shape, AgentExecutionResult): 'summary' (str, what was accomplished); 'artifacts' (list[str], optional); 'commits' (list[str], optional). artifacts and commits MUST be LISTS. Extra keys are allowed (e.g. files_changed, decisions_made)."
        ),
    ],
    acknowledge_closeout_todo: Annotated[
        bool,
        Field(
            description="RETIRED: accepted-and-ignored. The self-referential closeout TODO auto-completes structurally on your closeout call whether or not this is passed; non-closeout TODOs still block either way. Kept on the signature only so in-flight callers do not 422. Do not pass it. Default False."
        ),
    ] = False,
    acknowledge_messages_on_complete: Annotated[
        bool,
        Field(
            description="RETIRED: accepted-and-ignored. The messages gate blocks only on genuine action-required posts; drain them with get_thread_history() (unread_only=true, mark_read=true), act, and retry — there is no drain-bypass. Kept on the signature only so in-flight callers do not 422. Do not pass it. Default False."
        ),
    ] = False,
    ctx: Context = None,
) -> dict[str, Any]:
    """Mark a job as completed with results.

    Overloaded three ways by hidden server-side phase (staging_end / closeout /
    deliverable) -- the response's phase/message/next_action fields self-explain
    which one applied. See get_giljo_guide for the full three-phase detail.
    """
    return await _call_tool(
        ctx,
        "complete_job",
        {
            "job_id": job_id,
            "result": result,
            "acknowledge_closeout_todo": acknowledge_closeout_todo,
            "acknowledge_messages_on_complete": acknowledge_messages_on_complete,
        },
    )


@mcp.tool(
    title="Finalize Job",
    description=(
        "Accept a finished agent's work and seal the job (complete -> closed), after "
        "reviewing it. Orchestrator only: pass caller_job_id=<your own job_id>; a worker "
        "ends at complete_job and is refused (ORCHESTRATOR_ONLY). A sealed job is not "
        "woken by new messages. If the agent went silent and never reported, do NOT "
        "decommission it: call complete_job(job_id, result=<what you verified>) yourself, "
        "then finalize. If that returns COMPLETION_BLOCKED, settle its ledger with "
        "report_progress(job_id, todo_items=[...], replace=true), drain its "
        "action-required messages, and retry."
    ),
    annotations=_tool_hints("finalize_job", destructive=True),
)
async def finalize_job(
    job_id: Annotated[str, Field(max_length=MCP_ID_MAX)],
    caller_job_id: Annotated[str, Field(max_length=MCP_ID_MAX)] = "",
    ctx: Context = None,
) -> dict[str, Any]:
    try:
        return await _call_tool(ctx, "close_job", {"job_id": job_id, "caller_job_id": caller_job_id or None})
    except ValidationError as exc:
        if exc.error_code != ORCHESTRATOR_ONLY:
            raise
        return {
            "success": False,
            "error": ORCHESTRATOR_ONLY,
            "calling_agent_role": (exc.context or {}).get("caller_role", "unknown"),
            "message": exc.message + " The job was NOT changed.",
            "next_action": "complete_job, then the orchestrator reviews and finalizes",
        }


@mcp.tool(
    title="Resume Or Dismiss Job",
    description=(
        "A finished job that receives a message needing action is put on hold. Use this to "
        "say what happens next: 'resume' picks the work back up (then report_progress with "
        "todo_append to add new steps -- do not overwrite completed ones), or 'dismiss' "
        "acknowledges the message and leaves the job finished, when it was only for "
        "information. Only works while the job is on hold."
    ),
    annotations=_tool_hints("resume_or_dismiss_job"),
)
async def resume_or_dismiss_job(
    job_id: Annotated[str, Field(max_length=MCP_ID_MAX)],
    action: Annotated[
        Literal["resume", "dismiss"],
        Field(description="'resume' to pick the work back up, or 'dismiss' to acknowledge without resuming."),
    ],
    reason: Annotated[str, Field(max_length=MCP_SHORT_TEXT_MAX)] = "",
    ctx: Context = None,
) -> dict[str, Any]:
    kwargs: dict[str, Any] = {"job_id": job_id}
    if reason:
        kwargs["reason"] = reason
    target = "reactivate_job" if action == "resume" else "dismiss_reactivation"
    return await _call_tool(ctx, target, kwargs)


@mcp.tool(
    title="Set Agent Status",
    description=(
        "Set agent resting/blocked status: 'blocked' (needs human help), 'idle' (monitoring), or "
        "'sleeping' (periodic check-in). All three auto-wake to 'working' on report_progress(). "
        "Server-locked for the orchestrator during staging (403 STAGING_LOCK) -- use "
        "report_progress instead. Spawned non-orchestrator agents bypass the lock."
    ),
    annotations=_tool_hints("set_agent_status"),
)
async def set_agent_status(
    job_id: Annotated[str, Field(max_length=MCP_ID_MAX)],
    status: Annotated[
        Literal["blocked", "idle", "sleeping"],
        Field(description="Target status: 'blocked', 'idle', or 'sleeping'. Other statuses are not valid here."),
    ],
    reason: Annotated[
        str,
        Field(
            max_length=MCP_SHORT_TEXT_MAX,
            description="Human-readable reason. REQUIRED for 'blocked' status. Displayed on dashboard.",
        ),
    ] = "",
    wake_in_minutes: Annotated[
        int | None,
        Field(
            description="Sleep interval hint for 'sleeping' status. Agent will auto-check-in after this many minutes."
        ),
    ] = None,
    wake_on_signal: Annotated[
        bool,
        Field(
            description="For 'sleeping' status: True when you are parked on get_my_turn(wait_seconds=...) "
            "rather than a timed sleep, so the dashboard shows 'Waiting for wake' instead of a countdown. "
            "Mutually exclusive with wake_in_minutes (wake_on_signal wins)."
        ),
    ] = False,
    ctx: Context = None,
) -> dict[str, Any]:
    return await _call_tool(
        ctx,
        "set_agent_status",
        {
            "job_id": job_id,
            "status": status,
            "reason": reason,
            "wake_in_minutes": wake_in_minutes,
            "wake_on_signal": wake_on_signal,
        },
    )


_PLACEHOLDER_JOB_IDS = {"unknown", "none", "null", "", "undefined", "placeholder"}


@mcp.tool(
    title="Get Job Mission",
    description=(
        "Fetch agent-specific mission and context. Call immediately after receiving the thin "
        "prompt from spawn_job -- your first action. The response carries your full agent_profile "
        "(role, instructions, model and effort hints) -- act from it; do not look for installed "
        "agent files. Idempotent. Pass protocol_etag from a prior "
        "fetch to skip the unchanged identity+protocol block (response sets protocol_unchanged=true). "
        "Truncation recovery: pass section=<name from protocol_toc> to refetch ONE small section "
        "of full_protocol."
    ),
    meta=MCP_HEAVY_TOOL_META,
    annotations=_tool_hints("get_job_mission"),
)
async def get_job_mission(
    job_id: Annotated[str, Field(max_length=MCP_ID_MAX)],
    protocol_etag: Annotated[
        str | None,
        Field(
            max_length=128,
            description=(
                "Optional. The protocol_etag returned by a prior get_job_mission call. "
                "When supplied and unchanged, the static identity+protocol block is omitted."
            ),
        ),
    ] = None,
    harness: Annotated[str, Field(max_length=MCP_ID_MAX, description=_HARNESS_PARAM_DESCRIPTION)] = "",
    section: Annotated[
        str,
        Field(
            max_length=128,
            description=(
                "Optional truncation recovery. A section name from a prior response's "
                "protocol_toc; the response then carries ONLY that slice of full_protocol "
                "(byte-identical to the full render, small enough to survive any harness limit). "
                "Default '' returns the full mission response."
            ),
        ),
    ] = "",
    ctx: Context = None,
) -> dict[str, Any]:
    if job_id.strip().lower() in _PLACEHOLDER_JOB_IDS:
        raise ValidationError(
            "This agent was launched without orchestration context. "
            "To use GiljoAI orchestration, the orchestrator must call "
            "spawn_job() first, then pass the returned thin prompt "
            "(which contains the real job_id) to this agent. "
            "Without a valid job_id, you can still operate using your "
            "role instructions — just skip the GiljoAI protocol steps."
        )
    preset_name = _resolve_preset_name(harness, ctx)
    detected_harness = _detected_harness(ctx)
    return await _call_tool(
        ctx,
        "get_job_mission",
        {
            "job_id": job_id,
            "protocol_etag": protocol_etag,
            "preset_name": preset_name,
            "detected_harness": detected_harness,
            "section": section,
        },
    )


@mcp.tool(
    title="Spawn Job",
    description=(
        "Create specialist agent job for execution. Called by: ORCHESTRATOR ONLY during "
        "staging to delegate work (Step 4 of workflow). Orchestrator breaks down mission "
        "into agent-specific tasks and spawns agents who EXECUTE the work. Returns job_id "
        "and thin prompt (~10 lines). Agent later calls get_job_mission() to fetch full "
        "mission. Creates database record linking agent to project. In multi_terminal mode "
        "the returned prompt is normally a dashboard-Copy pointer -- pass inline_seed=true "
        "to get the actual seed text back inline instead (same generator subagent mode "
        "already uses)."
    ),
    annotations=_tool_hints("spawn_job"),
)
async def spawn_job(
    agent_display_name: Annotated[
        str,
        Field(
            max_length=MCP_NAME_MAX,
            description="Agent role label for UI display, e.g. 'implementer', 'tester', 'analyzer'.",
        ),
    ],
    agent_name: Annotated[
        str,
        Field(
            max_length=MCP_NAME_MAX,
            description="Agent template name from agent_templates list, e.g. 'implementer-backend', 'code-reviewer'.",
        ),
    ],
    project_id: Annotated[str, Field(max_length=MCP_ID_MAX)],
    mission: Annotated[
        str,
        Field(
            max_length=MCP_MISSION_MAX,
            description=(
                "The specific work assignment for this agent. Be detailed — this becomes the "
                "agent's full mission. Optional: omit (or pass empty) for a two-phase spawn that "
                "creates a 'staged', messageable agent now and writes the mission later via "
                "update_job_mission (which transitions it from 'staged' to 'waiting')."
            ),
        ),
    ] = "",
    phase: Annotated[
        int | None,
        Field(
            description=(
                "Optional ordering metadata. Same phase = parallel siblings; "
                "higher phase = depends on lower phases completing. "
                "In multi_terminal execution mode the dashboard groups Play buttons by phase. "
                "In subagent modes the orchestrator manages ordering "
                "via Task() / spawn_agent() / @-syntax invocation order; phase is informational. "
                "Must be an integer."
            )
        ),
    ] = None,
    predecessor_job_id: Annotated[
        str,
        Field(
            max_length=MCP_ID_MAX,
            description=(
                "Optional job_id of a previous agent whose output this successor needs. The server "
                "reads the predecessor's completion record and renders an appropriate context "
                "preamble into the successor's mission (chain vs replacement is auto-detected from "
                "the predecessor's status). In subagent execution modes the server silently skips "
                "the preamble because your CLI already returned the predecessor result inline."
            ),
        ),
    ] = "",
    inline_seed: Annotated[
        bool,
        Field(
            description=(
                "In multi_terminal mode, return the actual bootstrap seed text inline (like "
                "subagent modes already do) instead of the dashboard 'Copy prompt' pointer. "
                "No effect outside multi_terminal mode -- subagent modes always seed inline."
            )
        ),
    ] = False,
    ctx: Context = None,
) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "agent_display_name": agent_display_name,
        "agent_name": agent_name,
        "mission": mission,
        "project_id": project_id,
    }
    if phase is not None:
        kwargs["phase"] = phase
    if predecessor_job_id:
        kwargs["predecessor_job_id"] = predecessor_job_id
    if inline_seed:
        kwargs["inline_seed"] = inline_seed
    return await _call_tool(ctx, "spawn_job", kwargs)


@mcp.tool(
    title="Get Agent Result",
    description=(
        "Fetch the completion result of a finished agent job. Returns the structured "
        "result dict (summary, artifacts, commits) stored when the agent called "
        "complete_job. Use this to read what a predecessor agent accomplished."
    ),
    annotations=_tool_hints("get_agent_result"),
)
async def get_agent_result(
    job_id: Annotated[str, Field(max_length=MCP_ID_MAX)],
    ctx: Context = None,
) -> dict[str, Any]:
    return await _call_tool(ctx, "get_agent_result", {"job_id": job_id})


@mcp.tool(
    title="Get Workflow Status",
    description=(
        "Monitor workflow progress across all project agents. Returns active/completed/"
        "blocked/closed/silent/decommissioned/pending agent counts and progress_percent (0-100). "
        "Note: progress_percent is an agent-count ratio (completed/total agents), NOT a "
        "measure of work done. "
        "Use exclude_job_id to omit the calling orchestrator's own job from counts."
    ),
    annotations=_tool_hints("get_workflow_status"),
)
async def get_workflow_status(
    project_id: Annotated[str, Field(max_length=MCP_ID_MAX)],
    exclude_job_id: Annotated[str, Field(max_length=MCP_ID_MAX)] = "",
    ctx: Context = None,
) -> dict[str, Any]:
    kwargs: dict[str, Any] = {"project_id": project_id}
    if exclude_job_id:
        kwargs["exclude_job_id"] = exclude_job_id
    return await _call_tool(ctx, "get_workflow_status", kwargs)
