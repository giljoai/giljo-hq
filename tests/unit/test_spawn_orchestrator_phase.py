# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.models.agent_identity import AgentExecution, AgentJob
from giljo_mcp.models.products import Product
from giljo_mcp.models.projects import Project
from giljo_mcp.repositories.project_lifecycle_repository import ProjectLifecycleRepository




async def _seed_product(db_session: AsyncSession, tenant_key: str) -> Product:
    product = Product(
        id=str(uuid4()),
        tenant_key=tenant_key,
        name=f"Phase Unit Test Product {uuid4().hex[:6]}",
        description="CE-0026 spawn phase unit tests",
        is_active=True,
    )
    db_session.add(product)
    await db_session.flush()
    return product


async def _seed_active_project(
    db_session: AsyncSession,
    tenant_key: str,
    product_id: str,
    *,
    staging_status: str | None = None,
) -> Project:
    project = Project(
        id=str(uuid4()),
        tenant_key=tenant_key,
        product_id=product_id,
        name=f"Phase Unit Test Project {uuid4().hex[:6]}",
        description="CE-0026 spawn phase unit tests",
        mission="CE-0026 test mission",
        status="active",
        staging_status=staging_status,
        series_number=random.randint(1, 9000),
        created_at=datetime.now(UTC),
    )
    db_session.add(project)
    await db_session.flush()
    return project


def _make_launch_service(db_session: AsyncSession, tenant_key: str):
    from giljo_mcp.services.project_launch_service import ProjectLaunchService

    db_manager = MagicMock()
    tenant_manager = MagicMock()
    tenant_manager.get_current_tenant.return_value = tenant_key
    return ProjectLaunchService(
        db_manager=db_manager,
        tenant_manager=tenant_manager,
        test_session=db_session,
    )




@pytest.mark.asyncio
async def test_create_orchestrator_fixture_sets_staging_phase(
    db_session: AsyncSession,
    test_tenant_key: str,
):
    product = await _seed_product(db_session, test_tenant_key)
    project = await _seed_active_project(db_session, test_tenant_key, product.id)
    await db_session.commit()

    repo = ProjectLifecycleRepository()
    result = await repo.create_orchestrator_fixture(db_session, test_tenant_key, project)

    execution_id = result["execution_id"]
    execution = (await db_session.execute(select(AgentExecution).where(AgentExecution.id == execution_id))).scalar_one()

    assert execution.project_phase == "staging", (
        f"CE-0026: create_orchestrator_fixture must set project_phase='staging', got {execution.project_phase!r}"
    )




@pytest.mark.asyncio
async def test_launch_project_spawn_orchestrator_sets_staging_phase(
    db_session: AsyncSession,
    test_tenant_key: str,
):
    product = await _seed_product(db_session, test_tenant_key)
    project = await _seed_active_project(db_session, test_tenant_key, product.id)
    await db_session.commit()

    svc = _make_launch_service(db_session, test_tenant_key)
    result = await svc.launch_project(project_id=project.id)

    assert result.orchestrator_job_id is not None

    execution = (
        await db_session.execute(
            select(AgentExecution).where(
                AgentExecution.job_id == result.orchestrator_job_id,
                AgentExecution.tenant_key == test_tenant_key,
                AgentExecution.agent_display_name == "orchestrator",
            )
        )
    ).scalar_one()

    assert execution.project_phase == "staging", (
        f"CE-0026: _spawn_orchestrator must set project_phase='staging', got {execution.project_phase!r}"
    )
    refreshed_project = (
        await db_session.execute(select(Project).where(Project.id == project.id, Project.tenant_key == test_tenant_key))
    ).scalar_one()
    assert refreshed_project.staging_status == "staging", (
        "CE-0026: _spawn_orchestrator must set project.staging_status='staging'"
    )




@pytest.mark.asyncio
async def test_thin_prompt_generator_creates_orchestrator_with_staging_phase(
    db_session: AsyncSession,
    test_tenant_key: str,
):
    from giljo_mcp.thin_prompt_generator import ThinClientPromptGenerator

    product = await _seed_product(db_session, test_tenant_key)
    project = await _seed_active_project(db_session, test_tenant_key, product.id)
    await db_session.commit()

    generator = ThinClientPromptGenerator(db=db_session, tenant_key=test_tenant_key)

    orchestrator_id, _agent_id, _execution_id = await generator._find_or_create_orchestrator(
        project_id=project.id,
        project=project,
        field_toggles={},
        depth_config={},
        user_id=None,
        tool="universal",
    )

    assert orchestrator_id is not None

    execution = (
        await db_session.execute(
            select(AgentExecution).where(
                AgentExecution.job_id == orchestrator_id,
                AgentExecution.tenant_key == test_tenant_key,
            )
        )
    ).scalar_one()

    assert execution.project_phase == "staging", (
        f"CE-0026: ThinClientPromptGenerator._find_or_create_orchestrator must set "
        f"project_phase='staging' on new execution, got {execution.project_phase!r}"
    )




