# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-9098: SequenceRunService.mark_member_reviewed — durable chain review ack.

Regression at the SERVICE layer, where the bug lived: before this write, chain
per-member review acknowledgment existed ONLY in a client-side Pinia Map, so it
evaporated on refresh and the Review badge returned every page load. The fix
persists it to ``sequence_runs.reviewed_project_ids``. These tests exercise the
owning service directly:

  * the ack is readable back (persistence — the core regression);
  * idempotent (re-marking is a no-op, no duplicates);
  * tenant-isolated (a foreign run is a 404, not a cross-tenant write);
  * NON-GATING (project_statuses is never touched → purge_run / advancement
    behaviour is unchanged);
  * membership + input guards (422, not a 500 or unbounded growth).

Parallel-safe: DB-touching tests use db_session (TransactionalTestContext). No
module-level mutable state. Edition Scope: CE.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.exceptions import ResourceNotFoundError, ValidationError
from giljo_mcp.models import Product, Project
from giljo_mcp.models.sequence_runs import CHAIN_TERMINAL_PROJECT_STATUSES
from giljo_mcp.services.sequence_run_service import SequenceRunService
from giljo_mcp.tenant import TenantManager
from tests.helpers.taxonomy_seeds import next_series_number


async def _seed_project(session: AsyncSession, tenant_key: str) -> str:
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
        name=f"BE-9098 {uuid.uuid4().hex[:6]}",
        description="Chain member.",
        mission="Be a chain member.",
        status="active",
        tenant_key=tenant_key,
        product_id=_owning_product_project.id,
        # BE-9429: uq_project_taxonomy_active is NULLS NOT DISTINCT, so these
        # NULL-product/NULL-type rows collide unless the serial differs.
        series_number=next_series_number(),
        execution_mode="claude_code_cli",
        created_at=datetime.now(UTC),
    )
    session.add(project)
    session.info["tenant_key"] = tenant_key
    await session.flush()
    return project.id


def _run_svc(session: AsyncSession) -> SequenceRunService:
    return SequenceRunService(db_manager=None, tenant_manager=TenantManager(), session=session)


async def _make_run(session: AsyncSession, tenant: str) -> tuple[SequenceRunService, dict, str, str]:
    p1 = await _seed_project(session, tenant)
    p2 = await _seed_project(session, tenant)
    svc = _run_svc(session)
    run = await svc.create(
        project_ids=[p1, p2],
        resolved_order=[p1, p2],
        execution_mode="claude_code_cli",
        tenant_key=tenant,
        project_statuses={p1: "completed", p2: "completed"},
    )
    return svc, run, p1, p2


@pytest.mark.asyncio
async def test_mark_member_reviewed_persists_and_reads_back(db_session: AsyncSession) -> None:
    """The core regression: a review ack is durably written and reads back."""
    tenant = TenantManager.generate_tenant_key()
    svc, run, p1, _p2 = await _make_run(db_session, tenant)
    assert run["reviewed_project_ids"] == []

    updated = await svc.mark_member_reviewed(run_id=run["id"], project_id=p1, tenant_key=tenant)
    assert updated["reviewed_project_ids"] == [p1]

    # Read back through a fresh get() — proves it survives, not just an in-memory echo.
    refetched = await svc.get(run_id=run["id"], tenant_key=tenant)
    assert refetched["reviewed_project_ids"] == [p1]


@pytest.mark.asyncio
async def test_mark_member_reviewed_is_idempotent(db_session: AsyncSession) -> None:
    """Re-marking the same member is a no-op — no duplicates, no error."""
    tenant = TenantManager.generate_tenant_key()
    svc, run, p1, _p2 = await _make_run(db_session, tenant)

    await svc.mark_member_reviewed(run_id=run["id"], project_id=p1, tenant_key=tenant)
    again = await svc.mark_member_reviewed(run_id=run["id"], project_id=p1, tenant_key=tenant)

    assert again["reviewed_project_ids"] == [p1]


@pytest.mark.asyncio
async def test_mark_member_reviewed_appends_multiple_members(db_session: AsyncSession) -> None:
    """Distinct members accumulate (append-only, order preserved)."""
    tenant = TenantManager.generate_tenant_key()
    svc, run, p1, p2 = await _make_run(db_session, tenant)

    await svc.mark_member_reviewed(run_id=run["id"], project_id=p1, tenant_key=tenant)
    both = await svc.mark_member_reviewed(run_id=run["id"], project_id=p2, tenant_key=tenant)

    assert both["reviewed_project_ids"] == [p1, p2]


@pytest.mark.asyncio
async def test_mark_member_reviewed_does_not_touch_project_statuses(db_session: AsyncSession) -> None:
    """NON-GATING invariant: review never mutates project_statuses, so chain
    advancement / purge_run (which key on CHAIN_TERMINAL_PROJECT_STATUSES) are
    unaffected. 'awaiting_review' must never appear."""
    tenant = TenantManager.generate_tenant_key()
    svc, run, p1, _p2 = await _make_run(db_session, tenant)
    before = run["project_statuses"]

    updated = await svc.mark_member_reviewed(run_id=run["id"], project_id=p1, tenant_key=tenant)

    assert updated["project_statuses"] == before
    assert "awaiting_review" not in updated["project_statuses"].values()
    # Every member stays terminal → purge/advancement semantics unchanged.
    assert all(st in CHAIN_TERMINAL_PROJECT_STATUSES for st in updated["project_statuses"].values())


@pytest.mark.asyncio
async def test_mark_member_reviewed_tenant_isolated(db_session: AsyncSession) -> None:
    """A run created under tenant A is not markable under tenant B (404, no write)."""
    tenant_a = TenantManager.generate_tenant_key()
    tenant_b = TenantManager.generate_tenant_key()
    svc, run, p1, _p2 = await _make_run(db_session, tenant_a)

    with pytest.raises(ResourceNotFoundError):
        await svc.mark_member_reviewed(run_id=run["id"], project_id=p1, tenant_key=tenant_b)

    # Tenant A's run is untouched.
    refetched = await svc.get(run_id=run["id"], tenant_key=tenant_a)
    assert refetched["reviewed_project_ids"] == []


@pytest.mark.asyncio
async def test_mark_member_reviewed_rejects_non_member(db_session: AsyncSession) -> None:
    """A project_id that is not a member of the run is a 422, not a silent write."""
    tenant = TenantManager.generate_tenant_key()
    svc, run, _p1, _p2 = await _make_run(db_session, tenant)

    with pytest.raises(ValidationError):
        await svc.mark_member_reviewed(run_id=run["id"], project_id="not-a-member", tenant_key=tenant)


@pytest.mark.asyncio
async def test_mark_member_reviewed_rejects_empty_project_id(db_session: AsyncSession) -> None:
    """An empty/blank project_id is a 422 input guard."""
    tenant = TenantManager.generate_tenant_key()
    svc, run, _p1, _p2 = await _make_run(db_session, tenant)

    with pytest.raises(ValidationError):
        await svc.mark_member_reviewed(run_id=run["id"], project_id="   ", tenant_key=tenant)


@pytest.mark.asyncio
async def test_mark_member_reviewed_unknown_run_is_404(db_session: AsyncSession) -> None:
    """An unknown run id raises ResourceNotFoundError (-> 404)."""
    tenant = TenantManager.generate_tenant_key()
    svc = _run_svc(db_session)

    with pytest.raises(ResourceNotFoundError):
        await svc.mark_member_reviewed(run_id="no-such-run", project_id="p1", tenant_key=tenant)
