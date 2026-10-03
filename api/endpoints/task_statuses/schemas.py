# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from pydantic import BaseModel, Field


class TaskStatusResponse(BaseModel):
    """Public metadata for a single :class:`TaskStatus` member.

    Mirrors :class:`giljo_mcp.domain.task_status.TaskStatusMeta` plus the
    canonical ``value`` (the enum's string value).

    The frontend (``TaskStatusBadge.vue`` and its store) consumes this
    shape verbatim and resolves ``color_token`` against the CSS custom
    properties declared in ``main.scss``.
    """

    value: str = Field(..., description="Canonical task status string written to the tasks.status column.")
    label: str = Field(..., description="Human-readable badge label.")
    color_token: str = Field(..., description="CSS custom property name (no hex literal). Resolves at runtime.")
    is_lifecycle_finished: bool = Field(
        ...,
        description="True for COMPLETED and CANCELLED -- terminal states with no further progress.",
    )

    model_config = {"from_attributes": True}
