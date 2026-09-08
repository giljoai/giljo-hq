# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""Shared post_to_thread WS-broadcast helper (BE-9197 / BE-9502a).

Split out of _comm_tools.py (already at its 800-line file-size cap): the baton
and rename follow-ons re-read the thread through the MCP tool accessor and push
the SAME thread_update shape, so they share one function rather than two
near-identical inline blocks.
"""

from __future__ import annotations

import logging

from mcp.server.mcpserver import Context

from api.endpoints._comm_ws import broadcast_thread_update
from api.endpoints.mcp_tools import _base


logger = logging.getLogger(__name__)


async def broadcast_thread_metadata_update(
    ctx: Context,
    thread_id: str,
    *,
    update_type: str,
    next_action_owner: str | None = None,
    from_display_name: str | None = None,
    from_kind: str | None = None,
    include_subject: bool = False,
) -> None:
    """Best-effort thread_update shared by post_to_thread's baton (BE-9197) and
    rename (BE-9502a) follow-ons -- re-reads the thread fresh; never fails the
    post. ``include_subject`` defaults False so baton stays parity-tested
    byte-identical with standalone ``pass_baton`` (which omits it, BE-9289b).
    """
    try:
        from api.app_state import state as _state

        if not _state.websocket_manager:
            return
        tenant_key = _base._resolve_tenant(ctx)
        accessor = _base._get_tool_accessor()
        history = await accessor._comm_thread_service.get_thread_history(thread_id=thread_id, tenant_key=tenant_key)
        t = history["thread"]
        await broadcast_thread_update(
            _state.websocket_manager,
            tenant_key,
            thread_id=thread_id,
            chat_id=t["chat_id"],
            status=t["status"],
            next_action_owner=next_action_owner if next_action_owner is not None else t.get("next_action_owner"),
            subject=t.get("subject") if include_subject else None,
            update_type=update_type,
            from_display_name=from_display_name,
            from_kind=from_kind,
        )
    except Exception:  # noqa: BLE001 - WS failure is non-fatal; the underlying write already committed
        logger.debug("MCP post_to_thread %s WS broadcast failed (non-fatal)", update_type, exc_info=True)
