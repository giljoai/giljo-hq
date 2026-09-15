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

from giljo_mcp.services.progress_service import ProgressService


def _make_mock_execution(
    *,
    agent_id=None,
    job_id=None,
    tenant_key="test-tenant",
    status="working",
    agent_display_name="orchestrator",
):
    execution = Mock()
    execution.agent_id = agent_id or uuid.uuid4()
    execution.job_id = job_id or uuid.uuid4()
    execution.tenant_key = tenant_key
    execution.status = status
    execution.agent_display_name = agent_display_name
    execution.progress = 50
    execution.current_task = "Doing work"
    execution.last_progress_at = None
    return execution


def _make_mock_job(*, project_id=None, job_id=None, tenant_key="test-tenant"):
    job = Mock()
    job.job_id = job_id or str(uuid.uuid4())
    job.project_id = project_id or uuid.uuid4()
    job.tenant_key = tenant_key
    job.job_metadata = {}
    return job


def _make_service_with_ws(ws_manager):
    db_manager = Mock()
    tenant_manager = Mock()
    tenant_manager.get_current_tenant = Mock(return_value="test-tenant")

    return ProgressService(
        db_manager=db_manager,
        tenant_manager=tenant_manager,
        websocket_manager=ws_manager,
    )


def _extract_broadcast_call_data(ws_manager):
    assert ws_manager.broadcast_to_tenant.called, "broadcast_to_tenant was never called"
    call_kwargs = ws_manager.broadcast_to_tenant.call_args
    return call_kwargs.kwargs.get("data") or call_kwargs[1].get("data")


