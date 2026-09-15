# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import enum
from dataclasses import dataclass


@dataclass(frozen=True)
class ProjectStatusMeta:

    label: str
    color_token: str
    is_lifecycle_finished: bool
    is_immutable: bool
    is_user_mutable_via_mcp: bool


class ProjectStatus(enum.StrEnum):

    INACTIVE = "inactive"
    ACTIVE = "active"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    TERMINATED = "terminated"
    DELETED = "deleted"
    SUPERSEDED = "superseded"
    PARKED = "parked"

    @property
    def meta(self) -> ProjectStatusMeta:

        return PROJECT_STATUS_META[self]

    @property
    def label(self) -> str:

        return self.meta.label

    @property
    def color_token(self) -> str:

        return self.meta.color_token

    @property
    def is_lifecycle_finished(self) -> bool:

        return self.meta.is_lifecycle_finished

    @property
    def is_immutable(self) -> bool:

        return self.meta.is_immutable

    @property
    def is_user_mutable_via_mcp(self) -> bool:

        return self.meta.is_user_mutable_via_mcp


PROJECT_STATUS_META: dict[ProjectStatus, ProjectStatusMeta] = {
    ProjectStatus.INACTIVE: ProjectStatusMeta(
        label="Inactive",
        color_token="color-text-muted",
        is_lifecycle_finished=False,
        is_immutable=False,
        is_user_mutable_via_mcp=True,
    ),
    ProjectStatus.ACTIVE: ProjectStatusMeta(
        label="Active",
        color_token="color-agent-implementer",
        is_lifecycle_finished=False,
        is_immutable=False,
        is_user_mutable_via_mcp=True,
    ),
    ProjectStatus.COMPLETED: ProjectStatusMeta(
        label="Completed",
        color_token="color-status-complete",
        is_lifecycle_finished=True,
        is_immutable=True,
        is_user_mutable_via_mcp=True,
    ),
    ProjectStatus.CANCELLED: ProjectStatusMeta(
        label="Cancelled",
        color_token="color-status-blocked",
        is_lifecycle_finished=True,
        is_immutable=True,
        is_user_mutable_via_mcp=True,
    ),
    ProjectStatus.TERMINATED: ProjectStatusMeta(
        label="Terminated",
        color_token="color-agent-analyzer",
        is_lifecycle_finished=True,
        is_immutable=False,
        is_user_mutable_via_mcp=False,
    ),
    ProjectStatus.DELETED: ProjectStatusMeta(
        label="Deleted",
        color_token="color-agent-analyzer",
        is_lifecycle_finished=True,
        is_immutable=False,
        is_user_mutable_via_mcp=False,
    ),
    ProjectStatus.SUPERSEDED: ProjectStatusMeta(
        label="Superseded",
        color_token="color-agent-orchestrator",
        is_lifecycle_finished=True,
        is_immutable=True,
        is_user_mutable_via_mcp=True,
    ),
    ProjectStatus.PARKED: ProjectStatusMeta(
        label="Parked",
        color_token="color-agent-reviewer",
        is_lifecycle_finished=False,
        is_immutable=False,
        is_user_mutable_via_mcp=True,
    ),
}


if set(PROJECT_STATUS_META.keys()) != set(ProjectStatus):
    missing = set(ProjectStatus) - set(PROJECT_STATUS_META.keys())
    extra = set(PROJECT_STATUS_META.keys()) - set(ProjectStatus)
    raise RuntimeError(
        f"PROJECT_STATUS_META drift detected. Missing metadata: {missing}. "
        f"Extra metadata: {extra}. Update giljo_mcp.domain.project_status."
    )


IMMUTABLE_PROJECT_STATUSES: frozenset[ProjectStatus] = frozenset(
    s for s, m in PROJECT_STATUS_META.items() if m.is_immutable
)
LIFECYCLE_FINISHED_STATUSES: frozenset[ProjectStatus] = frozenset(
    s for s, m in PROJECT_STATUS_META.items() if m.is_lifecycle_finished
)
VALID_UPDATE_STATUSES: frozenset[ProjectStatus] = frozenset(
    s for s, m in PROJECT_STATUS_META.items() if m.is_user_mutable_via_mcp
)
VALID_PROJECT_STATUSES: frozenset[ProjectStatus] = frozenset(ProjectStatus)
