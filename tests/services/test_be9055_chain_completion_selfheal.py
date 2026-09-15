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
from giljo_mcp.services.job_completion_service import JobCompletionService
from giljo_mcp.services.project_helpers import complete_chain_run_if_finished
from giljo_mcp.services.sequence_run_service import SequenceRunService
from giljo_mcp.tenant import TenantManager
from giljo_mcp.tools.project_closeout import close_project_and_update_memory


pytestmark = pytest.mark.asyncio

_DB_MANAGER_SENTINEL = object()


async def _seed_project(session: AsyncSession, tenant_key: str) -> str:
    product = Product(
        id=str(uuid.uuid4()),
        name=f"BE-9055 Product {uuid.uuid4().hex[:6]}",
        description="Chain product.",
        tenant_key=tenant_key,
        is_active=False,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    session.add(product)
    await session.flush()
    project = Project(
        id=str(uuid.uuid4()),
        name=f"BE-9055 {uuid.uuid4().hex[:6]}",
        description="Chain member.",
        mission="Be a chain member.",
        status="active",
        tenant_key=tenant_key,
        product_id=product.id,
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


async def _close_member(session: AsyncSession, project_id: str, tenant_key: str) -> None:
    await close_project_and_update_memory(
        project_id=project_id,
        summary="done",
        key_outcomes=["x"],
        decisions_made=["y"],
        tenant_key=tenant_key,
        db_manager=_DB_MANAGER_SENTINEL,
        session=session,
        force=True,
    )


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


async def _corrupt_copy(session: AsyncSession, run: dict, tenant_key: str, statuses: dict) -> None:
    await _run_svc(session).update(
        run_id=run["id"],
        tenant_key=tenant_key,
        project_statuses=statuses,
    )




async def test_guard_heals_stale_copy_and_allows_completion(db_session: AsyncSession) -> None:
    tenant = TenantManager.generate_tenant_key()
    run = await _seed_two_project_run(db_session, tenant)
    p1, p2 = run["_project_ids"]

    for pid in (p1, p2):
        await _close_member(db_session, pid, tenant)

    await _corrupt_copy(db_session, run, tenant, {p1: "completed", p2: "implementing"})

    job, execution = await _conductor_job_and_exec(db_session, tenant, run["conductor_agent_id"])
    await _completion_svc(db_session)._guard_conductor_chain_incomplete(
        db_session, job, execution, tenant, str(job.job_id)
    )

    refetched = await _run_svc(db_session).get(run_id=run["id"], tenant_key=tenant)
    assert refetched["project_statuses"][p2] == "completed", "the guard must repair the stale copy, not just bypass it"


async def test_guard_heals_missing_copy_entry(db_session: AsyncSession) -> None:
    tenant = TenantManager.generate_tenant_key()
    run = await _seed_two_project_run(db_session, tenant)
    p1, p2 = run["_project_ids"]

    for pid in (p1, p2):
        await _close_member(db_session, pid, tenant)

    await _corrupt_copy(db_session, run, tenant, {p1: "completed"})

    job, execution = await _conductor_job_and_exec(db_session, tenant, run["conductor_agent_id"])
    await _completion_svc(db_session)._guard_conductor_chain_incomplete(
        db_session, job, execution, tenant, str(job.job_id)
    )


async def test_guard_proceeds_when_persisting_healed_copy_fails(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    tenant = TenantManager.generate_tenant_key()
    run = await _seed_two_project_run(db_session, tenant)
    p1, p2 = run["_project_ids"]

    for pid in (p1, p2):
        await _close_member(db_session, pid, tenant)
    await _corrupt_copy(db_session, run, tenant, {p1: "completed", p2: "implementing"})

    async def _boom(self, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003
        raise RuntimeError("persist of healed statuses failed")

    monkeypatch.setattr(SequenceRunService, "update", _boom)

    job, execution = await _conductor_job_and_exec(db_session, tenant, run["conductor_agent_id"])
    await _completion_svc(db_session)._guard_conductor_chain_incomplete(
        db_session, job, execution, tenant, str(job.job_id)
    )




async def test_purge_heals_stale_copy_and_completes_run(db_session: AsyncSession) -> None:
    tenant = TenantManager.generate_tenant_key()
    run = await _seed_two_project_run(db_session, tenant)
    p1, p2 = run["_project_ids"]

    for pid in (p1, p2):
        await _close_member(db_session, pid, tenant)

    await _corrupt_copy(db_session, run, tenant, {p1: "completed", p2: "implementing"})

    purged = await complete_chain_run_if_finished(
        db_manager=None,
        tenant_manager=TenantManager(),
        conductor_agent_id=run["conductor_agent_id"],
        tenant_key=tenant,
        test_session=db_session,
    )
    assert purged is True, "a stale copy must not stop a really-finished chain from completing"

    with pytest.raises(ResourceNotFoundError):
        await _run_svc(db_session).get(run_id=run["id"], tenant_key=tenant)




async def test_guard_still_blocks_genuinely_incomplete_chain(db_session: AsyncSession) -> None:
    tenant = TenantManager.generate_tenant_key()
    run = await _seed_two_project_run(db_session, tenant)
    p1, _p2 = run["_project_ids"]

    await _close_member(db_session, p1, tenant)

    job, execution = await _conductor_job_and_exec(db_session, tenant, run["conductor_agent_id"])
    with pytest.raises(ValidationError) as ei:
        await _completion_svc(db_session)._guard_conductor_chain_incomplete(
            db_session, job, execution, tenant, str(job.job_id)
        )
    assert ei.value.error_code == "CONDUCTOR_CHAIN_INCOMPLETE"

    purged = await complete_chain_run_if_finished(
        db_manager=None,
        tenant_manager=TenantManager(),
        conductor_agent_id=run["conductor_agent_id"],
        tenant_key=tenant,
        test_session=db_session,
    )
    assert purged is False, "an in-flight chain must not be purged by the self-heal"




async def test_soft_deleted_member_heals_to_terminated(db_session: AsyncSession) -> None:
    tenant = TenantManager.generate_tenant_key()
    run = await _seed_two_project_run(db_session, tenant)
    p1, p2 = run["_project_ids"]

    await _close_member(db_session, p1, tenant)

    p2_row = (
        await db_session.execute(select(Project).where(Project.id == p2, Project.tenant_key == tenant))
    ).scalar_one()
    p2_row.deleted_at = datetime.now(UTC)
    await db_session.flush()

    job, execution = await _conductor_job_and_exec(db_session, tenant, run["conductor_agent_id"])
    await _completion_svc(db_session)._guard_conductor_chain_incomplete(
        db_session, job, execution, tenant, str(job.job_id)
    )

    refetched = await _run_svc(db_session).get(run_id=run["id"], tenant_key=tenant)
    assert refetched["project_statuses"][p2] == "terminated", (
        "a soft-deleted member must heal to a terminal token the copy validator accepts"
    )
