# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""FE-9493 — split "implementing" into "planning" + "implementing".

The chain tab strip could not distinguish "this member's sub-orchestrator has
started working the project" from "the first worker it spawned has started" --
both wrote the SAME ``project_statuses`` value ("implementing"), and the FE bug
(a WAITING member flipping to PLANNING just from being clicked/visited) was a
separate client-side artifact fixed on the frontend side (useChainContext.spec.js).
This backend half makes the PLANNING state real:

1. ``VALID_PROJECT_STATUSES`` gains "planning"; ``CHAIN_TERMINAL_PROJECT_STATUSES``
   does NOT (it is not a terminal state).
2. ``advance_chain_member_to_implementing`` (the sub-orch entering the project, at
   launch or at staging-end) now writes "planning" instead of "implementing".
3. ``mission_service.get_agent_mission``'s atomic waiting->working start, when the
   job belongs to a non-orchestrator (a spawned worker) on a chain-member project,
   promotes that member's status to "implementing" -- the FIRST-WORKER-STARTED
   signal -- via a NEW forward-only guard on ``mark_chain_member_status`` (its
   ``not_from`` param) so a late/racing worker registration can never demote a
   member that already reached awaiting_review/completed/failed/stalled/terminated.
4. ``job_completion_staging._RUN_IMPL_STARTED_STATUSES`` (used by
   ``is_conductor_staging_end`` to decide whether a chain has left the staging
   phase) gains "planning" -- the same real-world event this set always meant to
   catch, just renamed.

