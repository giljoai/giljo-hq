# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import logging
from typing import Annotated, Any, Literal

from mcp.server.mcpserver import Context
from pydantic import Field

from api.endpoints._boundary_types import THREAD_PROJECT_TAGS_MAX
from api.endpoints._comm_ws import broadcast_thread_update
from api.endpoints.mcp_tools import _base
from api.endpoints.mcp_tools._base import MCP_ID_MAX, MCP_NAME_MAX, _call_tool, mcp
from api.endpoints.mcp_tools._tool_annotations import _tool_hints


logger = logging.getLogger(__name__)


@mcp.tool(
    title="Update Thread",
    description=(
        "Edit a thread in your own private Giljo HQ workspace only; no outside service is "
        "contacted. Rename it, set its status, and/or retag its product/projects. This is the "
        "ONLY way to give a pre-existing thread a product. Pass product_id to set it, "
        "clear_product=true to null it, or project_ids to full-replace its project tags (an "
        "empty list clears all). Omit a field to leave it untouched. A rename is refused on a "
        "project-bound thread (it takes its name from that project)."
    ),
    annotations=_tool_hints("update_thread", destructive=True),
)
async def update_thread(
    thread_id: Annotated[str, Field(max_length=MCP_ID_MAX, description="The thread UUID to update.")],
    subject: Annotated[str, Field(max_length=MCP_NAME_MAX, description="New subject. Omit to leave unchanged.")] = "",
    status: Annotated[
        Literal["", "open", "active", "resolved", "closed"],
        Field(description="New status. Omit (empty) to leave unchanged."),
    ] = "",
    product_id: Annotated[
        str, Field(max_length=MCP_ID_MAX, description="Product UUID to retag the thread with. Omit to leave unchanged.")
    ] = "",
    clear_product: Annotated[
        bool, Field(description="Explicitly null the thread's product back to product-less.")
    ] = False,
    project_ids: Annotated[
        list[Annotated[str, Field(max_length=MCP_ID_MAX)]] | None,
        Field(
            default=None,
            max_length=THREAD_PROJECT_TAGS_MAX,
            description=(
                "Full-replace the thread's project tags (0-50 UUIDs). Omit (null) to leave "
                "tags untouched; pass [] to clear all tags."
            ),
        ),
    ] = None,
    ctx: Context = None,
) -> dict[str, Any]:
    kwargs: dict[str, Any] = {"thread_id": thread_id}
    if subject:
        kwargs["subject"] = subject
    if status:
        kwargs["status"] = status
    if product_id:
        kwargs["product_id"] = product_id
    if clear_product:
        kwargs["clear_product"] = True
    if project_ids is not None:
        kwargs["project_ids"] = project_ids
    result = await _call_tool(ctx, "update_thread", kwargs)
    from api.app_state import state as _state

    if _state.websocket_manager:
        tenant_key = _base._resolve_tenant(ctx)
        await broadcast_thread_update(
            _state.websocket_manager,
            tenant_key,
            thread_id=result.get("thread_id", thread_id),
            chat_id=result.get("chat_id", ""),
            status=result.get("status", "open"),
            next_action_owner=result.get("next_action_owner"),
            subject=result.get("subject"),
            update_type="updated",
        )
    return result
