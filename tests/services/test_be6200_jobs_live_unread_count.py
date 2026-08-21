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
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.models import AgentExecution, AgentJob, Message, Product, Project
from giljo_mcp.models.tasks import MessageRecipient
from giljo_mcp.services.job_query_service import JobQueryService
from giljo_mcp.tenant import TenantManager


pytestmark = pytest.mark.asyncio


def _jobs_svc(session: AsyncSession) -> JobQueryService:
    return JobQueryService(db_manager=None, tenant_manager=TenantManager(), test_session=session)


async def _seed_project_with_two_agents(
    session: AsyncSession, tenant_key: str
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
            status="complete" if display_name == "orchestrator" else "working",
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
    """Real directives still count; completion_reports mixed in are excluded."""
    tenant = TenantManager.generate_tenant_key()
    pid, orchestrator, analyzer = await _seed_project_with_two_agents(db_session, tenant)

    await _send(db_session, tenant, pid, analyzer, orchestrator, 2, message_type="directive")
    await _send(db_session, tenant, pid, analyzer, orchestrator, 3, message_type="completion_report")
    orchestrator.messages_waiting_count = 99
    await db_session.flush()

    result = await _jobs_svc(db_session).list_jobs(tenant_key=tenant, project_id=pid)
    assert _waiting_for(result.jobs, orchestrator.agent_id) == 2, (
        "only the 2 real directives count as unread work; the 3 completion_reports are excluded"
    )
