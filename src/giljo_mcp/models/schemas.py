# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ProjectSummaryResponse(BaseModel):
    """
    Project summary with metrics and status.

    Returns comprehensive project overview including job statistics,
    completion metrics, and activity timestamps for dashboard display.
    """

    id: str = Field(..., description="Project UUID")
    name: str = Field(..., description="Project name")
    status: str = Field(..., description="Project status (staging/active/inactive/completed/cancelled)")
    mission: str | None = Field(None, description="Project mission statement")

    total_jobs: int = Field(0, description="Total number of agent jobs")
    completed_jobs: int = Field(0, description="Number of completed jobs")
    blocked_jobs: int = Field(0, description="Number of blocked jobs")
    active_jobs: int = Field(0, description="Number of currently active jobs")
    pending_jobs: int = Field(0, description="Number of pending jobs")

    completion_percentage: float = Field(0.0, ge=0.0, le=100.0, description="Project completion percentage (0-100)")

    created_at: datetime = Field(..., description="Project creation timestamp")
    last_activity_at: datetime | None = Field(None, description="Most recent activity timestamp")

    product_id: str = Field(..., description="Parent product UUID")
    product_name: str = Field(..., description="Parent product name")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "id": "abc-123-def-456",
                "name": "Feature Development Sprint",
                "status": "active",
                "mission": "Implement user authentication system",
                "total_jobs": 10,
                "completed_jobs": 7,
                "blocked_jobs": 1,
                "active_jobs": 1,
                "pending_jobs": 1,
                "completion_percentage": 70.0,
                "created_at": "2025-01-10T10:00:00Z",
                "last_activity_at": "2025-01-13T14:22:00Z",
                "product_id": "xyz-789",
                "product_name": "Authentication Platform",
            }
        }
    )


class ProjectLaunchResponse(BaseModel):
    """
    Project orchestrator launch response.

    Returns launch details including orchestrator job ID and
    thin-client launch prompt for starting the orchestrator instance.
    """

    project_id: str = Field(..., description="Project UUID")
    orchestrator_job_id: str = Field(..., description="Orchestrator agent job UUID")
    launch_prompt: str = Field(..., description="Thin-client launch prompt for orchestrator")
    status: str = Field(..., description="Project status after launch")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "project_id": "abc-123-def-456",
                "orchestrator_job_id": "orch-job-789",
                "launch_prompt": "Launch orchestrator for project...",
                "status": "active",
            }
        }
    )


class ProjectResponse(BaseModel):
    """
    Standard project response for lifecycle operations.

    Used for activation, deactivation, cancellation, and other
    state transition operations.
    """

    id: str = Field(..., description="Project UUID")
    name: str = Field(..., description="Project name")
    status: str = Field(..., description="Project status")
    mission: str | None = Field(None, description="Project mission")
    description: str | None = Field(None, description="Project description")

    cancellation_reason: str | None = Field(None, description="Reason for cancellation")
    early_termination: bool = Field(default=False, description="Whether project was terminated early")

    created_at: datetime = Field(..., description="Creation timestamp")
    updated_at: datetime = Field(..., description="Last update timestamp")
    completed_at: datetime | None = Field(None, description="Completion timestamp")

    product_id: str = Field(..., description="Parent product UUID")

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "example": {
                "id": "abc-123-def-456",
                "name": "Feature Development Sprint",
                "status": "active",
                "mission": "Implement user authentication",
                "description": "Complete authentication system",
                "cancellation_reason": None,
                "early_termination": False,
                "created_at": "2025-01-10T10:00:00Z",
                "updated_at": "2025-01-13T14:22:00Z",
                "completed_at": None,
                "product_id": "xyz-789",
            }
        },
    )


