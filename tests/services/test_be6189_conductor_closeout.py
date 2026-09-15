# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.exceptions import ResourceNotFoundError, ValidationError
from giljo_mcp.models import Product, Project
from giljo_mcp.models.agent_identity import AgentExecution, AgentJob
from giljo_mcp.services.job_completion_service import JobCompletionService
from giljo_mcp.services.project_helpers import (
    complete_chain_run_if_finished,
    mark_chain_member_status,
)
from giljo_mcp.services.sequence_run_service import SequenceRunService
from giljo_mcp.tenant import TenantManager
from tests.helpers.taxonomy_seeds import next_series_number


pytestmark = pytest.mark.asyncio




async def _seed_project(session: AsyncSession, tenant_key: str) -> str:
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
        name=f"BE-6189 {uuid.uuid4().hex[:6]}",
        description="Chain member.",
        mission="Be a chain member.",
        status="active",
        tenant_key=tenant_key,
        product_id=_owning_product_project.id,
        series_number=next_series_number(),
        execution_mode="claude_code_cli",
        created_at=datetime.now(UTC),
    )
    session.add(project)
    session.info["tenant_key"] = tenant_key
    await session.flush()
    return project.id


def _run_svc(session: AsyncSession) -> SequenceRunService:
    return SequenceRunService(db_manager=None, tenant_manager=TenantManager(), session=session)


async def _seed_run_with_conductor(session: AsyncSession, tenant_key: str) -> dict:
    p1 = await _seed_project(session, tenant_key)
    p2 = await _seed_project(session, tenant_key)
    run = await _run_svc(session).create(
        project_ids=[p1, p2],
        resolved_order=[p1, p2],
        execution_mode="claude_code_cli",
        tenant_key=tenant_key,
    )
    run["_project_ids"] = [p1, p2]
    return run


async def _conductor_job_and_exec(
    session: AsyncSession, tenant_key: str, conductor_agent_id: str
) -> tuple[AgentJob, AgentExecution]:
    exec_row = await session.execute(
        select(AgentExecution).where(
            AgentExecution.tenant_key == tenant_key,
            AgentExecution.agent_id == conductor_agent_id,
        )
    )
    execution = exec_row.scalar_one()
    job_row = await session.execute(
        select(AgentJob).where(
            AgentJob.tenant_key == tenant_key,
            AgentJob.job_id == execution.job_id,
        )
    )
    return job_row.scalar_one(), execution


def _completion_svc(session: AsyncSession) -> JobCompletionService:
    return JobCompletionService(db_manager=None, tenant_manager=TenantManager(), test_session=session)




async def test_sub_orch_closeout_marks_member_completed(db_session: AsyncSession) -> None:
    tenant = TenantManager.generate_tenant_key()
    run = await _seed_run_with_conductor(db_session, tenant)
    p0 = run["_project_ids"][0]

    flipped = await mark_chain_member_status(
        db_manager=None,
        tenant_manager=TenantManager(),
        project_id=p0,
        tenant_key=tenant,
        status="completed",
        test_session=db_session,
    )
    assert flipped is True

    refetched = await _run_svc(db_session).find_active_run_for_project(project_id=p0, tenant_key=tenant)
    assert refetched is not None
    assert refetched["project_statuses"][p0] == "completed"




async def test_c1_guard_passes_when_all_terminal(db_session: AsyncSession) -> None:
    tenant = TenantManager.generate_tenant_key()
    run = await _seed_run_with_conductor(db_session, tenant)
    p1, p2 = run["_project_ids"]

    for pid in (p1, p2):
        await mark_chain_member_status(
            db_manager=None,
            tenant_manager=TenantManager(),
            project_id=pid,
            tenant_key=tenant,
            status="completed",
            test_session=db_session,
        )

    job, execution = await _conductor_job_and_exec(db_session, tenant, run["conductor_agent_id"])

    await _completion_svc(db_session)._guard_conductor_chain_incomplete(
        db_session, job, execution, tenant, str(job.job_id)
    )




async def test_complete_chain_run_if_finished_purges_run(db_session: AsyncSession) -> None:
    tenant = TenantManager.generate_tenant_key()
    run = await _seed_run_with_conductor(db_session, tenant)
    p1, p2 = run["_project_ids"]
    conductor_agent_id = run["conductor_agent_id"]

    for pid in (p1, p2):
        await mark_chain_member_status(
            db_manager=None,
            tenant_manager=TenantManager(),
            project_id=pid,
            tenant_key=tenant,
            status="completed",
            test_session=db_session,
        )

    purged = await complete_chain_run_if_finished(
        db_manager=None,
        tenant_manager=TenantManager(),
        conductor_agent_id=conductor_agent_id,
        tenant_key=tenant,
        test_session=db_session,
    )
    assert purged is True

    with pytest.raises(ResourceNotFoundError):
        await _run_svc(db_session).get(run_id=run["id"], tenant_key=tenant)




async def test_complete_chain_run_if_finished_noop_when_incomplete(db_session: AsyncSession) -> None:
    tenant = TenantManager.generate_tenant_key()
    run = await _seed_run_with_conductor(db_session, tenant)
    p1, p2 = run["_project_ids"]

    await mark_chain_member_status(
        db_manager=None,
        tenant_manager=TenantManager(),
        project_id=p1,
        tenant_key=tenant,
        status="completed",
        test_session=db_session,
    )
    await mark_chain_member_status(
        db_manager=None,
        tenant_manager=TenantManager(),
        project_id=p2,
        tenant_key=tenant,
        status="implementing",
        test_session=db_session,
    )

    flipped = await complete_chain_run_if_finished(
        db_manager=None,
        tenant_manager=TenantManager(),
        conductor_agent_id=run["conductor_agent_id"],
        tenant_key=tenant,
        test_session=db_session,
    )
    assert flipped is False

    final = await _run_svc(db_session).get(run_id=run["id"], tenant_key=tenant)
    assert final["status"] != "completed", "run must NOT flip while a project is in flight"




async def test_complete_chain_run_if_finished_solo_noop(db_session: AsyncSession) -> None:
    tenant = TenantManager.generate_tenant_key()
    flipped = await complete_chain_run_if_finished(
        db_manager=None,
        tenant_manager=TenantManager(),
        conductor_agent_id=str(uuid.uuid4()),
        tenant_key=tenant,
        test_session=db_session,
    )
    assert flipped is False




async def test_c1_guard_message_no_terminate_chain(db_session: AsyncSession) -> None:
    tenant = TenantManager.generate_tenant_key()
    run = await _seed_run_with_conductor(db_session, tenant)
    p1, _p2 = run["_project_ids"]

    await mark_chain_member_status(
        db_manager=None,
        tenant_manager=TenantManager(),
        project_id=p1,
        tenant_key=tenant,
        status="completed",
        test_session=db_session,
    )

    job, execution = await _conductor_job_and_exec(db_session, tenant, run["conductor_agent_id"])

    with pytest.raises(ValidationError) as ei:
        await _completion_svc(db_session)._guard_conductor_chain_incomplete(
            db_session, job, execution, tenant, str(job.job_id)
        )

    assert ei.value.error_code == "CONDUCTOR_CHAIN_INCOMPLETE"
    message = str(ei.value)
    assert "TERMINATE_CHAIN" not in message, "dead TERMINATE_CHAIN prose must be gone"
    assert "Deactivate Chain" in message or "back-out" in message, "back-out guidance must be present"
