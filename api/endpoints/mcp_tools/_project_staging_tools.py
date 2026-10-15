# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from typing import Annotated, Any

from mcp.server.mcpserver import Context
from pydantic import Field

from api.endpoints.mcp_tools._base import MCP_ID_MAX, _call_tool, mcp
from api.endpoints.mcp_tools._tool_annotations import _tool_hints


@mcp.tool(
    title="Unstage Project",
    description=(
        "Undoes staging in your own private Giljo HQ workspace, any time before implementation "
        "starts. Clears the project's staging state and its mission, and retires an orchestrator "
        "that had already started on it for a fresh one. This also starts staging over: call "
        "stage_project again afterwards. Refused once implementation has started, and while the "
        "orchestrator is actively running. To abandon a project instead, call update_project with "
        "status 'cancelled'. It does not approve or launch anything. No outside service is contacted."
    ),
    annotations=_tool_hints("unstage_project", destructive=True),
)
async def unstage_project(
    project_id: Annotated[str, Field(max_length=MCP_ID_MAX, description="The project whose staging to undo.")],
    ctx: Context = None,
) -> dict[str, Any]:
    return await _call_tool(ctx, "unstage_project", {"project_id": project_id})
