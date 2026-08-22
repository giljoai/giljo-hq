# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-6181 — launch_implementation staging-complete guard + chain auto-advance.

Regression at the FAILING layer (ProjectStagingService.launch_implementation):

1. The launch gate now refuses a not-yet-staging-complete project with
   ImplementationNotReadyError(reason="staging_incomplete") — closing the hole
   where a premature conductor launch stamped implementation_launched_at and
   mis-routed the project's staging-end complete_job into the closeout gate
   (COMPLETION_BLOCKED -> chain dead-end). It SUCCEEDS (stamps) when the project
   is staging_complete.

2. Launching a chain member advances its active run FORWARD-ONLY (current_index)
   and marks project_statuses[member]="planning" (FE-9493: two-stage lifecycle —
   promoted to "implementing" separately once a worker actually spawns) —
   crossing the gate IS the advance. A solo project (no active run) leaves no
   trace and never errors (byte-identical solo behavior; Deletion Test holds).

DB-touching: uses the db_session fixture (TransactionalTestContext, rollback at
teardown). No module-level mutable state. No ordering dependencies.

Edition Scope: CE.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.exceptions import ImplementationNotReadyError
from giljo_mcp.models.products import Product
from giljo_mcp.models.projects import Project
from giljo_mcp.models.sequence_runs import SequenceRun
from giljo_mcp.services.project_staging_service import ProjectStagingService
from giljo_mcp.services.sequence_run_service import SequenceRunService
from giljo_mcp.tenant import TenantManager
from tests.helpers.taxonomy_seeds import next_series_number


pytestmark = pytest.mark.asyncio


async def _seed_project(
    session: AsyncSession,
    tenant_key: str,
    *,
    staging_status: str | None,
    launched: bool = False,
    closed_out: bool = False,
) -> str:
    # BE-9437: a project belongs to a product. Its own, so an active
    # seed cannot collide under idx_project_single_active_per_product.
    _owning_product_project = Product(
        id=str(uuid.uuid4()),
        tenant_key=tenant_key,
        name=f"Owning Product {uuid.uuid4().hex[:6]}",
        description="seeded",
        is_active=False,
    )
    session.add(_owning_product_project)
    project = Project(
        id=str(uuid.uuid4()),
        name=f"BE-6181 {uuid.uuid4().hex[:6]}",
        description="Launch-gate test project.",
        mission="Launch test.",
        status="active",
        tenant_key=tenant_key,
        product_id=_owning_product_project.id,
        # BE-9429: uq_project_taxonomy_active is NULLS NOT DISTINCT, so these
        # NULL-product/NULL-type rows collide unless the serial differs.
        series_number=next_series_number(),
        execution_mode="claude_code_cli",
        staging_status=staging_status,
        created_at=datetime.now(UTC),
        implementation_launched_at=datetime.now(UTC) if launched else None,
        # BE-6188: closeout_executed_at is the commit-SHA advance signal the
        # chain auto-advance guard keys on (a prior project must be closed out
        # before current_index bumps past it).
        closeout_executed_at=datetime.now(UTC) if closed_out else None,
    )
    session.add(project)
    session.info["tenant_key"] = tenant_key
    await session.flush()
    return project.id


