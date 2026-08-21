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

import json
import logging
from typing import Any

from giljo_mcp.utils.log_sanitizer import sanitize


logger = logging.getLogger(__name__)

# BE-9414: ids-not-blobs for the thread_message envelope.
#
# A message body is capped at 20,000 characters (MCP_MESSAGE_MAX / _CONTENT_MAX),
# but the CROSS-WORKER leg of this broadcast rides pg_notify, whose payload cap is
# 7999 bytes and is a PostgreSQL protocol limit that cannot be raised. Putting the
# whole body on the wire meant any post over ~7 KB failed the broker publish
# (BE-3008c's guard, working as designed) and every session on another uvicorn
# worker silently never saw it -- visible only on refetch.
#
# Bounded in BYTES, never in characters, because the two differ by up to 12x:
# json.dumps runs ensure_ascii=True, so a non-ASCII BMP character costs 6 bytes
# (\uXXXX) and an ASTRAL one costs 12 (an escaped surrogate pair). 20,000 astral
# characters serialize to ~241 KB -- 30x the cap. A character-count bound that
# provably fit the worst case would have to be ~583 characters, i.e. a headline
# rather than an excerpt.
#
# Measured (tests/api/test_be9414_thread_message_broker_cap.py pins all of this):
#   this event dict, worst-case ids, empty content ... 865 bytes
#   + ws envelope + broker envelope ................. 316 bytes
#   => worst-case NOTIFY payload at this budget ..... 6,816 bytes
#   => headroom under the 7999 cap .................. 1,183 bytes
# The budget leaves ~5.8 KB for content, so ordinary posts -- including most long
# ones -- still travel whole and set content_truncated=False.
_MAX_THREAD_MESSAGE_EVENT_BYTES = 6_500


def _event_size(event: dict[str, Any]) -> int:
    return len(json.dumps(event).encode("utf-8"))


def _bound_content(event: dict[str, Any], content: str) -> None:
    """Trim ``event["data"]["content"]`` in place until the event fits the budget.

    Binary search over prefixes, measured with ``json.dumps`` itself rather than a
    hand-rolled escape table: the guard downstream measures the encoder's output,
    so the bound has to be computed by the same encoder or it can drift away from
    the thing it is supposed to satisfy.
    """
    if _event_size(event) <= _MAX_THREAD_MESSAGE_EVENT_BYTES:
        return

    low, high = 0, len(content)  # invariant: `low` chars always fit, `high` may not
    while low < high:
        mid = (low + high + 1) // 2
        event["data"]["content"] = content[:mid]
        if _event_size(event) <= _MAX_THREAD_MESSAGE_EVENT_BYTES:
            low = mid
        else:
            high = mid - 1

    event["data"]["content"] = content[:low]
    # Set AFTER the search on purpose: the search measured the event carrying
    # ``false`` (5 bytes) and this writes ``true`` (4), so the payload that ships
    # is one byte SMALLER than the one that was measured against the budget --
    # never larger. Setting it first would have measured the smaller form and
    # left the shipped one unverified.
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
) -> None:
    """Broadcast a new thread message event to all clients in a tenant.

    Caller MUST check ``if state.websocket_manager:`` before calling.

    BE-9289a: ``from_kind`` carries the SERVER-resolved author kind onto the live
    event, so a message that arrives over the socket renders identically to the same
    message re-read from history. Without it the client would fall back to a default
    and could show the operator's own post as an agent until the next refresh.

    BE-9414: ``content`` is bounded to a byte budget that provably clears the
    pg_notify cap (see ``_MAX_THREAD_MESSAGE_EVENT_BYTES``), and the event always
    states ``content_truncated`` / ``content_length`` so a receiver can tell a
    SHORTENED body from a short one and fetch the rest. Both the local and the
    cross-worker legs are bounded, not only the cross-worker one: a
    worker-dependent payload shape would leave the trimmed path untested in a
    single-worker configuration, so both legs share the same bound.
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
            # Always present, so "no flag" can never be mistaken for "not truncated"
            # by a client reading an event from a worker that predates this field.
            "content_truncated": False,
            "content_length": len(content),
        },
    }
    _bound_content(event, content)
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
    from_display_name: str | None = None,
    from_kind: str | None = None,
) -> None:
    """Broadcast a thread metadata-change event (status/baton/rename) to all clients.

    Caller MUST check ``if state.websocket_manager:`` before calling.

    BE-9289b: ``subject`` carries a rename onto the live event. It defaults to None and
    every existing caller omits it, so their payloads are unchanged and the client's
    patch (which skips null fields) ignores it — but without it a rename would only
    appear after a refresh, which is the same half-working shape BE-9289a hit when
    ``from_kind`` was missing from this transport.

    BE-9296a: ``from_display_name`` / ``from_kind`` name WHO handed the baton. Without
    them the operator's bell could only name the thread ("<thread> — waiting on you"),
    which is the least useful half of the sentence: the operator already knows which
    thread they are being pulled into, and not which agent is blocked on them. The
    sibling ``broadcast_thread_message`` has carried the same two fields since BE-9289a,
    so this closes a gap between two transports that should have matched. Both default
    to None and are only supplied by the hand-off callers, so a status/rename/read
    update keeps its exact prior payload.
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
            "from_display_name": from_display_name,
            "from_kind": from_kind,
            "update_type": update_type,
        },
    }
    try:
        await ws_manager.broadcast_event_to_tenant(tenant_key, event)
    except Exception:  # noqa: BLE001 - WS failure must not affect the already-committed write
        logger.warning("broadcast_thread_update failed for thread %s (non-fatal)", sanitize(thread_id), exc_info=True)