Each numbered item is pinned by its own test group below, driven at the service
layer (the layer the split touches) with real DB writes through db_session
(TransactionalTestContext). No module-level mutable state. No ordering
dependencies. Parallel-safe. Edition Scope: CE.
"""

from __future__ import annotations

import random
import uuid
from datetime import UTC, datetime
from unittest.mock import Mock

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.models import Product, Project
from giljo_mcp.models.agent_identity import AgentExecution, AgentJob
from giljo_mcp.models.sequence_runs import CHAIN_TERMINAL_PROJECT_STATUSES, VALID_PROJECT_STATUSES
from giljo_mcp.services.job_completion_staging import is_conductor_staging_end
from giljo_mcp.services.mission_service import MissionService
from giljo_mcp.services.project_helpers import advance_chain_member_to_implementing, mark_chain_member_status
from giljo_mcp.services.sequence_run_service import SequenceRunService
from giljo_mcp.tenant import TenantManager


pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Seeding helpers (mirrors tests/services/test_be6206_chain_gateless_release.py)
# ---------------------------------------------------------------------------


async def _seed_project(session: AsyncSession, tenant_key: str, *, implementation_launched: bool = False) -> str:
    """``implementation_launched=True`` stamps ``implementation_launched_at`` so a
    WORKER (non-orchestrator) job on this project clears the mission_implementation_gate
    human/chain-staging gate -- required for any test that drives a real worker
    get_agent_mission call past that gate to reach the atomic-start block."""
    product = Product(
        id=str(uuid.uuid4()),
        name=f"FE-9493 Product {uuid.uuid4().hex[:6]}",
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
        name=f"FE-9493 {uuid.uuid4().hex[:6]}",
        description="Chain member.",
        mission="Be a chain member.",
        status="active",
        tenant_key=tenant_key,
        product_id=product.id,
        series_number=random.randint(1, 9000),
        execution_mode="claude_code_cli",
        implementation_launched_at=datetime.now(UTC) if implementation_launched else None,
        created_at=datetime.now(UTC),
    )
    session.add(project)
    session.info["tenant_key"] = tenant_key
    await session.flush()
    return project.id


async def _seed_job(
    session: AsyncSession,
    tenant_key: str,
    project_id: str,
    *,
    job_type: str,
    status: str = "waiting",
) -> AgentJob:
    """Hand-mint a job + execution at the given status (default "waiting" — the
    pre-first-mission-fetch state the atomic-start block keys on)."""
    job_id = str(uuid.uuid4())
    job = AgentJob(
        job_id=job_id,
        tenant_key=tenant_key,
        project_id=project_id,
        mission="do the work",
        job_type=job_type,
        status="active",
        job_metadata={},
    )
    session.add(job)
    session.add(
        AgentExecution(
            agent_id=str(uuid.uuid4()),
            job_id=job_id,
            tenant_key=tenant_key,
            agent_display_name=job_type,
            agent_name=job_type.title(),
            status=status,
            health_status="unknown",
            project_phase="implementation",
            started_at=datetime.now(UTC) if status != "waiting" else None,
        )
    )
    session.info["tenant_key"] = tenant_key
    await session.flush()
    return job


def _run_svc(session: AsyncSession) -> SequenceRunService:
    return SequenceRunService(db_manager=None, tenant_manager=TenantManager(), session=session)


def _mission_svc(session: AsyncSession, db_manager) -> MissionService:
    return MissionService(db_manager=db_manager, tenant_manager=TenantManager(), test_session=session)


async def _reload_execution(session: AsyncSession, job_id: str, tenant_key: str) -> AgentExecution:
    return (
        await session.execute(
            select(AgentExecution).where(AgentExecution.job_id == job_id, AgentExecution.tenant_key == tenant_key)
        )
    ).scalar_one()


# ===========================================================================
# 1. VALID_PROJECT_STATUSES / CHAIN_TERMINAL_PROJECT_STATUSES membership
# ===========================================================================


async def test_planning_is_a_valid_project_status() -> None:
    assert "planning" in VALID_PROJECT_STATUSES


async def test_planning_is_not_terminal() -> None:
    """PLANNING must never release the C1 conductor-chain-incomplete guard --
    only a genuinely finished member does."""
    assert "planning" not in CHAIN_TERMINAL_PROJECT_STATUSES


# ===========================================================================
# 2. advance_chain_member_to_implementing writes "planning", not "implementing"
# ===========================================================================


async def test_advance_writes_planning_not_implementing(db_session: AsyncSession) -> None:
    tenant = TenantManager.generate_tenant_key()
    p1 = await _seed_project(db_session, tenant)
    # advance_chain_member_to_implementing is a no-op without an active run.
    await _run_svc(db_session).create(
        project_ids=[p1], resolved_order=[p1], execution_mode="claude_code_cli", tenant_key=tenant
    )

    advanced = await advance_chain_member_to_implementing(
        db_manager=None,
        tenant_manager=TenantManager(),
        project_id=p1,
        tenant_key=tenant,
        session=db_session,
    )
    assert advanced is True

    refreshed = await _run_svc(db_session).find_active_run_for_project(project_id=p1, tenant_key=tenant)
    assert refreshed["project_statuses"][p1] == "planning", (
        "the sub-orch entering the project must write 'planning', not 'implementing' -- "
        "'implementing' is now reserved for the first spawned WORKER starting"
    )


# ===========================================================================
# 3a. mark_chain_member_status forward-only guard (not_from)
# ===========================================================================


async def test_not_from_none_preserves_existing_callers_byte_identical(db_session: AsyncSession) -> None:
    """Every EXISTING caller passes status="completed" with no not_from -- default
    None must change nothing for them (regression guard on the 4 existing call sites)."""
    tenant = TenantManager.generate_tenant_key()
    p1 = await _seed_project(db_session, tenant)
    await _run_svc(db_session).create(
        project_ids=[p1], resolved_order=[p1], execution_mode="claude_code_cli", tenant_key=tenant
    )

    ok = await mark_chain_member_status(
        db_manager=None,
        tenant_manager=TenantManager(),
        project_id=p1,
        tenant_key=tenant,
        status="completed",
        test_session=db_session,
    )
    assert ok is True
    refreshed = await _run_svc(db_session).find_active_run_for_project(project_id=p1, tenant_key=tenant)
    assert refreshed["project_statuses"][p1] == "completed"


@pytest.mark.parametrize("current_status", ["pending", "staged", "planning"])
async def test_not_from_permits_forward_transitions(db_session: AsyncSession, current_status: str) -> None:
    """planning (and any earlier state) -> implementing is a legitimate forward
    move and must NOT be blocked by the guard."""
    tenant = TenantManager.generate_tenant_key()
    p1 = await _seed_project(db_session, tenant)
    run = await _run_svc(db_session).create(
        project_ids=[p1], resolved_order=[p1], execution_mode="claude_code_cli", tenant_key=tenant
    )
    if current_status != "pending":
        await _run_svc(db_session).update(run_id=run["id"], tenant_key=tenant, project_statuses={p1: current_status})

    ok = await mark_chain_member_status(
        db_manager=None,
        tenant_manager=TenantManager(),
        project_id=p1,
        tenant_key=tenant,
        status="implementing",
        test_session=db_session,
        not_from=frozenset({"awaiting_review", "completed", "failed", "stalled", "terminated"}),
    )
    assert ok is True

    refreshed = await _run_svc(db_session).find_active_run_for_project(project_id=p1, tenant_key=tenant)
    assert refreshed["project_statuses"][p1] == "implementing"


@pytest.mark.parametrize("settled_status", ["awaiting_review", "completed", "failed", "stalled", "terminated"])
async def test_not_from_blocks_demotion_from_settled_states(db_session: AsyncSession, settled_status: str) -> None:
    """The load-bearing guard: a member already past 'implementing' must NEVER
    be written back to 'implementing' by a late/racing worker registration."""
    tenant = TenantManager.generate_tenant_key()
    p1 = await _seed_project(db_session, tenant)
    run = await _run_svc(db_session).create(
        project_ids=[p1], resolved_order=[p1], execution_mode="claude_code_cli", tenant_key=tenant
    )
    await _run_svc(db_session).update(run_id=run["id"], tenant_key=tenant, project_statuses={p1: settled_status})

    ok = await mark_chain_member_status(
        db_manager=None,
        tenant_manager=TenantManager(),
        project_id=p1,
        tenant_key=tenant,
        status="implementing",
        test_session=db_session,
        not_from=frozenset({"awaiting_review", "completed", "failed", "stalled", "terminated"}),
    )
    assert ok is False, f"a member at {settled_status!r} must not be demoted back to 'implementing'"

    refreshed = await _run_svc(db_session).find_active_run_for_project(project_id=p1, tenant_key=tenant)
    assert refreshed["project_statuses"][p1] == settled_status, "the settled status must be left untouched"


# ===========================================================================
# 3b. mission_service.get_agent_mission — the real integration: first worker
#     mission fetch promotes planning -> implementing; the orchestrator's own
#     first fetch does NOT; a settled member is never demoted.
# ===========================================================================


async def test_first_worker_mission_fetch_promotes_planning_to_implementing(
    db_session: AsyncSession, db_manager
) -> None:
    tenant = TenantManager.generate_tenant_key()
    p1 = await _seed_project(db_session, tenant, implementation_launched=True)
    run = await _run_svc(db_session).create(
        project_ids=[p1], resolved_order=[p1], execution_mode="claude_code_cli", tenant_key=tenant
    )
    await _run_svc(db_session).update(run_id=run["id"], tenant_key=tenant, project_statuses={p1: "planning"})
    worker_job = await _seed_job(db_session, tenant, p1, job_type="implementer", status="waiting")

    await _mission_svc(db_session, db_manager).get_agent_mission(worker_job.job_id, tenant)

    refreshed = await _run_svc(db_session).find_active_run_for_project(project_id=p1, tenant_key=tenant)
    assert refreshed["project_statuses"][p1] == "implementing", (
        "the first spawned worker's own first mission fetch must promote its chain member from planning to implementing"
    )


async def test_orchestrators_own_first_mission_fetch_does_not_promote(db_session: AsyncSession, db_manager) -> None:
    """job.job_type == "orchestrator" must be excluded -- the sub-orch's OWN
    first mission fetch already wrote 'planning' via the staging-end/launch
    path; this call must not re-promote to 'implementing' before any worker
    has actually started."""
    tenant = TenantManager.generate_tenant_key()
    p1 = await _seed_project(db_session, tenant)
    run = await _run_svc(db_session).create(
        project_ids=[p1], resolved_order=[p1], execution_mode="claude_code_cli", tenant_key=tenant
    )
    await _run_svc(db_session).update(run_id=run["id"], tenant_key=tenant, project_statuses={p1: "planning"})
    orch_job = await _seed_job(db_session, tenant, p1, job_type="orchestrator", status="waiting")

    await _mission_svc(db_session, db_manager).get_agent_mission(orch_job.job_id, tenant)

    refreshed = await _run_svc(db_session).find_active_run_for_project(project_id=p1, tenant_key=tenant)
    assert refreshed["project_statuses"][p1] == "planning", (
        "the orchestrator's own mission fetch must not promote its member to "
        "implementing -- only a NON-orchestrator (a spawned worker) may"
    )


async def test_late_worker_mission_fetch_does_not_demote_a_completed_member(
    db_session: AsyncSession, db_manager
) -> None:
    """Race guard: a worker's first-ever mission fetch lands AFTER its project
    already closed out (completed). Must not demote back to 'implementing'."""
    tenant = TenantManager.generate_tenant_key()
    p1 = await _seed_project(db_session, tenant, implementation_launched=True)
    run = await _run_svc(db_session).create(
        project_ids=[p1], resolved_order=[p1], execution_mode="claude_code_cli", tenant_key=tenant
    )
    await _run_svc(db_session).update(run_id=run["id"], tenant_key=tenant, project_statuses={p1: "completed"})
    worker_job = await _seed_job(db_session, tenant, p1, job_type="implementer", status="waiting")

    await _mission_svc(db_session, db_manager).get_agent_mission(worker_job.job_id, tenant)

    refreshed = await _run_svc(db_session).find_active_run_for_project(project_id=p1, tenant_key=tenant)
    assert refreshed["project_statuses"][p1] == "completed", (
        "a late worker mission-fetch race must never demote a settled member"
    )


async def test_solo_worker_mission_fetch_is_a_clean_noop(db_session: AsyncSession, db_manager) -> None:
    """Solo (no active run) project: the new promotion call must be a byte-
    identical no-op -- get_agent_mission still succeeds normally."""
    tenant = TenantManager.generate_tenant_key()
    p1 = await _seed_project(db_session, tenant, implementation_launched=True)  # no sequence run created
    worker_job = await _seed_job(db_session, tenant, p1, job_type="implementer", status="waiting")

    response = await _mission_svc(db_session, db_manager).get_agent_mission(worker_job.job_id, tenant)

    assert response.status == "working", "solo mission-start semantics must be unaffected"
    refreshed = await _reload_execution(db_session, worker_job.job_id, tenant)
    assert refreshed.status == "working"


# ===========================================================================
# 4. is_conductor_staging_end — "planning" must count as "implementation begun"
# ===========================================================================


async def test_planning_member_means_conductor_call_is_not_staging_end(db_session: AsyncSession) -> None:
    tenant = TenantManager.generate_tenant_key()
    p1 = await _seed_project(db_session, tenant)
    run = await _run_svc(db_session).create(
        project_ids=[p1], resolved_order=[p1], execution_mode="claude_code_cli", tenant_key=tenant
    )
    await _run_svc(db_session).update(run_id=run["id"], tenant_key=tenant, project_statuses={p1: "planning"})

    result = await is_conductor_staging_end(
        db_session,
        Mock(agent_id=run["conductor_agent_id"]),
        tenant,
        db_manager=None,
        tenant_manager=TenantManager(),
    )
    assert result is False, (
        "a member already at 'planning' means the conductor already released it -- "
        "this second complete_job is NOT another staging-end"
    )


async def test_no_member_started_still_reads_as_conductor_staging_end(db_session: AsyncSession) -> None:
    """Control: byte-identical for the case this fix does not touch -- nothing
    has started yet, so the conductor's call is still a genuine staging-end."""
    tenant = TenantManager.generate_tenant_key()
    p1 = await _seed_project(db_session, tenant)
    run = await _run_svc(db_session).create(
        project_ids=[p1], resolved_order=[p1], execution_mode="claude_code_cli", tenant_key=tenant
    )

    result = await is_conductor_staging_end(
        db_session,
        Mock(agent_id=run["conductor_agent_id"]),
        tenant,
        db_manager=None,
        tenant_manager=TenantManager(),
    )
    assert result is True
