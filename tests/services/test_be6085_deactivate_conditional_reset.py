# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import uuid
from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest
from sqlalchemy import and_, select

from giljo_mcp.domain.project_status import ProjectStatus
from giljo_mcp.models import Product, Project, Task
from giljo_mcp.models.agent_identity import AgentExecution, AgentJob
from giljo_mcp.services.project_lifecycle_service import ProjectLifecycleService
from tests.fixtures.base_fixtures import TestData


_PLACEHOLDER_MISSION = "Orchestrator for project: Wedged"


def _tenant_manager(tenant_key: str) -> MagicMock:
    tm = MagicMock()
    tm.get_current_tenant = MagicMock(return_value=tenant_key)
    return tm


async def _setup_project(
    db_session,
    tenant_key: str,
    *,
    staging_status: str | None = "staging",
    orch_status: str = "waiting",
    orch_working_started_at: datetime | None = None,
    orch_mission: str | None = _PLACEHOLDER_MISSION,
    with_subagent: bool = False,
    implementation_launched: bool = False,
    add_task: bool = True,
) -> tuple[Project, AgentExecution, Task | None]:
    product = Product(
        id=str(uuid.uuid4()),
        name="Wedged Product",
        description="desc",
        tenant_key=tenant_key,
        is_active=True,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    db_session.add(product)
    await db_session.flush()

    project = Project(
        id=str(uuid.uuid4()),
        name="Wedged Project",
        description="Human-written requirements that MUST survive deactivate.",
        mission="orchestrator-authored mission text",
        status=ProjectStatus.ACTIVE,
        staging_status=staging_status,
        product_id=product.id,
        tenant_key=tenant_key,
        series_number=1,
        implementation_launched_at=datetime.now(UTC) if implementation_launched else None,
    )
    db_session.add(project)
    await db_session.flush()

    task: Task | None = None
    if add_task:
        task = Task(
            id=str(uuid.uuid4()),
            title="Preserve me",
            description="task desc",
            tenant_key=tenant_key,
            product_id=product.id,
            project_id=project.id,
            status="pending",
            priority="medium",
        )
        db_session.add(task)

    orch_job = AgentJob(
        job_id=str(uuid.uuid4()),
        tenant_key=tenant_key,
        project_id=project.id,
        mission=orch_mission,
        job_type="orchestrator",
        status="active",
    )
    db_session.add(orch_job)
    orch_exec = AgentExecution(
        agent_id=str(uuid.uuid4()),
        job_id=orch_job.job_id,
        tenant_key=tenant_key,
        agent_display_name="orchestrator",
        agent_name="orchestrator",
        status=orch_status,
        working_started_at=orch_working_started_at,
        started_at=datetime.now(UTC),
        project_phase="staging",
    )
    db_session.add(orch_exec)

    if with_subagent:
        sub_job = AgentJob(
            job_id=str(uuid.uuid4()),
            tenant_key=tenant_key,
            project_id=project.id,
            mission="implement feature X",
            job_type="implementer",
            status="active",
        )
        db_session.add(sub_job)
        db_session.add(
            AgentExecution(
                agent_id=str(uuid.uuid4()),
                job_id=sub_job.job_id,
                tenant_key=tenant_key,
                agent_display_name="implementer",
                agent_name="implementer",
                status="waiting",
                started_at=datetime.now(UTC),
            )
        )

    await db_session.commit()
    return project, orch_exec, task


def _service(db_manager, db_session, tenant_key: str) -> ProjectLifecycleService:
    return ProjectLifecycleService(
        db_manager=db_manager,
        tenant_manager=_tenant_manager(tenant_key),
        test_session=db_session,
    )


async def _orch_execution_exists(db_session, execution_id: str) -> bool:
    row = (
        await db_session.execute(select(AgentExecution).where(AgentExecution.id == execution_id))
    ).scalar_one_or_none()
    return row is not None


async def _orch_job_exists(db_session, job_id: str) -> bool:
    row = (await db_session.execute(select(AgentJob).where(AgentJob.job_id == job_id))).scalar_one_or_none()
    return row is not None


async def _count_orchestrator_executions(db_session, project_id: str, tenant_key: str) -> int:
    rows = (
        (
            await db_session.execute(
                select(AgentExecution)
                .join(AgentJob, AgentExecution.job_id == AgentJob.job_id)
                .where(
                    and_(
                        AgentJob.project_id == project_id,
                        AgentExecution.agent_display_name == "orchestrator",
                        AgentExecution.tenant_key == tenant_key,
                    )
                )
            )
        )
        .scalars()
        .all()
    )
    return len(rows)




@pytest.mark.asyncio
async def test_deactivate_resets_never_run_orchestrator(db_session, db_manager):
    tenant_key = TestData.generate_tenant_key()
    project, orch_exec, task = await _setup_project(db_session, tenant_key)
    orig_title, orig_desc = project.name, project.description
    orch_exec_id, orch_job_id = orch_exec.id, orch_exec.job_id

    service = _service(db_manager, db_session, tenant_key)
    result = await service.deactivate_project(project.id, tenant_key=tenant_key)

    await db_session.refresh(project)
    await db_session.refresh(task)

    assert result.status == ProjectStatus.INACTIVE
    assert await _orch_execution_exists(db_session, orch_exec_id) is False
    assert await _orch_job_exists(db_session, orch_job_id) is False
    assert project.staging_status is None
    assert project.mission == ""
    assert project.implementation_launched_at is None
    assert project.name == orig_title
    assert project.description == orig_desc
    assert task.title == "Preserve me"


@pytest.mark.asyncio
async def test_deactivate_resets_staged_never_run_orchestrator(db_session, db_manager):
    tenant_key = TestData.generate_tenant_key()
    project, orch_exec, _ = await _setup_project(db_session, tenant_key, orch_status="staged", orch_mission=None)
    orch_exec_id, orch_job_id = orch_exec.id, orch_exec.job_id

    service = _service(db_manager, db_session, tenant_key)
    await service.deactivate_project(project.id, tenant_key=tenant_key)

    await db_session.refresh(project)
    assert await _orch_execution_exists(db_session, orch_exec_id) is False
    assert await _orch_job_exists(db_session, orch_job_id) is False
    assert project.staging_status is None




@pytest.mark.asyncio
async def test_deactivate_preserves_orchestrator_that_ran(db_session, db_manager):
    tenant_key = TestData.generate_tenant_key()
    project, orch_exec, _ = await _setup_project(db_session, tenant_key, orch_working_started_at=datetime.now(UTC))

    service = _service(db_manager, db_session, tenant_key)
    await service.deactivate_project(project.id, tenant_key=tenant_key)

    await db_session.refresh(project)
    await db_session.refresh(orch_exec)
    assert project.status == ProjectStatus.INACTIVE
    assert orch_exec.status == "waiting"
    assert project.staging_status == "staging"
    assert project.mission == "orchestrator-authored mission text"


@pytest.mark.asyncio
async def test_deactivate_preserves_orchestrator_with_subagents(db_session, db_manager):
    tenant_key = TestData.generate_tenant_key()
    project, orch_exec, _ = await _setup_project(db_session, tenant_key, with_subagent=True)

    service = _service(db_manager, db_session, tenant_key)
    await service.deactivate_project(project.id, tenant_key=tenant_key)

    await db_session.refresh(project)
    await db_session.refresh(orch_exec)
    assert project.status == ProjectStatus.INACTIVE
    assert orch_exec.status == "waiting"
    assert project.staging_status == "staging"


@pytest.mark.asyncio
async def test_deactivate_preserves_completed_staging(db_session, db_manager):
    tenant_key = TestData.generate_tenant_key()
    project, orch_exec, _ = await _setup_project(
        db_session,
        tenant_key,
        staging_status="staging_complete",
        orch_working_started_at=datetime.now(UTC),
    )

    service = _service(db_manager, db_session, tenant_key)
    await service.deactivate_project(project.id, tenant_key=tenant_key)

    await db_session.refresh(project)
    await db_session.refresh(orch_exec)
    assert project.status == ProjectStatus.INACTIVE
    assert orch_exec.status == "waiting"
    assert project.staging_status == "staging_complete"




@pytest.mark.asyncio
async def test_reset_then_reactivate_is_restageable(db_session, db_manager):
    tenant_key = TestData.generate_tenant_key()
    project, old_orch, _ = await _setup_project(db_session, tenant_key)
    old_orch_id, old_orch_job_id, old_agent_id = old_orch.id, old_orch.job_id, old_orch.agent_id

    service = _service(db_manager, db_session, tenant_key)
    await service.deactivate_project(project.id, tenant_key=tenant_key)
    assert await _orch_execution_exists(db_session, old_orch_id) is False
    assert await _orch_job_exists(db_session, old_orch_job_id) is False

    await service.activate_project(project.id, tenant_key=tenant_key)
    await db_session.refresh(project)

    assert project.status == ProjectStatus.ACTIVE
    assert project.staging_status is None

    live_orchestrators = (
        (
            await db_session.execute(
                select(AgentExecution)
                .join(AgentJob, AgentExecution.job_id == AgentJob.job_id)
                .where(
                    and_(
                        AgentJob.project_id == project.id,
                        AgentExecution.agent_display_name == "orchestrator",
                        AgentExecution.tenant_key == tenant_key,
                        AgentExecution.status != "decommissioned",
                    )
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(live_orchestrators) == 1
    assert live_orchestrators[0].agent_id != old_agent_id




async def _live_orchestrator(db_session, project_id: str, tenant_key: str) -> AgentExecution:
    rows = (
        (
            await db_session.execute(
                select(AgentExecution)
                .join(AgentJob, AgentExecution.job_id == AgentJob.job_id)
                .where(
                    and_(
                        AgentJob.project_id == project_id,
                        AgentExecution.agent_display_name == "orchestrator",
                        AgentExecution.tenant_key == tenant_key,
                        AgentExecution.status != "decommissioned",
                    )
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1, f"expected exactly 1 live orchestrator, found {len(rows)}"
    return rows[0]


@pytest.mark.asyncio
async def test_activate_deactivate_cycle_no_accumulation_and_ran_survives(db_session, db_manager):
    tenant_key = TestData.generate_tenant_key()

    product = Product(
        id=str(uuid.uuid4()),
        name="Cycle Product",
        description="desc",
        tenant_key=tenant_key,
        is_active=True,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    db_session.add(product)
    await db_session.flush()
    project = Project(
        id=str(uuid.uuid4()),
        name="Cycle Project",
        description="requirements that survive every cycle",
        mission="",
        status=ProjectStatus.INACTIVE,
        staging_status=None,
        product_id=product.id,
        tenant_key=tenant_key,
        series_number=1,
    )
    db_session.add(project)
    await db_session.commit()

    service = _service(db_manager, db_session, tenant_key)

    await service.activate_project(project.id, tenant_key=tenant_key)
    agent_id_1 = (await _live_orchestrator(db_session, project.id, tenant_key)).agent_id
    await service.deactivate_project(project.id, tenant_key=tenant_key)
    assert await _count_orchestrator_executions(db_session, project.id, tenant_key) == 0

    await service.activate_project(project.id, tenant_key=tenant_key)
    agent_id_2 = (await _live_orchestrator(db_session, project.id, tenant_key)).agent_id
    assert agent_id_2 != agent_id_1
    await service.deactivate_project(project.id, tenant_key=tenant_key)
    assert await _count_orchestrator_executions(db_session, project.id, tenant_key) == 0

    await service.activate_project(project.id, tenant_key=tenant_key)
    ran = await _live_orchestrator(db_session, project.id, tenant_key)
    ran_id, ran_agent_id = ran.id, ran.agent_id
    ran.working_started_at = datetime.now(UTC)
    await db_session.commit()

    await service.deactivate_project(project.id, tenant_key=tenant_key)
    assert await _orch_execution_exists(db_session, ran_id) is True
    survivor = await _live_orchestrator(db_session, project.id, tenant_key)
    assert survivor.agent_id == ran_agent_id
    assert survivor.status != "decommissioned"
