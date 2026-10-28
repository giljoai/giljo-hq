# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import random
import uuid
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.database import tenant_isolation_bypass
from giljo_mcp.exceptions import GateRefusalError
from giljo_mcp.models import Product, Project
from giljo_mcp.models.agent_identity import AgentExecution, AgentJob
from giljo_mcp.models.sequence_runs import SequenceRun
from giljo_mcp.services.job_completion_service import JobCompletionService
from giljo_mcp.services.project_service import ProjectService
from giljo_mcp.services.sequence_run_service import SequenceRunService
from giljo_mcp.tenant import TenantManager, current_tenant


pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture(autouse=True)
async def _wipe_sequence_runs(db_manager):
    yield
    async with db_manager.get_session_async() as session:
        with tenant_isolation_bypass(session, reason="test teardown: wipe sequence_runs", models=(SequenceRun,)):
            await session.execute(delete(SequenceRun))
        await session.commit()


@pytest_asyncio.fixture
async def chain(db_manager, db_session: AsyncSession):
    tenant = TenantManager.generate_tenant_key()
    product = Product(
        id=str(uuid.uuid4()),
        name=f"BE-9833 {uuid.uuid4().hex[:6]}",
        description="chain product",
        tenant_key=tenant,
        is_active=False,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    db_session.add(product)
    await db_session.flush()
    ids: list[str] = []
    for n, status in enumerate(("completed", "active", "inactive"), start=1):
        project = Project(
            id=str(uuid.uuid4()),
            name=f"BE-9833 member {n}",
            description="member",
            mission="member mission",
            status=status,
            tenant_key=tenant,
            product_id=product.id,
            series_number=random.randint(1, 9000),
            execution_mode="claude_code_cli",
            created_at=datetime.now(UTC),
        )
        db_session.add(project)
        ids.append(project.id)
    db_session.info["tenant_key"] = tenant
    await db_session.flush()

    manager = TenantManager()
    manager.set_current_tenant(tenant)
    token = current_tenant.set(tenant)
    run_svc = SequenceRunService(db_manager=None, tenant_manager=manager, session=db_session)
    run = await run_svc.create(
        project_ids=ids,
        resolved_order=ids,
        execution_mode="claude_code_cli",
        tenant_key=tenant,
    )
    run = await run_svc.update(
        run_id=run["id"],
        tenant_key=tenant,
        status="running",
        current_index=1,
        project_statuses={ids[0]: "completed", ids[1]: "implementing", ids[2]: "pending"},
    )
    svc = ProjectService(db_manager=db_manager, tenant_manager=manager, test_session=db_session)
    try:
        yield {"svc": svc, "run_svc": run_svc, "run": run, "ids": ids, "tenant": tenant, "session": db_session}
    finally:
        current_tenant.reset(token)


async def _conductor_guard(ctx: dict) -> None:
    session = ctx["session"]
    execution = (
        await session.execute(
            select(AgentExecution).where(
                AgentExecution.tenant_key == ctx["tenant"],
                AgentExecution.agent_id == ctx["run"]["conductor_agent_id"],
            )
        )
    ).scalar_one()
    job = (
        await session.execute(
            select(AgentJob).where(AgentJob.tenant_key == ctx["tenant"], AgentJob.job_id == execution.job_id)
        )
    ).scalar_one()
    completion = JobCompletionService(db_manager=None, tenant_manager=TenantManager(), test_session=session)
    await completion._guard_conductor_chain_incomplete(session, job, execution, ctx["tenant"], str(job.job_id))


async def _run(ctx: dict) -> dict:
    return await ctx["run_svc"].get(run_id=ctx["run"]["id"], tenant_key=ctx["tenant"])


async def _finish(ctx: dict, project_id: str) -> None:
    run = await _run(ctx)
    statuses = {**run["project_statuses"], project_id: "completed"}
    await ctx["run_svc"].update(run_id=run["id"], tenant_key=ctx["tenant"], project_statuses=statuses)


async def test_parked_tail_member_no_longer_blocks_the_conductor(chain) -> None:
    _p1, p2, p3 = chain["ids"]
    await _finish(chain, p2)
    await chain["svc"].update_project(project_id=p3, updates={"status": "parked"})

    await _conductor_guard(chain)

    run = await _run(chain)
    assert run["project_statuses"][p3] == "detached"
    assert run["status"] == "running"


async def test_parked_in_flight_member_opens_next_gate_and_chain_continues(chain) -> None:
    _p1, p2, p3 = chain["ids"]
    await chain["svc"].update_project(project_id=p2, updates={"status": "parked"})

    run = await _run(chain)
    assert run["project_statuses"][p2] == "detached"
    assert run["current_index"] == 2
    assert run["status"] == "running"
    nxt = (await chain["session"].execute(select(Project).where(Project.id == p3))).scalar_one()
    assert nxt.implementation_launched_at is not None, "the next member's gate must open as on a closeout"

    await _finish(chain, p3)
    await _conductor_guard(chain)


async def test_parking_a_member_not_yet_reached_keeps_the_in_flight_index(chain) -> None:
    _p1, _p2, p3 = chain["ids"]
    await chain["svc"].update_project(project_id=p3, updates={"status": "parked"})

    run = await _run(chain)
    assert run["project_statuses"][p3] == "detached"
    assert run["current_index"] == 1, "detaching a future member must not skip the in-flight one"
    with pytest.raises(GateRefusalError):
        await _conductor_guard(chain)


async def test_cancelled_and_superseded_doors_detach(chain) -> None:
    p1, p2, p3 = chain["ids"]
    await chain["svc"].lifecycle.cancel_project(p2, tenant_key=chain["tenant"], reason="no longer needed")
    await chain["svc"].update_project(project_id=p3, updates={"status": "superseded", "successor_project_id": p1})

    run = await _run(chain)
    assert run["project_statuses"][p2] == "detached"
    assert run["project_statuses"][p3] == "detached"
    await _conductor_guard(chain)


async def test_delete_door_detaches_instead_of_cancelling_the_run(chain) -> None:
    _p1, _p2, p3 = chain["ids"]
    await chain["svc"].deletion.delete_project(p3)

    run = await _run(chain)
    assert run["status"] == "running"
    assert run["project_statuses"][p3] == "detached"


async def test_detached_project_keeps_its_own_row(chain) -> None:
    _p1, _p2, p3 = chain["ids"]
    await chain["svc"].update_project(project_id=p3, updates={"status": "parked"})

    row = (await chain["session"].execute(select(Project).where(Project.id == p3))).scalar_one()
    assert row.status == "parked"
    assert row.mission == "member mission"
    assert row.description == "member"


async def test_detach_is_idempotent_and_never_overwrites_a_completed_member(chain) -> None:
    p1, p2, p3 = chain["ids"]
    await chain["svc"].update_project(project_id=p3, updates={"status": "parked"})
    await chain["svc"].update_project(project_id=p3, updates={"status": "superseded", "successor_project_id": p1})
    assert (await _run(chain))["project_statuses"][p3] == "detached"

    await chain["svc"].update_project(project_id=p1, updates={"status": "superseded", "successor_project_id": p2})
    assert (await _run(chain))["project_statuses"][p1] == "completed"


async def test_stuck_run_with_already_parked_member_heals_on_the_conductor_check(chain) -> None:
    _p1, p2, p3 = chain["ids"]
    await _finish(chain, p2)
    rows = (await chain["session"].execute(select(Project).where(Project.id == p3))).scalar_one()
    rows.status = "parked"
    await chain["session"].flush()
    assert (await _run(chain))["project_statuses"][p3] == "pending"

    await _conductor_guard(chain)

    assert (await _run(chain))["project_statuses"][p3] == "detached"


async def test_pending_run_membership_is_left_alone(chain) -> None:
    p1, p2, p3 = chain["ids"]
    await chain["run_svc"].update(
        run_id=chain["run"]["id"],
        tenant_key=chain["tenant"],
        status="pending",
        project_statuses={p1: "pending", p2: "pending", p3: "pending"},
    )
    await chain["svc"].update_project(project_id=p3, updates={"status": "parked"})

    assert (await _run(chain))["project_statuses"][p3] == "pending"
