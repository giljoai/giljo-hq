# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
WebSocket Event Factory and schema re-exports.

The Pydantic event models live in giljo_mcp.events.models (split for the
800-line CI guardrail).  This module owns the EventFactory and re-exports
every symbol so that ``from giljo_mcp.events.schemas import EventFactory``
continues to work as the canonical import path.

Handover 0086A: Production-Grade Stage Project Architecture
Task 1.4: Create Standardized Event Schemas
Created: 2025-11-02
Relocated from api/events/schemas.py: 2026-04-18 (Sprint 003a)
"""

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
    SetupAgentsDownloadedData,
    SetupAgentsDownloadedEvent,
    SetupCommandsInstalledData,
    SetupCommandsInstalledEvent,
    SetupToolConnectedData,
    SetupToolConnectedEvent,
    WebSocketEvent,
)


# ============================================================================
# Event Factory
# ============================================================================


# BE-9416: bound event payloads to the cross-worker broker's byte cap ----------
#
# The cross-worker leg of every tenant broadcast rides pg_notify, whose payload cap
# is 7999 bytes and is a PostgreSQL protocol limit that cannot be raised. An event
# carrying unbounded content fails PostgresNotifyWebSocketEventBroker.publish
# (BE-3008c's guard, working as designed), api/websocket.py swallows it as a WS006
# warning (also correct -- the local send already happened), and every session on a
# DIFFERENT uvicorn worker silently never sees it. Measured under production load:
# a project_update at 12,825 bytes, twice.
#
# Applied at the ONE funnel every tenant broadcast passes through
# (WebSocketManager.broadcast_event_to_tenant) rather than at each emitter. Six
# emitters produce these three event types across four files; a per-emitter bound is
# a rule an author has to remember, and the seventh emitter forgets it. Here it
# cannot be forgotten, and the envelope is already built so the REAL message is
# measured rather than a reconstruction of it.
#
# BE-9414's thread_message bounds itself inside api/endpoints/_comm_ws.py and is
# deliberately left alone: it is a shipped incident fix with its own pinned
# invariants, and `content` is not in this registry, so it is never double-bounded.
#
# Room left under 7999 for the broker envelope wrapped around this one (tenant_key,
# exclude_client, origin, control) -- BE-9414 measured that wrapping at 316 bytes at
# maximal ids. Pinned by test, not asserted here.
MAX_EVENT_BYTES = 6_500

# event type -> the variable-length data fields that may be trimmed, in no
# particular order (the bound always cuts the longest first). ONLY these three
# types are bounded; every other event is passed through untouched, so the impact
# area is exactly what BE-9416's consumer census covered.
BOUNDED_EVENT_FIELDS: dict[str, tuple[str, ...]] = {
    "project_update": ("description", "mission", "name"),
    "agent:created": ("mission",),
    "agent:mission_updated": ("mission",),
}


def _event_size(event: dict[str, Any]) -> int:
    """Serialized size of an envelope, measured the way the broker's guard measures it."""
    return len(json.dumps(event).encode("utf-8"))


def bound_event_message(message: dict[str, Any]) -> dict[str, Any]:
    """Trim a built envelope's registered fields until it fits the budget; return it.

    Mutates in place AND returns ``message`` so the caller can wrap its existing
    ``json.dumps(message)`` without a separate statement.

    Every bounded key always gets ``<key>_length`` and ``<key>_truncated``, so a
    receiver can tell a SHORTENED value from a short one and fetch the rest. "No flag"
    must never be readable as "not truncated" -- that ambiguity is what makes a silent
    truncation silent. They are written with ``setdefault`` because this funnel also
    handles events arriving FROM the broker: those are already bounded, and
    recomputing ``_length`` there would overwrite the TRUE original length with the
    excerpt's, telling the client its excerpt is complete.

    Bounded in BYTES, never characters: ``json.dumps`` runs ensure_ascii=True, so a
    non-ASCII BMP character costs 6 bytes and an ASTRAL one costs 12 (an escaped
    surrogate pair). A 50,000-character astral mission serializes to ~600 KB, 75x the
    cap; a character bound that provably fit the worst case would be a headline, not
    an excerpt.

    The search runs over CHARACTER prefixes measured by ``json.dumps`` itself, so it
    cannot drift from the encoder the guard measures, and a slice can never land
    inside a code point. A byte slice is faster and WRONG -- it emits U+FFFD mid-word.
    """
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
            # An absent field carries no bytes worth trimming, and flagging it would
            # invent a field the emitter deliberately did not send.
            continue
        originals[key] = value
        data.setdefault(f"{key}_length", len(value))
        # Written BEFORE the search so the measured envelope carries the same keys
        # the shipped one does. The value flips below.
        data.setdefault(f"{key}_truncated", False)

    if _event_size(message) <= MAX_EVENT_BYTES:
        return message

    # Longest first: a 12 KB description is cut before a 255-byte name is touched.
    for key in sorted(originals, key=lambda k: len(originals[k]), reverse=True):
        content = originals[key]
        low, high = 0, len(content)  # invariant: `low` chars always fit, `high` may not
        while low < high:
            mid = (low + high + 1) // 2
            data[key] = content[:mid]
            if _event_size(message) <= MAX_EVENT_BYTES:
                low = mid
            else:
                high = mid - 1

        data[key] = content[:low]
        if low < len(content):
            # Set AFTER the search on purpose: the search measured the envelope
            # carrying ``false`` (5 bytes) and this writes ``true`` (4), so the
            # payload that ships is one byte SMALLER than the one measured against
            # the budget -- never larger.
            data[f"{key}_truncated"] = True

        if _event_size(message) <= MAX_EVENT_BYTES:
            return message

    return message


class EventFactory:
    """
    Factory for creating standardized WebSocket events.

    Provides static methods for consistent event creation with:
    - Automatic timestamp generation
    - Pydantic validation
    - Type-safe event construction
    - JSON serialization ready output

    All factory methods return dict ready for JSON serialization,
    compatible with WebSocket.send_json() and FastAPI response models.
    """

    @staticmethod
    def tenant_envelope(
        event_type: str,
        tenant_key: str,
        data: dict[str, Any],
        schema_version: str = "1.0",
    ) -> dict:
        """Create a canonical tenant-scoped event envelope."""
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
        """Create project:mission_updated event."""
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
        """Create agent:created event."""
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
        """Create agent:status_changed event."""
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
        """Create agent:silent event."""
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

    # BE-9012d: message_sent / message_received / message_acknowledged (bus WS
    # events) were removed with the bus hard-removal. See events/models.py.

    @staticmethod
    def setup_tool_connected(tenant_key: str, user_id: str, tool_name: str) -> dict:
        """Create setup:tool_connected event."""
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
        """Create setup:commands_installed event."""
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

    @staticmethod
    def setup_agents_downloaded(tenant_key: str, user_id: str, agent_count: int) -> dict:
        """Create setup:agents_downloaded event."""
        event = SetupAgentsDownloadedEvent(
            timestamp=datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            data=SetupAgentsDownloadedData(
                tenant_key=tenant_key,
                user_id=user_id,
                agent_count=agent_count,
            ),
        )
        return event.model_dump(mode="json")


# ============================================================================
# Public API — re-export models + factory for single-import convenience
# ============================================================================

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
    "SetupAgentsDownloadedData",
    "SetupAgentsDownloadedEvent",
    "SetupCommandsInstalledData",
    "SetupCommandsInstalledEvent",
    "SetupToolConnectedData",
    "SetupToolConnectedEvent",
    "WebSocketEvent",
]
