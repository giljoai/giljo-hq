# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import sys
import types
import uuid
from unittest.mock import AsyncMock, Mock, patch

import pytest


if "api" not in sys.modules:
    _api_stub = types.ModuleType("api")
    _api_stub.__path__ = ["api"]
    _api_stub.__package__ = "api"
    sys.modules["api"] = _api_stub

from giljo_mcp.services.silence_detector import auto_clear_silent, clear_silent_status


def _make_mock_agent(
    *,
    agent_id=None,
    job_id=None,
    tenant_key="test-tenant",
    status="silent",
    agent_display_name="orchestrator",
):
    agent = Mock()
    agent.agent_id = agent_id or uuid.uuid4()
    agent.job_id = job_id or uuid.uuid4()
    agent.tenant_key = tenant_key
    agent.status = status
    agent.agent_display_name = agent_display_name
    agent.last_progress_at = None
    agent.duration_seconds = None
    return agent


def _make_session_returning_row(agent, project_id):
    session = AsyncMock()
    session.info = {}
    mock_result = Mock()
    mock_result.one_or_none = Mock(return_value=(agent, project_id))
    session.execute = AsyncMock(return_value=mock_result)
    session.flush = AsyncMock()
    return session


def _make_session_returning_none():
    session = AsyncMock()
    session.info = {}
    mock_result = Mock()
    mock_result.one_or_none = Mock(return_value=None)
    session.execute = AsyncMock(return_value=mock_result)
    return session


