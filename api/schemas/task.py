# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class TaskCreate(BaseModel):
    """
    Schema for creating a task (POST /tasks/).

    Product is required to ensure tasks are always bound to the active product
    (Handover 0433 Phase 4). Project is optional.
    """

    title: str = Field(..., min_length=1, max_length=255, description="Task title")
    description: str | None = Field(None, description="Task description")
    status: Literal["pending", "in_progress", "completed", "blocked", "cancelled"] | None = Field(
        None, description="Task status: pending, in_progress, completed, blocked, cancelled"
    )
    priority: Literal["low", "medium", "high", "critical"] | None = Field(
        None, description="Task priority: low, medium, high, critical"
    )
    task_type: str | None = Field(
        None,
        max_length=4,
        description=(
            "'TSK' (default, an ordinary task) or 'HND' (a session handover). No other value is "
            "accepted -- BE/FE/INF and the rest are PROJECT types. An 'HND' description must "
            "carry the headings '## Verify before trusting', '## Waiting on the operator' and "
            "'## Cannot testify', each with at least one line under it."
        ),
    )
    series_number: int | None = Field(
        None,
        ge=1,
        le=9999,
        description=(
            "Optional explicit series number. If omitted and task_type is set, the "
            "backend auto-assigns from the shared task+project counter (BE-5065)."
        ),
    )
    product_id: str = Field(..., description="Product ID (required - Handover 0433)")
    project_id: str | None = Field(None, description="Associated project ID")
    parent_task_id: str | None = Field(None, description="Parent task ID for hierarchy")
    estimated_effort: float | None = Field(None, ge=0, description="Estimated effort in hours")
    actual_effort: float | None = Field(None, ge=0, description="Actual effort in hours")

    model_config = ConfigDict(from_attributes=True)


class TaskUpdate(BaseModel):
    """
    Schema for updating a task (PATCH /tasks/{id}).

    Users can update their own tasks or tasks assigned to them.
    Admins can update any task in their tenant.
    """

    title: str | None = Field(None, min_length=1, max_length=255, description="Task title")
    description: str | None = Field(None, description="Task description")
    status: Literal["pending", "in_progress", "completed", "blocked", "cancelled"] | None = Field(
        None, description="Task status: pending, in_progress, completed, blocked, cancelled"
    )
    priority: Literal["low", "medium", "high", "critical"] | None = Field(
        None, description="Task priority: low, medium, high, critical"
    )
    task_type: str | None = Field(
        None,
        max_length=4,
        description=(
            "'TSK' (default, an ordinary task) or 'HND' (a session handover). No other value is "
            "accepted -- BE/FE/INF and the rest are PROJECT types. An 'HND' description must "
            "carry the headings '## Verify before trusting', '## Waiting on the operator' and "
            "'## Cannot testify', each with at least one line under it."
        ),
    )
    estimated_effort: float | None = Field(None, ge=0, description="Estimated effort in hours")
    actual_effort: float | None = Field(None, ge=0, description="Actual effort in hours")
    parent_task_id: str | None = Field(None, description="Parent task ID for hierarchy changes")
    product_id: str | None = Field(None, description="Update product scope")
    project_id: str | None = Field(None, description="Update associated project")
    hidden: bool | None = Field(
        None,
        description="Toggle the per-row UI declutter flag (FE-5046). Does NOT affect default list visibility for agents.",
    )
    completion_notes: str | None = Field(
        None,
        description=(
            "Audit-trail notes appended to the task description when status transitions to "
            "'completed'. Silently ignored for any other status. Mirrors the MCP "
            "complete_task tool's completion_notes parameter (no length cap)."
        ),
    )

    model_config = ConfigDict(from_attributes=True)


class TaskConversionRequest(BaseModel):
    """
    Schema for task-to-project conversion (POST /tasks/{id}/convert).

    Conversion strategies:
    - single: Convert task + subtasks to one project
    - individual: Convert each subtask to separate project
    - grouped: Group subtasks by category into projects
    """

    project_name: str | None = Field(
        default=None, min_length=1, max_length=255, description="Name for new project (defaults to task title)"
    )
    strategy: str = Field(default="single", description="Conversion strategy: single | individual | grouped")
    include_subtasks: bool = Field(default=True, description="Include subtasks in conversion")

    model_config = ConfigDict(from_attributes=True)


class ProjectConversionResponse(BaseModel):
    """
    Schema for conversion response after creating project from task.
    """

    project_id: str = Field(..., description="ID of created project")
    project_name: str = Field(..., description="Name of created project")
    original_task_id: str = Field(..., description="ID of original task")
    conversion_strategy: str = Field(..., description="Strategy used for conversion")
    created_at: datetime = Field(..., description="Project creation timestamp")

    model_config = ConfigDict(from_attributes=True)


class TaskResponse(BaseModel):
    """
    Enhanced task response with user fields for Phase 4.

    Includes:
    - User ownership (created_by_user_id)
    - User assignment (assigned_to_user_id)
    - Conversion tracking (converted_to_project_id)
    """

    id: str = Field(..., description="Task ID")
    title: str = Field(..., description="Task title")
    description: str | None = Field(None, description="Task description")
    task_type: str | None = Field(None, description="'TSK' (an ordinary task) or 'HND' (a session handover).")
    task_type_id: str | None = Field(None, description="FK to taxonomy_types row")
    task_type_color: str | None = Field(
        None,
        description="Hex color from taxonomy_types.color (FE renders type+serial badge tint).",
    )
    series_number: int | None = Field(
        None,
        description="Sequential number within task_type (e.g. 17 in BE-0017). Null for untyped tasks.",
    )
    subseries: str | None = Field(
        None,
        description="Single-letter subseries suffix (e.g. 'a' in BE-0017a). Null when not used.",
    )
    taxonomy_alias: str | None = Field(
        None,
        description="Composed alias 'TYPE-NNNN[suffix]' (e.g. 'BE-0017a'). Empty string for untyped tasks.",
    )
    hidden: bool = Field(
        default=False,
        description="Per-row UI declutter flag (FE-5046). Default-list dashboard filters hidden=false.",
    )
    status: str = Field(..., description="Task status")
    priority: str = Field(..., description="Task priority")
    product_id: str | None = Field(None, description="Product ID for isolation")
    project_id: str | None = Field(
        None, description="Associated project ID (nullable for unassigned tasks - Handover 0072)"
    )

    parent_task_id: str | None = Field(None, description="Parent task ID for subtasks")

    created_by_user_id: str | None = Field(None, description="User who created task")
    converted_to_project_id: str | None = Field(None, description="Project ID if task was converted")

    created_at: datetime = Field(..., description="Task creation timestamp")
    started_at: datetime | None = Field(None, description="Task start timestamp")
    completed_at: datetime | None = Field(None, description="Task completion timestamp")
    deleted_at: datetime | None = Field(None, description="Soft-delete timestamp (NULL for live tasks)")

    estimated_effort: float | None = Field(None, description="Estimated effort in hours")
    actual_effort: float | None = Field(None, description="Actual effort in hours")

    model_config = ConfigDict(from_attributes=True)


class StatusUpdate(BaseModel):
    """Schema for status-only updates."""

    status: Literal["pending", "in_progress", "completed", "blocked", "cancelled"] = Field(
        ..., description="New task status"
    )
