# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import random
import uuid
from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.models import AgentExecution, AgentJob, Product, Project
from giljo_mcp.models.projects import ProjectStatus
from giljo_mcp.services.project_staging_service import ProjectStagingService
from giljo_mcp.services.workflow_status_service import WorkflowStatusService
from giljo_mcp.tenant import TenantManager


pytestmark = pytest.mark.asyncio




def _staging_service(db_manager, tenant_key, db_session) -> ProjectStagingService:
    mock_tm = MagicMock()
    mock_tm.get_current_tenant.return_value = tenant_key
    return ProjectStagingService(db_manager=db_manager, tenant_manager=mock_tm, test_session=db_session)


async def _staged_project(db_session, tenant_key: str) -> Project:
    product = Product(id=str(uuid.uuid4()), tenant_key=tenant_key, name=f"be9541-product-{uuid.uuid4().hex[:8]}")
    db_session.add(product)
    await db_session.flush()

    project = Project(
        id=str(uuid.uuid4()),
        tenant_key=tenant_key,
        product_id=product.id,
        name=f"be9541-project-{uuid.uuid4().hex[:8]}",
        description="BE-9541 launch-response probe.",
        mission="BE-9541 probe mission.",
        status=ProjectStatus.ACTIVE,
        staging_status="staging_complete",
        created_at=datetime.now(UTC),
    )
    db_session.add(project)
    await db_session.flush()
    return project


async def test_first_launch_populates_a_timestamp_an_honest_caller_can_read(db_manager, db_session, test_tenant_key):
    svc = _staging_service(db_manager, test_tenant_key, db_session)
    project = await _staged_project(db_session, test_tenant_key)

    result = await svc.launch_implementation(project.id, tenant_key=test_tenant_key)

    assert result["already_launched"] is False
    assert result["implementation_launched_at"] is not None
    assert result["launched_at"] is not None, (
        "a caller branching on launched_at alone must not see None on a successful first launch"
    )
    assert result["launched_at"] == result["implementation_launched_at"]


async def test_already_launched_reply_also_populates_both_fields(db_manager, db_session, test_tenant_key):
    svc = _staging_service(db_manager, test_tenant_key, db_session)
    project = await _staged_project(db_session, test_tenant_key)

    await svc.launch_implementation(project.id, tenant_key=test_tenant_key)
    result = await svc.launch_implementation(project.id, tenant_key=test_tenant_key)

    assert result["already_launched"] is True
    assert result["launched_at"] is not None
    assert result["implementation_launched_at"] is not None, (
        "a caller branching on implementation_launched_at alone must not see None on the already-launched reply"
    )
    assert result["launched_at"] == result["implementation_launched_at"]


async def test_launch_report_on_a_project_left_inactive_be9532_pin(db_manager, db_session, test_tenant_key):
    svc = _staging_service(db_manager, test_tenant_key, db_session)
    project = await _staged_project(db_session, test_tenant_key)
    project.status = ProjectStatus.INACTIVE
    project.implementation_launched_at = datetime.now(UTC)
    await db_session.flush()

    result = await svc.launch_implementation(project.id, tenant_key=test_tenant_key)

    assert result["project_active"] is False
    assert "activ" in str(result.get("next_action", "")).lower()


async def test_mcp_tool_boundary_passes_a_readable_timestamp_through(
    db_manager, db_session, test_tenant_key, monkeypatch
):
    from giljo_mcp.tools.tool_accessor._project_tools import ProjectToolsMixin

    project = await _staged_project(db_session, test_tenant_key)

    class _Recorder:
        def __init__(self, *a, **kw):
            pass

        async def launch_implementation(self, project_id, **kwargs):
            svc = _staging_service(db_manager, test_tenant_key, db_session)
            return await svc.launch_implementation(project_id, tenant_key=test_tenant_key)

    monkeypatch.setattr(
        "giljo_mcp.services.project_staging_service.ProjectStagingService",
        _Recorder,
    )

    accessor = ProjectToolsMixin()
    accessor.db_manager = db_manager
    accessor.tenant_manager = MagicMock()
    accessor.tenant_manager.get_current_tenant.return_value = test_tenant_key
    accessor.websocket_manager = None
    accessor._test_session = db_session
    accessor._websocket_manager = None

    payload = await accessor.launch_implementation(project_id=project.id, tenant_key=test_tenant_key)

    assert payload["launched_at"] is not None, (
        "the agent-facing payload must not carry a null launched_at on a successful first launch"
    )




def _workflow_svc(session: AsyncSession) -> WorkflowStatusService:
    return WorkflowStatusService(db_manager=None, tenant_manager=TenantManager(), test_session=session)


async def _seed_project_with_one_closed_agent(session: AsyncSession, tenant_key: str) -> str:
    owning_product = Product(
        id=str(uuid.uuid4()),
        tenant_key=tenant_key,
        name=f"Owning Product {uuid.uuid4().hex[:6]}",
        description="seeded",
        is_active=False,
    )
    session.add(owning_product)
    project = Project(
        id=str(uuid.uuid4()),
        name="BE-9541 closed-agent project",
        description="closed_agents counting probe",
        mission="closed_agents counting probe mission",
        status="active",
        tenant_key=tenant_key,
        product_id=owning_product.id,
        execution_mode="multi_terminal",
        series_number=random.randint(1, 9000),
        created_at=datetime.now(UTC),
    )
    session.add(project)
    await session.flush()

    job = AgentJob(
        job_id=str(uuid.uuid4()),
        tenant_key=tenant_key,
        project_id=project.id,
        job_type="implementer",
        mission="do the work",
        status="completed",
    )
    session.add(job)
    execution = AgentExecution(
        job_id=job.job_id,
        tenant_key=tenant_key,
        agent_display_name="implementer",
        status="closed",
        messages_sent_count=0,
        messages_waiting_count=0,
        messages_read_count=0,
    )
    session.add(execution)
    await session.flush()
    return project.id


async def test_a_fully_closed_project_does_not_read_as_zero_percent_unknown(db_session: AsyncSession) -> None:
    tenant = TenantManager.generate_tenant_key()
    pid = await _seed_project_with_one_closed_agent(db_session, tenant)

    result = await _workflow_svc(db_session).get_workflow_status(pid, tenant)

    assert result.closed_agents == 1, "a closed agent must be counted somewhere -- currently it is not"
    assert result.progress_percent == 100.0, "a fully-closed project must not read as 0% progress"
    assert result.current_stage != "Unknown", "a fully-closed project must not read as an unknown stage"


async def test_workflow_status_schema_has_closed_agents_field() -> None:
    from giljo_mcp.schemas.responses.orchestration import WorkflowStatus

    ws = WorkflowStatus(closed_agents=3)
    assert ws.closed_agents == 3
    assert ws.model_dump()["closed_agents"] == 3
    assert WorkflowStatus().closed_agents == 0
