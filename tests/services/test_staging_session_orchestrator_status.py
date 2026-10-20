# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from sqlalchemy import select

from giljo_mcp.database import DatabaseManager
from giljo_mcp.models.agent_identity import AgentExecution, AgentJob
from giljo_mcp.models.organizations import Organization
from giljo_mcp.models.products import Product
from giljo_mcp.models.projects import Project
from giljo_mcp.services.orchestration_service import OrchestrationService
from giljo_mcp.services.silence_detector import SilenceDetector
from giljo_mcp.tenant import TenantManager


pytestmark = pytest.mark.asyncio


async def _seed(db_session, tenant_key: str) -> tuple[str, str]:
    suffix = uuid4().hex[:8]
    db_session.add(Organization(name=f"Org {suffix}", slug=f"org-{suffix}", tenant_key=tenant_key, is_active=True))
    product = Product(id=str(uuid4()), name=f"Product {suffix}", description="x", tenant_key=tenant_key, is_active=True)
    db_session.add(product)
    await db_session.flush()
    project = Project(
        id=str(uuid4()),
        tenant_key=tenant_key,
        product_id=product.id,
        name=f"Staging {suffix}",
        description="Plan the thing.",
        mission="",
        status="active",
        staging_status="staging",
        execution_mode="subagent",
        series_number=random.randint(1, 9000),
    )
    db_session.add(project)
    await db_session.flush()
    orch_job = AgentJob(
        job_id=str(uuid4()),
        tenant_key=tenant_key,
        project_id=project.id,
        job_type="orchestrator",
        mission="Orchestrate.",
        status="active",
    )
    worker_job = AgentJob(
        job_id=str(uuid4()),
        tenant_key=tenant_key,
        project_id=project.id,
        job_type="implementer",
        mission="Build it.",
        status="active",
    )
    db_session.add_all([orch_job, worker_job])
    await db_session.flush()
    db_session.add_all(
        [
            AgentExecution(
                id=str(uuid4()),
                agent_id=str(uuid4()),
                job_id=orch_job.job_id,
                tenant_key=tenant_key,
                agent_display_name="orchestrator",
                agent_name="orchestrator",
                status="waiting",
                project_phase="staging",
            ),
            AgentExecution(
                id=str(uuid4()),
                agent_id=str(uuid4()),
                job_id=worker_job.job_id,
                tenant_key=tenant_key,
                agent_display_name="implementer",
                agent_name="implementer",
                status="waiting",
            ),
        ]
    )
    await db_session.commit()
    return project.id, orch_job.job_id


async def _execution(db_session, tenant_key: str, job_id: str) -> AgentExecution:
    db_session.expire_all()
    return await db_session.scalar(
        select(AgentExecution).where(AgentExecution.tenant_key == tenant_key, AgentExecution.job_id == job_id)
    )


def _service(db_manager, db_session) -> OrchestrationService:
    return OrchestrationService(db_manager=db_manager, tenant_manager=TenantManager(), test_session=db_session)


def _detector() -> SilenceDetector:
    ws = AsyncMock()
    ws.broadcast_event_to_tenant = AsyncMock()
    return SilenceDetector(db_manager=Mock(spec=DatabaseManager), ws_manager=ws)


async def test_get_staging_instructions_starts_the_orchestrator(db_manager, db_session):
    tenant_key = TenantManager.generate_tenant_key()
    _project_id, orch_job_id = await _seed(db_session, tenant_key)
    before = datetime.now(UTC)

    await _service(db_manager, db_session)._mission.get_staging_instructions(orch_job_id, tenant_key)

    execution = await _execution(db_session, tenant_key, orch_job_id)
    assert execution.status == "working"
    assert execution.started_at is not None
    assert execution.last_progress_at is not None
    assert execution.last_progress_at >= before


async def test_staging_refetch_keeps_working_and_renders_the_same_staging_protocol(db_manager, db_session):
    tenant_key = TenantManager.generate_tenant_key()
    _project_id, orch_job_id = await _seed(db_session, tenant_key)
    service = _service(db_manager, db_session)

    first = await service._mission.get_staging_instructions(orch_job_id, tenant_key)
    second = await service._mission.get_staging_instructions(orch_job_id, tenant_key)

    assert (await _execution(db_session, tenant_key, orch_job_id)).status == "working"
    assert set(second["orchestrator_protocol"]) == set(first["orchestrator_protocol"])
    assert "ch5_reference" not in second["orchestrator_protocol"]


