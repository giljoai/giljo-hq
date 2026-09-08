# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""Comm-thread response serializers (BE-9207 split).

Cohesive model->API-dict mapping extracted from ``CommThreadService`` to keep that
module under its size budget. Pure functions (no session, no ``self``): they read
a ``CommThread`` / ``Message`` ORM row and return the plain dict the Hub tool
surface and REST adapters return. ``CommThreadService`` calls these; behavior is
byte-identical to the pre-split static methods.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any


if TYPE_CHECKING:
    from giljo_mcp.models.comm import CommThread
    from giljo_mcp.models.tasks import Message


def thread_dict(thread: CommThread, *, extra_project_ids: list[str] | None = None) -> dict[str, Any]:
    """FE-9530: ``project_ids`` is the PLURAL view -- ``thread.project_id`` (the
    single lifecycle-bound project, unchanged) plus any ``comm_thread_project_tags``
    rows the caller looked up, de-duplicated with the bound project always first.
    ``extra_project_ids`` is omitted by callers that have not (yet) fetched tags --
    the list then degrades to exactly the single ``project_id``, so every existing
    caller keeps working without a second query it doesn't want.
    """
    project_ids: list[str] = []
    if thread.project_id:
        project_ids.append(thread.project_id)
    for pid in extra_project_ids or []:
        if pid and pid not in project_ids:
            project_ids.append(pid)
    return {
        "thread_id": thread.id,
        "chat_id": thread.taxonomy_alias,
        "subject": thread.subject,
        "status": thread.status,
        "next_action_owner": thread.next_action_owner,
        "severity": thread.severity,
        "product_id": thread.product_id,
        "project_id": thread.project_id,
        # FE-9530: the plural view. Always present, always a list --
        # [] when the thread is standalone AND untagged, never null.
        "project_ids": project_ids,
        # BE-9291: non-NULL only on a chain hub. The structural link that replaced
        # substring-searching the run_id out of ``subject``.
        "sequence_run_id": thread.sequence_run_id,
        "created_at": thread.created_at.isoformat() if thread.created_at else None,
    }


def message_dict(msg: Message, recipient_state: dict[str, list[str]] | None = None) -> dict[str, Any]:
    out = {
        "message_id": msg.id,
        "thread_id": msg.thread_id,
        "from_agent_id": msg.from_agent_id,
        "from_display_name": msg.from_display_name,
        # BE-9289a: what the author IS, resolved server-side at post time. Readers must
        # use THIS, never the shape of from_agent_id — that slug is self-declared, and
        # an agent posting under its own UUID is legitimate (it once rendered as the
        # human user because a reader guessed from the shape). Never NULL: the column is
        # NOT NULL with an 'agent' default.
        "from_kind": msg.from_kind,
        "content": msg.content,
        "message_type": msg.message_type,
        "priority": msg.priority,
        "status": msg.status,
        "requires_action": msg.requires_action,
        "loop_interval_minutes": msg.loop_interval_minutes,
        "created_at": msg.created_at.isoformat() if msg.created_at else None,
    }
    # FE-9012c (D3): additive MESSAGE-relative junction state, only when the caller
    # (the Hub REST path) asks for it. Absent on the default read (byte-identical).
    if recipient_state is not None:
        recipients = recipient_state.get("recipients", [])
        acted = set(recipient_state.get("acked_by", [])) | set(recipient_state.get("completed_by", []))
        out["recipients"] = recipients
        out["acked_by"] = recipient_state.get("acked_by", [])
        out["completed_by"] = recipient_state.get("completed_by", [])
        out["pending_for"] = [r for r in recipients if r not in acted]
    return out
