# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from datetime import UTC, datetime
from unittest.mock import AsyncMock, Mock, patch

import pytest

from giljo_mcp.services.orchestration_service import OrchestrationService


def _make_mock_execution(
    *,
    agent_id="agent-001",
    job_id="job-001",
    tenant_key="test-tenant",
    status="working",
    block_reason=None,
    agent_display_name="Test Agent",
):
    execution = Mock()
    execution.agent_id = agent_id
    execution.job_id = job_id
    execution.tenant_key = tenant_key
    execution.status = status
    execution.block_reason = block_reason
    execution.last_progress_at = None
    execution.progress = 0
    execution.current_task = None
    execution.started_at = datetime(2026, 1, 1, tzinfo=UTC)
    execution.agent_display_name = agent_display_name
    return execution


def _make_mock_job(*, job_id="job-001", project_id="proj-001", tenant_key="test-tenant"):
    job = Mock()
    job.job_id = job_id
    job.project_id = project_id
    job.tenant_key = tenant_key
    job.job_metadata = {}
    return job


def _build_service(db_manager, mock_tenant_manager, mock_ws=None):
    return OrchestrationService(
        db_manager=db_manager,
        tenant_manager=mock_tenant_manager,
        websocket_manager=mock_ws,
    )


def _setup_session_mocks(session, execution, job):
    exec_result = Mock()
    exec_result.scalar_one_or_none = Mock(return_value=execution)
    job_result = Mock()
    job_result.scalar_one_or_none = Mock(return_value=job)
    todo_result = Mock()
    todo_result.scalars = Mock(return_value=Mock(all=Mock(return_value=[])))
    session.execute = AsyncMock(side_effect=[exec_result, job_result, todo_result])


@pytest.mark.asyncio
async def test_report_progress_transitions_blocked_to_working(mock_db_manager, mock_tenant_manager):
    db_manager, session = mock_db_manager
    mock_ws = Mock()
    mock_ws.broadcast_to_tenant = AsyncMock()

    execution = _make_mock_execution(status="blocked", block_reason="Waiting for user input")
    job = _make_mock_job()
    _setup_session_mocks(session, execution, job)

    service = _build_service(db_manager, mock_tenant_manager, mock_ws)

    with patch.object(service._progress, "_fetch_and_broadcast_progress", new_callable=AsyncMock):
        result = await service.report_progress(
            job_id="job-001",
            tenant_key="test-tenant",
            progress={"percent": 50, "message": "Working on task"},
        )

    assert result.status == "success"
    assert execution.status == "working"
    assert execution.block_reason is None


@pytest.mark.asyncio
async def test_report_progress_broadcasts_status_change_on_blocked_to_working(mock_db_manager, mock_tenant_manager):
    db_manager, session = mock_db_manager
    mock_ws = Mock()
    mock_ws.broadcast_to_tenant = AsyncMock()

    execution = _make_mock_execution(status="blocked", block_reason="Need clarification")
    job = _make_mock_job()
    _setup_session_mocks(session, execution, job)

    service = _build_service(db_manager, mock_tenant_manager, mock_ws)

    with patch.object(service._progress, "_fetch_and_broadcast_progress", new_callable=AsyncMock):
        await service.report_progress(
            job_id="job-001",
            tenant_key="test-tenant",
            progress={"percent": 25, "message": "Resumed work"},
        )

    mock_ws.broadcast_to_tenant.assert_called_once()
    call_kwargs = mock_ws.broadcast_to_tenant.call_args
    assert call_kwargs.kwargs["tenant_key"] == "test-tenant"
    assert call_kwargs.kwargs["event_type"] == "agent:status_changed"
    data = call_kwargs.kwargs["data"]
    assert data["old_status"] == "blocked"
    assert data["status"] == "working"
    assert data["agent_display_name"] == "Test Agent"


@pytest.mark.asyncio
async def test_report_progress_does_not_change_working_status(mock_db_manager, mock_tenant_manager):
    db_manager, session = mock_db_manager
    mock_ws = Mock()
    mock_ws.broadcast_to_tenant = AsyncMock()

    execution = _make_mock_execution(status="working")
    job = _make_mock_job()
    _setup_session_mocks(session, execution, job)

    service = _build_service(db_manager, mock_tenant_manager, mock_ws)

    with patch.object(service._progress, "_fetch_and_broadcast_progress", new_callable=AsyncMock):
        result = await service.report_progress(
            job_id="job-001",
            tenant_key="test-tenant",
            progress={"percent": 50, "message": "In progress"},
        )

    assert result.status == "success"
    assert execution.status == "working"
    mock_ws.broadcast_to_tenant.assert_not_called()


@pytest.mark.asyncio
async def test_report_progress_does_not_change_waiting_status(mock_db_manager, mock_tenant_manager):
    db_manager, session = mock_db_manager
    mock_ws = Mock()
    mock_ws.broadcast_to_tenant = AsyncMock()

    execution = _make_mock_execution(status="waiting")
    job = _make_mock_job()
    _setup_session_mocks(session, execution, job)

    service = _build_service(db_manager, mock_tenant_manager, mock_ws)

    with patch.object(service._progress, "_fetch_and_broadcast_progress", new_callable=AsyncMock):
        result = await service.report_progress(
            job_id="job-001",
            tenant_key="test-tenant",
            progress={"percent": 10, "message": "Starting"},
        )

    assert result.status == "success"
    assert execution.status == "waiting"
    mock_ws.broadcast_to_tenant.assert_not_called()


@pytest.mark.asyncio
async def test_report_progress_does_not_change_silent_status(mock_db_manager, mock_tenant_manager):
    db_manager, session = mock_db_manager
    mock_ws = Mock()
    mock_ws.broadcast_to_tenant = AsyncMock()

    execution = _make_mock_execution(status="silent")
    job = _make_mock_job()
    _setup_session_mocks(session, execution, job)

    service = _build_service(db_manager, mock_tenant_manager, mock_ws)

    with patch.object(service._progress, "_fetch_and_broadcast_progress", new_callable=AsyncMock):
        result = await service.report_progress(
            job_id="job-001",
            tenant_key="test-tenant",
            progress={"percent": 30, "message": "Working silently"},
        )

    assert result.status == "success"
    assert execution.status == "silent"
    mock_ws.broadcast_to_tenant.assert_not_called()
