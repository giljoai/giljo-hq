# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


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
    title="Link Projects",
    description=(
        "Link two or more existing projects to run one after another, under one shared "
        "goal. Say which projects, in the order they should run. Your session then drives "
        "them: work the first to completion, and the next becomes ready automatically -- "
        "check get_workflow_status(project_id) and its ready_to_advance field to see when. "
        "Use unlink_projects to abandon the group part-way. Projects must already exist "
        "and be unfinished; create them first."
    ),
    annotations=_tool_hints("link_projects"),
)
async def link_projects(
    project_ids: Annotated[
        list[str],
        Field(
            description=(
                "The projects to link, as ids, in the order they should run. At least two, "
                "all different. Resolve names to ids with list_projects first."
            )
        ),
    ],
    mission: Annotated[
        str | None,
        Field(
            max_length=MCP_MISSION_MAX,
            description=(
                "The shared goal for the whole group, in plain words. Optional -- pass it now "
                "if you already know it, or write it later once you have planned the work."
            ),
        ),
    ] = None,
    ordered: Annotated[
        list[str] | None,
        Field(
            description=(
                "Only if the run order differs from the order of project_ids: the same ids, "
                "rearranged. Omit and project_ids order is used."
            )
        ),
    ] = None,
    execution_mode: Annotated[
        str | None,
        Field(
            json_schema_extra={"enum": ["subagent", "multi_terminal"]},
            description=(
                "How the work runs: 'subagent' (this session drives the worker agents itself, "
                "the usual choice) or 'multi_terminal' (a separate terminal per agent)."
            ),
        ),
    ] = None,
    ctx: Context = None,
) -> dict[str, Any]:
    """Link projects into one ordered run (BE-9554, replacing start_chain_run's 'start').

    ONE WRITE, then mechanism. BE-9540 made advancement automatic -- a member finishing
    through either door marks review and advances or retires the run server-side -- and
    the read side is ``get_workflow_status.ready_to_advance``. So the record needs
    establishing once and never driving by hand, which is why this is a single verb
    rather than the action-enum tool it replaces.

    Delegates to the SAME accessor method start_chain_run always used, so the owning
    writer is untouched: this is a renamed door, not a parallel write path.
    """
    kwargs: dict[str, Any] = {"project_ids": project_ids, "execution_mode": execution_mode}
    if ordered is not None:
        kwargs["resolved_order"] = ordered
    if mission is not None:
        kwargs["chain_mission"] = mission
    return await _call_tool(ctx, "start_chain_run", kwargs)


@mcp.tool(
    title="Unlink Projects",
    description=(
        "Abandon a linked group of projects part-way: the ones that have not run yet are "
        "released and the group stops. Projects already finished stay finished. Use this "
        "when the plan changes mid-run."
    ),
    annotations=_tool_hints("unlink_projects", destructive=True),
)
async def unlink_projects(
    run_id: Annotated[str, Field(description="The id of the linked group, from link_projects.")],
    ctx: Context = None,
) -> dict[str, Any]:
    """Cancel a linked run, releasing its not-yet-run members (BE-9554).

    The abandon verb, deliberately its own plainly-named tool rather than
    an ``action='cancel'`` enum value: the harness agent IS the conductor now, and a
    conductor with no way to abandon its own run would leave the record pinned open with
    no headless door to release it.

    Byte-identical to the dashboard's Stop chain control -- both reach
    ``SequenceRunService.stop_chain`` through the one owning service (FE-9632). The
    group stops without throwing away the work already done: a member already finished
    stays finished, the member underway is terminated with its agent history kept, and
    members the chain never reached return to inactive so they can be staged again.
    """
    return await _call_tool(ctx, "start_chain_run", {"action": "terminate_remaining", "run_id": run_id})
