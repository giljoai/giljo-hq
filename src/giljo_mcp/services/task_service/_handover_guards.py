# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from typing import Any

from giljo_mcp.services.handover_validation import HANDOVER_TYPE_ABBR, require_handover_shape
from giljo_mcp.services.taxonomy_ops import resolve_task_type_abbr


HANDOVER_NOT_CONVERTIBLE = "HANDOVER_NOT_CONVERTIBLE"
PENDING_HANDOVER_NOT_ARCHIVABLE = "PENDING_HANDOVER_NOT_ARCHIVABLE"


def resolve_create_task_type(task_type: str | None, description: str | None) -> str:
    requested = resolve_task_type_abbr(task_type, operation="create_task")
    if requested == HANDOVER_TYPE_ABBR:
        require_handover_shape(description, operation="create_task")
    return requested


async def handover_state(get_task, task_id: str) -> tuple[bool, str | None]:
    try:
        task = await get_task(task_id)
    except Exception:  # noqa: BLE001 - not-found/permission belong to the caller, not here
        return False, None
    abbreviation = getattr(getattr(task, "task_type", None), "abbreviation", None)
    status = getattr(task, "status", None)
    return abbreviation == HANDOVER_TYPE_ABBR, getattr(status, "value", status)


def handover_not_convertible(task_id: str) -> dict[str, Any]:
    return {
        "success": False,
        "error": HANDOVER_NOT_CONVERTIBLE,
        "task_id": task_id,
        "message": (
            "A handover records a session that already happened; a project plans one that has "
            "not. Converting would delete the handover row and leave a project describing "
            "finished work. Nothing was changed. If the handover surfaced work that still needs "
            "doing, create that project with create_project and leave the handover as the record "
            "of where it came from."
        ),
    }


def pending_handover_not_archivable(task_id: str) -> dict[str, Any]:
    return {
        "success": False,
        "error": PENDING_HANDOVER_NOT_ARCHIVABLE,
        "task_id": task_id,
        "message": (
            "This handover is still pending, which means nobody has read it yet. Hiding it now "
            "would remove it from the list of the one person it was written for. Nothing was "
            "changed. Set status='in_progress' while you verify its claims, then 'completed' "
            "once you have (or 'blocked' if a claim turned out to be false) -- after that it can "
            "be archived."
        ),
    }


async def require_handover_description_shape(get_task, task_id: str, description: str | None) -> None:
    if description is None:
        return
    is_handover, _status = await handover_state(get_task, task_id)
    if is_handover:
        require_handover_shape(description, operation="update_task")


def require_handover_description_shape_of(task: Any, description: str | None) -> None:
    if description is None or description == getattr(task, "description", None):
        return
    if getattr(getattr(task, "task_type", None), "abbreviation", None) == HANDOVER_TYPE_ABBR:
        require_handover_shape(description, operation="update_task")