class TestAutoClearSilent:

    @pytest.mark.asyncio
    async def test_auto_clear_silent_broadcasts_with_project_id(self):
        project_id = str(uuid.uuid4())
        agent = _make_mock_agent(status="silent")
        session = _make_session_returning_row(agent, project_id)

        ws_manager = AsyncMock()
        ws_manager.broadcast_event_to_tenant = AsyncMock()

        await auto_clear_silent(
            session=session, job_id=str(agent.job_id), ws_manager=ws_manager, tenant_key=agent.tenant_key
        )

        ws_manager.broadcast_event_to_tenant.assert_called_once()
        call_kwargs = ws_manager.broadcast_event_to_tenant.call_args
        event = call_kwargs.kwargs.get("event") or call_kwargs[0][0] if call_kwargs[0] else None
        if event is None:
            event = call_kwargs[1].get("event")

        assert event is not None
        assert event["type"] == "agent:status_changed"
        assert event["data"]["project_id"] == project_id

    @pytest.mark.asyncio
    async def test_auto_clear_silent_broadcast_event_uses_status_field_not_new_status(self):
        project_id = str(uuid.uuid4())
        agent = _make_mock_agent(status="silent")
        session = _make_session_returning_row(agent, project_id)

        ws_manager = AsyncMock()
        ws_manager.broadcast_event_to_tenant = AsyncMock()

        await auto_clear_silent(
            session=session, job_id=str(agent.job_id), ws_manager=ws_manager, tenant_key=agent.tenant_key
        )

        call_kwargs = ws_manager.broadcast_event_to_tenant.call_args
        event = call_kwargs.kwargs.get("event") or call_kwargs[1].get("event")

        assert "status" in event["data"]
        assert "new_status" not in event["data"]
        assert event["data"]["status"] == "working"

    @pytest.mark.asyncio
    async def test_auto_clear_silent_broadcast_old_status_is_silent(self):
        project_id = str(uuid.uuid4())
        agent = _make_mock_agent(status="silent")
        session = _make_session_returning_row(agent, project_id)

        ws_manager = AsyncMock()
        ws_manager.broadcast_event_to_tenant = AsyncMock()

        await auto_clear_silent(
            session=session, job_id=str(agent.job_id), ws_manager=ws_manager, tenant_key=agent.tenant_key
        )

        call_kwargs = ws_manager.broadcast_event_to_tenant.call_args
        event = call_kwargs.kwargs.get("event") or call_kwargs[1].get("event")

        assert event["data"]["old_status"] == "silent"

    @pytest.mark.asyncio
    async def test_auto_clear_silent_transitions_agent_status_to_working(self):
        project_id = str(uuid.uuid4())
        agent = _make_mock_agent(status="silent")
        session = _make_session_returning_row(agent, project_id)

        ws_manager = AsyncMock()
        ws_manager.broadcast_event_to_tenant = AsyncMock()

        await auto_clear_silent(
            session=session, job_id=str(agent.job_id), ws_manager=ws_manager, tenant_key=agent.tenant_key
        )

        assert agent.status == "working"

    @pytest.mark.asyncio
    async def test_auto_clear_silent_updates_last_progress_at(self):
        project_id = str(uuid.uuid4())
        agent = _make_mock_agent(status="silent")
        session = _make_session_returning_row(agent, project_id)

        ws_manager = AsyncMock()
        ws_manager.broadcast_event_to_tenant = AsyncMock()

        await auto_clear_silent(
            session=session, job_id=str(agent.job_id), ws_manager=ws_manager, tenant_key=agent.tenant_key
        )

        assert agent.last_progress_at is not None

    @pytest.mark.asyncio
    async def test_auto_clear_silent_no_broadcast_when_agent_not_silent(self):
        session = _make_session_returning_none()

        ws_manager = AsyncMock()
        ws_manager.broadcast_event_to_tenant = AsyncMock()

        await auto_clear_silent(
            session=session, job_id=str(uuid.uuid4()), ws_manager=ws_manager, tenant_key="test-tenant"
        )

        ws_manager.broadcast_event_to_tenant.assert_not_called()

    @pytest.mark.asyncio
    async def test_auto_clear_silent_ws_manager_none_raises_no_exception(self):
        project_id = str(uuid.uuid4())
        agent = _make_mock_agent(status="silent")
        session = _make_session_returning_row(agent, project_id)

        await auto_clear_silent(session=session, job_id=str(agent.job_id), ws_manager=None, tenant_key=agent.tenant_key)

        assert agent.status == "working"

    @pytest.mark.asyncio
    async def test_auto_clear_silent_ws_manager_none_logs_warning(self):
        project_id = str(uuid.uuid4())
        agent = _make_mock_agent(status="silent")
        session = _make_session_returning_row(agent, project_id)

        with patch("giljo_mcp.services.silence_detector.logger") as mock_logger:
            await auto_clear_silent(
                session=session, job_id=str(agent.job_id), ws_manager=None, tenant_key=agent.tenant_key
            )

        mock_logger.warning.assert_called_once()

    @pytest.mark.asyncio
    async def test_auto_clear_silent_flushes_session(self):
        project_id = str(uuid.uuid4())
        agent = _make_mock_agent(status="silent")
        session = _make_session_returning_row(agent, project_id)

        ws_manager = AsyncMock()
        ws_manager.broadcast_event_to_tenant = AsyncMock()

        await auto_clear_silent(
            session=session, job_id=str(agent.job_id), ws_manager=ws_manager, tenant_key=agent.tenant_key
        )

        session.flush.assert_called_once()

    @pytest.mark.asyncio
    async def test_auto_clear_silent_project_id_none_when_job_has_no_project(self):
        agent = _make_mock_agent(status="silent")
        session = _make_session_returning_row(agent, project_id=None)

        ws_manager = AsyncMock()
        ws_manager.broadcast_event_to_tenant = AsyncMock()

        await auto_clear_silent(
            session=session, job_id=str(agent.job_id), ws_manager=ws_manager, tenant_key=agent.tenant_key
        )

        call_kwargs = ws_manager.broadcast_event_to_tenant.call_args
        event = call_kwargs.kwargs.get("event") or call_kwargs[1].get("event")

        assert event["data"]["project_id"] is None