async def _seed_run(
    session: AsyncSession,
    tenant_key: str,
    *,
    resolved_order: list[str],
    current_index: int = 0,
    project_statuses: dict[str, str] | None = None,
) -> str:
    run_id = str(uuid.uuid4())
    run = SequenceRun(
        id=run_id,
        tenant_key=tenant_key,
        project_ids=resolved_order,
        resolved_order=resolved_order,
        current_index=current_index,
        execution_mode="claude_code_cli",
        status="running",
        review_policy="per_card",
        project_statuses=project_statuses or {},
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    session.add(run)
    await session.flush()
    return run_id


def _staging_svc(session: AsyncSession) -> ProjectStagingService:
    return ProjectStagingService(
        db_manager=None,  # type: ignore[arg-type]
        tenant_manager=TenantManager(),
        test_session=session,
    )


# ---------------------------------------------------------------------------
# Task 1 — staging-complete guard
# ---------------------------------------------------------------------------


async def test_launch_refuses_when_staging_not_complete(db_session: AsyncSession) -> None:
    """A not-yet-staging-complete project is refused with reason=staging_incomplete."""
    tenant = TenantManager.generate_tenant_key()
    pid = await _seed_project(db_session, tenant, staging_status="staging")

    svc = _staging_svc(db_session)
    with pytest.raises(ImplementationNotReadyError) as exc:
        await svc.launch_implementation(project_id=pid, tenant_key=tenant)

    assert exc.value.reason == "staging_incomplete"

    # The gate is sacred: the stamp must NOT have been written.
    refreshed = await db_session.get(Project, pid)
    assert refreshed.implementation_launched_at is None


async def test_launch_succeeds_when_staging_complete(db_session: AsyncSession) -> None:
    """A staging_complete project launches and stamps implementation_launched_at."""
    tenant = TenantManager.generate_tenant_key()
    pid = await _seed_project(db_session, tenant, staging_status="staging_complete")

    svc = _staging_svc(db_session)
    result = await svc.launch_implementation(project_id=pid, tenant_key=tenant)

    assert result["success"] is True
    assert result["already_launched"] is False
    refreshed = await db_session.get(Project, pid)
    assert refreshed.implementation_launched_at is not None


async def test_relaunch_skips_guard_and_is_idempotent(db_session: AsyncSession) -> None:
    """A re-launch (already_launched) skips the guard and returns unchanged."""
    tenant = TenantManager.generate_tenant_key()
    # already launched, and staging_status deliberately NOT complete: the guard is
    # inside `if not already_launched`, so a re-launch must NOT trip it.
    pid = await _seed_project(db_session, tenant, staging_status="staging", launched=True)

    svc = _staging_svc(db_session)
    result = await svc.launch_implementation(project_id=pid, tenant_key=tenant)

    assert result["already_launched"] is True


# ---------------------------------------------------------------------------
# Task 2 — chain auto-advance
# ---------------------------------------------------------------------------


async def test_launch_advances_chain_member_forward(db_session: AsyncSession) -> None:
    """Launching a chain member at idx 1 advances current_index forward + marks planning.

    BE-6188: the advance now requires the prior project (p0) to have closed out
    (closeout_executed_at set) — the commit-SHA gate. p0 is seeded closed_out.
    """
    tenant = TenantManager.generate_tenant_key()
    p0 = await _seed_project(db_session, tenant, staging_status="staging_complete", closed_out=True)
    p1 = await _seed_project(db_session, tenant, staging_status="staging_complete")
    run_id = await _seed_run(
        db_session,
        tenant,
        resolved_order=[p0, p1],
        current_index=0,
        project_statuses={p0: "completed"},
    )

    svc = _staging_svc(db_session)
    await svc.launch_implementation(project_id=p1, tenant_key=tenant)

    run_svc = SequenceRunService(db_manager=None, tenant_manager=TenantManager(), session=db_session)
    run = await run_svc.get(run_id=run_id, tenant_key=tenant)
    assert run["current_index"] == 1  # advanced forward to idx of p1
    assert run["project_statuses"][p1] == "planning"
    assert run["project_statuses"][p0] == "completed"  # merge preserved


async def test_launch_advance_blocked_without_prior_closeout(db_session: AsyncSession) -> None:
    """BE-6188: launching p1 does NOT advance current_index past p0 while p0 has no
    closeout (the commit-SHA gate). The launch itself still succeeds and p1 is marked
    planning; only the index stays put until p0 closes out."""
    tenant = TenantManager.generate_tenant_key()
    p0 = await _seed_project(db_session, tenant, staging_status="staging_complete")  # NOT closed out
    p1 = await _seed_project(db_session, tenant, staging_status="staging_complete")
    run_id = await _seed_run(
        db_session,
        tenant,
        resolved_order=[p0, p1],
        current_index=0,
    )

    svc = _staging_svc(db_session)
    await svc.launch_implementation(project_id=p1, tenant_key=tenant)

    run_svc = SequenceRunService(db_manager=None, tenant_manager=TenantManager(), session=db_session)
    run = await run_svc.get(run_id=run_id, tenant_key=tenant)
    assert run["current_index"] == 0  # advance BLOCKED — p0 never closed out
    assert run["project_statuses"][p1] == "planning"  # status still applied


async def test_launch_advance_is_forward_only(db_session: AsyncSession) -> None:
    """Launching an EARLIER member never rewinds current_index (forward-only)."""
    tenant = TenantManager.generate_tenant_key()
    p0 = await _seed_project(db_session, tenant, staging_status="staging_complete")
    p1 = await _seed_project(db_session, tenant, staging_status="staging_complete")
    run_id = await _seed_run(
        db_session,
        tenant,
        resolved_order=[p0, p1],
        current_index=1,  # already past p0
    )

    svc = _staging_svc(db_session)
    await svc.launch_implementation(project_id=p0, tenant_key=tenant)

    run_svc = SequenceRunService(db_manager=None, tenant_manager=TenantManager(), session=db_session)
    run = await run_svc.get(run_id=run_id, tenant_key=tenant)
    assert run["current_index"] == 1  # NOT rewound to 0
    assert run["project_statuses"][p0] == "planning"


async def test_solo_launch_leaves_no_run_trace(db_session: AsyncSession) -> None:
    """A solo project (no active run) launches with no chain side-effect and no error."""
    tenant = TenantManager.generate_tenant_key()
    pid = await _seed_project(db_session, tenant, staging_status="staging_complete")

    svc = _staging_svc(db_session)
    result = await svc.launch_implementation(project_id=pid, tenant_key=tenant)

    assert result["success"] is True
    # No run exists for this project — find returns None, so nothing was written.
    run_svc = SequenceRunService(db_manager=None, tenant_manager=TenantManager(), session=db_session)
    assert await run_svc.find_active_run_for_project(project_id=pid, tenant_key=tenant) is None