class TestBroadcastProgressUpdateOldStatus:

    @pytest.mark.asyncio
    async def test_auto_wake_from_blocked_broadcasts_old_status_blocked(self):
        ws_manager = AsyncMock()
        ws_manager.broadcast_to_tenant = AsyncMock()

        service = _make_service_with_ws(ws_manager)
        job = _make_mock_job()
        execution = _make_mock_execution()

        with patch.object(service, "_fetch_and_broadcast_progress", new=AsyncMock()):
            await service._broadcast_progress_update(
                tenant_key="test-tenant",
                job_id=str(job.job_id),
                job=job,
                execution=execution,
                progress={"percent": 50},
                blocked_to_working=True,
                old_resting_status="blocked",
            )

        data = _extract_broadcast_call_data(ws_manager)
        assert data["old_status"] == "blocked"
        assert data["status"] == "working"

    @pytest.mark.asyncio
    async def test_auto_wake_from_idle_broadcasts_old_status_idle(self):
        ws_manager = AsyncMock()
        ws_manager.broadcast_to_tenant = AsyncMock()

        service = _make_service_with_ws(ws_manager)
        job = _make_mock_job()
        execution = _make_mock_execution()

        with patch.object(service, "_fetch_and_broadcast_progress", new=AsyncMock()):
            await service._broadcast_progress_update(
                tenant_key="test-tenant",
                job_id=str(job.job_id),
                job=job,
                execution=execution,
                progress={"percent": 25},
                blocked_to_working=True,
                old_resting_status="idle",
            )

        data = _extract_broadcast_call_data(ws_manager)
        assert data["old_status"] == "idle"
        assert data["status"] == "working"

    @pytest.mark.asyncio
    async def test_auto_wake_from_sleeping_broadcasts_old_status_sleeping(self):
        ws_manager = AsyncMock()
        ws_manager.broadcast_to_tenant = AsyncMock()

        service = _make_service_with_ws(ws_manager)
        job = _make_mock_job()
        execution = _make_mock_execution()

        with patch.object(service, "_fetch_and_broadcast_progress", new=AsyncMock()):
            await service._broadcast_progress_update(
                tenant_key="test-tenant",
                job_id=str(job.job_id),
                job=job,
                execution=execution,
                progress={"percent": 75},
                blocked_to_working=True,
                old_resting_status="sleeping",
            )

        data = _extract_broadcast_call_data(ws_manager)
        assert data["old_status"] == "sleeping"
        assert data["status"] == "working"

    @pytest.mark.asyncio
    async def test_auto_wake_broadcast_includes_project_id(self):
        ws_manager = AsyncMock()
        ws_manager.broadcast_to_tenant = AsyncMock()

        service = _make_service_with_ws(ws_manager)
        project_id = uuid.uuid4()
        job = _make_mock_job(project_id=project_id)
        execution = _make_mock_execution()

        with patch.object(service, "_fetch_and_broadcast_progress", new=AsyncMock()):
            await service._broadcast_progress_update(
                tenant_key="test-tenant",
                job_id=str(job.job_id),
                job=job,
                execution=execution,
                progress={"percent": 10},
                blocked_to_working=True,
                old_resting_status="blocked",
            )

        data = _extract_broadcast_call_data(ws_manager)
        assert data["project_id"] == str(project_id)

    @pytest.mark.asyncio
    async def test_auto_wake_broadcast_event_type_is_agent_status_changed(self):
        ws_manager = AsyncMock()
        ws_manager.broadcast_to_tenant = AsyncMock()

        service = _make_service_with_ws(ws_manager)
        job = _make_mock_job()
        execution = _make_mock_execution()

        with patch.object(service, "_fetch_and_broadcast_progress", new=AsyncMock()):
            await service._broadcast_progress_update(
                tenant_key="test-tenant",
                job_id=str(job.job_id),
                job=job,
                execution=execution,
                progress={"percent": 10},
                blocked_to_working=True,
                old_resting_status="idle",
            )

        call_kwargs = ws_manager.broadcast_to_tenant.call_args
        event_type = call_kwargs.kwargs.get("event_type") or call_kwargs[1].get("event_type")
        assert event_type == "agent:status_changed"

    @pytest.mark.asyncio
    async def test_auto_wake_broadcast_includes_agent_display_name(self):
        ws_manager = AsyncMock()
        ws_manager.broadcast_to_tenant = AsyncMock()

        service = _make_service_with_ws(ws_manager)
        job = _make_mock_job()
        execution = _make_mock_execution(agent_display_name="implementer")

        with patch.object(service, "_fetch_and_broadcast_progress", new=AsyncMock()):
            await service._broadcast_progress_update(
                tenant_key="test-tenant",
                job_id=str(job.job_id),
                job=job,
                execution=execution,
                progress={"percent": 60},
                blocked_to_working=True,
                old_resting_status="blocked",
            )

        data = _extract_broadcast_call_data(ws_manager)
        assert data["agent_display_name"] == "implementer"

    @pytest.mark.asyncio
    async def test_no_status_broadcast_when_blocked_to_working_is_false(self):
        ws_manager = AsyncMock()
        ws_manager.broadcast_to_tenant = AsyncMock()

        service = _make_service_with_ws(ws_manager)
        job = _make_mock_job()
        execution = _make_mock_execution()

        with patch.object(service, "_fetch_and_broadcast_progress", new=AsyncMock()):
            await service._broadcast_progress_update(
                tenant_key="test-tenant",
                job_id=str(job.job_id),
                job=job,
                execution=execution,
                progress={"percent": 30},
                blocked_to_working=False,
                old_resting_status=None,
            )

        ws_manager.broadcast_to_tenant.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_status_broadcast_when_ws_manager_is_none(self):
        service = _make_service_with_ws(ws_manager=None)
        job = _make_mock_job()
        execution = _make_mock_execution()

        with patch.object(service, "_fetch_and_broadcast_progress", new=AsyncMock()):
            result = await service._broadcast_progress_update(
                tenant_key="test-tenant",
                job_id=str(job.job_id),
                job=job,
                execution=execution,
                progress={"percent": 20},
                blocked_to_working=True,
                old_resting_status="blocked",
            )

        assert result is not None
        assert result.status == "success"

    @pytest.mark.asyncio
    async def test_old_resting_status_none_falls_back_to_blocked(self):
        ws_manager = AsyncMock()
        ws_manager.broadcast_to_tenant = AsyncMock()

        service = _make_service_with_ws(ws_manager)
        job = _make_mock_job()
        execution = _make_mock_execution()

        with patch.object(service, "_fetch_and_broadcast_progress", new=AsyncMock()):
            await service._broadcast_progress_update(
                tenant_key="test-tenant",
                job_id=str(job.job_id),
                job=job,
                execution=execution,
                progress={"percent": 10},
                blocked_to_working=True,
                old_resting_status=None,
            )

        data = _extract_broadcast_call_data(ws_manager)
        assert data["old_status"] == "blocked"

    @pytest.mark.asyncio
    async def test_broadcast_progress_update_returns_progress_result(self):
        ws_manager = AsyncMock()
        ws_manager.broadcast_to_tenant = AsyncMock()

        service = _make_service_with_ws(ws_manager)
        job = _make_mock_job()
        execution = _make_mock_execution()

        with patch.object(service, "_fetch_and_broadcast_progress", new=AsyncMock()):
            result = await service._broadcast_progress_update(
                tenant_key="test-tenant",
                job_id=str(job.job_id),
                job=job,
                execution=execution,
                progress={"percent": 50, "todo_items": [{"content": "step", "status": "in_progress"}]},
                blocked_to_working=False,
                old_resting_status=None,
            )

        assert result.status == "success"
        assert result.message == "Progress reported successfully"