class TestClearSilentStatus:

    @pytest.mark.asyncio
    async def test_clear_silent_status_broadcasts_with_project_id(self):
        project_id = str(uuid.uuid4())
        agent = _make_mock_agent(status="silent")
        session = _make_session_returning_row(agent, project_id)

        ws_manager = AsyncMock()
        ws_manager.broadcast_event_to_tenant = AsyncMock()

        result = await clear_silent_status(
            session=session,
            agent_id=str(agent.agent_id),
            tenant_key=agent.tenant_key,
            ws_manager=ws_manager,
        )

        assert result is not None
        ws_manager.broadcast_event_to_tenant.assert_called_once()
        call_kwargs = ws_manager.broadcast_event_to_tenant.call_args
        event = call_kwargs.kwargs.get("event") or call_kwargs[1].get("event")

        assert event["type"] == "agent:status_changed"
        assert event["data"]["project_id"] == project_id

    @pytest.mark.asyncio
    async def test_clear_silent_status_broadcast_event_uses_status_field_not_new_status(self):
        project_id = str(uuid.uuid4())
        agent = _make_mock_agent(status="silent")
        session = _make_session_returning_row(agent, project_id)

        ws_manager = AsyncMock()
        ws_manager.broadcast_event_to_tenant = AsyncMock()

        await clear_silent_status(
            session=session,
            agent_id=str(agent.agent_id),
            tenant_key=agent.tenant_key,
            ws_manager=ws_manager,
        )

        call_kwargs = ws_manager.broadcast_event_to_tenant.call_args
        event = call_kwargs.kwargs.get("event") or call_kwargs[1].get("event")

        assert "status" in event["data"]
        assert "new_status" not in event["data"]
        assert event["data"]["status"] == "working"

    @pytest.mark.asyncio
    async def test_clear_silent_status_returns_none_when_agent_not_found(self):
        session = _make_session_returning_none()
        ws_manager = AsyncMock()

        result = await clear_silent_status(
            session=session,
            agent_id=str(uuid.uuid4()),
            tenant_key="test-tenant",
            ws_manager=ws_manager,
        )

        assert result is None
        ws_manager.broadcast_event_to_tenant.assert_not_called()

    @pytest.mark.asyncio
    async def test_clear_silent_status_returns_agent_info_dict_on_success(self):
        project_id = str(uuid.uuid4())
        agent = _make_mock_agent(status="silent")
        session = _make_session_returning_row(agent, project_id)

        ws_manager = AsyncMock()
        ws_manager.broadcast_event_to_tenant = AsyncMock()

        result = await clear_silent_status(
            session=session,
            agent_id=str(agent.agent_id),
            tenant_key=agent.tenant_key,
            ws_manager=ws_manager,
        )

        assert result is not None
        assert "agent_id" in result
        assert "job_id" in result
        assert result["status"] == "working"
        assert "last_progress_at" in result

    @pytest.mark.asyncio
    async def test_clear_silent_status_ws_manager_none_raises_no_exception(self):
        project_id = str(uuid.uuid4())
        agent = _make_mock_agent(status="silent")
        session = _make_session_returning_row(agent, project_id)

        result = await clear_silent_status(
            session=session,
            agent_id=str(agent.agent_id),
            tenant_key=agent.tenant_key,
            ws_manager=None,
        )

        assert result is not None
        assert result["status"] == "working"

    @pytest.mark.asyncio
    async def test_clear_silent_status_transitions_agent_to_working(self):
        project_id = str(uuid.uuid4())
        agent = _make_mock_agent(status="silent")
        session = _make_session_returning_row(agent, project_id)

        ws_manager = AsyncMock()
        ws_manager.broadcast_event_to_tenant = AsyncMock()

        await clear_silent_status(
            session=session,
            agent_id=str(agent.agent_id),
            tenant_key=agent.tenant_key,
            ws_manager=ws_manager,
        )

        assert agent.status == "working"

    @pytest.mark.asyncio
    async def test_clear_silent_status_flushes_session(self):
        project_id = str(uuid.uuid4())
        agent = _make_mock_agent(status="silent")
        session = _make_session_returning_row(agent, project_id)

        ws_manager = AsyncMock()
        ws_manager.broadcast_event_to_tenant = AsyncMock()

        await clear_silent_status(
            session=session,
            agent_id=str(agent.agent_id),
            tenant_key=agent.tenant_key,
            ws_manager=ws_manager,
        )

        session.flush.assert_called_once()
