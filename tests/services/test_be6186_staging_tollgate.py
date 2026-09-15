# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import pytest
import pytest_asyncio
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.database import tenant_isolation_bypass
from giljo_mcp.exceptions import ValidationError
from giljo_mcp.models.agent_identity import AgentExecution, AgentJob
from giljo_mcp.models.products import Product
from giljo_mcp.models.projects import Project
from giljo_mcp.models.sequence_runs import SequenceRun
from giljo_mcp.services.job_completion_service import JobCompletionService
from giljo_mcp.tenant import TenantManager


pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture(autouse=True)
async def _wipe_sequence_runs(db_manager):
    yield
    async with db_manager.get_session_async() as session:
        with tenant_isolation_bypass(
            session, reason="test teardown: wipe sequence_runs (per-worker DB)", models=(SequenceRun,)
        ):
            await session.execute(delete(SequenceRun))
        await session.commit()


def _completion_service(db_session: AsyncSession, tenant_key: str) -> JobCompletionService:
    tenant_manager = MagicMock()
    tenant_manager.get_current_tenant.return_value = tenant_key
    return JobCompletionService(
        db_manager=MagicMock(),
        tenant_manager=tenant_manager,
        test_session=db_session,
    )


async def _seed_conductor(db_session: AsyncSession, tenant_key: str) -> tuple[str, str]:
    job_id = str(uuid.uuid4())
    agent_id = str(uuid.uuid4())
    db_session.add(
        AgentJob(
            job_id=job_id,
            tenant_key=tenant_key,
            project_id=None,
            mission="chain plan",
            job_type="orchestrator",
            status="active",
            job_metadata={"chain_conductor": True},
        )
    )
    db_session.add(
        AgentExecution(
            agent_id=agent_id,
            job_id=job_id,
            tenant_key=tenant_key,
            agent_display_name="orchestrator",
            agent_name="Chain Conductor",
            status="working",
            health_status="unknown",
            project_phase="implementation",
            started_at=datetime.now(UTC) - timedelta(minutes=2),
        )
    )
    db_session.info["tenant_key"] = tenant_key
    await db_session.flush()
    return job_id, agent_id


async def _seed_run(
    db_session: AsyncSession,
    tenant_key: str,
    *,
    conductor_agent_id: str,
    project_statuses: dict[str, str],
    current_index: int = 0,
    status: str = "pending",
) -> str:
    resolved = list(project_statuses.keys())
    run = SequenceRun(
        id=str(uuid.uuid4()),
        tenant_key=tenant_key,
        project_ids=resolved,
        resolved_order=resolved,
        current_index=current_index,
        execution_mode="claude_code_cli",
        status=status,
        review_policy="per_card",
        project_statuses=project_statuses,
        conductor_agent_id=conductor_agent_id,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    db_session.add(run)
    await db_session.flush()
    return run.id


async def _seed_solo_orchestrator(db_session: AsyncSession, tenant_key: str) -> str:
    project_id = str(uuid.uuid4())
    _product_id = str(uuid.uuid4())
    db_session.add(
        Product(
            id=_product_id,
            tenant_key=tenant_key,
            name=f"Owning Product {_product_id[:8]}",
            description="seeded",
            is_active=False,
        )
    )
    db_session.add(
        Project(
            id=project_id,
            product_id=_product_id,
            tenant_key=tenant_key,
            name="Solo",
            description="d",
            mission="m",
            status="active",
            staging_status="staging",
            series_number=1,
            execution_mode="claude_code_cli",
            created_at=datetime.now(UTC),
        )
    )
    job_id = str(uuid.uuid4())
    db_session.add(
        AgentJob(
            job_id=job_id,
            tenant_key=tenant_key,
            project_id=project_id,
            mission="solo plan",
            job_type="orchestrator",
            status="active",
            job_metadata={},
        )
    )
    db_session.add(
        AgentExecution(
            agent_id=str(uuid.uuid4()),
            job_id=job_id,
            tenant_key=tenant_key,
            agent_display_name="orchestrator",
            agent_name="Solo Orchestrator",
            status="working",
            health_status="unknown",
            project_phase="staging",
            started_at=datetime.now(UTC) - timedelta(minutes=2),
        )
    )
    db_session.info["tenant_key"] = tenant_key
    await db_session.flush()
    return job_id




async def test_conductor_staging_end_with_zero_agents_succeeds(db_session: AsyncSession) -> None:
    tenant = TenantManager.generate_tenant_key()
    job_id, agent_id = await _seed_conductor(db_session, tenant)
    p1, p2 = str(uuid.uuid4()), str(uuid.uuid4())
    await _seed_run(
        db_session,
        tenant,
        conductor_agent_id=agent_id,
        project_statuses={p1: "pending", p2: "pending"},
        current_index=0,
        status="pending",
    )

    svc = _completion_service(db_session, tenant)
    result = await svc.complete_job(
        job_id=job_id,
        result={"summary": "Chain staged; stopping for the Implement gate."},
        tenant_key=tenant,
    )

    assert result.status == "success", "the conductor must be allowed to end staging with zero agents"
    assert result.staging_directive is not None, "a STOP staging_directive must be returned"
    assert result.phase == "staging_end"

    assert result.staging_directive.action == "STOP", "the conductor must keep action=STOP at staging-end"
    assert "GO" in result.staging_directive.message, "the conductor directive must firm the await-GO wording"
    assert result.next_action and "EXPLICIT GO" in result.next_action["why"], (
        "the conductor staging-end next_action must tell it to wait for the user's explicit GO"
    )

    exec_row = await db_session.execute(
        select(AgentExecution).where(AgentExecution.job_id == job_id, AgentExecution.tenant_key == tenant)
    )
    execution = exec_row.scalar_one()
    assert execution.status == "waiting", "staging-end parks the conductor at 'waiting', not 'complete'"

    job_row = await db_session.execute(select(AgentJob).where(AgentJob.job_id == job_id, AgentJob.tenant_key == tenant))
    assert job_row.scalar_one().status == "active", "the conductor job must stay 'active' to drive implementation"




async def test_solo_staging_end_zero_agents_still_raises(db_session: AsyncSession) -> None:
    tenant = TenantManager.generate_tenant_key()
    job_id = await _seed_solo_orchestrator(db_session, tenant)

    svc = _completion_service(db_session, tenant)
    with pytest.raises(ValidationError) as ei:
        await svc.complete_job(
            job_id=job_id,
            result={"summary": "trying to end staging with no agents"},
            tenant_key=tenant,
        )
    assert ei.value.error_code == "STAGING_END_NO_AGENTS", "solo staging-end with zero agents must still be refused"




async def test_conductor_self_complete_blocked_when_run_in_flight(db_session: AsyncSession) -> None:
    tenant = TenantManager.generate_tenant_key()
    job_id, agent_id = await _seed_conductor(db_session, tenant)
    p1, p2 = str(uuid.uuid4()), str(uuid.uuid4())
    await _seed_run(
        db_session,
        tenant,
        conductor_agent_id=agent_id,
        project_statuses={p1: "implementing", p2: "pending"},
        current_index=0,
        status="running",
    )

    svc = _completion_service(db_session, tenant)
    with pytest.raises(ValidationError) as ei:
        await svc.complete_job(
            job_id=job_id,
            result={"summary": "premature self-complete mid-drive"},
            tenant_key=tenant,
        )
    assert ei.value.error_code == "CONDUCTOR_CHAIN_INCOMPLETE", (
        "a conductor mid-drive (a member implementing) must be blocked, not treated as a zero-agent staging-end"
    )
