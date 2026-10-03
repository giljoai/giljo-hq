# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from typing import Annotated, Any

from mcp.server.mcpserver import Context
from mcp_types import InputRequiredResult
from pydantic import Field

from api.endpoints.mcp_tools import _base
from api.endpoints.mcp_tools._base import (
    MCP_ID_MAX,
    MCP_SHORT_TEXT_MAX,
    _call_tool,
    mcp,
)
from api.endpoints.mcp_tools._inline_approval import (
    approval_project_label,
    harness_may_decide,
    maybe_offer_approval_inline,
    resolve_pending_inline_approval,
    with_dashboard_only_notice,
)
from api.endpoints.mcp_tools._tool_annotations import _tool_hints


@mcp.tool(
    title="Request Approval",
    description=(
        "Request a user approval before continuing (HITL gate: closeout with deferred findings, "
        "an ambiguous decision). Orchestrator jobs only -- a worker call is rejected with "
        "ORCHESTRATOR_ONLY_APPROVAL; escalate via post_to_thread instead. See get_giljo_guide for "
        "how the dashboard surfaces and clears this gate."
    ),
    annotations=_tool_hints("request_approval"),
)
async def request_approval(
    job_id: Annotated[
        str,
        Field(
            max_length=MCP_ID_MAX,
            description="Calling agent's job_id (UUID). Flips to status='awaiting_user' until decided.",
        ),
    ],
    project_id: Annotated[str, Field(max_length=MCP_ID_MAX, description="Project UUID the approval belongs to.")],
    reason: Annotated[
        str,
        Field(
            max_length=MCP_SHORT_TEXT_MAX, description="Plain-English explanation shown to the user (<= 2000 chars)."
        ),
    ],
    options: Annotated[
        list[dict],
        Field(description="List of {id, label} option dicts (1-10 items, unique ids)."),
    ],
    context: Annotated[
        dict | None,
        Field(description="Optional structured payload (deferred findings, etc). <= 16 KB serialized."),
    ] = None,
    ctx: Context = None,
) -> dict[str, Any] | InputRequiredResult:
    may_decide = await harness_may_decide(ctx)
    settled = await resolve_pending_inline_approval(ctx, options, may_decide=may_decide)
    if settled is not None:
        return settled

    kwargs: dict[str, Any] = {
        "job_id": job_id,
        "project_id": project_id,
        "reason": reason,
        "options": options,
        "context": context,
    }
    result = await _call_tool(ctx, "request_approval", kwargs)
    if not may_decide:
        return with_dashboard_only_notice(result)
    label = await approval_project_label(ctx, project_id)
    return maybe_offer_approval_inline(ctx, result, reason=reason, options=options, project_label=label)


@mcp.tool(
    title="Decide Approval",
    description=(
        "Answer a pending user approval from the harness -- clears awaiting_user for the "
        "orchestrator that called request_approval. Relay the pending question's reason + "
        "options to the user in your terminal, then call this with the option id they chose. "
        "Routes through the SAME service write the dashboard's decide button uses -- there is "
        "no separate write path. Available by default; a tenant that has switched Settings to "
        "HITL mode is refused here and decides from the dashboard instead."
    ),
    annotations=_tool_hints("decide_approval", destructive=True),
)
async def decide_approval(
    approval_id: Annotated[str, Field(max_length=36, description="The pending approval's id (UUID).")],
    option_id: Annotated[
        str,
        Field(max_length=100, description="The id of the option the user chose (must match one of approval.options)."),
    ],
    ctx: Context = None,
) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "approval_id": approval_id,
        "option_id": option_id,
        "user_id": _base._resolve_user_id(ctx),
    }
    return await _call_tool(ctx, "decide_approval", kwargs)
