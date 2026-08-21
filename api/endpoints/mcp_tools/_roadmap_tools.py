# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
Roadmap Tools -- @mcp.tool wrappers (FE-6022a).

Registers ``update_roadmap_metadata`` against the shared ``mcp`` instance from
``_base`` as a decorator side effect at import time, mirroring the other domain
wrapper modules. The local CLI agent does all roadmap reasoning client-side and
persists the result here; the server only validates + stores.
"""

from typing import Annotated, Any

from mcp.server.mcpserver import Context
from pydantic import Field

from api.endpoints.mcp_tools._base import (
    MCP_SHORT_TEXT_MAX,
    _call_tool,
    mcp,
)
from api.endpoints.mcp_tools._tool_annotations import _tool_hints


@mcp.tool(
    title="Update Roadmap",
    description=(
        "Persist a roadmap for the ACTIVE product. The local agent does all "
        "ranking/risk/complexity reasoning; the server runs no inference, just validates + "
        "stores. Bulk upsert, de-duped on (item_type, project/task) -- re-saving an item updates "
        "it in place. See the items/remove params for their exact per-item shape. Requires an "
        "active product."
    ),
    annotations=_tool_hints("update_roadmap_metadata"),
)
async def update_roadmap_metadata(
    items: Annotated[
        list[dict[str, Any]],
        Field(
            description=(
                "List of roadmap items to upsert. Each: {item_type: 'project'|'task', "
                "project_id OR task_id, sort_order (int 0..100000), risk?: 'low'|'med'|'high', "
                "complexity?: 'light'|'med'|'heavy', blocked?: bool (default false), "
                "blocked_reason?: str (<=500 chars, the red BLOCKED-row note; dropped when "
                "blocked is false)}. project_id / task_id take EITHER the row's id or its "
                "taxonomy_alias -- the handle already shown everywhere else ('BE-0001', "
                "'IMP-0086') -- so no list_projects/list_tasks lookup is needed. Must "
                "reference a project/task of the active product; invalid "
                "enums/lengths/ids are rejected with a ValidationError (422), never a DB 500, "
                "and a rejection names EVERY bad row at once, not just the first."
            )
        ),
    ],
    summary: Annotated[
        str,
        Field(
            max_length=MCP_SHORT_TEXT_MAX,
            description="Optional AI insight banner copy for the roadmap. Empty string leaves it unchanged.",
        ),
    ] = "",
    remove: Annotated[
        list[dict[str, Any]],
        Field(
            description=(
                "Optional list of items to remove from the roadmap. Each: "
                "{item_type: 'project'|'task', project_id|task_id}. Idempotent; "
                "removes only the roadmap entry, never the project/task itself."
            )
        ),
    ] = None,
    patch_fields: Annotated[
        bool,
        Field(
            description=(
                "Partial update. Default false, which keeps the original behaviour: every "
                "metadata field is written from the item you send, so a field you leave out "
                "is reset. Set true and each item patches only what it carries -- a field you "
                "OMIT keeps its stored value, and a field you send as null or an empty string "
                "is CLEARed. Use it to move one item without resending its risk, complexity and "
                "blocked note. Omitting a field and sending it empty are DIFFERENT instructions. "
                "Two details worth knowing: 'blocked' and 'blocked_reason' patch together -- send "
                "both or neither, because an unblocked item never keeps a note; and 'sort_order' is "
                "always a number, so its empty value is 0 and null is still refused. A row that "
                "does not exist yet is inserted with the usual defaults either way."
            )
        ),
    ] = False,
    ctx: Context = None,
) -> dict[str, Any]:
    kwargs: dict[str, Any] = {"items": items}
    if summary:
        kwargs["summary"] = summary
    if remove:
        kwargs["remove"] = remove
    if patch_fields:
        kwargs["patch_fields"] = True
    return await _call_tool(ctx, "update_roadmap_metadata", kwargs)


@mcp.tool(
    title="Get Roadmap",
    description=(
        "Read the current roadmap for the ACTIVE product (read-only). Items are sorted by "
        "sort_order; returns roadmap=null + items=[] when none exists yet. Call this before "
        "re-ranking to see the existing order and any terminal-state items. Requires an active "
        "product."
    ),
    annotations=_tool_hints("get_roadmap"),
)
async def get_roadmap(ctx: Context = None) -> dict[str, Any]:
    # FE-6240: flag the agent path so the service emits roadmap:agent_active.
    # The REST read (the user's browser) calls the service without this flag.
    return await _call_tool(ctx, "get_roadmap", {"emit_agent_active": True})
