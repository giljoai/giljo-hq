# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator




class EventMetadata(BaseModel):
    """
    Standard metadata for all WebSocket events.

    Ensures consistent structure across all event types with:
    - Event type identification
    - ISO 8601 timestamp with timezone
    - Schema version for backwards compatibility
    """

    type: str = Field(..., description="Event type (e.g., 'project:mission_updated')")
    timestamp: str = Field(..., description="ISO 8601 timestamp with timezone")
    schema_version: str = Field(default="1.0", description="Event schema version")

    @field_validator("timestamp")
    @classmethod
    def validate_timestamp(cls, v: str) -> str:
        try:
            datetime.fromisoformat(v.replace("Z", "+00:00"))
            return v
        except ValueError as e:
            raise ValueError(f"Invalid ISO 8601 timestamp: {v}") from e




class ProjectMissionUpdatedData(BaseModel):
    """Data payload for project:mission_updated event."""

    project_id: str = Field(..., description="Project UUID as string")
    tenant_key: str = Field(..., min_length=1, description="Tenant identifier")
    mission: str = Field(..., min_length=1, description="Generated mission text")
    generated_by: Literal["orchestrator", "user"] = Field(
        default="orchestrator", description="Source of mission generation"
    )
    user_config_applied: bool = Field(default=False, description="Whether user configuration was applied")
    field_toggles: dict[str, Any] = Field(None, description="Field toggle config used in generation")


class ProjectMissionUpdatedEvent(BaseModel):
    """Complete event structure for project:mission_updated."""

    type: Literal["project:mission_updated"] = "project:mission_updated"
    timestamp: str = Field(..., description="ISO 8601 timestamp")
    schema_version: str = Field(default="1.0", description="Event schema version")
    data: ProjectMissionUpdatedData

    model_config = {
        "json_schema_extra": {
            "example": {
                "type": "project:mission_updated",
                "timestamp": "2025-11-02T10:30:00Z",
                "schema_version": "1.0",
                "data": {
                    "project_id": "550e8400-e29b-41d4-a716-446655440000",
                    "tenant_key": "tenant_123",
                    "mission": "Implement user authentication with OAuth2",
                    "generated_by": "orchestrator",
                    "user_config_applied": True,
                    "field_toggles": {"product_core": {"toggle": True}, "git_history": {"toggle": False}},
                },
            }
        }
    }




class AgentCreatedData(BaseModel):
    """Data payload for agent:created event."""

    project_id: str = Field(..., description="Project UUID as string")
    tenant_key: str = Field(..., min_length=1, description="Tenant identifier")
    agent: dict[str, Any] = Field(..., description="Complete agent job data")

    @field_validator("agent")
    @classmethod
    def validate_agent_data(cls, v: dict[str, Any]) -> dict[str, Any]:
        required_fields = ["id", "agent_display_name", "status"]
        missing = [f for f in required_fields if f not in v]
        if missing:
            raise ValueError(f"Agent data missing required fields: {missing}")
        return v


class AgentCreatedEvent(BaseModel):
    """Complete event structure for agent:created."""

    type: Literal["agent:created"] = "agent:created"
    timestamp: str = Field(..., description="ISO 8601 timestamp")
    schema_version: str = Field(default="1.0", description="Event schema version")
    data: AgentCreatedData

    model_config = {
        "json_schema_extra": {
            "example": {
                "type": "agent:created",
                "timestamp": "2025-11-02T10:31:00Z",
                "schema_version": "1.0",
                "data": {
                    "project_id": "550e8400-e29b-41d4-a716-446655440000",
                    "tenant_key": "tenant_123",
                    "agent": {
                        "id": "660e8400-e29b-41d4-a716-446655440000",
                        "agent_display_name": "orchestrator",
                        "status": "pending",
                        "mission": "Coordinate project implementation",
                        "mode": "claude",
                    },
                },
            }
        }
    }


class AgentStatusChangedData(BaseModel):
    """Data payload for agent:status_changed event."""

    job_id: str = Field(..., description="Agent job UUID as string")
    project_id: str | None = Field(None, description="Project UUID if applicable")
    tenant_key: str = Field(..., min_length=1, description="Tenant identifier")
    old_status: str = Field(..., min_length=1, description="Previous status")
    status: str = Field(..., min_length=1, description="New status")
    agent_display_name: str = Field(..., min_length=1, description="Human-readable display name for UI")
    duration_seconds: float | None = Field(None, ge=0, description="Job duration for completed/failed status")

    @field_validator("status")
    @classmethod
    def validate_status_transition(cls, v: str, info) -> str:
        valid_statuses = {
            "waiting",
            "working",
            "blocked",
            "complete",
            "silent",
            "decommissioned",
            "idle",
            "sleeping",
            "awaiting_user",
        }
        if v not in valid_statuses:
            raise ValueError(f"Invalid agent status: {v}. Must be one of {valid_statuses}")
        return v


