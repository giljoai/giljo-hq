# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, Mock

import pytest

from giljo_mcp.events.schemas import EventFactory




class TestAgentSilentEventFactory:

    def test_agent_silent_event_factory_creates_correct_event(self):
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




class TestBroadcastStatusChangeProjectId:

    @pytest.mark.asyncio
    async def test_status_changed_event_includes_project_id(self):
        from giljo_mcp.services.silence_detector import _broadcast_status_change

        ws_manager = AsyncMock()
        ws_manager.broadcast_event_to_tenant = AsyncMock()

        agent = Mock()
        agent.job_id = uuid.uuid4()
        agent.tenant_key = "test-tenant"
        agent.agent_display_name = "implementor"
        agent.duration_seconds = None

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
        from giljo_mcp.services.silence_detector import _broadcast_status_change

        ws_manager = AsyncMock()
        ws_manager.broadcast_event_to_tenant = AsyncMock()

        agent = Mock()
        agent.job_id = uuid.uuid4()
        agent.tenant_key = "test-tenant"
        agent.agent_display_name = "implementor"
        agent.duration_seconds = None

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




class TestDetectSilentAgentsEmitsAgentSilent:

    @pytest.mark.asyncio
    async def test_detect_silent_agents_emits_agent_silent_event(self):
        from giljo_mcp.database import DatabaseManager
        from giljo_mcp.services.silence_detector import SilenceDetector

        db_manager = Mock(spec=DatabaseManager)
        ws_manager = AsyncMock()
        ws_manager.broadcast_event_to_tenant = AsyncMock()

        detector = SilenceDetector(db_manager=db_manager, ws_manager=ws_manager)

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
        mock_agent.duration_seconds = None

        session = AsyncMock()
        session.info = {}
        scalars_result = Mock()
        scalars_result.all.return_value = [mock_agent]
        mock_result = Mock()
        mock_result.scalars.return_value = scalars_result
        session.execute = AsyncMock(return_value=mock_result)
        session.flush = AsyncMock()

        count = await detector._detect_silent_agents(session, threshold_minutes=10)

        assert count == 1
        assert mock_agent.status == "silent"

        assert ws_manager.broadcast_event_to_tenant.call_count == 2

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
        mock_agent.job = None
        mock_agent.duration_seconds = None

        session = AsyncMock()
        session.info = {}
        scalars_result = Mock()
        scalars_result.all.return_value = [mock_agent]
        mock_result = Mock()
        mock_result.scalars.return_value = scalars_result
        session.execute = AsyncMock(return_value=mock_result)
        session.flush = AsyncMock()

        count = await detector._detect_silent_agents(session, threshold_minutes=10)

        assert count == 1

        assert ws_manager.broadcast_event_to_tenant.call_count == 2

        calls = ws_manager.broadcast_event_to_tenant.call_args_list

        status_event = calls[0].kwargs.get("event") or calls[0][1].get("event")
        assert status_event["data"]["project_id"] is None

        silent_event = calls[1].kwargs.get("event") or calls[1][1].get("event")
        assert silent_event["type"] == "agent:silent"
        assert silent_event["data"]["project_id"] is None
        assert silent_event["data"]["project_name"] is None
