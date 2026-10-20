# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from typing import Annotated, Any, Literal

from mcp.server.mcpserver import Context
from pydantic import Field

from api.endpoints.mcp_tools._base import (
    CONSTRAINT_MUTUALLY_EXCLUSIVE,
    GIT_COMMITS_DESC,
    MCP_ID_MAX,
    _call_tool,
    mcp,
    validation_rejection,
)
from api.endpoints.mcp_tools._tool_annotations import _tool_hints
from giljo_mcp.services.memory_entry_write_validator import (
    MEMORY_DECISION_MAX,
    MEMORY_DECISIONS_COUNT,
    MEMORY_KEY_OUTCOME_MAX,
    MEMORY_KEY_OUTCOMES_COUNT,
    MEMORY_SUMMARY_MAX,
)
from giljo_mcp.tools._memory_helpers import NO_CODE_CHANGES_MAX


_SUMMARY_CAP_TEXT = f"Max {MEMORY_SUMMARY_MAX} chars (server-enforced)."

_SUMMARY_ORDER_TEXT = (
    "Send this argument LAST in your call: anything ordered after a long free-text argument "
    "can be silently absorbed into it."
)
_OUTCOMES_CAP_TEXT = (
    f"Max {MEMORY_KEY_OUTCOMES_COUNT} items, each max {MEMORY_KEY_OUTCOME_MAX} chars (server-enforced)."
)
_DECISIONS_CAP_TEXT = f"Max {MEMORY_DECISIONS_COUNT} items, each max {MEMORY_DECISION_MAX} chars (server-enforced)."

_NoCodeChanges = Annotated[
    str,
    Field(max_length=NO_CODE_CHANGES_MAX, description="If nothing was committed, why (instead of git_commits)."),
]


def _both_commits_and_declaration(git_commits: Any, no_code_changes: str) -> dict[str, Any] | None:
    if not (git_commits and no_code_changes.strip()):
        return None
    return validation_rejection(
        field="no_code_changes",
        constraint=CONSTRAINT_MUTUALLY_EXCLUSIVE,
        message="Pass git_commits or no_code_changes, not both.",
    )


_EntryType = Literal[
    "project_completion",
    "project_closeout",
    "baseline",
    "decision",
    "architecture",
    "discovery",
]


@mcp.tool(
    title="Write Project Closeout",
    description=(
        "Close a project and write the 360 Memory closeout entry. Orchestrator-only, at project "
        "completion. All agents must be complete, closed or decommissioned first (resolve via "
        "report_progress + complete_job). With git integration on it needs git_commits, "
        "no_code_changes, or git_commits=[]."
    ),
    annotations=_tool_hints("write_project_closeout", destructive=True),
)
async def write_project_closeout(
    project_id: Annotated[str, Field(max_length=MCP_ID_MAX, description="Project id.")],
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
                "1-5 tags from the 16-tag vocabulary. Change-type: feature, bug-fix, refactor, perf, security, "
                "docs, test, chore. Domain: frontend, backend, database, api, infrastructure, ui-ux, integration."
                " Operational: migration. Pick 1-3 of each axis; an unknown tag is rejected with the allowed "
                "enum. None or [] = no tags."
            )
        ),
    ] = None,
    force: Annotated[
        bool,
        Field(
            description=(
                "Auto-decommission remaining agents and close anyway. Use only when CLOSEOUT_BLOCKED says so (a "
                "leftover 'waiting' orchestrator); refused while the calling orchestrator is still active. An "
                "agent whose work you accepted should be finished with complete_job then finalize_job instead, "
                "since force records it as abandoned."
            )
        ),
    ] = False,
    no_code_changes: _NoCodeChanges = "",
    ctx: Context = None,
) -> dict[str, Any]:
    if (rejection := _both_commits_and_declaration(git_commits, no_code_changes)) is not None:
        return rejection
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
    if no_code_changes:
        kwargs["no_code_changes"] = no_code_changes
    return await _call_tool(ctx, "write_project_closeout", kwargs)


@mcp.tool(
    title="Write Memory Entry",
    description=(
        "Write a 360 memory entry for project completion or handover (orchestrator on completion, "
        "or any agent on handover). With git integration on, project_completion needs git_commits, "
        "no_code_changes, or git_commits=[]."
    ),
    annotations=_tool_hints("write_memory_entry"),
)
async def write_memory_entry(
    project_id: Annotated[str, Field(max_length=MCP_ID_MAX, description="Project id.")],
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
                "baseline, decision, architecture or discovery (any agent); project_completion is "
                "orchestrator-only. For a session handover create a task of type HND instead."
            )
        ),
    ] = "project_completion",
    author_job_id: Annotated[
        str,
        Field(max_length=MCP_ID_MAX, description="The orchestrator's job ID; required for project_completion."),
    ] = "",
    git_commits: Annotated[
        list[dict | str] | None,
        Field(description=GIT_COMMITS_DESC),
    ] = None,
    tags: Annotated[
        list[str] | None,
        Field(
            description=("Up to 8 tags from the 16-tag vocabulary (the same axes as write_project_closeout.tags)."),
        ),
    ] = None,
    acknowledge_closeout_todo: Annotated[
        bool,
        Field(
            description=(
                "Auto-complete your own self-referential closeout TODO before the readiness gate runs; other open"
                " TODOs still block."
            )
        ),
    ] = False,
    no_code_changes: _NoCodeChanges = "",
    ctx: Context = None,
) -> dict[str, Any]:
    if (rejection := _both_commits_and_declaration(git_commits, no_code_changes)) is not None:
        return rejection
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
    if no_code_changes:
        kwargs["no_code_changes"] = no_code_changes
    return await _call_tool(ctx, "write_memory_entry", kwargs)
