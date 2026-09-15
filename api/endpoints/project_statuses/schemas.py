# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from pydantic import BaseModel, Field


class ProjectStatusResponse(BaseModel):
    """Public metadata for a single :class:`ProjectStatus` member.

    Mirrors :class:`giljo_mcp.domain.project_status.ProjectStatusMeta`
    plus the canonical ``value`` (the enum's string value).

    The frontend (``StatusBadge.vue``, ``useProjectStatuses`` composable)
    consumes this shape verbatim and resolves ``color_token`` against
    the SCSS custom properties declared in ``design-tokens.scss``.
    """

    value: str = Field(..., description="Canonical status string (matches the Postgres ENUM 'project_status').")
    label: str = Field(..., description="Human-readable badge label.")
    color_token: str = Field(..., description="SCSS custom-property name (no hex literal). Resolves at runtime.")
    is_lifecycle_finished: bool = Field(..., description="True for COMPLETED, CANCELLED, TERMINATED, DELETED.")
    is_immutable: bool = Field(..., description="True if writes via ProjectService.update_project() should be blocked.")
    is_user_mutable_via_mcp: bool = Field(
        ..., description="True if MCP tools may pass this value to update_project_metadata."
    )

    model_config = {"from_attributes": True}