@pytest.mark.asyncio
async def test_launch_project_reuses_orch_across_phases_ce_0032(
    db_session: AsyncSession,
    test_tenant_key: str,
):
    product = await _seed_product(db_session, test_tenant_key)
    project = await _seed_active_project(db_session, test_tenant_key, product.id, staging_status="staging_complete")

    job_id = str(uuid4())
    job = AgentJob(
        job_id=job_id,
        tenant_key=test_tenant_key,
        project_id=project.id,
        job_type="orchestrator",
        mission="CE-0032 single-exec reuse",
        status="active",
        created_at=datetime.now(UTC),
    )
    db_session.add(job)
    orch_exec = AgentExecution(
        agent_id=str(uuid4()),
        job_id=job_id,
        tenant_key=test_tenant_key,
        agent_display_name="orchestrator",
        status="waiting",
        started_at=datetime.now(UTC) - timedelta(minutes=10),
        project_phase="staging",
    )
    db_session.add(orch_exec)
    await db_session.commit()

    svc = _make_launch_service(db_session, test_tenant_key)
    result = await svc.launch_project(project_id=project.id)

    assert result.orchestrator_job_id == job_id, "CE-0032: launch_project must reuse the same AgentJob"

    executions = list(
        (
            await db_session.execute(
                select(AgentExecution).where(
                    AgentExecution.job_id == job_id,
                    AgentExecution.tenant_key == test_tenant_key,
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(executions) == 1, (
        f"CE-0032: launch_project MUST NOT spawn a second orch exec; got {len(executions)} rows"
    )
    assert executions[0].agent_id == orch_exec.agent_id




@pytest.mark.asyncio
async def test_agent_execution_default_project_phase_is_implementation(
    db_session: AsyncSession,
    test_tenant_key: str,
):
    product = await _seed_product(db_session, test_tenant_key)
    project = await _seed_active_project(db_session, test_tenant_key, product.id)

    job_id = str(uuid4())
    job = AgentJob(
        job_id=job_id,
        tenant_key=test_tenant_key,
        project_id=project.id,
        job_type="orchestrator",
        mission="back-compat default test",
        status="active",
        created_at=datetime.now(UTC),
    )
    db_session.add(job)

    execution = AgentExecution(
        agent_id=str(uuid4()),
        job_id=job_id,
        tenant_key=test_tenant_key,
        agent_display_name="orchestrator",
        status="working",
        started_at=datetime.now(UTC),
    )
    db_session.add(execution)
    await db_session.commit()
    await db_session.refresh(execution)

    assert execution.project_phase == "implementation", (
        f"CE-0026: back-compat default for project_phase must be 'implementation', got {execution.project_phase!r}"
    )




@pytest.mark.asyncio
async def test_agent_execution_check_constraint_rejects_invalid_phase(
    db_session: AsyncSession,
    test_tenant_key: str,
):
    product = await _seed_product(db_session, test_tenant_key)
    project = await _seed_active_project(db_session, test_tenant_key, product.id)

    job_id = str(uuid4())
    job = AgentJob(
        job_id=job_id,
        tenant_key=test_tenant_key,
        project_id=project.id,
        job_type="orchestrator",
        mission="CHECK constraint test",
        status="active",
        created_at=datetime.now(UTC),
    )
    db_session.add(job)
    await db_session.flush()

    agent_id = str(uuid4())
    exec_id = str(uuid4())

    async def _insert_invalid_phase() -> None:
        await db_session.execute(
            text(
                """
                INSERT INTO agent_executions
                  (id, agent_id, job_id, tenant_key, agent_display_name, status,
                   health_status, messages_sent_count, messages_waiting_count,
                   messages_read_count, progress, accumulated_duration_seconds,
                   reactivation_count, tool_type, project_phase)
                VALUES
                  (:id, :agent_id, :job_id, :tenant_key, :display, :status,
                   :health, 0, 0, 0, 0, 0.0, 0, :tool, :phase)
                """
            ),
            {
                "id": exec_id,
                "agent_id": agent_id,
                "job_id": job_id,
                "tenant_key": test_tenant_key,
                "display": "orchestrator",
                "status": "working",
                "health": "unknown",
                "tool": "universal",
                "phase": "garbage",
            },
        )
        await db_session.flush()

    with pytest.raises((IntegrityError, Exception)) as exc_info:
        await _insert_invalid_phase()

    err_str = str(exc_info.value).lower()
    assert any(term in err_str for term in ("check", "constraint", "project_phase", "integrity")), (
        f"CE-0026: expected a CHECK constraint IntegrityError for project_phase='garbage', got: {exc_info.value!r}"
    )
