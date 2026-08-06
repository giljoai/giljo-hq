# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
Tests for silence detector notification events (agent:silent + project_id).

Verifies:
1. EventFactory.agent_silent creates correct event structure
2. agent:status_changed event includes project_id
3. _detect_silent_agents emits both agent:status_changed and agent:silent events
"""

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, Mock

import pytest

from giljo_mcp.events.schemas import EventFactory


# ---------------------------------------------------------------------------
# EventFactory.agent_silent unit tests
# ---------------------------------------------------------------------------


class TestAgentSilentEventFactory:
    """Unit tests for EventFactory.agent_silent static method."""

    def test_agent_silent_event_factory_creates_correct_event(self):
        """Verify agent_silent produces an event with type 'agent:silent' and all required fields."""
        job_id = str(uuid.uuid4())
        tenant_key = "test-tenant"
        agent_display_name = "implementor"
        reason = "Agent stopped communicating"
        project_id = str(uuid.uuid4())
        project_name = "My Project"
        execution_id = str(uuid.uuid4())

        event = EventFactory.agent_silent(
            job_id=job_id,
            tenant_key=tenant_key,
            agent_display_name=agent_display_name,
            reason=reason,
            project_id=project_id,
            project_name=project_name,
            execution_id=execution_id,
        )

        assert event["type"] == "agent:silent"
        assert event["schema_version"] == "1.0"
        assert "timestamp" in event

        data = event["data"]
        assert data["job_id"] == job_id
        assert data["tenant_key"] == tenant_key
        assert data["agent_display_name"] == agent_display_name
        assert data["reason"] == reason
        assert data["project_id"] == project_id
        assert data["project_name"] == project_name
        assert data["execution_id"] == execution_id

    def test_agent_silent_event_factory_optional_fields_none(self):
        """Verify agent_silent works when optional fields are None."""
        event = EventFactory.agent_silent(
            job_id=str(uuid.uuid4()),
            tenant_key="test-tenant",
            agent_display_name="orchestrator",
            reason="No heartbeat",
            project_id=None,
            project_name=None,
            execution_id=None,
        )

        assert event["type"] == "agent:silent"
        data = event["data"]
        assert data["project_id"] is None
        assert data["project_name"] is None
        assert data["execution_id"] is None

    def test_agent_silent_event_factory_converts_uuid_job_id(self):
        """Verify agent_silent converts UUID objects to strings."""
        job_uuid = uuid.uuid4()
        project_uuid = uuid.uuid4()

        event = EventFactory.agent_silent(
            job_id=job_uuid,
            tenant_key="test-tenant",
            agent_display_name="architect",
            reason="Timeout",
            project_id=project_uuid,
            project_name="Test Project",
            execution_id=str(uuid.uuid4()),
        )

        data = event["data"]
        assert data["job_id"] == str(job_uuid)
        assert data["project_id"] == str(project_uuid)


# ---------------------------------------------------------------------------
# _broadcast_status_change with project_id
# ---------------------------------------------------------------------------


class TestBroadcastStatusChangeProjectId:
    """Tests that _broadcast_status_change passes project_id to the event."""

    @pytest.mark.asyncio
    async def test_status_changed_event_includes_project_id(self):
        """Verify agent:status_changed event includes project_id when provided."""
        from giljo_mcp.services.silence_detector import _broadcast_status_change

        ws_manager = AsyncMock()
        ws_manager.broadcast_event_to_tenant = AsyncMock()

        agent = Mock()
        agent.job_id = uuid.uuid4()
        agent.tenant_key = "test-tenant"
        agent.agent_display_name = "implementor"
        agent.duration_seconds = None  # BE-5107

        project_id = str(uuid.uuid4())

        await _broadcast_status_change(
            ws_manager=ws_manager,
            agent=agent,
            old_status="working",
            new_status="silent",
            project_id=project_id,
        )

        ws_manager.broadcast_event_to_tenant.assert_called_once()
        call_kwargs = ws_manager.broadcast_event_to_tenant.call_args
        event = call_kwargs.kwargs.get("event") or call_kwargs[1].get("event")

        assert event["type"] == "agent:status_changed"
        assert event["data"]["project_id"] == project_id

    @pytest.mark.asyncio
    async def test_status_changed_event_project_id_defaults_none(self):
        """Verify agent:status_changed event has project_id=None when not provided."""
        from giljo_mcp.services.silence_detector import _broadcast_status_change

        ws_manager = AsyncMock()
        ws_manager.broadcast_event_to_tenant = AsyncMock()

        agent = Mock()
        agent.job_id = uuid.uuid4()
        agent.tenant_key = "test-tenant"
        agent.agent_display_name = "implementor"
        agent.duration_seconds = None  # BE-5107

        await _broadcast_status_change(
            ws_manager=ws_manager,
            agent=agent,
            old_status="working",
            new_status="silent",
        )

        ws_manager.broadcast_event_to_tenant.assert_called_once()
        call_kwargs = ws_manager.broadcast_event_to_tenant.call_args
        event = call_kwargs.kwargs.get("event") or call_kwargs[1].get("event")

        assert event["data"]["project_id"] is None


# ---------------------------------------------------------------------------
# _detect_silent_agents emits agent:silent event
# ---------------------------------------------------------------------------


class TestDetectSilentAgentsEmitsAgentSilent:
    """Tests that _detect_silent_agents emits agent:silent events with project context."""

    @pytest.mark.asyncio
    async def test_detect_silent_agents_emits_agent_silent_event(self):
        """Verify that when an agent is marked silent, an agent:silent event is broadcast."""
        from giljo_mcp.database import DatabaseManager
        from giljo_mcp.services.silence_detector import SilenceDetector

        # Set up mocks
        db_manager = Mock(spec=DatabaseManager)
        ws_manager = AsyncMock()
        ws_manager.broadcast_event_to_tenant = AsyncMock()

        detector = SilenceDetector(db_manager=db_manager, ws_manager=ws_manager)

        # Create mock agent with job and project relationships
        mock_project = Mock()
        mock_project.name = "Test Project"

        mock_job = Mock()
        mock_job.project_id = uuid.uuid4()
        mock_job.project = mock_project

        agent_id = uuid.uuid4()
        mock_agent = Mock()
        mock_agent.agent_id = agent_id
        mock_agent.job_id = uuid.uuid4()
        mock_agent.tenant_key = "test-tenant"
        mock_agent.agent_display_name = "implementor"
        mock_agent.status = "working"
        mock_agent.last_progress_at = datetime.now(UTC) - timedelta(minutes=30)
        mock_agent.job = mock_job
        mock_agent.duration_seconds = None  # BE-5107

        # Mock the session and query result
        # scalars() returns a sync object with .all(), not an async one
        session = AsyncMock()
        session.info = {}  # tenant_session_context save/restore target
        scalars_result = Mock()
        scalars_result.all.return_value = [mock_agent]
        mock_result = Mock()
        mock_result.scalars.return_value = scalars_result
        session.execute = AsyncMock(return_value=mock_result)
        session.flush = AsyncMock()

        count = await detector._detect_silent_agents(session, threshold_minutes=10)

        assert count == 1
        assert mock_agent.status == "silent"

        # Should have been called twice: once for agent:status_changed, once for agent:silent
        assert ws_manager.broadcast_event_to_tenant.call_count == 2

        # Check the second call is the agent:silent event
        calls = ws_manager.broadcast_event_to_tenant.call_args_list
        silent_event_call = calls[1]
        silent_event = silent_event_call.kwargs.get("event") or silent_event_call[1].get("event")

        assert silent_event["type"] == "agent:silent"
        assert silent_event["data"]["job_id"] == str(mock_agent.job_id)
        assert silent_event["data"]["tenant_key"] == "test-tenant"
        assert silent_event["data"]["agent_display_name"] == "implementor"
        assert silent_event["data"]["reason"] == "Agent stopped communicating"
        assert silent_event["data"]["project_id"] == str(mock_job.project_id)
        assert silent_event["data"]["project_name"] == "Test Project"
        assert silent_event["data"]["execution_id"] == str(agent_id)

    @pytest.mark.asyncio
    async def test_detect_silent_agents_handles_no_job_gracefully(self):
        """Verify agent:silent event handles agent with no job relationship."""
        from giljo_mcp.database import DatabaseManager
        from giljo_mcp.services.silence_detector import SilenceDetector

        db_manager = Mock(spec=DatabaseManager)
        ws_manager = AsyncMock()
        ws_manager.broadcast_event_to_tenant = AsyncMock()

        detector = SilenceDetector(db_manager=db_manager, ws_manager=ws_manager)

        agent_id = uuid.uuid4()
        mock_agent = Mock()
        mock_agent.agent_id = agent_id
        mock_agent.job_id = uuid.uuid4()
        mock_agent.tenant_key = "test-tenant"
        mock_agent.agent_display_name = "lonely-agent"
        mock_agent.status = "working"
        mock_agent.last_progress_at = datetime.now(UTC) - timedelta(minutes=30)
        mock_agent.job = None  # No job loaded
        mock_agent.duration_seconds = None  # BE-5107

        session = AsyncMock()
        session.info = {}  # tenant_session_context save/restore target
        scalars_result = Mock()
        scalars_result.all.return_value = [mock_agent]
        mock_result = Mock()
        mock_result.scalars.return_value = scalars_result
        session.execute = AsyncMock(return_value=mock_result)
        session.flush = AsyncMock()

        count = await detector._detect_silent_agents(session, threshold_minutes=10)

        assert count == 1

        # Both events should still be emitted, with None project fields
        assert ws_manager.broadcast_event_to_tenant.call_count == 2

        calls = ws_manager.broadcast_event_to_tenant.call_args_list

        # Check agent:status_changed has project_id=None
        status_event = calls[0].kwargs.get("event") or calls[0][1].get("event")
        assert status_event["data"]["project_id"] is None

        # Check agent:silent has project fields as None
        silent_event = calls[1].kwargs.get("event") or calls[1][1].get("event")
        assert silent_event["type"] == "agent:silent"
        assert silent_event["data"]["project_id"] is None
        assert silent_event["data"]["project_name"] is None
