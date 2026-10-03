# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.models import AgentExecution, AgentJob, Product, Project
from giljo_mcp.services import next_action as na
from giljo_mcp.services.project_closeout_service import ProjectCloseoutService
from giljo_mcp.services.project_service import ProjectService
from giljo_mcp.services.workflow_status_service import WorkflowStatusService
from giljo_mcp.tenant import TenantManager
from tests.helpers.test_db_helper import purge_tenant_rows


pytestmark = pytest.mark.asyncio


async def _seed_project(
    session: AsyncSession,
    tenant_key: str,
    *,
    status: str = "inactive",
    staging_status: str | None = None,
    implementation_launched_at: datetime | None = None,
) -> Project:
    product = Product(
        id=str(uuid.uuid4()),
        tenant_key=tenant_key,
        name=f"BE-9613 product {uuid.uuid4().hex[:6]}",
        description="seeded",
        is_active=False,
    )
    session.add(product)
    project = Project(
        id=str(uuid.uuid4()),
        name=f"BE-9613 {uuid.uuid4().hex[:6]}",
        description="seeded",
        mission="Carry a hint.",
        status=status,
        tenant_key=tenant_key,
        product_id=product.id,
        series_number=1,
        execution_mode="claude_code_cli",
        staging_status=staging_status,
        implementation_launched_at=implementation_launched_at,
        created_at=datetime.now(UTC),
    )
    session.add(project)
    session.info["tenant_key"] = tenant_key
    await session.flush()
    return project


async def _seed_agent(session: AsyncSession, tenant_key: str, project_id: str, *, status: str) -> None:
    job = AgentJob(
        job_id=str(uuid.uuid4()),
        project_id=project_id,
        tenant_key=tenant_key,
        job_type="implementer",
        status="active",
        created_at=datetime.now(UTC),
    )
    session.add(job)
    await session.flush()
    session.add(
        AgentExecution(
            id=str(uuid.uuid4()),
            agent_id=str(uuid.uuid4()),
            job_id=job.job_id,
            tenant_key=tenant_key,
            agent_display_name="BE-9613 agent",
            status=status,
            started_at=datetime.now(UTC),
        )
    )
    await session.flush()




@pytest_asyncio.fixture
async def committed_projects(db_manager):
    tenant_key = TenantManager.generate_tenant_key()
    async with db_manager.get_session_async(tenant_key=tenant_key) as session:
        product = Product(
            id=str(uuid.uuid4()),
            tenant_key=tenant_key,
            name=f"BE-9613 product {uuid.uuid4().hex[:6]}",
            description="seeded",
            is_active=True,
        )
        session.add(product)
        await session.flush()
        fresh = Project(
            id=str(uuid.uuid4()),
            name=f"BE-9613 fresh {uuid.uuid4().hex[:6]}",
            description="seeded",
            mission="Carry a hint.",
            status="inactive",
            tenant_key=tenant_key,
            product_id=product.id,
            series_number=1,
            execution_mode="claude_code_cli",
            created_at=datetime.now(UTC),
        )
        done = Project(
            id=str(uuid.uuid4()),
            name=f"BE-9613 done {uuid.uuid4().hex[:6]}",
            description="seeded",
            mission="Be finished.",
            status="completed",
            tenant_key=tenant_key,
            product_id=product.id,
            series_number=2,
            execution_mode="claude_code_cli",
            completed_at=datetime.now(UTC),
            created_at=datetime.now(UTC),
        )
        session.add_all([fresh, done])
        await session.commit()
        ids = (fresh.id, done.id)

    tenant_manager = TenantManager()
    tenant_manager.set_current_tenant(tenant_key)
    service = ProjectService(db_manager=db_manager, tenant_manager=tenant_manager)
    try:
        yield service, tenant_key, ids
    finally:
        await purge_tenant_rows(db_manager, tenant_key)


async def test_planning_mode_rows_carry_a_per_row_hint(committed_projects):
    service, tenant_key, (fresh_id, _done_id) = committed_projects

    response = await service.list_projects_for_mcp(tenant_key=tenant_key, mode="planning")

    row = next(r for r in response["projects"] if r["project_id"] == fresh_id)
    assert row["next_action"]["tool"] == "stage_project"
    assert row["next_action"]["why"] == na.PROJECT_NOT_STAGED_HINT


async def test_triage_mode_stays_lean(committed_projects):
    service, tenant_key, _ids = committed_projects

    response = await service.list_projects_for_mcp(tenant_key=tenant_key, mode="triage")

    assert response["projects"]
    assert all("next_action" not in row for row in response["projects"])


async def test_a_completed_row_omits_the_field_entirely(committed_projects):
    service, tenant_key, (_fresh_id, done_id) = committed_projects

    response = await service.list_projects_for_mcp(
        tenant_key=tenant_key, mode="planning", status="completed", include_completed=True
    )

    row = next(r for r in response["projects"] if r["project_id"] == done_id)
    assert "next_action" not in row




async def test_summary_mode_carries_one_response_level_hint(two_tenant_service_setup):
    tenant = two_tenant_service_setup["tenant_a"]
    task_service = two_tenant_service_setup["task_service_a"]
    await task_service.create_task_for_mcp(
        title="BE-9613 probe task",
        description="",
        tenant_key=tenant,
        db_manager=two_tenant_service_setup["db_manager"],
    )

    response = await task_service.list_tasks_for_mcp(tenant_key=tenant, mode="summary")

    assert response["next_action"]["why"] == na.TASK_OPEN_HINT
    assert all("next_action" not in row for row in response["tasks"])