class AgentStatusChangedEvent(BaseModel):
    """Complete event structure for agent:status_changed."""

    type: Literal["agent:status_changed"] = "agent:status_changed"
    timestamp: str = Field(..., description="ISO 8601 timestamp")
    schema_version: str = Field(default="1.0", description="Event schema version")
    data: AgentStatusChangedData

    model_config = {
        "json_schema_extra": {
            "example": {
                "type": "agent:status_changed",
                "timestamp": "2025-11-02T10:32:00Z",
                "schema_version": "1.0",
                "data": {
                    "job_id": "660e8400-e29b-41d4-a716-446655440000",
                    "project_id": "550e8400-e29b-41d4-a716-446655440000",
                    "tenant_key": "tenant_123",
                    "old_status": "pending",
                    "status": "active",
                    "agent_display_name": "orchestrator",
                    "duration_seconds": None,
                },
            }
        }
    }


class AgentSilentData(BaseModel):
    """Data payload for agent:silent event."""

    job_id: str = Field(..., description="Agent job UUID as string")
    tenant_key: str = Field(..., min_length=1, description="Tenant identifier")
    agent_display_name: str = Field(..., min_length=1, description="Human-readable display name for UI")
    reason: str = Field(..., min_length=1, description="Reason for silence detection")
    project_id: str | None = Field(None, description="Project UUID if applicable")
    project_name: str | None = Field(None, description="Project name for display")
    execution_id: str | None = Field(None, description="Agent execution UUID")


class AgentSilentEvent(BaseModel):
    """Complete event structure for agent:silent."""

    type: Literal["agent:silent"] = "agent:silent"
    timestamp: str = Field(..., description="ISO 8601 timestamp")
    schema_version: str = Field(default="1.0", description="Event schema version")
    data: AgentSilentData

    model_config = {
        "json_schema_extra": {
            "example": {
                "type": "agent:silent",
                "timestamp": "2025-11-02T10:32:00Z",
                "schema_version": "1.0",
                "data": {
                    "job_id": "660e8400-e29b-41d4-a716-446655440000",
                    "tenant_key": "tenant_123",
                    "agent_display_name": "implementor",
                    "reason": "Agent stopped communicating",
                    "project_id": "550e8400-e29b-41d4-a716-446655440000",
                    "project_name": "My Project",
                    "execution_id": "770e8400-e29b-41d4-a716-446655440000",
                },
            }
        }
    }






class SetupToolConnectedData(BaseModel):
    """Data payload for setup:tool_connected event."""

    tenant_key: str = Field(..., min_length=1, description="Tenant identifier")
    user_id: str = Field(..., min_length=1, description="User identifier")
    tool_name: str = Field(..., min_length=1, description="AI tool name (claude_code, codex_cli, opencode, generic)")
    connected_at: str = Field(..., description="ISO 8601 timestamp of connection")


class SetupToolConnectedEvent(BaseModel):
    """Complete event structure for setup:tool_connected."""

    type: Literal["setup:tool_connected"] = "setup:tool_connected"
    timestamp: str = Field(..., description="ISO 8601 timestamp")
    schema_version: str = Field(default="1.0", description="Event schema version")
    data: SetupToolConnectedData


class SetupCommandsInstalledData(BaseModel):
    """Data payload for setup:commands_installed event."""

    tenant_key: str = Field(..., min_length=1, description="Tenant identifier")
    user_id: str = Field(..., min_length=1, description="User identifier")
    tool_name: str = Field(..., min_length=1, description="AI tool name")
    command_count: int = Field(..., ge=0, description="Number of commands installed")


class SetupCommandsInstalledEvent(BaseModel):
    """Complete event structure for setup:commands_installed."""

    type: Literal["setup:commands_installed"] = "setup:commands_installed"
    timestamp: str = Field(..., description="ISO 8601 timestamp")
    schema_version: str = Field(default="1.0", description="Event schema version")
    data: SetupCommandsInstalledData



WebSocketEvent = (
    ProjectMissionUpdatedEvent
    | AgentCreatedEvent
    | AgentStatusChangedEvent
    | AgentSilentEvent
    | SetupToolConnectedEvent
    | SetupCommandsInstalledEvent
)



__all__ = [
    "AgentCreatedData",
    "AgentCreatedEvent",
    "AgentSilentData",
    "AgentSilentEvent",
    "AgentStatusChangedData",
    "AgentStatusChangedEvent",
    "EventMetadata",
    "ProjectMissionUpdatedData",
    "ProjectMissionUpdatedEvent",
    "SetupCommandsInstalledData",
    "SetupCommandsInstalledEvent",
    "SetupToolConnectedData",
    "SetupToolConnectedEvent",
    "WebSocketEvent",
]
