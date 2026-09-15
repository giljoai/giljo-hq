# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.models import AgentExecution, AgentJob, Product, Project
from giljo_mcp.services.workflow_status_service import WorkflowStatusService
from giljo_mcp.tenant import TenantManager


async def _seed_project(
    session: AsyncSession,
    tenant_key: str,
    *,
    closeout_executed_at: datetime | None = None,
) -> str:
    _owning_product_project = Product(
        id=str(uuid.uuid4()),
        tenant_key=tenant_key,
        name=f"Owning Product {uuid.uuid4().hex[:6]}",
        description="seeded",
        is_active=False,
    )
    session.add(_owning_product_project)
    project = Project(
        id=str(uuid.uuid4()),
        name=f"BE-6208f {uuid.uuid4().hex[:6]}",
        description="Chain member.",
        mission="Be a chain member.",
        status="active",
        tenant_key=tenant_key,
        product_id=_owning_product_project.id,
        series_number=1,
        execution_mode="claude_code_cli",
        closeout_executed_at=closeout_executed_at,
        created_at=datetime.now(UTC),
    )
    session.add(project)
    session.info["tenant_key"] = tenant_key
    await session.flush()
    return project.id


async def _seed_complete_agent(session: AsyncSession, tenant_key: str, project_id: str) -> None:
    job = AgentJob(
        job_id=str(uuid.uuid4()),
        project_id=project_id,
        tenant_key=tenant_key,
        job_type="implementer",
        status="completed",
        created_at=datetime.now(UTC),
    )
    session.add(job)
    await session.flush()
    execution = AgentExecution(
        id=str(uuid.uuid4()),
        agent_id=str(uuid.uuid4()),
        job_id=job.job_id,
        tenant_key=tenant_key,
        agent_display_name="BE-6208f agent",
        status="complete",
        started_at=datetime.now(UTC),
    )
    session.add(execution)
    await session.flush()


def _workflow_svc(session: AsyncSession) -> WorkflowStatusService:
    return WorkflowStatusService(db_manager=None, tenant_manager=TenantManager(), test_session=session)




@pytest.mark.asyncio
async def test_ready_to_advance_false_at_100_percent_without_closeout(db_session: AsyncSession) -> None:
    tenant = TenantManager.generate_tenant_key()
    pid = await _seed_project(db_session, tenant, closeout_executed_at=None)
    await _seed_complete_agent(db_session, tenant, pid)

    result = await _workflow_svc(db_session).get_workflow_status(pid, tenant)

    assert result.current_stage == "Completed"
    assert result.progress_percent == 100.0
    assert result.project_closeout_at is None
    assert result.ready_to_advance is False




@pytest.mark.asyncio
async def test_ready_to_advance_true_once_closeout_set(db_session: AsyncSession) -> None:
    tenant = TenantManager.generate_tenant_key()
    pid = await _seed_project(db_session, tenant, closeout_executed_at=datetime.now(UTC))
    await _seed_complete_agent(db_session, tenant, pid)

    result = await _workflow_svc(db_session).get_workflow_status(pid, tenant)

    assert result.project_closeout_at is not None
    assert result.ready_to_advance is True




@pytest.mark.asyncio
async def test_ready_to_advance_is_only_added_field(db_session: AsyncSession) -> None:
    tenant = TenantManager.generate_tenant_key()
    pid = await _seed_project(db_session, tenant, closeout_executed_at=None)

    result = await _workflow_svc(db_session).get_workflow_status(pid, tenant)
    dumped = result.model_dump()

    pre_be6208f_keys = {
        "active_agents",
        "completed_agents",
        "pending_agents",
        "blocked_agents",
        "silent_agents",
        "decommissioned_agents",
        "current_stage",
        "progress_percent",
        "total_agents",
        "caller_note",
        "agents",
        "auto_checkin_enabled",
        "auto_checkin_interval",
        "project_closeout_at",
        "staging_status",
    }
    assert set(dumped) == pre_be6208f_keys | {
        "ready_to_advance",
        "next_action",
        "checkin_cadence_minutes",
        "closed_agents",
    }
