# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
Memory & Closeout Tools -- @mcp.tool wrappers (BE-6042d split of mcp_sdk_server.py).

Mechanically extracted verbatim from the pre-split ``mcp_sdk_server.py``. Each
wrapper registers against the shared ``mcp`` instance from ``_base`` as a decorator
side effect at import time. Behavior, signatures, names, and descriptions unchanged.
"""

from typing import Annotated, Any, Literal

from mcp.server.mcpserver import Context
from pydantic import Field

from api.endpoints.mcp_tools._base import (
    GIT_COMMITS_DESC,
    MCP_ID_MAX,
    _call_tool,
    mcp,
)
from api.endpoints.mcp_tools._tool_annotations import _tool_hints
from giljo_mcp.services.memory_entry_write_validator import (
    MEMORY_DECISION_MAX,
    MEMORY_DECISIONS_COUNT,
    MEMORY_KEY_OUTCOME_MAX,
    MEMORY_KEY_OUTCOMES_COUNT,
    MEMORY_SUMMARY_MAX,
)


# BE-3006d: the agent-facing cap text is derived from the SAME constants the
# server-side validator (memory_entry_write_validator) enforces, so the advertised
# limit can never drift from the enforced one (it previously claimed "Max 500"
# while the validator enforced 1500). The boundary validation itself lives in
# validate_memory_entry_write (raises the structured MemoryEntryWriteValidationError,
# surfaced clean by the _call_tool catch-all) — the wrappers only advertise it.
_SUMMARY_CAP_TEXT = f"Max {MEMORY_SUMMARY_MAX} chars (server-enforced)."

# BE-9464: TSK-9450 fixed the message a caller sees AFTER an absorbed call is
# refused; it never touched what the schema teaches beforehand. Length is not
# the variable that matters here -- absorption swallows whatever FOLLOWS a long
# free-text argument in the caller's own tool-call serialization, so send this
# one LAST and there is nothing left to swallow. Why + measurements:
# tests/integration/test_tsk9450_absorption_remedy_wording_mcp_boundary.py
_SUMMARY_ORDER_TEXT = (
    "Send this argument LAST in your call -- anything ordered after a long "
    "free-text argument like this one can be silently absorbed into it and "
    "never arrive as its own argument."
)
_OUTCOMES_CAP_TEXT = (
    f"Max {MEMORY_KEY_OUTCOMES_COUNT} items, each max {MEMORY_KEY_OUTCOME_MAX} chars (server-enforced)."
)
_DECISIONS_CAP_TEXT = f"Max {MEMORY_DECISIONS_COUNT} items, each max {MEMORY_DECISION_MAX} chars (server-enforced)."

# write_memory_entry entry_type allowed set. Mirrors valid_entry_types in
# tools/write_memory_entry.py plus the back-compat alias 'project_closeout' the
# service normalises to 'project_completion'. A hard Literal rejects garbage at
# the FastMCP boundary while the service still owns the worker/orchestrator
# authorization matrix for the orchestrator-only types.
_EntryType = Literal[
    "project_completion",
    "project_closeout",
    "handover_closeout",
    "session_handover",
    "baseline",
    "decision",
    "architecture",
    "discovery",
]


@mcp.tool(
    title="Write Project Closeout",
    description=(
        "Close a project and write the 360 Memory closeout entry. Orchestrator-only, at project "
        "completion. All agents MUST be complete/closed/decommissioned first (resolve via "
        "report_progress + complete_job). git_commits is REQUIRED when git integration is "
        "enabled -- see that param for the accepted shape."
    ),
    # BE-9251: closes the project (terminal) -- see _tool_hints docstring.
    annotations=_tool_hints("write_project_closeout", destructive=True),
)
async def write_project_closeout(
    project_id: Annotated[str, Field(max_length=MCP_ID_MAX)],
    summary: Annotated[
        str,
        Field(description=f"Brief 2-3 sentence headline of project outcome. {_SUMMARY_CAP_TEXT} {_SUMMARY_ORDER_TEXT}"),
    ],
    key_outcomes: Annotated[
        list[str],
        Field(description=f"List of key achievements. {_OUTCOMES_CAP_TEXT}"),
    ],
    decisions_made: Annotated[
        list[str],
        Field(description=f"List of key decisions with rationale. {_DECISIONS_CAP_TEXT}"),
    ],
    git_commits: Annotated[
        list[dict | str] | None,
        Field(description=GIT_COMMITS_DESC),
    ] = None,
    tags: Annotated[
        list[str] | None,
        Field(
            description=(
                "REQUIRED-IN-SPIRIT: 1-5 tags from the 16-entry controlled "
                "vocabulary. Change-type axis: feature, bug-fix, refactor, perf, "
                "security, docs, test, chore. Domain axis: frontend, backend, "
                "database, api, infrastructure, ui-ux, integration. Operational: "
                "migration. Pick 1-3 from change-type AND 1-3 from domain. "
                "Invalid tags are rejected with a structured error carrying the "
                "offending tag and the full allowed enum. None or [] persists "
                "with empty tags (no auto-extraction)."
            )
        ),
    ] = None,
    force: Annotated[
        bool,
        Field(
            description=(
                "Force-close: auto-decommission remaining agents before closing. "
                "Use when the CLOSEOUT_BLOCKED hint says so — e.g. a leftover "
                "'waiting' orchestrator after work was executed outside a staged "
                "session. Refused only while the CALLING orchestrator itself is "
                "still active; it does NOT refuse on account of a specialist. "
                "Any specialist still in flight — including one the health "
                "monitor marked 'silent' — is DECOMMISSIONED, which records it "
                "as failed/replaced/abandoned. So never reach for force to "
                "retire an agent whose work you ACCEPTED: call "
                "complete_job(job_id, result={...}) on it and then "
                "finalize_job(job_id), which reaches 'closed' from any "
                "non-terminal status, 'silent' included. If that complete_job "
                "returns COMPLETION_BLOCKED, the stalled agent left TODOs or "
                "unread messages behind: settle its ledger with "
                "report_progress(job_id, todo_items=[...], replace=true) and "
                "drain its action-required messages, then retry."
            )
        ),
    ] = False,
    ctx: Context = None,
) -> dict[str, Any]:
    # BE-9165 (wall 1): force was hardcoded False here, so the CLOSEOUT_BLOCKED
    # hint "pass force=true" was unwirable from the transport. It is now a real
    # boundary parameter.
    kwargs: dict[str, Any] = {
        "project_id": project_id,
        "summary": summary,
        "key_outcomes": key_outcomes,
        "decisions_made": decisions_made,
        "force": force,
    }
    if git_commits is not None:
        kwargs["git_commits"] = git_commits
    if tags is not None:
        kwargs["tags"] = tags
    return await _call_tool(ctx, "write_project_closeout", kwargs)


@mcp.tool(
    title="Write Memory Entry",
    description=(
        "Write a 360 memory entry for project completion or handover (orchestrator on completion, "
        "or any agent on handover). git_commits is REQUIRED for project_completion when git "
        "integration is enabled -- see that param for the accepted shape."
    ),
    annotations=_tool_hints("write_memory_entry"),
)
async def write_memory_entry(
    project_id: Annotated[str, Field(max_length=MCP_ID_MAX)],
    summary: Annotated[
        str,
        Field(
            description=(
                f"Brief 2-3 sentence headline of what was accomplished or handed over. "
                f"{_SUMMARY_CAP_TEXT} {_SUMMARY_ORDER_TEXT}"
            )
        ),
    ],
    key_outcomes: Annotated[
        list[str],
        Field(description=f"List of key outcomes/achievements. {_OUTCOMES_CAP_TEXT}"),
    ],
    decisions_made: Annotated[
        list[str],
        Field(description=f"List of key decisions with rationale. {_DECISIONS_CAP_TEXT}"),
    ],
    entry_type: Annotated[
        _EntryType,
        Field(
            description=(
                "Entry type. Workers may write: "
                "baseline (foundation context); "
                "decision (a specific choice with rationale); "
                "architecture (structural notes); "
                "discovery (surprising finding worth remembering). "
                "Orchestrator-only (rejected with ORCHESTRATOR_ONLY_ENTRY_TYPE for workers): "
                "project_completion (project closeout); "
                "session_handover (orchestrator-to-orchestrator across sessions). "
                "Legacy: handover_closeout (preserved for back-compat)."
            )
        ),
    ] = "project_completion",
    author_job_id: Annotated[
        str, Field(description="Job ID of the authoring agent (usually the orchestrator's job_id).")
    ] = "",
    git_commits: Annotated[
        list[dict | str] | None,
        Field(description=GIT_COMMITS_DESC),
    ] = None,
    tags: Annotated[
        list[str] | None,
        Field(
            description=(
                "Tags for categorization. Max 8 tags, each from the controlled 16-tag vocabulary "
                "(server-enforced): change-type [feature, bug-fix, refactor, perf, security, docs, test, chore], "
                "domain [frontend, backend, database, api, infrastructure, ui-ux, integration], "
                "operational [migration]."
            ),
        ),
    ] = None,
    acknowledge_closeout_todo: Annotated[
        bool,
        Field(
            description=(
                "When True, auto-complete YOUR OWN self-referential closeout TODOs "
                "(e.g. 'Write series summary') before the closeout-readiness gate "
                "evaluates. Resolves the chicken-and-egg where the TODO this write "
                "satisfies blocks the write. Non-closeout TODOs still block. (This "
                "flag is live HERE; complete_job needs no equivalent -- its closeout "
                "TODO auto-completes structurally.)"
            )
        ),
    ] = False,
    ctx: Context = None,
) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "project_id": project_id,
        "summary": summary,
        "key_outcomes": key_outcomes,
        "decisions_made": decisions_made,
        "entry_type": entry_type,
    }
    if author_job_id:
        kwargs["author_job_id"] = author_job_id
    if git_commits is not None:
        kwargs["git_commits"] = git_commits
    if tags is not None:
        kwargs["tags"] = tags
    if acknowledge_closeout_todo:
        kwargs["acknowledge_closeout_todo"] = acknowledge_closeout_todo
    return await _call_tool(ctx, "write_memory_entry", kwargs)
