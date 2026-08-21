# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
Message Communication Tools -- @mcp.tool wrappers (BE-6042d split of mcp_sdk_server.py).

Mechanically extracted verbatim from the pre-split ``mcp_sdk_server.py``. Each
wrapper registers against the shared ``mcp`` instance from ``_base`` as a decorator
side effect at import time. Behavior, signatures, names, and descriptions unchanged.

BE-9012d (bus retirement, phase d): send_message / receive_messages / get_messages
(and their ``_drain_agent_threads`` shim support) were HARD-REMOVED — the Agent
Message Hub (create_thread / post_to_thread / get_thread_history / ...) is the sole
inter-agent messaging surface now. ``request_approval`` was never part of the bus
and is unaffected.
"""

from typing import Annotated, Any

from mcp.server.mcpserver import Context
from mcp_types import InputRequiredResult
from pydantic import Field

from api.endpoints.mcp_tools._base import (
    MCP_SHORT_TEXT_MAX,
    _call_tool,
    mcp,
)
from api.endpoints.mcp_tools._inline_approval import (
    maybe_offer_approval_inline,
    resolve_pending_inline_approval,
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
        str, Field(description="Calling agent's job_id (UUID). Flips to status='awaiting_user' until decided.")
    ],
    project_id: Annotated[str, Field(description="Project UUID the approval belongs to.")],
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
    # BE-8003l ROUND 2 -- this MUST come before dispatch. A client answering an
    # inline offer retries `tools/call` with BYTE-IDENTICAL arguments (the sealed
    # requestState binds an args digest, so it cannot differ), so dispatching first
    # would mint a SECOND parked approval row for one gate. Returns None on an
    # ordinary first-round call.
    settled = await resolve_pending_inline_approval(ctx, options)
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
    # BE-8003l ROUND 1: the row is now created and the agent parked -- today's
    # behaviour, unconditionally. On a connection that can carry the round-trip
    # (2026-07-28+ AND declared elicitation) we ADDITIONALLY offer the choice
    # inline; every other client gets ``result`` unchanged. Never raises.
    return maybe_offer_approval_inline(ctx, result, reason=reason, options=options)
