# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import random
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from giljo_mcp.models.agent_identity import AgentExecution, AgentJob
from giljo_mcp.models.products import Product
from giljo_mcp.models.projects import Project
from giljo_mcp.services.agent_health_ws_broadcast import broadcast_agent_auto_failed
from giljo_mcp.services.job_lifecycle_service import JobLifecycleService
from giljo_mcp.services.notification_service import NotificationService
from giljo_mcp.services.progress_service import ProgressService
from giljo_mcp.services.project_helpers import broadcast_deferred_events, mark_staging_complete
from giljo_mcp.services.project_lifecycle_service import ProjectLifecycleService
from giljo_mcp.services.project_staging_service import ProjectStagingService
from giljo_mcp.tenant import TenantManager


pytestmark = pytest.mark.asyncio




async def test_spawn_job_agent_created_carries_product_id(db_session, db_manager, tenant_key, project):
    mock_ws = MagicMock()
    mock_ws.broadcast_to_tenant = AsyncMock()
    mock_ws.broadcast_project_update = AsyncMock()
    service = JobLifecycleService(
        db_manager=db_manager,
        tenant_manager=TenantManager(),
        test_session=db_session,
        websocket_manager=mock_ws,
    )

    await service.spawn_job(
        agent_display_name="impl",
        agent_name="specialist-1",
        mission="do work",
        project_id=project.id,
        tenant_key=tenant_key,
    )

    mock_ws.broadcast_to_tenant.assert_called_once()
    call = mock_ws.broadcast_to_tenant.call_args
    assert call.kwargs["event_type"] == "agent:created"
    assert call.kwargs["data"]["product_id"] == project.product_id




async def test_mark_staging_complete_carries_product_id(db_session, tenant_key, project):
    mock_ws = MagicMock()
    mock_ws.broadcast_to_tenant = AsyncMock()
    mock_ws.broadcast_project_update = AsyncMock()

    flipped = await mark_staging_complete(db_session, project, source="test", websocket_manager=mock_ws)

    assert flipped is True
    mock_ws.broadcast_to_tenant.assert_not_called()
    await broadcast_deferred_events(db_session)
    mock_ws.broadcast_to_tenant.assert_called_once()
    call = mock_ws.broadcast_to_tenant.call_args
    assert call.kwargs["event_type"] == "project:staging_complete"
    assert call.kwargs["data"]["product_id"] == project.product_id




async def test_launch_implementation_carries_product_id(db_session, db_manager, tenant_key, project):
    project.staging_status = "staging_complete"
    project.implementation_launched_at = None
    await db_session.commit()

    mock_ws = MagicMock()
    mock_ws.broadcast_to_tenant = AsyncMock()
    mock_ws.broadcast_project_update = AsyncMock()
    mock_tm = MagicMock()
    mock_tm.get_current_tenant.return_value = tenant_key
    service = ProjectStagingService(
        db_manager=db_manager, tenant_manager=mock_tm, test_session=db_session, websocket_manager=mock_ws
    )

    await service.launch_implementation(project.id, tenant_key=tenant_key)

    mock_ws.broadcast_to_tenant.assert_called_once()
    call = mock_ws.broadcast_to_tenant.call_args
    assert call.kwargs["event_type"] == "project:implementation_launched"
    assert call.kwargs["data"]["product_id"] == project.product_id




async def test_report_progress_carries_product_id(db_session, db_manager, tenant_key, project):
    job = AgentJob(
        job_id=str(uuid4()),
        tenant_key=tenant_key,
        project_id=project.id,
        job_type="implementer",
        mission="do work",
        status="active",
        created_at=datetime.now(UTC),
    )
    db_session.add(job)
    await db_session.flush()
    execution = AgentExecution(
        job_id=job.job_id,
        tenant_key=tenant_key,
        agent_display_name="impl",
        status="working",
        started_at=datetime.now(UTC),
    )
    db_session.add(execution)
    await db_session.commit()

    mock_ws = MagicMock()
    mock_ws.broadcast_to_tenant = AsyncMock()
    mock_ws.broadcast_project_update = AsyncMock()
    mock_tm = MagicMock()
    mock_tm.get_current_tenant.return_value = tenant_key
    service = ProgressService(db_manager=db_manager, tenant_manager=mock_tm, test_session=db_session)
    service._websocket_manager = mock_ws

    await service.report_progress(job_id=job.job_id, tenant_key=tenant_key, progress={"percent": 50})

    progress_calls = [
        c for c in mock_ws.broadcast_to_tenant.call_args_list if c.kwargs.get("event_type") == "job:progress_update"
    ]
    assert len(progress_calls) == 1
    assert progress_calls[0].kwargs["data"]["product_id"] == project.product_id




async def test_agent_auto_failed_carries_project_id():
    mock_ws = MagicMock()
    mock_ws.broadcast_event_to_tenant = AsyncMock()

    await broadcast_agent_auto_failed(
        mock_ws,
        tenant_key="tk_1",
        job_id="job-1",
        agent_display_name="impl",
        reason="Abandoned 90m",
        product_id="prod-1",
        project_id="proj-1",
    )

    mock_ws.broadcast_event_to_tenant.assert_called_once()
    event = mock_ws.broadcast_event_to_tenant.call_args.kwargs["event"]
    assert event["data"]["project_id"] == "proj-1"
    assert event["data"]["product_id"] == "prod-1"


