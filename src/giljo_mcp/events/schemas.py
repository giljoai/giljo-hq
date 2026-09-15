# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import json
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID

from giljo_mcp.events.models import (
    AgentCreatedData,
    AgentCreatedEvent,
    AgentSilentData,
    AgentSilentEvent,
    AgentStatusChangedData,
    AgentStatusChangedEvent,
    EventMetadata,
    ProjectMissionUpdatedData,
    ProjectMissionUpdatedEvent,
    SetupCommandsInstalledData,
    SetupCommandsInstalledEvent,
    SetupToolConnectedData,
    SetupToolConnectedEvent,
    WebSocketEvent,
)




MAX_EVENT_BYTES = 6_500

BOUNDED_EVENT_FIELDS: dict[str, tuple[str, ...]] = {
    "project_update": ("description", "mission", "name"),
    "agent:created": ("mission",),
    "agent:mission_updated": ("mission",),
}


def _event_size(event: dict[str, Any]) -> int:
    return len(json.dumps(event).encode("utf-8"))


def bound_event_message(message: dict[str, Any]) -> dict[str, Any]:
    keys = BOUNDED_EVENT_FIELDS.get(message.get("type", ""))
    if not keys:
        return message

    data = message.get("data")
    if not isinstance(data, dict):
        return message

    originals: dict[str, str] = {}
    for key in keys:
        value = data.get(key)
        if not isinstance(value, str):
            continue
        originals[key] = value
        data.setdefault(f"{key}_length", len(value))
        data.setdefault(f"{key}_truncated", False)

    if _event_size(message) <= MAX_EVENT_BYTES:
        return message

    for key in sorted(originals, key=lambda k: len(originals[k]), reverse=True):
        content = originals[key]
        low, high = 0, len(content)
        while low < high:
            mid = (low + high + 1) // 2
            data[key] = content[:mid]
            if _event_size(message) <= MAX_EVENT_BYTES:
                low = mid
            else:
                high = mid - 1

        data[key] = content[:low]
        if low < len(content):
            data[f"{key}_truncated"] = True

        if _event_size(message) <= MAX_EVENT_BYTES:
            return message

    return message


class EventFactory:

    @staticmethod
    def tenant_envelope(
        event_type: str,
        tenant_key: str,
        data: dict[str, Any],
        schema_version: str = "1.0",
    ) -> dict:
        if not tenant_key:
            raise ValueError("tenant_key cannot be empty")

        payload = dict(data or {})
        if "tenant_key" not in payload:
            payload["tenant_key"] = tenant_key
        elif payload.get("tenant_key") != tenant_key:
            raise ValueError("data.tenant_key must match tenant_key")

        return {
            "type": event_type,
            "timestamp": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "schema_version": schema_version,
            "data": payload,
        }

    @staticmethod
    def project_mission_updated(
        project_id: str | UUID,
        tenant_key: str,
        mission: str,
        generated_by: Literal["orchestrator", "user"] = "orchestrator",
        user_config_applied: bool = False,
        field_toggles: dict[str, Any] = None,
    ) -> dict:
        project_id_str = str(project_id) if isinstance(project_id, UUID) else project_id

        event = ProjectMissionUpdatedEvent(
            timestamp=datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            data=ProjectMissionUpdatedData(
                project_id=project_id_str,
                tenant_key=tenant_key,
                mission=mission,
                generated_by=generated_by,
                user_config_applied=user_config_applied,
                field_toggles=field_toggles,
            ),
        )
        return event.model_dump(mode="json")

    @staticmethod
    def agent_created(
        project_id: str | UUID,
        tenant_key: str,
        agent: dict[str, Any],
    ) -> dict:
        project_id_str = str(project_id) if isinstance(project_id, UUID) else project_id

        event = AgentCreatedEvent(
            timestamp=datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            data=AgentCreatedData(
                project_id=project_id_str,
                tenant_key=tenant_key,
                agent=agent,
            ),
        )
        return event.model_dump(mode="json")

    @staticmethod
    def agent_status_changed(
        job_id: str | UUID,
        tenant_key: str,
        old_status: str,
        new_status: str,
        agent_display_name: str,
        project_id: str | UUID | None = None,
        duration_seconds: float | None = None,
    ) -> dict:
        job_id_str = str(job_id) if isinstance(job_id, UUID) else job_id
        project_id_str = str(project_id) if project_id and isinstance(project_id, UUID) else project_id

        event = AgentStatusChangedEvent(
            timestamp=datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            data=AgentStatusChangedData(
                job_id=job_id_str,
                project_id=project_id_str,
                tenant_key=tenant_key,
                old_status=old_status,
                status=new_status,
                agent_display_name=agent_display_name,
                duration_seconds=duration_seconds,
            ),
        )
        return event.model_dump(mode="json")

    @staticmethod
    def agent_silent(
        job_id: str | UUID,
        tenant_key: str,
        agent_display_name: str,
        reason: str,
        project_id: str | UUID | None = None,
        project_name: str | None = None,
        execution_id: str | None = None,
    ) -> dict:
        job_id_str = str(job_id) if isinstance(job_id, UUID) else job_id
        project_id_str = str(project_id) if project_id and isinstance(project_id, UUID) else project_id

        event = AgentSilentEvent(
            timestamp=datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            data=AgentSilentData(
                job_id=job_id_str,
                tenant_key=tenant_key,
                agent_display_name=agent_display_name,
                reason=reason,
                project_id=project_id_str,
                project_name=project_name,
                execution_id=execution_id,
            ),
        )
        return event.model_dump(mode="json")


    @staticmethod
    def setup_tool_connected(tenant_key: str, user_id: str, tool_name: str) -> dict:
        event = SetupToolConnectedEvent(
            timestamp=datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            data=SetupToolConnectedData(
                tenant_key=tenant_key,
                user_id=user_id,
                tool_name=tool_name,
                connected_at=datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            ),
        )
        return event.model_dump(mode="json")

    @staticmethod
    def setup_commands_installed(tenant_key: str, user_id: str, tool_name: str, command_count: int) -> dict:
        event = SetupCommandsInstalledEvent(
            timestamp=datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            data=SetupCommandsInstalledData(
                tenant_key=tenant_key,
                user_id=user_id,
                tool_name=tool_name,
                command_count=command_count,
            ),
        )
        return event.model_dump(mode="json")



__all__ = [
    "AgentCreatedData",
    "AgentCreatedEvent",
    "AgentSilentData",
    "AgentSilentEvent",
    "AgentStatusChangedData",
    "AgentStatusChangedEvent",
    "EventFactory",
    "EventMetadata",
    "ProjectMissionUpdatedData",
    "ProjectMissionUpdatedEvent",
    "SetupCommandsInstalledData",
    "SetupCommandsInstalledEvent",
    "SetupToolConnectedData",
    "SetupToolConnectedEvent",
    "WebSocketEvent",
]
