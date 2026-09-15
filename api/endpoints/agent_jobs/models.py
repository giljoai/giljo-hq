# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from datetime import datetime

from pydantic import BaseModel, Field




class SpawnAgentRequest(BaseModel):
    """Request model for spawning a new agent job."""

    agent_display_name: str = Field(..., description="Human-readable display name for UI")
    agent_name: str | None = Field(None, description="User-readable agent name")
    mission: str = Field(..., description="Agent mission/instructions")
    project_id: str = Field(..., description="Project UUID")
    parent_job_id: str | None = Field(None, description="Parent job UUID")
    context_chunks: list[str] = Field(default_factory=list, description="Context chunk IDs")


class SpawnAgentResponse(BaseModel):
    """Response model for agent spawn operation."""

    success: bool = Field(..., description="Whether spawn succeeded")
    job_id: str = Field(..., description="Created agent job ID (Handover 0381: renamed from agent_job_id)")
    agent_prompt: str = Field(..., description="Generated agent prompt")
    mission_stored: bool = Field(..., description="Whether mission was stored")
    thin_client: bool = Field(..., description="Whether using thin client architecture")




class TodoItemResponse(BaseModel):
    """Response model for individual TODO item - Handover 0423."""

    content: str
    status: str


class JobResponse(BaseModel):
    """Response model for job details."""

    id: str
    job_id: str
    agent_id: str | None = None
    execution_id: str | None = None
    tenant_key: str
    project_id: str | None = None
    chain_conductor: bool = False
    agent_display_name: str
    agent_name: str | None = None
    mission: str
    status: str
    progress: int = 0
    spawned_by: str | None = None
    tool_type: str = "universal"
    context_chunks: list[str] = Field(default_factory=list)
    messages_sent_count: int = 0
    messages_waiting_count: int = 0
    action_required_unread: int = 0
    messages_read_count: int = 0
    started_at: datetime | None = None
    completed_at: datetime | None = None
    created_at: datetime
    updated_at: datetime | None = None
    steps: dict[str, int] | None = None
    todo_items: list[TodoItemResponse] = Field(default_factory=list)
    phase: int | None = None
    result: dict | None = None
    accumulated_duration_seconds: float = 0.0
    reactivation_count: int = 0
    duration_seconds: float | None = None




class JobListResponse(BaseModel):
    """Response model for job list with pagination (Handover 0135)."""

    jobs: list[JobResponse]
    total: int
    limit: int
    offset: int




class UpdateMissionRequest(BaseModel):
    """Request model for updating agent mission."""

    mission: str = Field(..., min_length=1, max_length=50000, description="Updated mission/instructions for the agent")


class UpdateMissionResponse(BaseModel):
    """Response model for mission update."""

    success: bool = Field(..., description="Whether update succeeded")
    job_id: str = Field(..., description="Job ID that was updated")
    mission: str = Field(..., description="Updated mission text")




class AgentExecutionResponse(BaseModel):
    """Response model for agent execution instance (Handover 0366d-1)."""

    agent_id: str
    job_id: str
    status: str
    progress: int = 0
    spawned_by: str | None = None
    created_at: datetime
    updated_at: datetime | None = None

    class Config:
        from_attributes = True
