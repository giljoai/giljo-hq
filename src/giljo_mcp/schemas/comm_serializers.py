# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from typing import TYPE_CHECKING, Any


if TYPE_CHECKING:
    from giljo_mcp.models.comm import CommThread
    from giljo_mcp.models.tasks import Message


def thread_dict(thread: CommThread, *, extra_project_ids: list[str] | None = None) -> dict[str, Any]:
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
        "project_ids": project_ids,
        "sequence_run_id": thread.sequence_run_id,
        "created_at": thread.created_at.isoformat() if thread.created_at else None,
    }


def message_dict(msg: Message, recipient_state: dict[str, list[str]] | None = None) -> dict[str, Any]:
    out = {
        "message_id": msg.id,
        "thread_id": msg.thread_id,
        "from_agent_id": msg.from_agent_id,
        "from_display_name": msg.from_display_name,
        "from_kind": msg.from_kind,
        "content": msg.content,
        "message_type": msg.message_type,
        "priority": msg.priority,
        "status": msg.status,
        "requires_action": msg.requires_action,
        "loop_interval_minutes": msg.loop_interval_minutes,
        "created_at": msg.created_at.isoformat() if msg.created_at else None,
    }
    if recipient_state is not None:
        recipients = recipient_state.get("recipients", [])
        acted = set(recipient_state.get("acked_by", [])) | set(recipient_state.get("completed_by", []))
        out["recipients"] = recipients
        out["acked_by"] = recipient_state.get("acked_by", [])
        out["completed_by"] = recipient_state.get("completed_by", [])
        out["pending_for"] = [r for r in recipients if r not in acted]
    return out
