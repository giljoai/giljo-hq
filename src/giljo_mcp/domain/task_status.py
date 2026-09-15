# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import enum
from dataclasses import dataclass


@dataclass(frozen=True)
class TaskStatusMeta:

    label: str
    color_token: str
    is_lifecycle_finished: bool


class TaskStatus(enum.StrEnum):

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    BLOCKED = "blocked"
    CANCELLED = "cancelled"

    @property
    def meta(self) -> TaskStatusMeta:
        return TASK_STATUS_META[self]

    @property
    def label(self) -> str:
        return self.meta.label

    @property
    def color_token(self) -> str:
        return self.meta.color_token

    @property
    def is_lifecycle_finished(self) -> bool:
        return self.meta.is_lifecycle_finished


TASK_STATUS_META: dict[TaskStatus, TaskStatusMeta] = {
    TaskStatus.PENDING: TaskStatusMeta(
        label="Pending",
        color_token="color-text-muted",
        is_lifecycle_finished=False,
    ),
    TaskStatus.IN_PROGRESS: TaskStatusMeta(
        label="In Progress",
        color_token="color-agent-implementer",
        is_lifecycle_finished=False,
    ),
    TaskStatus.COMPLETED: TaskStatusMeta(
        label="Completed",
        color_token="color-agent-researcher",
        is_lifecycle_finished=True,
    ),
    TaskStatus.BLOCKED: TaskStatusMeta(
        label="Blocked",
        color_token="color-agent-analyzer",
        is_lifecycle_finished=False,
    ),
    TaskStatus.CANCELLED: TaskStatusMeta(
        label="Cancelled",
        color_token="color-text-muted",
        is_lifecycle_finished=True,
    ),
}


if set(TASK_STATUS_META.keys()) != set(TaskStatus):
    missing = set(TaskStatus) - set(TASK_STATUS_META.keys())
    extra = set(TASK_STATUS_META.keys()) - set(TaskStatus)
    raise RuntimeError(
        f"TASK_STATUS_META drift detected. Missing metadata: {missing}. "
        f"Extra metadata: {extra}. Update giljo_mcp.domain.task_status."
    )


TASK_LIFECYCLE_FINISHED_STATUSES: frozenset[TaskStatus] = frozenset(
    s for s, m in TASK_STATUS_META.items() if m.is_lifecycle_finished
)
VALID_TASK_STATUSES: frozenset[TaskStatus] = frozenset(TaskStatus)