_HANDOVER_BODY = (
    "## Verify before trusting\n- x -- check with: y\n\n"
    "## Waiting on the operator\n- nothing\n\n## Cannot testify\n- nothing"
)


async def test_a_page_holding_an_open_handover_tells_the_successor_to_complete_it(two_tenant_service_setup):
    tenant = two_tenant_service_setup["tenant_a"]
    task_service = two_tenant_service_setup["task_service_a"]
    await task_service.create_task_for_mcp(
        title="IMP-9732 handover probe",
        description=_HANDOVER_BODY,
        task_type="HND",
        tenant_key=tenant,
        db_manager=two_tenant_service_setup["db_manager"],
    )

    response = await task_service.list_tasks_for_mcp(tenant_key=tenant, mode="summary")

    assert na.TASK_HANDOVER_HINT in response["next_action"]["why"]


async def test_a_page_of_ordinary_tasks_does_not_carry_the_handover_sentence(two_tenant_service_setup):
    tenant = two_tenant_service_setup["tenant_a"]
    task_service = two_tenant_service_setup["task_service_a"]
    await task_service.create_task_for_mcp(
        title="IMP-9732 ordinary probe",
        description="",
        tenant_key=tenant,
        db_manager=two_tenant_service_setup["db_manager"],
    )

    response = await task_service.list_tasks_for_mcp(tenant_key=tenant, mode="summary")

    assert na.TASK_HANDOVER_HINT not in response["next_action"]["why"]


async def test_index_mode_stays_lean(two_tenant_service_setup):
    tenant = two_tenant_service_setup["tenant_a"]
    task_service = two_tenant_service_setup["task_service_a"]
    await task_service.create_task_for_mcp(
        title="BE-9613 lean probe",
        description="",
        tenant_key=tenant,
        db_manager=two_tenant_service_setup["db_manager"],
    )

    response = await task_service.list_tasks_for_mcp(tenant_key=tenant, mode="index")

    assert "next_action" not in response


async def test_a_page_with_no_open_task_omits_the_hint(two_tenant_service_setup):
    tenant = two_tenant_service_setup["tenant_a"]
    task_service = two_tenant_service_setup["task_service_a"]

    response = await task_service.list_tasks_for_mcp(tenant_key=tenant, mode="summary")

    assert response["count"] == 0
    assert "next_action" not in response




async def test_workflow_status_falls_back_to_the_lifecycle_hint(db_session: AsyncSession):
    tenant = TenantManager.generate_tenant_key()
    project = await _seed_project(db_session, tenant, staging_status="staging_complete")
    service = WorkflowStatusService(db_manager=None, tenant_manager=TenantManager(), test_session=db_session)

    result = await service.get_workflow_status(project.id, tenant)

    assert result.next_action["tool"] == "launch_implementation"
    assert result.next_action["why"] == na.PROJECT_AWAITING_GO_HINT


async def test_a_wedged_project_still_gets_the_specific_diagnostic(db_session: AsyncSession):
    tenant = TenantManager.generate_tenant_key()
    project = await _seed_project(
        db_session,
        tenant,
        status="active",
        staging_status="staging_complete",
        implementation_launched_at=datetime.now(UTC),
    )
    await _seed_agent(db_session, tenant, project.id, status="blocked")
    service = WorkflowStatusService(db_manager=None, tenant_manager=TenantManager(), test_session=db_session)

    result = await service.get_workflow_status(project.id, tenant)

    assert result.next_action["tool"] == "diagnose_project_state"


async def test_an_awaiting_user_agent_surfaces_the_approval_hint(db_session: AsyncSession):
    tenant = TenantManager.generate_tenant_key()
    project = await _seed_project(
        db_session,
        tenant,
        status="active",
        staging_status="staging_complete",
        implementation_launched_at=datetime.now(UTC),
    )
    await _seed_agent(db_session, tenant, project.id, status="awaiting_user")
    service = WorkflowStatusService(db_manager=None, tenant_manager=TenantManager(), test_session=db_session)

    result = await service.get_workflow_status(project.id, tenant)

    assert result.next_action["why"] == na.PROJECT_AWAITING_USER_HINT




async def test_diagnose_carries_the_hint_next_to_suggested_actions(db_session: AsyncSession):
    tenant = TenantManager.generate_tenant_key()
    project = await _seed_project(db_session, tenant)
    service = ProjectCloseoutService(None, TenantManager(), test_session=db_session)

    report = await service.diagnose_project_state(project.id, tenant_key=tenant)

    assert report["next_action"]["why"] == na.PROJECT_NOT_STAGED_HINT
    assert isinstance(report["suggested_actions"], list)


async def test_diagnose_omits_the_hint_for_a_completed_project(db_session: AsyncSession):
    tenant = TenantManager.generate_tenant_key()
    project = await _seed_project(db_session, tenant, status="completed")
    service = ProjectCloseoutService(None, TenantManager(), test_session=db_session)

    report = await service.diagnose_project_state(project.id, tenant_key=tenant)

    assert "next_action" not in report
