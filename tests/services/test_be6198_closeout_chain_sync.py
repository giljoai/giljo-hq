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

from giljo_mcp.exceptions import ResourceNotFoundError
from giljo_mcp.models import Product, Project
from giljo_mcp.services.job_completion_service import JobCompletionService
from giljo_mcp.services.project_helpers import complete_chain_run_if_finished
from giljo_mcp.services.sequence_run_service import SequenceRunService
from giljo_mcp.services.workflow_status_service import WorkflowStatusService
from giljo_mcp.tenant import TenantManager
from giljo_mcp.tools.project_closeout import close_project_and_update_memory


pytestmark = pytest.mark.asyncio


_DB_MANAGER_SENTINEL = object()




async def _seed_project(session: AsyncSession, tenant_key: str, product_id: str | None = None) -> str:
    if product_id is None:
        product = Product(
            id=str(uuid.uuid4()),
            name=f"BE-6198 Product {uuid.uuid4().hex[:6]}",
            description="Chain product.",
            tenant_key=tenant_key,
            is_active=False,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        session.add(product)
        await session.flush()
        product_id = product.id
    project = Project(
        id=str(uuid.uuid4()),
        name=f"BE-6198 {uuid.uuid4().hex[:6]}",
        description="Chain member.",
        mission="Be a chain member.",
        status="active",
        tenant_key=tenant_key,
        product_id=product_id,
        series_number=1,
        execution_mode="claude_code_cli",
        created_at=datetime.now(UTC),
    )
    session.add(project)
    session.info["tenant_key"] = tenant_key
    await session.flush()
    return project.id


def _run_svc(session: AsyncSession) -> SequenceRunService:
    return SequenceRunService(db_manager=None, tenant_manager=TenantManager(), session=session)


def _completion_svc(session: AsyncSession) -> JobCompletionService:
    return JobCompletionService(db_manager=None, tenant_manager=TenantManager(), test_session=session)


def _workflow_svc(session: AsyncSession) -> WorkflowStatusService:
    return WorkflowStatusService(db_manager=None, tenant_manager=TenantManager(), test_session=session)


async def _seed_two_project_run(session: AsyncSession, tenant_key: str) -> dict:
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


async def _conductor_job_and_exec(session: AsyncSession, tenant_key: str, conductor_agent_id: str):
    from giljo_mcp.models.agent_identity import AgentExecution, AgentJob

    execution = (
        await session.execute(
            select(AgentExecution).where(
                AgentExecution.tenant_key == tenant_key,
                AgentExecution.agent_id == conductor_agent_id,
            )
        )
    ).scalar_one()
    job = (
        await session.execute(
            select(AgentJob).where(
                AgentJob.tenant_key == tenant_key,
                AgentJob.job_id == execution.job_id,
            )
        )
    ).scalar_one()
    return job, execution


async def _reload_project(session: AsyncSession, project_id: str, tenant_key: str) -> Project:
    return (
        await session.execute(select(Project).where(Project.id == project_id, Project.tenant_key == tenant_key))
    ).scalar_one()




async def test_chain_member_closeout_stamps_signals(db_session: AsyncSession) -> None:
    tenant = TenantManager.generate_tenant_key()
    run = await _seed_two_project_run(db_session, tenant)
    p1, _p2 = run["_project_ids"]

    result = await close_project_and_update_memory(
        project_id=p1,
        summary="done",
        key_outcomes=["x"],
        decisions_made=["y"],
        tenant_key=tenant,
        db_manager=_DB_MANAGER_SENTINEL,
        session=db_session,
        force=True,
    )

    message = result["message"]
    assert "archive" not in message.lower(), (
        f"a chain member's closeout already flipped its status -- the solo-only Archive "
        f"remedy must not appear here: {message!r}"
    )

    reloaded = await _reload_project(db_session, p1, tenant)
    assert reloaded.closeout_executed_at is not None, "the real closeout must stamp closeout_executed_at"

    refetched = await _run_svc(db_session).find_active_run_for_project(project_id=p1, tenant_key=tenant)
    assert refetched is not None
    assert refetched["project_statuses"][p1] == "completed", (
        "the real closeout must mark the chain member completed in the run"
    )

    status = await _workflow_svc(db_session).get_workflow_status(project_id=p1, tenant_key=tenant)
    assert status.project_closeout_at is not None, "project_closeout_at must surface for the conductor's drive loop"

    assert reloaded.status == "completed", "chain member closeout must flip the project row to completed"
    assert reloaded.completed_at is not None, "chain member closeout must stamp completed_at"




async def test_all_chain_members_end_completed(db_session: AsyncSession) -> None:
    tenant = TenantManager.generate_tenant_key()
    run = await _seed_two_project_run(db_session, tenant)
    p1, p2 = run["_project_ids"]

    for pid in (p1, p2):
        await close_project_and_update_memory(
            project_id=pid,
            summary="done",
            key_outcomes=["x"],
            decisions_made=["y"],
            tenant_key=tenant,
            db_manager=_DB_MANAGER_SENTINEL,
            session=db_session,
            force=True,
        )

    for pid in (p1, p2):
        reloaded = await _reload_project(db_session, pid, tenant)
        assert reloaded.status == "completed", f"every chain member must end completed (project {pid})"
        assert reloaded.completed_at is not None




async def test_final_closeout_lets_conductor_complete(db_session: AsyncSession) -> None:
    tenant = TenantManager.generate_tenant_key()
    run = await _seed_two_project_run(db_session, tenant)
    p1, p2 = run["_project_ids"]
    conductor_agent_id = run["conductor_agent_id"]

    for pid in (p1, p2):
        await close_project_and_update_memory(
            project_id=pid,
            summary="done",
            key_outcomes=["x"],
            decisions_made=["y"],
            tenant_key=tenant,
            db_manager=_DB_MANAGER_SENTINEL,
            session=db_session,
            force=True,
        )

    job, execution = await _conductor_job_and_exec(db_session, tenant, conductor_agent_id)
    await _completion_svc(db_session)._guard_conductor_chain_incomplete(
        db_session, job, execution, tenant, str(job.job_id)
    )

    purged = await complete_chain_run_if_finished(
        db_manager=None,
        tenant_manager=TenantManager(),
        conductor_agent_id=conductor_agent_id,
        tenant_key=tenant,
        test_session=db_session,
    )
    assert purged is True, "complete_chain_run_if_finished must purge the run once all members closed"

    with pytest.raises(ResourceNotFoundError):
        await _run_svc(db_session).get(run_id=run["id"], tenant_key=tenant)




async def test_solo_closeout_unchanged(db_session: AsyncSession) -> None:
    tenant = TenantManager.generate_tenant_key()
    p_solo = await _seed_project(db_session, tenant)

    result = await close_project_and_update_memory(
        project_id=p_solo,
        summary="solo done",
        key_outcomes=["x"],
        decisions_made=["y"],
        tenant_key=tenant,
        db_manager=_DB_MANAGER_SENTINEL,
        session=db_session,
        force=True,
    )
    assert result["message"], "solo closeout must return the normal success response"

    reloaded = await _reload_project(db_session, p_solo, tenant)
    assert reloaded.closeout_executed_at is not None, "closeout_executed_at is stamped even for solo (inert)"

    assert reloaded.status == "active", "solo closeout must NOT flip status (stays whatever it was)"

    assert reloaded.completed_at is not None, "BE-9343: a solo closeout stamps completed_at"

    run = await _run_svc(db_session).find_active_run_for_project(project_id=p_solo, tenant_key=tenant)
    assert run is None, "a solo project must have no active run to touch"
