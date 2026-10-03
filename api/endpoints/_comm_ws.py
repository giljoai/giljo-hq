# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import json
import logging
from typing import Any


logger = logging.getLogger(__name__)

_MAX_THREAD_MESSAGE_EVENT_BYTES = 6_500


def _event_size(event: dict[str, Any]) -> int:
    return len(json.dumps(event).encode("utf-8"))


def _bound_content(event: dict[str, Any], content: str) -> None:
    if _event_size(event) <= _MAX_THREAD_MESSAGE_EVENT_BYTES:
        return

    low, high = 0, len(content)
    while low < high:
        mid = (low + high + 1) // 2
        event["data"]["content"] = content[:mid]
        if _event_size(event) <= _MAX_THREAD_MESSAGE_EVENT_BYTES:
            low = mid
        else:
            high = mid - 1

    event["data"]["content"] = content[:low]
    event["data"]["content_truncated"] = True


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
    to_participant: str | None = None,
) -> None:
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
            "to_participant": to_participant,
            "update_type": "new",
            "content_truncated": False,
            "content_length": len(content),
        },
    }
    _bound_content(event, content)
    await ws_manager.broadcast_event_to_tenant(tenant_key, event)


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
    from_display_name: str | None = None,
    from_kind: str | None = None,
) -> None:
    event: dict[str, Any] = {
        "type": "thread_update",
        "data": {
            "tenant_key": tenant_key,
            "thread_id": thread_id,
            "chat_id": chat_id,
            "status": status,
            "next_action_owner": next_action_owner,
            "subject": subject,
            "from_display_name": from_display_name,
            "from_kind": from_kind,
            "update_type": update_type,
        },
    }
    await ws_manager.broadcast_event_to_tenant(tenant_key, event)
