# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-9153 — chain-runtime settlement gate (two-phase closeout inside a chain).

Edition Scope: Both.

A findings-bearing chain link under closeout_mode='hitl' is accepted PROVISIONALLY
(its settlement approval is created WITHOUT parking the agent — the conductor
advances), and the chain's OWN closeout is held until every settlement approval is
decided. This exercises that at the chain-runtime layer:

* ``create_pending(park_execution=False)`` creates the settlement approval without
  flipping the agent to awaiting_user (provisional completion).
* ``complete_chain_run_if_finished`` HOLDS (returns False, does not purge) while a
  settlement approval for the run is pending — even though every project is terminal.
* deciding the last settlement approval (``mark_decided``) drains the queue and the
  run purges.

Parallel-safe: unique tenant per test, shared ``db_session`` rolled back at teardown.
"""

from __future__ import annotations

import random
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.models.agent_identity import AgentExecution, AgentJob
from giljo_mcp.models.products import Product
from giljo_mcp.models.projects import Project
from giljo_mcp.models.user_approval import UserApproval
from giljo_mcp.services.project_helpers import complete_chain_run_if_finished
from giljo_mcp.services.sequence_run_service import SequenceRunService
from giljo_mcp.services.user_approval_service import UserApprovalService
from giljo_mcp.tenant import TenantManager


pytestmark = pytest.mark.asyncio


def _run_svc(session: AsyncSession) -> SequenceRunService:
    return SequenceRunService(db_manager=None, tenant_manager=TenantManager(), session=session)


def _approval_svc(session: AsyncSession) -> UserApprovalService:
    return UserApprovalService(db_manager=None, tenant_manager=TenantManager(), test_session=session)


async def _seed_member(db_session, tenant_key: str) -> dict:
    """A chain-member project with an orchestrator (sub-orch) job + working execution."""
    # BE-9437: a project belongs to a product. Its own, so an active
    # seed cannot collide under idx_project_single_active_per_product.
    _owning_product_project = Product(
        id=str(uuid4()),
        tenant_key=tenant_key,
        name=f"Owning Product {uuid4().hex[:6]}",
        description="seeded",
        is_active=False,
    )
    db_session.add(_owning_product_project)
    project = Project(
        id=str(uuid4()),
        tenant_key=tenant_key,
        product_id=_owning_product_project.id,
        name=f"Link {uuid4().hex[:6]}",
        description="x",
        mission="x",
        status="active",
        execution_mode="claude_code_cli",
        series_number=random.randint(1, 9000),
    )
    db_session.add(project)
    db_session.info["tenant_key"] = tenant_key
    await db_session.flush()

    job = AgentJob(
        job_id=str(uuid4()),
        tenant_key=tenant_key,
        project_id=project.id,
        job_type="orchestrator",
        mission="x",
        status="active",
        created_at=datetime.now(UTC),
    )
    db_session.add(job)
    await db_session.flush()

    execution = AgentExecution(
        id=str(uuid4()),
        agent_id=str(uuid4()),
        job_id=job.job_id,
        tenant_key=tenant_key,
        agent_display_name="orchestrator",
        agent_name="orchestrator",
        status="working",
        started_at=datetime.now(UTC),
    )
    db_session.add(execution)
    await db_session.commit()
    return {"project": project, "job": job, "execution": execution}


async def _create_settlement_approval(db_session, tenant_key, member, run) -> UserApproval:
    return await _approval_svc(db_session).create_pending(
        tenant_key=tenant_key,
        job_id=member["job"].job_id,
        project_id=str(member["project"].id),
        reason="chain link closeout carries signal",
        options=[{"id": "approve", "label": "Approve"}, {"id": "reject", "label": "Rework"}],
        context={
            "closeout_gate": True,
            "chain_settlement": True,
            "sequence_run_id": str(run["id"]),
            "conductor_agent_id": run["conductor_agent_id"],
            "signal_reasons": ["1 deferred finding(s) awaiting a user decision"],
        },
        park_execution=False,
    )


async def _reload(db_session, tenant_key, execution_id) -> AgentExecution:
    return (
        await db_session.execute(
            select(AgentExecution).where(AgentExecution.tenant_key == tenant_key, AgentExecution.id == execution_id)
        )
    ).scalar_one()


async def test_settlement_approval_does_not_park_the_agent(db_session):
    """park_execution=False leaves the link agent free to complete (provisional)."""
    tenant = TenantManager.generate_tenant_key()
    member = await _seed_member(db_session, tenant)
    run = await _run_svc(db_session).create(
        project_ids=[member["project"].id],
        resolved_order=[member["project"].id],
        execution_mode="claude_code_cli",
        tenant_key=tenant,
    )

    approval = await _create_settlement_approval(db_session, tenant, member, run)

    assert approval.status == "pending"
    execution = await _reload(db_session, tenant, member["execution"].id)
    assert execution.status == "working", "settlement approval must NOT park the link agent (provisional completion)"


async def test_chain_closeout_held_then_drained_on_decide(db_session):
    """complete_chain_run_if_finished holds while a settlement approval is pending,
    and the run purges once it is decided (drain via mark_decided)."""
    tenant = TenantManager.generate_tenant_key()
    member = await _seed_member(db_session, tenant)
    run = await _run_svc(db_session).create(
        project_ids=[member["project"].id],
        resolved_order=[member["project"].id],
        execution_mode="claude_code_cli",
        tenant_key=tenant,
    )
    conductor = run["conductor_agent_id"]
    # Every project terminal (the link completed provisionally).
    await _run_svc(db_session).update(
        run_id=run["id"], tenant_key=tenant, project_statuses={str(member["project"].id): "completed"}
    )

    approval = await _create_settlement_approval(db_session, tenant, member, run)

    # HOLD: all projects terminal, but the settlement approval is still pending.
    held = await complete_chain_run_if_finished(
        db_manager=None,
        tenant_manager=TenantManager(),
        conductor_agent_id=conductor,
        tenant_key=tenant,
        test_session=db_session,
    )
    assert held is False, "chain closeout must be HELD while a settlement approval is pending"
    still_there = await _run_svc(db_session).find_active_run_for_conductor(
        conductor_agent_id=conductor, tenant_key=tenant
    )
    assert still_there is not None, "run must not be purged while settlement is pending"

    # DRAIN: deciding the last settlement approval re-triggers the chain closeout.
    await _approval_svc(db_session).mark_decided(
        tenant_key=tenant, approval_id=approval.id, option_id="approve", user_id=None
    )

    purged = await _run_svc(db_session).find_active_run_for_conductor(conductor_agent_id=conductor, tenant_key=tenant)
    assert purged is None, "run must purge once the last settlement approval is decided (drain)"
