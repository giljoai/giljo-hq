# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from typing import Annotated, Any

from mcp.server.mcpserver import Context
from pydantic import Field

from api.endpoints._boundary_types import LIST_ITEMS_MAX
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
        "are written, replacing any earlier entry for the same project or task; see items for "
        "the shape. To take an item off the board call remove_roadmap_items. Defaults to your "
        "default product; pass product_id for a specific one."
    ),
    annotations=_tool_hints("save_roadmap", destructive=True),
)
async def save_roadmap(
    items: Annotated[
        list[dict[str, Any]],
        Field(
            max_length=LIST_ITEMS_MAX,
            description=(
                "Roadmap items to upsert: {item_type: 'project'|'task', project_id OR task_id (the row's id or "
                "its taxonomy_alias, 'BE-0001' or 'IMP-0086'), sort_order (0..100000), risk?: low|med|high, "
                "complexity?: light|med|heavy, blocked?: bool, blocked_reason?: str (<=500 chars, dropped when "
                "not blocked)}. Items must belong to the resolved product; a rejection names EVERY bad row at "
                "once."
            ),
        ),
    ],
    summary: Annotated[
        str,
        Field(
            max_length=MCP_SHORT_TEXT_MAX,
            description="One-sentence AI insight banner: why this order, not status notes. Empty=unchanged.",
        ),
    ] = "",
    patch_fields: Annotated[
        bool,
        Field(
            description=(
                "Partial update. Default false writes every metadata field from each item (an omitted field is "
                "reset). True patches only what you send: an omitted field keeps its value, null or '' clears it;"
                " blocked and blocked_reason patch together; sort_order is always a number. New rows are inserted"
                " either way."
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
    if patch_fields:
        kwargs["patch_fields"] = True
    if product_id:
        kwargs["product_id"] = product_id
    return await _call_tool(ctx, "update_roadmap_metadata", kwargs)


@mcp.tool(
    title="Remove Roadmap Items",
    description=(
        "Take items off the roadmap. Removes only the roadmap entry, never the project or task "
        "itself; an item that is not on the roadmap is a no-op. Defaults to your default "
        "product; pass product_id for a specific one."
    ),
    annotations=_tool_hints("remove_roadmap_items", destructive=True),
)
async def remove_roadmap_items(
    items: Annotated[
        list[dict[str, Any]],
        Field(
            min_length=1,
            max_length=LIST_ITEMS_MAX,
            description=(
                "Roadmap entries to remove. Each: {item_type: 'project'|'task', project_id OR "
                "task_id}, by the row's id or its taxonomy_alias ('BE-0001', 'IMP-0086')."
            ),
        ),
    ],
    product_id: Annotated[
        str,
        Field(
            max_length=MCP_ID_MAX,
            description=READ_PRODUCT_ID_DESC.format(what="remove roadmap entries from"),
        ),
    ] = "",
    ctx: Context = None,
) -> dict[str, Any]:
    kwargs: dict[str, Any] = {"items": [], "remove": items}
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
    kwargs: dict[str, Any] = {"emit_agent_active": True}
    if product_id:
        kwargs["product_id"] = product_id
    return await _call_tool(ctx, "get_roadmap", kwargs)