async def test_staging_end_parks_at_waiting_and_implementation_starts_it_again(db_manager, db_session):
    tenant_key = TenantManager.generate_tenant_key()
    project_id, orch_job_id = await _seed(db_session, tenant_key)
    service = _service(db_manager, db_session)

    await service._mission.get_staging_instructions(orch_job_id, tenant_key)
    assert (await _execution(db_session, tenant_key, orch_job_id)).status == "working"

    done = await service.complete_job(orch_job_id, {"summary": "staged"}, tenant_key=tenant_key)
    assert done.staging_directive is not None
    assert (await _execution(db_session, tenant_key, orch_job_id)).status == "waiting"

    project = await db_session.get(Project, project_id)
    project.implementation_launched_at = datetime.now(UTC)
    await db_session.commit()

    await service.get_agent_mission(orch_job_id, tenant_key)
    assert (await _execution(db_session, tenant_key, orch_job_id)).status == "working"


async def test_orchestrator_at_the_gate_is_never_flagged_silent(db_manager, db_session):
    tenant_key = TenantManager.generate_tenant_key()
    _project_id, orch_job_id = await _seed(db_session, tenant_key)
    service = _service(db_manager, db_session)
    await service._mission.get_staging_instructions(orch_job_id, tenant_key)
    await service.complete_job(orch_job_id, {"summary": "staged"}, tenant_key=tenant_key)

    execution = await _execution(db_session, tenant_key, orch_job_id)
    execution.last_progress_at = datetime.now(UTC) - timedelta(hours=3)
    await db_session.commit()

    await _detector()._detect_silent_agents(db_session, threshold_minutes=10)

    assert (await _execution(db_session, tenant_key, orch_job_id)).status == "waiting"


async def test_a_quiet_planning_orchestrator_is_flagged_silent(db_manager, db_session):
    tenant_key = TenantManager.generate_tenant_key()
    _project_id, orch_job_id = await _seed(db_session, tenant_key)
    await _service(db_manager, db_session)._mission.get_staging_instructions(orch_job_id, tenant_key)

    execution = await _execution(db_session, tenant_key, orch_job_id)
    execution.last_progress_at = datetime.now(UTC) - timedelta(hours=3)
    await db_session.commit()

    await _detector()._detect_silent_agents(db_session, threshold_minutes=10)

    assert (await _execution(db_session, tenant_key, orch_job_id)).status == "silent"


async def test_restage_is_still_allowed_while_the_orchestrator_plans(db_manager, db_session, monkeypatch):
    tenant_key = TenantManager.generate_tenant_key()
    project_id, orch_job_id = await _seed(db_session, tenant_key)
    await _service(db_manager, db_session)._mission.get_staging_instructions(orch_job_id, tenant_key)
    assert (await _execution(db_session, tenant_key, orch_job_id)).status == "working"

    from giljo_mcp.services.project_staging_service import ProjectStagingService

    tenant_manager = TenantManager()
    monkeypatch.setattr(tenant_manager, "get_current_tenant", lambda: tenant_key)
    lifecycle = Mock()
    lifecycle._ensure_orchestrator_fixture = AsyncMock(return_value={"job_id": "fresh"})
    staging = ProjectStagingService(
        db_manager=db_manager, tenant_manager=tenant_manager, test_session=db_session, lifecycle_service=lifecycle
    )

    result = await staging.restage(project_id)

    assert result["project_id"] == project_id
    assert (await _execution(db_session, tenant_key, orch_job_id)).status == "decommissioned"


async def test_chain_conductor_works_while_staging_and_waits_for_the_go(db_manager, db_session):
    from giljo_mcp.services.sequence_run_service import SequenceRunService

    tenant_key = TenantManager.generate_tenant_key()
    head_id, _ = await _seed(db_session, tenant_key)
    run = await SequenceRunService(db_manager=None, tenant_manager=TenantManager(), session=db_session).create(
        project_ids=[head_id], resolved_order=[head_id], execution_mode="subagent", tenant_key=tenant_key
    )
    conductor_job_id = await db_session.scalar(
        select(AgentExecution.job_id).where(
            AgentExecution.tenant_key == tenant_key, AgentExecution.agent_id == run["conductor_agent_id"]
        )
    )
    service = _service(db_manager, db_session)
    assert (await _execution(db_session, tenant_key, conductor_job_id)).status == "waiting"

    staging = await service._mission.get_staging_instructions(conductor_job_id, tenant_key)
    assert staging["status"] == "CHAIN_CONDUCTOR_STAGING"
    assert (await _execution(db_session, tenant_key, conductor_job_id)).status == "working"

    done = await service.complete_job(conductor_job_id, {"summary": "chain staged"}, tenant_key=tenant_key)
    assert done.staging_directive is not None
    assert (await _execution(db_session, tenant_key, conductor_job_id)).status == "waiting"

    await service._mission.get_staging_instructions(conductor_job_id, tenant_key)
    assert (await _execution(db_session, tenant_key, conductor_job_id)).status == "waiting"
