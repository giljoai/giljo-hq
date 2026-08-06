# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-6198 — the MCP write_project_closeout path stamps the chain-advance signals.

THE finish-line regression. The MCP write_project_closeout tool calls
close_project_and_update_memory DIRECTLY (tool_accessor/_memory_tools.py:49). Before
this fix that function wrote ONLY the 360 memory + agent decommission -- it never set
project.closeout_executed_at and never marked the chain member, so a chain sub-orch's
write_project_closeout left:

  - project_closeout_at NULL  -> CH_CHAIN_DRIVE STEP D never advanced
  - the run's project_statuses[P_i] unmarked -> C1 guard raised CONDUCTOR_CHAIN_INCOMPLETE

forever. Every chain stalled at the finish line. The chain sync lived only in
ProjectCloseoutService.close_out_project / project_lifecycle_service.complete_project --
NONE of which the MCP write_project_closeout path goes through.

The prior chain tests (BE-6188/6189) SEEDED closeout_executed_at + project_statuses
MANUALLY, so they never exercised the failing layer. These tests call the REAL
close_project_and_update_memory so they catch the bug:

1. test_chain_member_closeout_stamps_signals — the real closeout stamps
   closeout_executed_at, marks project_statuses[p]="completed", and surfaces
   project_closeout_at via get_workflow_status.
2. test_final_closeout_lets_conductor_complete — THE ALPHA REGRESSION: close BOTH
   members via the real closeout, then the C1 guard no longer raises and
   complete_chain_run_if_finished flips the run to "completed".
3. test_solo_closeout_unchanged — a solo project (no run) closes fine; its
   closeout_executed_at is stamped (inert) and there is no run to touch.

DB-touching: db_session fixture (TransactionalTestContext). No module-level mutable
state. No ordering dependencies. Parallel-safe. Edition Scope: CE.
"""

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


# close_project_and_update_memory hard-requires a non-None db_manager at its input
# gate (_validate_closeout_inputs), but when a session is injected (owns_session=False)
# the db_manager is never dereferenced: the session path uses _provided_session and the
# chain sync routes through SequenceRunService(test_session=active_session). A bare
# sentinel object satisfies the gate without pulling in mock machinery.
_DB_MANAGER_SENTINEL = object()


# ---------------------------------------------------------------------------
# Helpers (product-minting seed mirrored from test_be6186; conductor/guard
# patterns mirrored from test_be6189).
# ---------------------------------------------------------------------------


async def _seed_project(session: AsyncSession, tenant_key: str, product_id: str | None = None) -> str:
    """Seed a project under a real product so close_project_and_update_memory resolves.

    close_project_and_update_memory fetches BOTH the project and its linked product
    (_fetch_project_and_product), so the project MUST carry a real product_id. When
    product_id is None a fresh inactive product is minted (is_active=False keeps the
    single-active-product-per-tenant index happy when several products coexist).
    """
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
    """Create a 2-project run + its minted conductor; return the serialized run.

    Each project gets its OWN inactive product: two ACTIVE projects cannot share one
    product (idx_project_single_active_per_product), and is_active=False keeps the
    single-active-product-per-tenant index satisfied across the two products.
    """
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


# ---------------------------------------------------------------------------
# 1. the real MCP closeout stamps BOTH chain-advance signals
# ---------------------------------------------------------------------------


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

    # Closeout-message companion: unlike solo, a chain member's row genuinely IS flipped
    # below (status + completed_at), so its message may say so -- and it must NOT
    # carry the solo-only Archive remedy, which would be actively misleading here
    # (the row is already terminal; there's nothing left to archive).
    message = result["message"]
    assert "archive" not in message.lower(), (
        f"a chain member's closeout already flipped its status -- the solo-only Archive "
        f"remedy must not appear here: {message!r}"
    )

    # (a) closeout_executed_at is now stamped on the project (was NULL before the fix).
    reloaded = await _reload_project(db_session, p1, tenant)
    assert reloaded.closeout_executed_at is not None, "the real closeout must stamp closeout_executed_at"

    # (b) the run's project_statuses[p1] is now "completed" (C1 guard's terminal signal).
    refetched = await _run_svc(db_session).find_active_run_for_project(project_id=p1, tenant_key=tenant)
    assert refetched is not None
    assert refetched["project_statuses"][p1] == "completed", (
        "the real closeout must mark the chain member completed in the run"
    )

    # (c) get_workflow_status surfaces project_closeout_at (the conductor's STEP D poll).
    status = await _workflow_svc(db_session).get_workflow_status(project_id=p1, tenant_key=tenant)
    assert status.project_closeout_at is not None, "project_closeout_at must surface for the conductor's drive loop"

    # (d) BUG #7: the project ROW is flipped to "completed" (+ completed_at) so /projects
    # shows it like a solo project, instead of lingering "inactive"/"active" forever.
    assert reloaded.status == "completed", "chain member closeout must flip the project row to completed"
    assert reloaded.completed_at is not None, "chain member closeout must stamp completed_at"


# ---------------------------------------------------------------------------
# 1b. BUG #7: ALL members of a finished chain end up status=completed
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# 2. THE ALPHA REGRESSION: closing the LAST member lets the conductor finish
# ---------------------------------------------------------------------------


async def test_final_closeout_lets_conductor_complete(db_session: AsyncSession) -> None:
    tenant = TenantManager.generate_tenant_key()
    run = await _seed_two_project_run(db_session, tenant)
    p1, p2 = run["_project_ids"]
    conductor_agent_id = run["conductor_agent_id"]

    # Close BOTH members via the REAL closeout path (not seeded statuses).
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

    # The C1 guard must NOT raise now that every member is terminal.
    job, execution = await _conductor_job_and_exec(db_session, tenant, conductor_agent_id)
    await _completion_svc(db_session)._guard_conductor_chain_incomplete(
        db_session, job, execution, tenant, str(job.job_id)
    )

    # And the finished run is PURGED (Option A: the dead run row is deleted, not flipped).
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


# ---------------------------------------------------------------------------
# 3. solo behavior preserved: closeout stamps the inert field, touches no run
# ---------------------------------------------------------------------------


async def test_solo_closeout_unchanged(db_session: AsyncSession) -> None:
    tenant = TenantManager.generate_tenant_key()
    p_solo = await _seed_project(db_session, tenant)  # no run created

    # The closeout succeeds with no run in play (no exception from the chain sync).
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

    # closeout_executed_at IS stamped (inert for solo; only chain machinery reads it).
    reloaded = await _reload_project(db_session, p_solo, tenant)
    assert reloaded.closeout_executed_at is not None, "closeout_executed_at is stamped even for solo (inert)"

    # BUG #7 guard: a SOLO closeout must NOT flip the project row status
    # (solo relies on the user's archive press, unchanged). The seed leaves it "active".
    assert reloaded.status == "active", "solo closeout must NOT flip status (stays whatever it was)"

    # BE-9343 supersedes the former "must NOT stamp completed_at" assertion here.
    # That gap is exactly the defect: a solo project closed by an agent kept
    # completed_at NULL, so the dashboard showed updated_at under a "Completed"
    # heading and completed_after/completed_before matched nothing. The status
    # half of BUG #7's guard is untouched and asserted above.
    assert reloaded.completed_at is not None, "BE-9343: a solo closeout stamps completed_at"

    # No run exists for a solo project -> mark_chain_member_status was a clean no-op.
    run = await _run_svc(db_session).find_active_run_for_project(project_id=p_solo, tenant_key=tenant)
    assert run is None, "a solo project must have no active run to touch"
