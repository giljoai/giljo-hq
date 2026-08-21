# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""Chain (linked multi-project) tools -- @mcp.tool wrappers (BE-6221a).

``start_chain_run`` is the headless/CLI entry point the dashboard "Run Sequential"
button already has but MCP lacked. The wrapper registers against the shared ``mcp``
instance from ``_base`` as a decorator side effect at import time and delegates to
the ChainToolsMixin method via ``_call_tool`` (which injects the caller's tenant
from the MCP context). Mirrors _job_tools / _project_tools exactly.
"""

from typing import Annotated, Any

from mcp.server.mcpserver import Context
from pydantic import Field

from api.endpoints.mcp_tools._base import (
    MCP_MISSION_MAX,
    _call_tool,
    mcp,
)
from api.endpoints.mcp_tools._tool_annotations import _tool_hints


@mcp.tool(
    title="Start Chain Run",
    description=(
        "Start a chain run (linked multi-project sequential run) -- the MCP equivalent of the "
        "dashboard 'Run Sequential' button. On success, your session becomes the chain conductor."
    ),
    annotations=_tool_hints("start_chain_run"),
)
async def start_chain_run(
    project_ids: Annotated[
        list[str],
        Field(
            description=(
                "The projects to link into the chain (>= 2 distinct, CHAINABLE project_id strings), "
                "in run order. Capped at the server's MAX_SEQUENCE_PROJECTS."
            )
        ),
    ],
    execution_mode: Annotated[
        str,
        Field(
            description=(
                "REQUIRED. Uniform execution mode for every project in the chain: 'subagent' (one "
                "orchestrator session drives the workers -- the normal headless choice) or "
                "'multi_terminal' (one terminal per agent)."
            )
        ),
    ],
    resolved_order: Annotated[
        list[str] | None,
        Field(
            description=(
                "Optional explicit run order -- a permutation of project_ids. Defaults to the project_ids order."
            )
        ),
    ] = None,
    review_policy: Annotated[
        str,
        Field(description="'per_card' (default, pause for review between projects) or 'auto_close'."),
    ] = "per_card",
    chain_mission: Annotated[
        str | None,
        Field(
            max_length=MCP_MISSION_MAX,
            description=(
                "Optional initial cross-project chain plan. The conductor normally AUTHORS this during "
                "staging; pass it only to seed an initial value."
            ),
        ),
    ] = None,
    ctx: Context = None,
) -> dict[str, Any]:
    """Start a chain run from a headless / CLI agent.

    A bad input (e.g. fewer than 2 distinct project_ids, a non-chainable project)
    returns a structured {success: false, error: CODE} rejection rather than
    raising. See get_giljo_guide for the conductor protocol (get_staging_instructions,
    the human-gate STOP, and the drive-to-finale sequence) once this call succeeds.
    """
    kwargs: dict[str, Any] = {
        "project_ids": project_ids,
        "execution_mode": execution_mode,
        "review_policy": review_policy,
    }
    if resolved_order is not None:
        kwargs["resolved_order"] = resolved_order
    if chain_mission is not None:
        kwargs["chain_mission"] = chain_mission
    return await _call_tool(ctx, "start_chain_run", kwargs)
