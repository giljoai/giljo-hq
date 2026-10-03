# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import random
from datetime import UTC, datetime
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from sqlalchemy import select

from giljo_mcp.models.agent_identity import AgentExecution, AgentJob
from giljo_mcp.models.products import Product
from giljo_mcp.models.projects import Project, ProjectStatus
from giljo_mcp.services.job_completion_service import JobCompletionService
from giljo_mcp.services.project_staging_service import ProjectStagingService
from giljo_mcp.services.sequence_run_service import SequenceRunService
from giljo_mcp.tenant import TenantManager


pytestmark = pytest.mark.asyncio


def _staging_service(db_manager, tenant_key, db_session) -> ProjectStagingService:
    tenant_manager = MagicMock()
    tenant_manager.get_current_tenant.return_value = tenant_key
    return ProjectStagingService(db_manager=db_manager, tenant_manager=tenant_manager, test_session=db_session)


async def _project(
    db_session,
    tenant_key: str,
    *,
    status: ProjectStatus,
    staging_status: str = "staging_complete",
    launched: bool = False,
) -> Project:
    product = Product(id=str(uuid4()), tenant_key=tenant_key, name=f"be9709c-product-{uuid4().hex[:8]}")
    db_session.add(product)
    await db_session.flush()
    project = Project(
        id=str(uuid4()),
        tenant_key=tenant_key,
        product_id=product.id,
        name=f"be9709c-project-{uuid4().hex[:8]}",
        description="Launch activation probe.",
        mission="Launch activation probe mission.",
        status=status,
        staging_status=staging_status,
        implementation_launched_at=datetime.now(UTC) if launched else None,
        series_number=random.randint(1, 9000),
        created_at=datetime.now(UTC),
    )
    db_session.add(project)
    db_session.info["tenant_key"] = tenant_key
    await db_session.flush()
    return project


async def _status(db_session, project_id: str, tenant_key: str) -> ProjectStatus:
    return (
        await db_session.execute(
            select(Project.status).where(Project.id == project_id, Project.tenant_key == tenant_key)
        )
    ).scalar_one()


async def test_dashboard_door_launch_makes_an_inactive_project_active(db_manager, db_session, test_tenant_key):
    svc = _staging_service(db_manager, test_tenant_key, db_session)
    project = await _project(db_session, test_tenant_key, status=ProjectStatus.INACTIVE)

    result = await svc.launch_implementation(
        project.id, tenant_key=test_tenant_key, launched_by="operator", origin="ui"
    )

    assert result["success"] is True
    assert result["already_launched"] is False
    assert result["project_active"] is True
    assert not result.get("next_action"), f"nothing further is required, got: {result.get('next_action')!r}"
    assert await _status(db_session, project.id, test_tenant_key) == ProjectStatus.ACTIVE


async def test_launch_leaves_a_parked_project_parked_and_says_so(db_manager, db_session, test_tenant_key):
    svc = _staging_service(db_manager, test_tenant_key, db_session)
    project = await _project(db_session, test_tenant_key, status=ProjectStatus.PARKED)

    result = await svc.launch_implementation(project.id, tenant_key=test_tenant_key)

    assert result["success"] is True
    assert result["project_active"] is False
    assert "activ" in str(result.get("next_action", "")).lower()
    assert await _status(db_session, project.id, test_tenant_key) == ProjectStatus.PARKED


async def test_project_launched_earlier_and_still_inactive_keeps_working(db_manager, db_session, test_tenant_key):
    svc = _staging_service(db_manager, test_tenant_key, db_session)
    project = await _project(db_session, test_tenant_key, status=ProjectStatus.INACTIVE, launched=True)

    result = await svc.launch_implementation(project.id, tenant_key=test_tenant_key)

    assert result["success"] is True
    assert result["already_launched"] is True
    assert result["project_active"] is False
    assert "activ" in str(result.get("next_action", "")).lower()
    assert await _status(db_session, project.id, test_tenant_key) == ProjectStatus.INACTIVE


async def test_another_tenant_cannot_launch_or_activate_the_project(db_manager, db_session, test_tenant_key):
    from giljo_mcp.exceptions import ResourceNotFoundError

    project = await _project(db_session, test_tenant_key, status=ProjectStatus.INACTIVE)
    other_tenant = TenantManager.generate_tenant_key()

    with pytest.raises(ResourceNotFoundError):
        await _staging_service(db_manager, other_tenant, db_session).launch_implementation(
            project.id, tenant_key=other_tenant
        )

    assert await _status(db_session, project.id, test_tenant_key) == ProjectStatus.INACTIVE


async def test_chain_member_staging_end_makes_an_inactive_member_active(db_session):
    tenant = TenantManager.generate_tenant_key()
    first = await _project(db_session, tenant, status=ProjectStatus.INACTIVE, staging_status="staging")
    second = await _project(db_session, tenant, status=ProjectStatus.INACTIVE, staging_status="staging")
    await SequenceRunService(db_manager=None, tenant_manager=TenantManager(), session=db_session).create(
        project_ids=[first.id, second.id],
        resolved_order=[first.id, second.id],
        execution_mode="claude_code_cli",
        tenant_key=tenant,
    )
    orchestrator_job = AgentJob(
        job_id=str(uuid4()),
        tenant_key=tenant,
        project_id=first.id,
        mission="orchestrate this project",
        job_type="orchestrator",
        status="active",
        job_metadata={},
    )
    worker_job = AgentJob(
        job_id=str(uuid4()),
        tenant_key=tenant,
        project_id=first.id,
        mission="implement the thing",
        job_type="implementer",
        status="active",
        job_metadata={},
    )
    db_session.add_all([orchestrator_job, worker_job])
    db_session.add_all(
        [
            AgentExecution(
                agent_id=str(uuid4()),
                job_id=orchestrator_job.job_id,
                tenant_key=tenant,
                agent_display_name="orchestrator",
                agent_name="SubOrch",
                status="waiting",
                health_status="unknown",
                project_phase="staging",
                started_at=datetime.now(UTC),
            ),
            AgentExecution(
                agent_id=str(uuid4()),
                job_id=worker_job.job_id,
                tenant_key=tenant,
                agent_display_name="implementer",
                agent_name="implementer",
                status="working",
                health_status="unknown",
                project_phase="implementation",
            ),
        ]
    )
    await db_session.flush()

    result = await JobCompletionService(
        db_manager=None, tenant_manager=TenantManager(), test_session=db_session
    ).complete_job(job_id=orchestrator_job.job_id, result={"summary": "staging done"}, tenant_key=tenant)

    assert result.phase == "staging_end"
    reloaded = (
        await db_session.execute(select(Project).where(Project.id == first.id, Project.tenant_key == tenant))
    ).scalar_one()
    assert reloaded.implementation_launched_at is not None
    assert reloaded.status == ProjectStatus.ACTIVE
    assert await _status(db_session, second.id, tenant) == ProjectStatus.INACTIVE, "only the member that started"
