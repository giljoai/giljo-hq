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
    MCP_ID_MAX,
    MCP_SHORT_TEXT_MAX,
    READ_PRODUCT_ID_DESC,
    _call_tool,
    mcp,
)
from api.endpoints.mcp_tools._tool_annotations import _tool_hints


@mcp.tool(
    title="Save Roadmap",
    description=(
        "Save the roadmap -- the ranked list of what to build next. YOU do the ranking; the "
        "server only validates and stores it. Send the items you want on the board and they "
        "are written, replacing any earlier entry for the same project or task. See the items "
        "and remove params for their shape. Defaults to your default product; pass product_id "
        "for a specific one."
    ),
    annotations=_tool_hints("save_roadmap"),
)
async def save_roadmap(
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
                "reference a project/task of the resolved product; invalid "
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
    product_id: Annotated[
        str,
        Field(
            max_length=MCP_ID_MAX,
            description=READ_PRODUCT_ID_DESC.format(what="persist the roadmap for"),
        ),
    ] = "",
    ctx: Context = None,
) -> dict[str, Any]:
    kwargs: dict[str, Any] = {"items": items}
    if summary:
        kwargs["summary"] = summary
    if remove:
        kwargs["remove"] = remove
    if patch_fields:
        kwargs["patch_fields"] = True
    if product_id:
        kwargs["product_id"] = product_id
    return await _call_tool(ctx, "update_roadmap_metadata", kwargs)


@mcp.tool(
    title="Get Roadmap",
    description=(
        "Read the current roadmap for the DEFAULT product, or an explicit product_id (read-only). "
        "Items are sorted by sort_order; returns roadmap=null + items=[] when none exists yet. "
        "Call this before re-ranking to see the existing order and any terminal-state items. "
        "Defaults to your default product; pass product_id to read a specific product's roadmap."
    ),
    annotations=_tool_hints("get_roadmap"),
)
async def get_roadmap(
    product_id: Annotated[
        str,
        Field(
            max_length=MCP_ID_MAX,
            description=(
                "Optional product UUID to read the roadmap for. Omit to use the default product "
                "(the default, and what every existing caller gets). A product_id that does not "
                "belong to your account is rejected; it never falls back to the default product."
            ),
        ),
    ] = "",
    ctx: Context = None,
) -> dict[str, Any]:
    # FE-6240: flag the agent path so the service emits roadmap:agent_active.
    # The REST read (the user's browser) calls the service without this flag.
    kwargs: dict[str, Any] = {"emit_agent_active": True}
    if product_id:
        kwargs["product_id"] = product_id
    return await _call_tool(ctx, "get_roadmap", kwargs)
