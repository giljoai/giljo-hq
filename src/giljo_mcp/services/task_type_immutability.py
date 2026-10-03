# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from typing import Any

from giljo_mcp.exceptions import AuthorizationError, ResourceNotFoundError


TASK_TYPE_FIELD = "task_type"
TASK_TYPE_IMMUTABLE_CONSTRAINT = "immutable"


class TaskTypeImmutableError(ValueError):

    field = TASK_TYPE_FIELD
    constraint = TASK_TYPE_IMMUTABLE_CONSTRAINT

    def __init__(self, *, current_type: str | None, requested_type: str, task_id: str):
        self.current_type = current_type
        self.requested_type = requested_type
        self.task_id = task_id
        current = current_type or "unset"
        super().__init__(
            f"A task's type is fixed at creation and cannot be changed. This task is "
            f"'{current}' and you asked for '{requested_type}'. Nothing was changed. "
            f"Create a new task of type '{requested_type}' with create_task instead."
        )


def require_no_task_type_change(*, current_type: str | None, requested_type: str, task_id: str) -> None:
    requested = (requested_type or "").strip()
    if not requested or requested == (current_type or ""):
        return
    raise TaskTypeImmutableError(current_type=current_type, requested_type=requested, task_id=task_id)


async def require_unchanged_task_type(get_task: Any, task_id: str, requested_type: str | None) -> None:
    if not (requested_type or "").strip():
        return
    try:
        task = await get_task(task_id)
    except (ResourceNotFoundError, AuthorizationError):
        return
    current_type = getattr(getattr(task, "task_type", None), "abbreviation", None)
    if current_type is None:
        return
    require_no_task_type_change(current_type=current_type, requested_type=requested_type, task_id=task_id)
