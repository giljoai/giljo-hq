# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
Pydantic models for agent_jobs endpoints.

Request/response models for agent job operations with validation.
"""

from datetime import datetime

from pydantic import BaseModel, Field


# ============================================================================
# Spawn Agent Models
# ============================================================================


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


# ============================================================================
# Job Status Models
# ============================================================================


class TodoItemResponse(BaseModel):
    """Response model for individual TODO item - Handover 0423."""

    content: str
    status: str  # pending, in_progress, completed


class JobResponse(BaseModel):
    """Response model for job details."""

    id: str  # Changed from int to str for UUID (0366 series)
    job_id: str
    agent_id: str | None = None  # Handover 0401: Executor UUID for WebSocket event matching
    execution_id: str | None = None  # UNIQUE per row - AgentExecution primary key
    tenant_key: str
    project_id: str | None = None
    # BE-6200 (#6 follow-up): True for the dedicated chain conductor job (and its
    # pre-spawned impl-phase execution). Flat, not nested under job_metadata,
    # because the WS progress handler overwrites job_metadata. Lets the FE keep
    # the conductor out of any project's agent lane.
    chain_conductor: bool = False
    agent_display_name: str
    agent_name: str | None = None
    mission: str
    status: str
    progress: int = 0
    spawned_by: str | None = None
    tool_type: str = "universal"
    context_chunks: list[str] = Field(default_factory=list)
    # Handover 0407: Counter fields for message tracking (used by frontend store)
    messages_sent_count: int = 0
    messages_waiting_count: int = 0
    # BE-9273: the subset of messages_waiting_count that is genuinely
    # requires_action + non-auto_generated (the same definition the closeout
    # gate blocks complete_job on) -- surfaced distinctly so the dashboard can
    # tell "someone is waiting on THIS agent" apart from plain unread.
    action_required_unread: int = 0
    messages_read_count: int = 0
    started_at: datetime | None = None
    completed_at: datetime | None = None
    created_at: datetime
    updated_at: datetime | None = None
    # Numeric steps summary for TODO-style progress (Handover 0297)
    # When present, represents completed/total steps for dashboard Steps column.
    steps: dict[str, int] | None = None
    # Handover 0423: TODO items for Plan tab display
    todo_items: list[TodoItemResponse] = Field(default_factory=list)
    # Handover 0411a: Execution phase for multi-terminal ordering
    phase: int | None = None
    # Handover 0497e: Completion result for frontend display
    result: dict | None = None
    # Handover 0827d: Reactivation tracking for frontend duration display
    accumulated_duration_seconds: float = 0.0
    reactivation_count: int = 0
    # BE-5107: server-computed working duration (None until first 'working'
    # transition; freezes at completed_at once status reaches complete/closed)
    duration_seconds: float | None = None


# ============================================================================
# Job List Model (Handover 0135)
# ============================================================================


class JobListResponse(BaseModel):
    """Response model for job list with pagination (Handover 0135)."""

    jobs: list[JobResponse]
    total: int
    limit: int
    offset: int


# ============================================================================
# Mission Update Models (Handover 0244b)
# ============================================================================


class UpdateMissionRequest(BaseModel):
    """Request model for updating agent mission."""

    mission: str = Field(..., min_length=1, max_length=50000, description="Updated mission/instructions for the agent")


class UpdateMissionResponse(BaseModel):
    """Response model for mission update."""

    success: bool = Field(..., description="Whether update succeeded")
    job_id: str = Field(..., description="Job ID that was updated")
    mission: str = Field(..., description="Updated mission text")


# ============================================================================
# Agent Execution Models (Handover 0366d-1)
# ============================================================================


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
