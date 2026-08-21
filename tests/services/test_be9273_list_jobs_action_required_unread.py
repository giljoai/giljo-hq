# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-9273 item 3 (backend half) -- ``JobQueryService.list_jobs`` must surface
``action_required_unread`` per job so the dashboard AgentRow badge can
distinguish "someone is waiting on THIS agent" from plain unread mail.

Root cause: the field already existed on the agent-facing
``AgentWorkflowDetail`` schema (``workflow_status_service.get_workflow_status``,
BE-9242 deliverable #3), but the dashboard's REST job list
(``JobQueryService.list_jobs`` -> ``GET /api/agent-jobs/``, the endpoint
``agentJobsStore.js`` actually polls) never computed or returned it -- so the
frontend had no field to bind a distinct badge to.

Fix (failing layer = JobQueryService.list_jobs, mirrors the existing
``messages_waiting_count`` / ``get_live_unread_counts_by_project_agent``
precedent from BE-6200 exactly): a new multi-project sibling repository method
``get_live_action_required_unread_counts_by_project_agent`` (same
requires_action=True + auto_generated=False + not-yet-acked definition as the
single-project ``get_live_action_required_unread_counts_by_agent`` the MCP
``get_workflow_status`` tool already uses) is threaded into ``list_jobs`` and
surfaced as ``job["action_required_unread"]``.

DB-touching: db_session (TransactionalTestContext). No module-level mutable
state. Parallel-safe (pytest-xdist -n auto). Edition Scope: Both (CE
dashboard core).
"""

from __future__ import annotations

import random
import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.database import tenant_session_context
from giljo_mcp.models import AgentExecution, AgentJob, Message, Product, Project
from giljo_mcp.models.tasks import MessageRecipient
from giljo_mcp.repositories.agent_operations_repository import AgentOperationsRepository
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
        name="BE-9273 action_required_unread project",
        description="action_required_unread wiring",
        mission="action_required_unread wiring mission",
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
    requires_action: bool,
    auto_generated: bool = False,
) -> None:
    for i in range(n):
        msg = Message(
            tenant_key=tenant_key,
            project_id=project_id,
            content=f"msg {i} requires_action={requires_action} auto_generated={auto_generated}",
            message_type="direct",
            status="pending",
            from_agent_id=str(from_agent.agent_id),
            requires_action=requires_action,
            auto_generated=auto_generated,
        )
        session.add(msg)
        await session.flush()
        session.add(MessageRecipient(message_id=msg.id, agent_id=to_agent.agent_id, tenant_key=tenant_key))
    await session.flush()


def _job_for(jobs: list[dict], agent_id: str) -> dict:
    for job in jobs:
        if job["agent_id"] == agent_id:
            return job
    raise AssertionError(f"agent {agent_id} not present in list_jobs output")


async def test_list_jobs_surfaces_action_required_unread_for_directed_action_message(
    db_session: AsyncSession,
) -> None:
    """A directed, requires_action, non-auto_generated post counts toward
    BOTH messages_waiting_count and action_required_unread."""
    tenant = TenantManager.generate_tenant_key()
    pid, orchestrator, analyzer = await _seed_project_with_two_agents(db_session, tenant)

    await _send(db_session, tenant, pid, analyzer, orchestrator, 2, requires_action=True)

    result = await _jobs_svc(db_session).list_jobs(tenant_key=tenant, project_id=pid)
    job = _job_for(result.jobs, orchestrator.agent_id)
    assert job["messages_waiting_count"] == 2
    assert job["action_required_unread"] == 2


async def test_list_jobs_excludes_informational_from_action_required_unread(db_session: AsyncSession) -> None:
    """An informational (requires_action=False) post counts toward the broader
    badge (messages_waiting_count) but NOT toward action_required_unread --
    matching the closeout gate's own definition of "blocking work"."""
    tenant = TenantManager.generate_tenant_key()
    pid, orchestrator, analyzer = await _seed_project_with_two_agents(db_session, tenant)

    await _send(db_session, tenant, pid, analyzer, orchestrator, 3, requires_action=False)

    result = await _jobs_svc(db_session).list_jobs(tenant_key=tenant, project_id=pid)
    job = _job_for(result.jobs, orchestrator.agent_id)
    assert job["messages_waiting_count"] == 3, "informational posts still count toward the broader badge"
    assert job["action_required_unread"] == 0, "informational posts must NOT inflate the blocking subset"


async def test_list_jobs_excludes_auto_generated_from_action_required_unread(db_session: AsyncSession) -> None:
    """A requires_action=True but auto_generated=True post (e.g. a forwarded
    system notice) still counts toward messages_waiting_count but NOT toward
    action_required_unread -- mirrors get_unread_messages_for_agent's gate
    definition exactly."""
    tenant = TenantManager.generate_tenant_key()
    pid, orchestrator, analyzer = await _seed_project_with_two_agents(db_session, tenant)

    await _send(db_session, tenant, pid, analyzer, orchestrator, 1, requires_action=True, auto_generated=True)

    result = await _jobs_svc(db_session).list_jobs(tenant_key=tenant, project_id=pid)
    job = _job_for(result.jobs, orchestrator.agent_id)
    assert job["messages_waiting_count"] == 1
    assert job["action_required_unread"] == 0, "auto_generated posts must not count as genuinely actionable"


async def test_list_jobs_action_required_unread_is_a_subset_never_exceeding_waiting_count(
    db_session: AsyncSession,
) -> None:
    """Mixed inbox: 1 real directive + 1 informational + 1 auto_generated
    directive -- action_required_unread must equal exactly the 1 genuinely
    actionable post, never more than messages_waiting_count."""
    tenant = TenantManager.generate_tenant_key()
    pid, orchestrator, analyzer = await _seed_project_with_two_agents(db_session, tenant)

    await _send(db_session, tenant, pid, analyzer, orchestrator, 1, requires_action=True)
    await _send(db_session, tenant, pid, analyzer, orchestrator, 1, requires_action=False)
    await _send(db_session, tenant, pid, analyzer, orchestrator, 1, requires_action=True, auto_generated=True)

    result = await _jobs_svc(db_session).list_jobs(tenant_key=tenant, project_id=pid)
    job = _job_for(result.jobs, orchestrator.agent_id)
    assert job["messages_waiting_count"] == 3
    assert job["action_required_unread"] == 1
    assert job["action_required_unread"] <= job["messages_waiting_count"]


async def test_list_jobs_zero_action_required_unread_for_project_less_row(db_session: AsyncSession) -> None:
    """A project-less row (e.g. the chain conductor) must resolve to 0, same
    as messages_waiting_count already does -- never a KeyError/None."""
    tenant = TenantManager.generate_tenant_key()
    job = AgentJob(
        job_id=str(uuid.uuid4()),
        tenant_key=tenant,
        project_id=None,
        job_type="orchestrator",
        mission="project-less conductor",
        status="active",
    )
    db_session.add(job)
    ex = AgentExecution(
        job_id=job.job_id,
        tenant_key=tenant,
        agent_display_name="orchestrator",
        status="working",
        messages_sent_count=0,
        messages_waiting_count=0,
        messages_read_count=0,
    )
    db_session.add(ex)
    await db_session.flush()
    await db_session.refresh(ex)

    result = await _jobs_svc(db_session).list_jobs(tenant_key=tenant)
    job_row = _job_for(result.jobs, ex.agent_id)
    assert job_row["messages_waiting_count"] == 0
    assert job_row["action_required_unread"] == 0


# ---------------------------------------------------------------------------
# Cross-tenant isolation (ADR-009) -- repository layer, adversarial audit
# Finding A. Reuses the SAME literal agent_id across both tenants (a real
# agent_id has no cross-tenant uniqueness constraint) and, on each call,
# passes BOTH tenants' project_ids together -- the only thing standing
# between "tenant A sees tenant B's count" is the tenant_key predicate
# inside get_live_action_required_unread_counts_by_project_agent itself, not
# disjoint id space (project ids ARE globally unique, but that alone must
# not be what's silently making this test pass).
# ---------------------------------------------------------------------------


async def _seed_project_with_shared_agent(
    session: AsyncSession, tenant_key: str, shared_agent_id: str
) -> tuple[str, AgentExecution]:
    """One project + one execution whose ``agent_id`` is caller-supplied (so
    two tenants can share the identical literal), with one directed,
    requires_action message addressed to it."""
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
        name=f"BE-9273 cross-tenant project ({tenant_key})",
        description="cross-tenant action_required_unread isolation",
        mission="cross-tenant isolation mission",
        status="active",
        tenant_key=tenant_key,
        product_id=_owning_product_proj.id,
        execution_mode="multi_terminal",
        series_number=random.randint(1, 9000),
        created_at=datetime.now(UTC),
    )
    session.add(proj)
    await session.flush()

    job = AgentJob(
        job_id=str(uuid.uuid4()),
        tenant_key=tenant_key,
        project_id=proj.id,
        job_type="analyzer",
        mission="cross-tenant fixture agent",
        status="active",
    )
    session.add(job)
    ex = AgentExecution(
        agent_id=shared_agent_id,
        job_id=job.job_id,
        tenant_key=tenant_key,
        agent_display_name="analyzer",
        status="working",
        messages_sent_count=0,
        messages_waiting_count=0,
        messages_read_count=0,
    )
    session.add(ex)
    await session.flush()

    msg = Message(
        tenant_key=tenant_key,
        project_id=proj.id,
        content=f"action-required post for {tenant_key}",
        message_type="direct",
        status="pending",
        from_agent_id="some-orchestrator",
        requires_action=True,
        auto_generated=False,
    )
    session.add(msg)
    await session.flush()
    session.add(MessageRecipient(message_id=msg.id, agent_id=shared_agent_id, tenant_key=tenant_key))
    await session.flush()

    return proj.id, ex