async def test_agent_auto_failed_omits_project_id_when_not_given():
    mock_ws = MagicMock()
    mock_ws.broadcast_event_to_tenant = AsyncMock()

    await broadcast_agent_auto_failed(
        mock_ws,
        tenant_key="tk_1",
        job_id="job-1",
        agent_display_name="impl",
        reason="Abandoned 90m",
    )

    event = mock_ws.broadcast_event_to_tenant.call_args.kwargs["event"]
    assert "project_id" not in event["data"]




async def test_approval_read_carries_product_id(db_session, db_manager, tenant_key):
    from giljo_mcp.services.user_approval_service import UserApprovalService

    product = Product(
        id=str(uuid4()),
        name=f"BE-9525c Product {uuid4().hex[:6]}",
        description="seed",
        tenant_key=tenant_key,
        is_active=True,
    )
    db_session.add(product)
    proj = Project(
        id=str(uuid4()),
        tenant_key=tenant_key,
        product_id=product.id,
        name="BE-9525c approval project",
        description="seed",
        mission="seed",
        status="active",
        series_number=random.randint(1, 9000),
    )
    db_session.add(proj)
    await db_session.flush()
    job = AgentJob(
        job_id=str(uuid4()),
        tenant_key=tenant_key,
        project_id=proj.id,
        job_type="orchestrator",
        mission="orchestrator mission",
        status="active",
        created_at=datetime.now(UTC),
    )
    db_session.add(job)
    await db_session.flush()
    execution = AgentExecution(
        id=str(uuid4()),
        agent_id=str(uuid4()),
        job_id=job.job_id,
        tenant_key=tenant_key,
        agent_display_name="orchestrator",
        status="working",
        started_at=datetime.now(UTC),
    )
    db_session.add(execution)
    await db_session.commit()

    mock_ws = MagicMock()
    mock_ws.broadcast_to_tenant = AsyncMock()
    mock_ws.broadcast_project_update = AsyncMock()
    service = UserApprovalService(
        db_manager=db_manager, tenant_manager=TenantManager(), websocket_manager=mock_ws, test_session=db_session
    )
    await service.create_pending(
        tenant_key=tenant_key,
        job_id=job.job_id,
        project_id=proj.id,
        reason="Which option?",
        options=[{"id": "a", "label": "Option A"}],
        context=None,
    )

    reads, total = await service.list_pending(tenant_key=tenant_key)

    assert total == 1
    assert reads[0].product_id == product.id




async def test_deactivate_never_run_orchestrator_agent_removed_carries_product_id(db_session, db_manager, tenant_key):
    product = Product(
        id=str(uuid4()),
        name=f"BE-9525c removed-product {uuid4().hex[:6]}",
        description="seed",
        tenant_key=tenant_key,
        is_active=False,
    )
    db_session.add(product)
    proj = Project(
        id=str(uuid4()),
        tenant_key=tenant_key,
        product_id=product.id,
        name="BE-9525c never-run-orchestrator project",
        description="seed",
        mission="",
        status="inactive",
        series_number=random.randint(1, 9000),
    )
    db_session.add(proj)
    await db_session.commit()

    mock_ws = MagicMock()
    mock_ws.broadcast_to_tenant = AsyncMock()
    mock_ws.broadcast_project_update = AsyncMock()
    service = ProjectLifecycleService(
        db_manager=db_manager, tenant_manager=TenantManager(), test_session=db_session, websocket_manager=mock_ws
    )

    await service.activate_project(proj.id, tenant_key=tenant_key)
    mock_ws.broadcast_to_tenant.reset_mock()

    await service.deactivate_project(proj.id, tenant_key=tenant_key)

    removed_calls = [
        c for c in mock_ws.broadcast_to_tenant.call_args_list if c.kwargs.get("event_type") == "agent:removed"
    ]
    assert len(removed_calls) == 1, "the never-run orchestrator must be deleted and broadcast agent:removed"
    assert removed_calls[0].kwargs["data"]["product_id"] == product.id




async def test_notification_new_envelope_carries_top_level_ids(db_session, db_manager, tenant_key):
    mock_ws = MagicMock()
    mock_ws.broadcast_to_tenant = AsyncMock()
    mock_ws.broadcast_project_update = AsyncMock()
    service = NotificationService(db_manager=db_manager, websocket_manager=mock_ws, session=db_session)

    await service.create(
        tenant_key=tenant_key,
        notification_type="project.pre_launch_workproduct",
        severity="warning",
        title="Work committed without launch",
        dedupe_key=f"project.pre_launch_workproduct:{tenant_key}",
        payload={"project_id": "proj-abc", "project_name": "Test Project", "commit_count": 3},
    )

    mock_ws.broadcast_to_tenant.assert_called_once()
    call = mock_ws.broadcast_to_tenant.call_args
    assert call.kwargs["event_type"] == "notification:new"
    assert call.kwargs["data"]["project_id"] == "proj-abc"
    assert call.kwargs["data"]["product_id"] is None
