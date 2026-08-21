# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
Regression tests for CE-0026: JobCompletionService._handle_staging_end
state-machine branch.

Five focused behaviors:
  a. Staging-end orchestrator returns STOP directive and flips staging_status.
  b. Idempotent: already-flipped project still returns the directive.
  c. Implementation-phase orchestrator: no directive.
  d. Non-orchestrator job type: no directive even on staging-phase project.
  e. mark_staging_complete is called exactly once per staging-end complete_job.
"""

from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.models.agent_identity import AgentExecution, AgentJob, AgentTodoItem
from giljo_mcp.models.products import Product
from giljo_mcp.models.projects import Project
from giljo_mcp.services.job_completion_service import JobCompletionService


# ============================================================================
# Fixtures
# ============================================================================


@pytest_asyncio.fixture
async def test_product(db_session: AsyncSession, test_tenant_key: str) -> Product:
    product = Product(
        id=str(uuid4()),
        tenant_key=test_tenant_key,
        name="CE-0026 State Machine Product",
        description="Product for CE-0026 state machine tests",
        product_memory={},
    )
    db_session.add(product)
    await db_session.commit()
    await db_session.refresh(product)
    return product


@pytest.fixture
def completion_service(db_session: AsyncSession, test_tenant_key: str) -> JobCompletionService:
    db_manager = MagicMock()
    tenant_manager = MagicMock()
    tenant_manager.get_current_tenant.return_value = test_tenant_key
    return JobCompletionService(
        db_manager=db_manager,
        tenant_manager=tenant_manager,
        test_session=db_session,
    )


async def _seed_orchestrator_job(
    db_session: AsyncSession,
    tenant_key: str,
    project_id: str,
    *,
    project_phase: str = "staging",
) -> tuple[AgentJob, AgentExecution]:
    """Seed an orchestrator AgentJob + working AgentExecution."""
    job_id = str(uuid4())
    job = AgentJob(
        job_id=job_id,
        tenant_key=tenant_key,
        project_id=project_id,
        job_type="orchestrator",
        mission="CE-0026 staging orchestrator",
        status="active",
    )
    db_session.add(job)

    now = datetime.now(UTC)
    execution = AgentExecution(
        job_id=job_id,
        tenant_key=tenant_key,
        agent_display_name="orchestrator",
        status="working",
        messages_sent_count=0,
        messages_waiting_count=0,
        messages_read_count=0,
        started_at=now - timedelta(minutes=5),
        project_phase=project_phase,
    )
    db_session.add(execution)
    await db_session.commit()
    await db_session.refresh(job)
    await db_session.refresh(execution)
    return job, execution


async def _seed_deliverable_job(
    db_session: AsyncSession,
    tenant_key: str,
    project_id: str,
    *,
    job_type: str = "implementer",
    project_phase: str = "staging",
) -> tuple[AgentJob, AgentExecution]:
    """Seed a non-orchestrator AgentJob + working AgentExecution."""
    job_id = str(uuid4())
    job = AgentJob(
        job_id=job_id,
        tenant_key=tenant_key,
        project_id=project_id,
        job_type=job_type,
        mission="CE-0026 deliverable agent",
        status="active",
    )
    db_session.add(job)

    now = datetime.now(UTC)
    execution = AgentExecution(
        job_id=job_id,
        tenant_key=tenant_key,
        agent_display_name=job_type,
        status="working",
        messages_sent_count=0,
        messages_waiting_count=0,
        messages_read_count=0,
        started_at=now - timedelta(minutes=3),
        project_phase=project_phase,
    )
    db_session.add(execution)
    await db_session.commit()
    await db_session.refresh(job)
    await db_session.refresh(execution)
    return job, execution


async def _seed_project(
    db_session: AsyncSession,
    tenant_key: str,
    product_id: str,
    *,
    staging_status: str | None = "staging",
) -> Project:
    project = Project(
        id=str(uuid4()),
        tenant_key=tenant_key,
        product_id=product_id,
        name="CE-0026 Test Project",
        description="Project for CE-0026 state machine tests",
        mission="Staging state machine test",
        status="active",
        staging_status=staging_status,
        created_at=datetime.now(UTC),
        series_number=random.randint(1, 9000),
    )
    db_session.add(project)
    await db_session.commit()
    await db_session.refresh(project)
    return project


# ============================================================================
# Tests
# ============================================================================


@pytest.mark.asyncio
async def test_staging_end_orchestrator_returns_stop_directive_and_flips_status(
    db_session: AsyncSession,
    completion_service: JobCompletionService,
    test_tenant_key: str,
    test_product: Product,
):
    """(a) Staging-phase orchestrator complete_job returns STOP directive and
    flips project.staging_status to 'staging_complete'.

    CE-0026 + CE-0032: the _handle_staging_end branch triggers when:
      - job.job_type == 'orchestrator'
      - execution.project_phase == 'staging' (vestigial column; spawn paths
        still set it)
      - project.staging_status != 'staging_complete' (flip needed)
      - project.implementation_launched_at IS NULL (safeguard against
        treating impl-end as staging-end)

    CE-0032: the staging-end branch sets exec.status='waiting' (NOT
    'complete') so the same orch row carries forward into impl session.
    """
    project = await _seed_project(db_session, test_tenant_key, test_product.id, staging_status="staging")
    job, execution = await _seed_orchestrator_job(db_session, test_tenant_key, project.id, project_phase="staging")

    # BE-5114: staging-end requires >=1 spawned specialist agent; seed one to reach the gated path.
    await _seed_deliverable_job(
        db_session, test_tenant_key, project.id, job_type="implementer", project_phase="staging"
    )

    result = await completion_service.complete_job(
        job_id=job.job_id,
        result={"summary": "Staging session complete"},
        tenant_key=test_tenant_key,
    )

    assert result.status == "success"
    assert result.staging_directive is not None, "CE-0026: staging-phase orchestrator must return a staging_directive"
    assert result.staging_directive.action == "STOP", f"Expected action=STOP, got {result.staging_directive.action!r}"
    assert result.staging_directive.status == "STAGING_SESSION_COMPLETE", (
        f"Expected status=STAGING_SESSION_COMPLETE, got {result.staging_directive.status!r}"
    )

    refreshed = (
        await db_session.execute(select(Project).where(Project.id == project.id, Project.tenant_key == test_tenant_key))
    ).scalar_one()
    assert refreshed.staging_status == "staging_complete", (
        f"CE-0026: staging_status must be flipped to 'staging_complete', got {refreshed.staging_status!r}"
    )

    # CE-0032: exec.status stays 'waiting'; the orch row persists across the
    # staging→impl boundary. No completed_at set.
    refreshed_exec = (
        await db_session.execute(select(AgentExecution).where(AgentExecution.id == execution.id))
    ).scalar_one()
    assert refreshed_exec.status == "waiting", (
        f"CE-0032: staging-end must leave exec.status='waiting', got {refreshed_exec.status!r}"
    )
    assert refreshed_exec.completed_at is None, (
        f"CE-0032: staging-end must leave exec.completed_at unset, got {refreshed_exec.completed_at!r}"
    )

    # CE-0032: exactly one orch exec on the job — no pre-spawn second row.
    orch_execs = list(
        (
            await db_session.execute(
                select(AgentExecution).where(
                    AgentExecution.job_id == job.job_id,
                    AgentExecution.tenant_key == test_tenant_key,
                    AgentExecution.agent_display_name == "orchestrator",
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(orch_execs) == 1, (
        f"CE-0032: single orchestrator entity — exactly one orch exec must remain, got {len(orch_execs)}"
    )


@pytest.mark.asyncio
async def test_staging_end_already_flipped_still_returns_directive(
    db_session: AsyncSession,
    completion_service: JobCompletionService,
    test_tenant_key: str,
    test_product: Product,
):
    """(b) Idempotent: if project.staging_status is already 'staging_complete',
    complete_job still returns the STOP directive (the orchestrator still needs
    the signal even though mark_staging_complete was a no-op).

    CE-0026: mark_staging_complete returns False when already complete, but
    _handle_staging_end still returns StagingDirective() regardless.

    CE-0032: this is also the regression guard for "second staging-end
    complete_job MUST NOT flip exec.status to 'complete'". The same row that
    was set to 'waiting' on the first call stays at 'waiting' — defensive
    re-calls are no-ops for the row.
    """
    project = await _seed_project(db_session, test_tenant_key, test_product.id, staging_status="staging_complete")
    job, execution = await _seed_orchestrator_job(db_session, test_tenant_key, project.id, project_phase="staging")
    # Simulate the post-first-call state: exec was already flipped to 'waiting'
    # by an earlier staging-end. The second call is the idempotent re-entry.
    execution.status = "waiting"
    await db_session.commit()
    await db_session.refresh(execution)

    # BE-5114: staging-end requires >=1 spawned specialist agent; seed one to reach the gated path.
    await _seed_deliverable_job(
        db_session, test_tenant_key, project.id, job_type="implementer", project_phase="staging"
    )

    result = await completion_service.complete_job(
        job_id=job.job_id,
        result={"summary": "Staging already complete — idempotent path"},
        tenant_key=test_tenant_key,
    )

    assert result.status == "success"
    assert result.staging_directive is not None, "CE-0026: idempotent staging-end must still return a staging_directive"
    assert result.staging_directive.action == "STOP"

    # staging_status must remain unchanged (not re-flipped).
    refreshed = (
        await db_session.execute(select(Project).where(Project.id == project.id, Project.tenant_key == test_tenant_key))
    ).scalar_one()
    assert refreshed.staging_status == "staging_complete"

    # CE-0032: exec.status stays 'waiting' on the idempotent re-call.
    refreshed_exec = (
        await db_session.execute(select(AgentExecution).where(AgentExecution.id == execution.id))
    ).scalar_one()
    assert refreshed_exec.status == "waiting", (
        f"CE-0032 idempotency: exec.status must stay 'waiting' on re-entry, got {refreshed_exec.status!r}"
    )


@pytest.mark.asyncio
async def test_implementation_phase_orchestrator_no_directive(
    db_session: AsyncSession,
    completion_service: JobCompletionService,
    test_tenant_key: str,
    test_product: Product,
):
    """(c) Implementation-phase orchestrator: complete_job returns no
    staging_directive and normal closeout_checklist behavior is unchanged.

    CE-0026: _handle_staging_end returns None when project_phase='implementation'.
    """
    project = await _seed_project(db_session, test_tenant_key, test_product.id, staging_status="staging_complete")
    job, _ = await _seed_orchestrator_job(db_session, test_tenant_key, project.id, project_phase="implementation")

    result = await completion_service.complete_job(
        job_id=job.job_id,
        result={"summary": "Implementation complete"},
        tenant_key=test_tenant_key,
    )

    assert result.status == "success"
    assert result.staging_directive is None, (
        "CE-0026: implementation-phase orchestrator must NOT return a staging_directive"
    )
    # Closeout checklist is still built for orchestrators (INF-5076 regression guard).
    assert result.closeout_checklist is not None, (
        "closeout_checklist must still be populated for orchestrator complete_job"
    )


@pytest.mark.asyncio
async def test_deliverable_agent_no_directive_even_on_staging_phase_project(
    db_session: AsyncSession,
    completion_service: JobCompletionService,
    test_tenant_key: str,
    test_product: Product,
):
    """(d) Non-orchestrator job type: complete_job returns no staging_directive
    regardless of the project's staging_status.

    CE-0026: _handle_staging_end returns None immediately when
    job.job_type != 'orchestrator'.
    """
    project = await _seed_project(db_session, test_tenant_key, test_product.id, staging_status="staging")
    job, _ = await _seed_deliverable_job(
        db_session,
        test_tenant_key,
        project.id,
        job_type="implementer",
        project_phase="staging",
    )

    result = await completion_service.complete_job(
        job_id=job.job_id,
        result={"summary": "Implementer done"},
        tenant_key=test_tenant_key,
    )

    assert result.status == "success"
    assert result.staging_directive is None, "CE-0026: non-orchestrator job must never return a staging_directive"
    # project staging_status must not have been touched by this non-orch complete.
    refreshed = (
        await db_session.execute(select(Project).where(Project.id == project.id, Project.tenant_key == test_tenant_key))
    ).scalar_one()
    assert refreshed.staging_status == "staging", "Non-orchestrator complete_job must not alter project.staging_status"


@pytest.mark.asyncio
async def test_mark_staging_complete_called_exactly_once_on_staging_end(
    db_session: AsyncSession,
    test_tenant_key: str,
    test_product: Product,
):
    """(e) mark_staging_complete is invoked exactly once, with
    source='complete_job:staging_end', during a staging-end complete_job.

    Uses unittest.mock.patch on the helper at the job_completion_service
    import site so the patched version is what the service calls.
    """
    project = await _seed_project(db_session, test_tenant_key, test_product.id, staging_status="staging")
    job, _ = await _seed_orchestrator_job(db_session, test_tenant_key, project.id, project_phase="staging")
    # BE-5114: staging-end requires >=1 spawned specialist agent; seed one to reach the gated path.
    await _seed_deliverable_job(
        db_session, test_tenant_key, project.id, job_type="implementer", project_phase="staging"
    )

    db_manager = MagicMock()
    tenant_manager = MagicMock()
    tenant_manager.get_current_tenant.return_value = test_tenant_key
    svc = JobCompletionService(
        db_manager=db_manager,
        tenant_manager=tenant_manager,
        test_session=db_session,
    )

    with patch(
        # BE-9060 item 2: the staging-end machinery moved to job_completion_staging;
        # patch the symbol where handle_staging_end now resolves it.
        "giljo_mcp.services.job_completion_staging.mark_staging_complete",
        new_callable=AsyncMock,
        return_value=True,
    ) as mock_msc:
        await svc.complete_job(
            job_id=job.job_id,
            result={"summary": "Staging end — mock test"},
            tenant_key=test_tenant_key,
        )

    mock_msc.assert_called_once()
    _, kwargs = mock_msc.call_args
    assert kwargs.get("source") == "complete_job:staging_end", (
        f"CE-0026: mark_staging_complete must be called with source='complete_job:staging_end', "
        f"got source={kwargs.get('source')!r}"
    )


# ============================================================================
# CE-0027 regression tests — phase-aware gate + phase-aware closeout_checklist
# ============================================================================


async def _seed_incomplete_todos(
    db_session: AsyncSession,
    tenant_key: str,
    job_id: str,
    count: int = 3,
) -> list[AgentTodoItem]:
    """Seed `count` pending TODO items for a job — simulates deliverable plan."""
    todos: list[AgentTodoItem] = []
    for i in range(count):
        todo = AgentTodoItem(
            job_id=job_id,
            tenant_key=tenant_key,
            content=f"CE-0027 deliverable item {i + 1}",
            status="pending",
            sequence=i,
        )
        db_session.add(todo)
        todos.append(todo)
    await db_session.commit()
    return todos


@pytest.mark.asyncio
async def test_staging_orchestrator_complete_job_bypasses_incomplete_todos_gate(
    db_session: AsyncSession,
    completion_service: JobCompletionService,
    test_tenant_key: str,
    test_product: Product,
):
    """CE-0027 (f): staging-phase orchestrator's complete_job must NOT be
    blocked by incomplete TODOs.

    Reason: the orchestrator protocol instructs the staging orch to write
    deliverable-shaped TODOs (e.g., "Build billing service") that are meant to
    survive into implementation. The pre-CE-0027 gate blocked staging-close
    on these, forcing the agent to lie about completion status. CE-0027
    makes the gate phase-aware.
    """
    project = await _seed_project(db_session, test_tenant_key, test_product.id, staging_status="staging")
    job, _ = await _seed_orchestrator_job(db_session, test_tenant_key, project.id, project_phase="staging")
    await _seed_incomplete_todos(db_session, test_tenant_key, job.job_id, count=3)
    # BE-5114: staging-end requires >=1 spawned specialist agent; seed one to reach the gated path.
    await _seed_deliverable_job(
        db_session, test_tenant_key, project.id, job_type="implementer", project_phase="staging"
    )

    result = await completion_service.complete_job(
        job_id=job.job_id,
        result={"summary": "Staging done; 3 deliverable TODOs survive into impl"},
        tenant_key=test_tenant_key,
    )

    assert result.status == "success", "CE-0027: staging orch must close successfully despite incomplete TODOs"
    assert result.staging_directive is not None, "CE-0027: staging close should still return STOP directive"
    assert result.staging_directive.action == "STOP"


@pytest.mark.asyncio
async def test_implementation_orchestrator_complete_job_still_blocks_on_incomplete_todos(
    db_session: AsyncSession,
    completion_service: JobCompletionService,
    test_tenant_key: str,
    test_product: Product,
):
    """CE-0027 (f) regression: implementation-phase orchestrator with
    incomplete TODOs MUST still be blocked (the gate's original purpose —
    preventing premature closure — still applies in impl phase).

    CE-0032 update: impl-phase is signaled by project.implementation_launched_at
    being non-null, not by the vestigial execution.project_phase column.
    """
    from giljo_mcp.exceptions import ValidationError

    project = await _seed_project(db_session, test_tenant_key, test_product.id, staging_status="staging_complete")
    # CE-0032: impl_launched_at non-null is the disqualifier for the TODOs bypass.
    project.implementation_launched_at = datetime.now(UTC)
    await db_session.commit()
    await db_session.refresh(project)

    job, _ = await _seed_orchestrator_job(db_session, test_tenant_key, project.id, project_phase="implementation")
    await _seed_incomplete_todos(db_session, test_tenant_key, job.job_id, count=2)

    with pytest.raises(ValidationError) as exc_info:
        await completion_service.complete_job(
            job_id=job.job_id,
            result={"summary": "Tried to close impl with incomplete TODOs"},
            tenant_key=test_tenant_key,
        )

    assert "COMPLETION_BLOCKED" in str(exc_info.value), (
        f"CE-0027 regression: impl orch with incomplete TODOs must still raise COMPLETION_BLOCKED, "
        f"got: {exc_info.value!r}"
    )


@pytest.mark.asyncio
async def test_deliverable_agent_still_blocks_on_incomplete_todos(
    db_session: AsyncSession,
    completion_service: JobCompletionService,
    test_tenant_key: str,
    test_product: Product,
):
    """CE-0027 (f) regression: non-orchestrator agents (implementer, tester,
    etc.) MUST still be blocked by incomplete TODOs regardless of phase.
    The phase-aware bypass applies only to orchestrators.
    """
    from giljo_mcp.exceptions import ValidationError

    project = await _seed_project(db_session, test_tenant_key, test_product.id, staging_status="staging_complete")
    job, _ = await _seed_deliverable_job(
        db_session, test_tenant_key, project.id, job_type="implementer", project_phase="staging"
    )
    await _seed_incomplete_todos(db_session, test_tenant_key, job.job_id, count=2)

    with pytest.raises(ValidationError) as exc_info:
        await completion_service.complete_job(
            job_id=job.job_id,
            result={"summary": "Implementer trying to close with pending work"},
            tenant_key=test_tenant_key,
        )

    assert "COMPLETION_BLOCKED" in str(exc_info.value), (
        "CE-0027 regression: implementer agent must still be blocked on incomplete TODOs"
    )


@pytest.mark.asyncio
async def test_staging_orchestrator_response_has_no_closeout_checklist(
    db_session: AsyncSession,
    completion_service: JobCompletionService,
    test_tenant_key: str,
    test_product: Product,
):
    """CE-0027 (g): staging-phase orchestrator's complete_job response must
    NOT include closeout_checklist. The checklist content (request_approval,
    deferred findings) is impl-phase guidance and confused the staging agent
    on the test-install billing test.
    """
    project = await _seed_project(db_session, test_tenant_key, test_product.id, staging_status="staging")
    job, _ = await _seed_orchestrator_job(db_session, test_tenant_key, project.id, project_phase="staging")

    # BE-5114: staging-end requires >=1 spawned specialist agent; seed one to reach the gated path.
    await _seed_deliverable_job(
        db_session, test_tenant_key, project.id, job_type="implementer", project_phase="staging"
    )

    result = await completion_service.complete_job(
        job_id=job.job_id,
        result={"summary": "Staging close — should not get impl-phase checklist"},
        tenant_key=test_tenant_key,
    )

    assert result.staging_directive is not None
    assert result.closeout_checklist is None, (
        f"CE-0027: staging orch response must not carry closeout_checklist, got {result.closeout_checklist!r}"
    )


@pytest.mark.asyncio
async def test_implementation_orchestrator_response_has_closeout_checklist(
    db_session: AsyncSession,
    completion_service: JobCompletionService,
    test_tenant_key: str,
    test_product: Product,
):
    """CE-0027 (g) regression: impl-phase orchestrator's response STILL
    includes closeout_checklist (impl-phase guidance is preserved for the
    audience it's actually for).
    """
    project = await _seed_project(db_session, test_tenant_key, test_product.id, staging_status="staging_complete")
    job, _ = await _seed_orchestrator_job(db_session, test_tenant_key, project.id, project_phase="implementation")

    result = await completion_service.complete_job(
        job_id=job.job_id,
        result={"summary": "Impl close — should still get checklist"},
        tenant_key=test_tenant_key,
    )

    assert result.staging_directive is None, "Impl orch should not get staging_directive"
    assert result.closeout_checklist is not None, (
        "CE-0027 regression: impl orch response must still carry closeout_checklist"
    )
    assert "instruction" in result.closeout_checklist or "follow_up_items" in result.closeout_checklist


@pytest.mark.asyncio
async def test_staging_orchestrator_complete_job_leaves_job_status_active(
    db_session: AsyncSession,
    completion_service: JobCompletionService,
    test_tenant_key: str,
    test_product: Product,
):
    """CE-0028 (h) + CE-0032: the staging→implementation transition must
    preserve ``AgentJob.status='active'`` AND leave the orchestrator's
    single AgentExecution row at ``status='waiting'``.

    CE-0028 fixed job.status='active' preservation across the phase
    boundary; CE-0032 collapsed the multi-exec model so the SAME exec row
    (no second row spawned) transitions Working→Waiting at staging-end and
    Waiting→Working when the impl session's first get_agent_mission call
    fires.
    """
    project = await _seed_project(db_session, test_tenant_key, test_product.id, staging_status="staging")
    job, _ = await _seed_orchestrator_job(db_session, test_tenant_key, project.id, project_phase="staging")

    # BE-5114: staging-end requires >=1 spawned specialist agent; seed one to reach the gated path.
    await _seed_deliverable_job(
        db_session, test_tenant_key, project.id, job_type="implementer", project_phase="staging"
    )

    result = await completion_service.complete_job(
        job_id=job.job_id,
        result={"summary": "Staging end — should NOT flip job.status"},
        tenant_key=test_tenant_key,
    )

    assert result.status == "success"
    assert result.staging_directive is not None and result.staging_directive.action == "STOP"

    refreshed_job = (await db_session.execute(select(AgentJob).where(AgentJob.job_id == job.job_id))).scalar_one()
    assert refreshed_job.status == "active", (
        f"CE-0028: staging-end must leave job.status='active', got {refreshed_job.status!r}"
    )
    assert refreshed_job.completed_at is None, (
        f"CE-0028: staging-end must leave job.completed_at unset, got {refreshed_job.completed_at!r}"
    )

    # CE-0032: exactly one orch exec row, status='waiting'. The CE-0029 Item 2
    # pre-spawn is gone — same row transitions across phases.
    refreshed_execs = list(
        (await db_session.execute(select(AgentExecution).where(AgentExecution.job_id == job.job_id))).scalars().all()
    )
    assert len(refreshed_execs) == 1, (
        f"CE-0032 single-exec: expected 1 orch exec on the job, got {len(refreshed_execs)} "
        f"(statuses: {[e.status for e in refreshed_execs]})"
    )
    assert refreshed_execs[0].status == "waiting", (
        f"CE-0032: staging-end orch exec must end at status='waiting', got {refreshed_execs[0].status!r}"
    )


# ============================================================================
# CE-0032 — single-orchestrator-entity restoration
# ============================================================================


@pytest.mark.asyncio
async def test_impl_phase_complete_job_marks_exec_complete(
    db_session: AsyncSession,
    completion_service: JobCompletionService,
    test_tenant_key: str,
    test_product: Product,
):
    """CE-0032 negative case: an impl-phase orchestrator's complete_job
    completes the orchestrator entity for real — status='complete',
    completed_at set, AgentJob flipped to 'completed'.

    Under CE-0032's single-exec model the orch's row was created with
    project_phase='staging' (spawn paths still set that vestigial value)
    and now has implementation_launched_at non-null on the project. The
    detector's safeguard returns is_staging_end=False; _apply_completion_status
    sets status='complete' and _finalize_job_if_last_execution flips the job.
    """
    project = await _seed_project(db_session, test_tenant_key, test_product.id, staging_status="staging_complete")
    # Simulate the impl-launched state: this is what distinguishes "impl end"
    # from "staging end" under CE-0032's project-flag-driven detector.
    project.implementation_launched_at = datetime.now(UTC) - timedelta(hours=1)
    await db_session.commit()
    await db_session.refresh(project)

    job, execution = await _seed_orchestrator_job(db_session, test_tenant_key, project.id, project_phase="staging")

    result = await completion_service.complete_job(
        job_id=job.job_id,
        result={"summary": "Impl close — project end"},
        tenant_key=test_tenant_key,
    )

    assert result.status == "success"
    assert result.staging_directive is None, (
        "CE-0032: impl-end (impl_launched_at non-null) must NOT return a staging_directive"
    )

    refreshed_exec = (
        await db_session.execute(select(AgentExecution).where(AgentExecution.id == execution.id))
    ).scalar_one()
    assert refreshed_exec.status == "complete", (
        f"CE-0032 impl-end: exec.status must be 'complete', got {refreshed_exec.status!r}"
    )
    assert refreshed_exec.completed_at is not None, "CE-0032 impl-end: exec.completed_at must be set"

    refreshed_job = (await db_session.execute(select(AgentJob).where(AgentJob.job_id == job.job_id))).scalar_one()
    assert refreshed_job.status == "completed", (
        f"CE-0032 impl-end: job.status must be 'completed', got {refreshed_job.status!r}"
    )
    assert refreshed_job.completed_at is not None, "CE-0032 impl-end: job.completed_at must be set"


@pytest.mark.asyncio
async def test_be6182_stamped_but_not_staging_complete_is_staging_end(
    db_session: AsyncSession,
    completion_service: JobCompletionService,
    test_tenant_key: str,
    test_product: Product,
):
    """BE-6182 belt-and-suspenders: the closeout-vs-staging-end detector treats a
    complete_job as an implementation CLOSEOUT only when BOTH
    implementation_launched_at is stamped AND staging_status == 'staging_complete'.

    The ANOMALOUS state — implementation_launched_at stamped but staging_status NOT
    'staging_complete' (e.g. 'staging') — is now classified as a STAGING-END, not a
    closeout. (A legitimate staging-end always has implementation_launched_at None,
    so this only re-routes the anomaly; the BE-6181 launch guard is the primary fix.)
    """
    project = await _seed_project(db_session, test_tenant_key, test_product.id, staging_status="staging")
    # Anomalous: stamped, but staging never reached staging_complete.
    project.implementation_launched_at = datetime.now(UTC) - timedelta(hours=1)
    await db_session.commit()
    await db_session.refresh(project)

    job, execution = await _seed_orchestrator_job(db_session, test_tenant_key, project.id, project_phase="staging")

    is_staging_end, returned_project = await completion_service._is_staging_end_orchestrator_call(
        db_session, job, execution, test_tenant_key
    )
    assert is_staging_end is True, (
        "BE-6182: stamped-but-not-staging_complete must be classified as STAGING-END, not closeout"
    )
    assert returned_project is not None and returned_project.id == project.id


@pytest.mark.asyncio
async def test_be6182_stamped_and_staging_complete_is_closeout(
    db_session: AsyncSession,
    completion_service: JobCompletionService,
    test_tenant_key: str,
    test_product: Product,
):
    """BE-6182 complement: the legitimate impl-closeout state (stamped AND
    staging_complete) still returns is_staging_end=False (closeout)."""
    project = await _seed_project(db_session, test_tenant_key, test_product.id, staging_status="staging_complete")
    project.implementation_launched_at = datetime.now(UTC) - timedelta(hours=1)
    await db_session.commit()
    await db_session.refresh(project)

    job, execution = await _seed_orchestrator_job(db_session, test_tenant_key, project.id, project_phase="staging")

    is_staging_end, _ = await completion_service._is_staging_end_orchestrator_call(
        db_session, job, execution, test_tenant_key
    )
    assert is_staging_end is False, "BE-6182: stamped AND staging_complete remains a closeout"


@pytest.mark.asyncio
async def test_staging_end_no_second_exec_spawned(
    db_session: AsyncSession,
    completion_service: JobCompletionService,
    test_tenant_key: str,
    test_product: Product,
):
    """CE-0032 regression guard: staging-end complete_job MUST NOT spawn a
    second orchestrator exec. The CE-0029 Item 2 pre-spawn is gone; the
    same row simply transitions states. Any future re-introduction of a
    spawn helper inside _handle_staging_end would break the
    single-orchestrator-entity invariant.
    """
    project = await _seed_project(db_session, test_tenant_key, test_product.id, staging_status="staging")
    job, _ = await _seed_orchestrator_job(db_session, test_tenant_key, project.id, project_phase="staging")

    # BE-5114: staging-end requires >=1 spawned specialist agent; seed one to reach the gated path.
    await _seed_deliverable_job(
        db_session, test_tenant_key, project.id, job_type="implementer", project_phase="staging"
    )

    await completion_service.complete_job(
        job_id=job.job_id,
        result={"summary": "Staging end — single-exec invariant"},
        tenant_key=test_tenant_key,
    )

    orch_execs = list(
        (
            await db_session.execute(
                select(AgentExecution).where(
                    AgentExecution.job_id == job.job_id,
                    AgentExecution.tenant_key == test_tenant_key,
                    AgentExecution.agent_display_name == "orchestrator",
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(orch_execs) == 1, (
        f"CE-0032 single-exec invariant: staging-end MUST NOT spawn a second orch exec; got {len(orch_execs)}"
    )


# ============================================================================
# CE-0032 — TODOs-bypass key edge cases (re-keyed onto project flags)
# ============================================================================


@pytest.mark.asyncio
async def test_todos_bypass_fires_for_staging_status_staged(
    db_session: AsyncSession,
    completion_service: JobCompletionService,
    test_tenant_key: str,
    test_product: Product,
):
    """CE-0032 bypass edge case: 'staged' status is included defensively in
    the IN clause. An orch reaching complete_job from this state (pathological
    but possible) gets the bypass — no TODOs to block on anyway.
    """
    project = await _seed_project(db_session, test_tenant_key, test_product.id, staging_status="staged")
    job, _ = await _seed_orchestrator_job(db_session, test_tenant_key, project.id, project_phase="staging")
    await _seed_incomplete_todos(db_session, test_tenant_key, job.job_id, count=2)
    # BE-5114: staging-end requires >=1 spawned specialist agent; seed one to reach the gated path.
    await _seed_deliverable_job(
        db_session, test_tenant_key, project.id, job_type="implementer", project_phase="staging"
    )

    result = await completion_service.complete_job(
        job_id=job.job_id,
        result={"summary": "Edge: staged status"},
        tenant_key=test_tenant_key,
    )
    assert result.status == "success", "CE-0032: 'staged' staging_status must hit the bypass"


@pytest.mark.asyncio
async def test_todos_bypass_does_not_fire_when_impl_launched_at_set(
    db_session: AsyncSession,
    completion_service: JobCompletionService,
    test_tenant_key: str,
    test_product: Product,
):
    """CE-0032 bypass edge case: impl_launched_at non-null disqualifies the
    bypass (real impl-end requires TODOs to be done).
    """
    from giljo_mcp.exceptions import ValidationError

    project = await _seed_project(db_session, test_tenant_key, test_product.id, staging_status="staging_complete")
    project.implementation_launched_at = datetime.now(UTC)
    await db_session.commit()
    await db_session.refresh(project)

    job, _ = await _seed_orchestrator_job(db_session, test_tenant_key, project.id, project_phase="staging")
    await _seed_incomplete_todos(db_session, test_tenant_key, job.job_id, count=2)

    with pytest.raises(ValidationError) as exc_info:
        await completion_service.complete_job(
            job_id=job.job_id,
            result={"summary": "Impl end with incomplete TODOs"},
            tenant_key=test_tenant_key,
        )
    assert "COMPLETION_BLOCKED" in str(exc_info.value)
