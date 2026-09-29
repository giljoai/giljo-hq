# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock

import pytest

from giljo_mcp.services.orchestration_agent_state_service import OrchestrationAgentStateService


pytestmark = pytest.mark.asyncio


@asynccontextmanager
async def _async_ctx(value):
    yield value


def _make_service() -> OrchestrationAgentStateService:
    mock_db = MagicMock()
    mock_tenant = MagicMock()
    mock_tenant.get_current_tenant.return_value = "test_tenant"
    svc = OrchestrationAgentStateService(db_manager=mock_db, tenant_manager=mock_tenant)
    svc._websocket_manager = MagicMock()
    svc._websocket_manager.broadcast_to_tenant = AsyncMock()
    return svc


def _last_broadcast_data(svc: OrchestrationAgentStateService) -> dict:
    return svc._websocket_manager.broadcast_to_tenant.await_args.kwargs["data"]


async def test_resolve_product_id_returns_none_for_project_less_job():
    svc = _make_service()
    job = MagicMock(project_id=None)
    assert await svc._resolve_product_id(session=MagicMock(), tenant_key="t", job=job) is None


async def test_resolve_product_id_returns_none_for_none_job():
    svc = _make_service()
    assert await svc._resolve_product_id(session=MagicMock(), tenant_key="t", job=None) is None


async def test_resolve_product_id_resolves_via_project():
    svc = _make_service()
    job = MagicMock(project_id="proj-1")
    svc._job_repo.get_project_by_id = AsyncMock(return_value=MagicMock(product_id="prod-1"))
    assert await svc._resolve_product_id(session=MagicMock(), tenant_key="t", job=job) == "prod-1"


async def test_broadcast_completion_includes_product_id():
    svc = _make_service()
    job = MagicMock(project_id="proj-1", job_metadata={})
    execution = MagicMock(
        agent_display_name="implementer",
        agent_name="worker",
        status="complete",
        completed_at=None,
        duration_seconds=5.0,
        working_started_at=None,
    )
    await svc._broadcast_completion(
        tenant_key="t",
        job_id="job-1",
        job=job,
        execution=execution,
        old_status="working",
        duration_seconds=5.0,
        product_id="prod-completion",
    )
    assert _last_broadcast_data(svc)["product_id"] == "prod-completion"


async def test_reactivate_job_broadcasts_product_id():
    svc = _make_service()
    mock_session = AsyncMock()
    mock_session.info = {}
    svc._get_session = MagicMock(return_value=_async_ctx(mock_session))

    execution = MagicMock(status="blocked", completed_at=None, started_at=None, reactivation_count=0)
    job = MagicMock(project_id="proj-1", status="completed", job_metadata={})
    project = MagicMock(status="active", product_id="prod-reactivate")

    svc._job_repo.find_blocked_execution_for_job = AsyncMock(return_value=execution)
    svc._job_repo.get_agent_job_by_job_id = AsyncMock(return_value=job)
    svc._job_repo.get_project_by_id = AsyncMock(return_value=project)
    svc._job_repo.flush = AsyncMock()

    await svc.reactivate_job(job_id="job-1", tenant_key="test_tenant", reason="follow-up")

    assert _last_broadcast_data(svc)["product_id"] == "prod-reactivate"


async def test_dismiss_reactivation_broadcasts_product_id():
    svc = _make_service()
    mock_session = AsyncMock()
    mock_session.info = {}
    svc._get_session = MagicMock(return_value=_async_ctx(mock_session))

    execution = MagicMock(status="blocked", duration_seconds=1.0, working_started_at=None)
    job = MagicMock(project_id="proj-1", status="active", job_metadata={})
    project = MagicMock(product_id="prod-dismiss")

    svc._job_repo.find_blocked_execution_for_job = AsyncMock(return_value=execution)
    svc._job_repo.get_agent_job_by_job_id = AsyncMock(return_value=job)
    svc._job_repo.find_other_active_executions = AsyncMock(return_value=[MagicMock()])
    svc._job_repo.get_project_by_id = AsyncMock(return_value=project)
    svc._job_repo.flush = AsyncMock()

    await svc.dismiss_reactivation(job_id="job-1", tenant_key="test_tenant", reason="ack")

    assert _last_broadcast_data(svc)["product_id"] == "prod-dismiss"


async def test_close_job_broadcasts_product_id():
    svc = _make_service()
    mock_session = AsyncMock()
    mock_session.info = {}
    svc._get_session = MagicMock(return_value=_async_ctx(mock_session))

    execution = MagicMock(status="complete", agent_id="agent-1", duration_seconds=1.0, working_started_at=None)
    job = MagicMock(project_id="proj-1", job_metadata={})
    project = MagicMock(product_id="prod-close")

    svc._job_repo.find_complete_execution_for_job = AsyncMock(return_value=execution)
    orchestrator = MagicMock(project_id="proj-1", job_type="orchestrator")
    svc._job_repo.get_agent_job_by_job_id = AsyncMock(
        side_effect=lambda _s, _t, job_id: orchestrator if job_id == "orch-1" else job
    )
    svc._job_repo.get_project_by_id = AsyncMock(return_value=project)
    svc._job_repo.flush = AsyncMock()

    async def _no_op_cursors(*args, **kwargs):
        return None

    import giljo_mcp.services.orchestration_agent_state_service as oas_module

    original = oas_module.resolve_terminal_agent_cursors
    oas_module.resolve_terminal_agent_cursors = _no_op_cursors
    try:
        await svc.close_job(job_id="job-1", tenant_key="test_tenant", caller_job_id="orch-1")
    finally:
        oas_module.resolve_terminal_agent_cursors = original

    assert _last_broadcast_data(svc)["product_id"] == "prod-close"


async def test_set_agent_status_broadcasts_product_id():
    svc = _make_service()
    mock_session = AsyncMock()
    mock_session.info = {}
    svc._get_session = MagicMock(return_value=_async_ctx(mock_session))

    execution = MagicMock(
        agent_display_name="implementer",
        agent_name="worker",
        status="working",
        duration_seconds=1.0,
        working_started_at=None,
    )
    job = MagicMock(project_id="proj-1", job_metadata={})
    project = MagicMock(product_id="prod-status")

    svc._job_repo.find_active_execution_for_job = AsyncMock(return_value=execution)
    svc._job_repo.get_agent_job_by_job_id = AsyncMock(return_value=job)
    svc._job_repo.get_project_by_id = AsyncMock(return_value=project)
    svc._job_repo.flush = AsyncMock()

    await svc.set_agent_status(job_id="job-1", status="idle", reason="", tenant_key="test_tenant")

    assert _last_broadcast_data(svc)["product_id"] == "prod-status"
