# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""Best-effort WS broadcast helpers for the Agent Message Hub (BE-6054ef).

These two helpers are called from BOTH the REST router (comm_threads.py) and
the MCP wrapper (_comm_tools.py) so every post/baton update pushes a live
WS event to the dashboard. All failures are swallowed and logged — the DB
write has already committed before these are called, so a WS send failure
must NEVER surface as a 500 to the caller.
"""

import logging
from typing import Any

from giljo_mcp.utils.log_sanitizer import sanitize


logger = logging.getLogger(__name__)


async def broadcast_thread_message(
    ws_manager: Any,
    tenant_key: str,
    *,
    thread_id: str,
    message_id: str,
    from_agent_id: str,
    from_display_name: str,
    content: str,
    message_type: str,
    priority: str,
    requires_action: bool,
    project_id: str | None,
    from_kind: str = "agent",
) -> None:
    """Broadcast a new thread message event to all clients in a tenant.

    Caller MUST check ``if state.websocket_manager:`` before calling.

    BE-9289a: ``from_kind`` carries the SERVER-resolved author kind onto the live
    event, so a message that arrives over the socket renders identically to the same
    message re-read from history. Without it the client would fall back to a default
    and could show the operator's own post as an agent until the next refresh.
    """
    event: dict[str, Any] = {
        "type": "thread_message",
        "data": {
            "tenant_key": tenant_key,
            "thread_id": thread_id,
            "message_id": message_id,
            "from_agent_id": from_agent_id,
            "from_display_name": from_display_name,
            "from_kind": from_kind,
            "content": content,
            "message_type": message_type,
            "priority": priority,
            "requires_action": requires_action,
            "project_id": project_id,
            "update_type": "new",
        },
    }
    try:
        await ws_manager.broadcast_event_to_tenant(tenant_key, event)
    except Exception:  # noqa: BLE001 - WS failure must not affect the already-committed write
        logger.warning("broadcast_thread_message failed for thread %s (non-fatal)", sanitize(thread_id), exc_info=True)


async def broadcast_thread_update(
    ws_manager: Any,
    tenant_key: str,
    *,
    thread_id: str,
    chat_id: str,
    status: str,
    next_action_owner: str | None,
    update_type: str,
    subject: str | None = None,
) -> None:
    """Broadcast a thread metadata-change event (status/baton/rename) to all clients.

    Caller MUST check ``if state.websocket_manager:`` before calling.

    BE-9289b: ``subject`` carries a rename onto the live event. It defaults to None and
    every existing caller omits it, so their payloads are unchanged and the client's
    patch (which skips null fields) ignores it — but without it a rename would only
    appear after a refresh, which is the same half-working shape BE-9289a hit when
    ``from_kind`` was missing from this transport.
    """
    event: dict[str, Any] = {
        "type": "thread_update",
        "data": {
            "tenant_key": tenant_key,
            "thread_id": thread_id,
            "chat_id": chat_id,
            "status": status,
            "next_action_owner": next_action_owner,
            "subject": subject,
            "update_type": update_type,
        },
    }
    try:
        await ws_manager.broadcast_event_to_tenant(tenant_key, event)
    except Exception:  # noqa: BLE001 - WS failure must not affect the already-committed write
        logger.warning("broadcast_thread_update failed for thread %s (non-fatal)", sanitize(thread_id), exc_info=True)