async def test_get_live_action_required_unread_counts_by_project_agent_is_tenant_isolated(
    db_session: AsyncSession,
) -> None:
    """ADR-009 hardening: tenant A's count must NEVER include tenant B's row,
    and vice versa, even when both tenants share the identical agent_id and
    the query is called with BOTH tenants' project_ids in one request."""
    tenant_a = TenantManager.generate_tenant_key()
    tenant_b = TenantManager.generate_tenant_key()
    shared_agent_id = f"agent-shared-{uuid.uuid4().hex[:8]}"

    project_a_id, _ex_a = await _seed_project_with_shared_agent(db_session, tenant_a, shared_agent_id)
    project_b_id, _ex_b = await _seed_project_with_shared_agent(db_session, tenant_b, shared_agent_id)

    repo = AgentOperationsRepository()
    both_project_ids = [project_a_id, project_b_id]

    # The fail-closed tenant guard (tenant_guard.py) requires an EXPLICIT
    # service-level tenant context for a SELECT carrying an explicit tenant
    # predicate -- a flush-derived context (left behind by the seeding above)
    # is not trusted to authorize it. tenant_session_context is the same
    # mechanism optional_tenant_session/tenant_scoped_session apply for every
    # injected-test-session service call in this suite.
    with tenant_session_context(db_session, tenant_a):
        counts_as_tenant_a = await repo.get_live_action_required_unread_counts_by_project_agent(
            db_session, tenant_a, both_project_ids, [shared_agent_id]
        )
    assert counts_as_tenant_a.get((project_a_id, shared_agent_id)) == 1, (
        "tenant A must see its own action-required unread message"
    )
    assert (project_b_id, shared_agent_id) not in counts_as_tenant_a, (
        "tenant A's result must NEVER include tenant B's row, even though the "
        "same agent_id and both project_ids were passed in"
    )

    with tenant_session_context(db_session, tenant_b):
        counts_as_tenant_b = await repo.get_live_action_required_unread_counts_by_project_agent(
            db_session, tenant_b, both_project_ids, [shared_agent_id]
        )
    assert counts_as_tenant_b.get((project_b_id, shared_agent_id)) == 1, (
        "tenant B must see its own action-required unread message"
    )
    assert (
        project_a_id,
        shared_agent_id,
    ) not in counts_as_tenant_b, "tenant B's result must NEVER include tenant A's row"
