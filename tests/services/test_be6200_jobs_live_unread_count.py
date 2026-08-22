# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-6200 (#3) — list_jobs "Messages Waiting" must EXCLUDE completion_reports.

The bug: JobQueryService.list_jobs surfaced the denormalized
``AgentExecution.messages_waiting_count`` column, which is incremented for the
auto-sent ``completion_report`` notifications agents fire on completion. A
completed sub-orchestrator whose ONLY waiting messages were completion_reports
therefore showed a phantom "N msgs" badge in the /jobs view (and, via
ProjectTabs orchMessagesWaiting, mis-timed the solo orch-unlocked banner
auto-clear).

Fix (failing layer = JobQueryService.list_jobs): read the LIVE pending count
(``get_live_unread_counts_by_project_agent``), which excludes completion_report
system notifications — the SAME "counts as unread work" definition the closeout
gate and receive_messages use.

SOLO IMPACT (validated here, not assumed inert): ProjectTabs derives
orchMessagesWaiting from this count; a completion_report-only orchestrator must
return 0 so the solo orch-unlocked banner auto-clears correctly — that timing
shift is the INTENDED behavior (completion_reports must not count as unread
anywhere).

DB-touching: db_session (TransactionalTestContext). No module-level mutable
state. Parallel-safe (pytest-xdist -n auto). Edition Scope: CE.
"""

from __future__ import annotations

import random
import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.models import AgentExecution, AgentJob, Message, Product, Project
from giljo_mcp.models.auth import User
from giljo_mcp.models.tasks import MessageRecipient
from giljo_mcp.repositories.agent_operations_repository import AgentOperationsRepository
from giljo_mcp.services.job_query_service import JobQueryService
from giljo_mcp.tenant import TenantManager


pytestmark = pytest.mark.asyncio


def _jobs_svc(session: AsyncSession) -> JobQueryService:
    return JobQueryService(db_manager=None, tenant_manager=TenantManager(), test_session=session)


async def _seed_project_with_two_agents(
    session: AsyncSession, tenant_key: str, *, orchestrator_status: str = "complete"
) -> tuple[str, AgentExecution, AgentExecution]:
    # BE-9437: a project belongs to a product. Its own, so an active
    # seed cannot collide under idx_project_single_active_per_product.
    _owning_product_proj = Product(
        id=str(uuid.uuid4()),
        tenant_key=tenant_key,
        name=f"Owning Product {uuid.uuid4().hex[:6]}",
        description="seeded",
        is_active=False,
    )
    session.add(_owning_product_proj)
    proj = Project(
        id=str(uuid.uuid4()),
        name="BE-6200 #3 project",
        description="unread exclusion",
        mission="unread exclusion mission",
        status="active",
        tenant_key=tenant_key,
        product_id=_owning_product_proj.id,
        execution_mode="multi_terminal",
        series_number=random.randint(1, 9000),
        created_at=datetime.now(UTC),
    )
    session.add(proj)
    await session.flush()

    execs: list[AgentExecution] = []
    for display_name, job_type in (("orchestrator", "orchestrator"), ("analyzer", "analyzer")):
        job = AgentJob(
            job_id=str(uuid.uuid4()),
            tenant_key=tenant_key,
            project_id=proj.id,
            job_type=job_type,
            mission=f"mission {display_name}",
            status="active",
        )
        session.add(job)
        ex = AgentExecution(
            job_id=job.job_id,
            tenant_key=tenant_key,
            agent_display_name=display_name,
            status=orchestrator_status if display_name == "orchestrator" else "working",
            messages_sent_count=0,
            messages_waiting_count=0,
            messages_read_count=0,
        )
        session.add(ex)
        execs.append(ex)
    await session.flush()
    for ex in execs:
        await session.refresh(ex)
    return proj.id, execs[0], execs[1]


async def _send(
    session: AsyncSession,
    tenant_key: str,
    project_id: str,
    from_agent: AgentExecution,
    to_agent: AgentExecution,
    n: int,
    *,
    message_type: str,
) -> None:
    for i in range(n):
        msg = Message(
            tenant_key=tenant_key,
            project_id=project_id,
            content=f"{message_type} {i}",
            message_type=message_type,
            status="pending",
            from_agent_id=str(from_agent.agent_id),
        )
        session.add(msg)
        await session.flush()
        session.add(MessageRecipient(message_id=msg.id, agent_id=to_agent.agent_id, tenant_key=tenant_key))
    await session.flush()


def _waiting_for(jobs: list[dict], agent_id: str) -> int:
    for job in jobs:
        if job["agent_id"] == agent_id:
            return job["messages_waiting_count"]
    raise AssertionError(f"agent {agent_id} not present in list_jobs output")


async def test_list_jobs_excludes_completion_reports_from_waiting_count(db_session: AsyncSession) -> None:
    """A completion_report-only orchestrator returns 0 (the SOLO regression assertion)."""
    tenant = TenantManager.generate_tenant_key()
    pid, orchestrator, analyzer = await _seed_project_with_two_agents(db_session, tenant)

    # 3 completion_reports addressed to the orchestrator, and the denormalized column
    # deliberately drifted to a wrong, inflated value (what the OLD code surfaced).
    await _send(db_session, tenant, pid, analyzer, orchestrator, 3, message_type="completion_report")
    orchestrator.messages_waiting_count = 99
    await db_session.flush()

    result = await _jobs_svc(db_session).list_jobs(tenant_key=tenant, project_id=pid)
    assert _waiting_for(result.jobs, orchestrator.agent_id) == 0, (
        "completion_report-only orchestrator must show 0 waiting (not the inflated 99); "
        "this is the intended solo auto-clear behavior"
    )


async def test_list_jobs_counts_real_directives_not_completion_reports(db_session: AsyncSession) -> None:
    """Real directives still count; completion_reports mixed in are excluded.

    BE-9491: the orchestrator here is seeded LIVE ('blocked'), not 'complete' --
    this test's concern is message TYPE filtering (directive vs completion_report),
    which is orthogonal to recipient liveness. A 'complete' recipient's real
    directives are now EXCLUDED too (see
    test_terminal_orchestrator_real_broadcast_now_shows_zero_unread below) --
    that is the intended BE-9491 fix, not a regression of this test.
    """
    tenant = TenantManager.generate_tenant_key()
    pid, orchestrator, analyzer = await _seed_project_with_two_agents(db_session, tenant, orchestrator_status="blocked")

    await _send(db_session, tenant, pid, analyzer, orchestrator, 2, message_type="directive")
    await _send(db_session, tenant, pid, analyzer, orchestrator, 3, message_type="completion_report")
    orchestrator.messages_waiting_count = 99
    await db_session.flush()

    result = await _jobs_svc(db_session).list_jobs(tenant_key=tenant, project_id=pid)
    assert _waiting_for(result.jobs, orchestrator.agent_id) == 2, (
        "only the 2 real directives count as unread work; the 3 completion_reports are excluded"
    )


async def test_terminal_orchestrator_real_broadcast_now_shows_zero_unread(db_session: AsyncSession) -> None:
    """BE-9491: a COMPLETE orchestrator's genuinely-unread broadcast (not a
    completion_report -- this is the exact 3,503-shape bug) must now show 0,
    WITHOUT deleting or touching the seeded ``message_recipients`` row
    (forward-only, no backfill, no migration)."""
    tenant = TenantManager.generate_tenant_key()
    pid, orchestrator, analyzer = await _seed_project_with_two_agents(db_session, tenant)  # orchestrator: 'complete'

    await _send(db_session, tenant, pid, analyzer, orchestrator, 1, message_type="broadcast")
    await db_session.flush()

    row_count_before = (
        await db_session.execute(
            select(func.count(MessageRecipient.id)).where(MessageRecipient.agent_id == orchestrator.agent_id)
        )
    ).scalar_one()
    assert row_count_before == 1  # the phantom row exists, exactly like the 3,503

    result = await _jobs_svc(db_session).list_jobs(tenant_key=tenant, project_id=pid)
    assert _waiting_for(result.jobs, orchestrator.agent_id) == 0, (
        "a finished agent's genuinely-unread broadcast must no longer count"
    )

    row_count_after = (
        await db_session.execute(
            select(func.count(MessageRecipient.id)).where(MessageRecipient.agent_id == orchestrator.agent_id)
        )
    ).scalar_one()
    assert row_count_after == row_count_before, "the read-side fix must not touch the underlying row"


async def test_human_user_recipient_unread_count_unaffected_by_terminal_clause(db_session: AsyncSession) -> None:
    """Two-EXISTS regression guard (Risk #1 in the BE-9491 project description):
    ``MessageRecipient.agent_id`` also holds a directed post's HUMAN user_id. A
    naive single-EXISTS liveness clause would be vacuously "terminal" for a
    human (zero AgentExecution rows) and silently zero the operator's own
    unread badge -- this must never happen."""
    tenant = TenantManager.generate_tenant_key()
    pid, orchestrator, _analyzer = await _seed_project_with_two_agents(db_session, tenant)
    user = User(id=str(uuid.uuid4()), tenant_key=tenant, username=f"operator_{uuid.uuid4().hex[:6]}")
    db_session.add(user)
    await db_session.flush()

    msg = Message(
        tenant_key=tenant,
        project_id=pid,
        content="direct to the operator",
        message_type="direct",
        status="pending",
        from_agent_id=str(orchestrator.agent_id),
    )
    db_session.add(msg)
    await db_session.flush()
    db_session.add(MessageRecipient(message_id=msg.id, agent_id=user.id, tenant_key=tenant))
    await db_session.flush()

    counts = await AgentOperationsRepository().get_live_unread_counts_by_agent(db_session, tenant, pid, [user.id])
    assert counts.get(user.id, 0) == 1, "a human user_id recipient must never be zeroed by the terminal-agent clause"
