# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""Background/cross-tenant-scan regression tests for BE6004C-5 (RC-5).

Bug class: legitimately cross-tenant discovery reads enumerate EVERY tenant by
design and so cannot supply a single ``tenant_key``. Under the fail-closed
``do_orm_execute`` guard they raised ``TenantIsolationError`` at lifespan
startup (``AgentHealthMonitor._get_all_tenants`` and
``purge_expired_deleted_items``), taking the background tasks down.

The fix wraps each discovery read in a SCOPED ``tenant_isolation_bypass`` with
an honest reason and a model tuple limited to the tenant-scoped entities the
statement touches. The bypass is the correct, audited mechanism -- not a leak:
it is explicit, reasoned, and model-scoped. The per-tenant work that FOLLOWS a
discovery stays tenant-scoped (not under the bypass).

These tests exercise the FAILING layer -- the real ``do_orm_execute`` guard --
against a REAL transactional database session with NO tenant context, proving:
  1. the discovery read RAISES TenantIsolationError WITHOUT the bypass, and
  2. it COMPLETES across multiple tenants WITH the bypass.

Parallel-safe: each test runs inside ``TransactionalTestContext`` (rolled back
at teardown) and seeds unique ``tk_...`` tenants; no module-level mutable
state; no ordering dependency. Runs under the default ``enforce`` guard mode.

Project: BE6004C-5 (RC-5).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.database import (
    TENANT_BYPASS_MODELS_KEY,
    TENANT_BYPASS_REASON_KEY,
    TENANT_CONTEXT_SOURCE_KEY,
    TenantIsolationError,
    tenant_isolation_bypass,
)
from giljo_mcp.domain.project_status import ProjectStatus
from giljo_mcp.models import Product, Project
from giljo_mcp.models.agent_identity import AgentExecution, AgentJob
from giljo_mcp.monitoring.agent_health_monitor import AgentHealthMonitor
from giljo_mcp.tenant import TenantManager


async def _seed_active_job(session: AsyncSession, tenant_key: str, started_at: datetime | None = None) -> None:
    """Seed an active Project + AgentJob + AgentExecution for one tenant.

    ``started_at`` defaults to now (healthy); pass an ancient timestamp to seed
    an execution past the abandon ceiling (exercises the auto-fail handler).
    """
    suffix = uuid.uuid4().hex[:8]
    # BE-9437: a project belongs to a product. Its own, so the ACTIVE status here
    # cannot collide with another seed under idx_project_single_active_per_product.
    product = Product(
        id=str(uuid.uuid4()),
        name=f"BE6004C-5 HealthProd {suffix}",
        tenant_key=tenant_key,
        is_active=False,
        product_memory={},
    )
    session.add(product)
    await session.flush()

    project = Project(
        id=str(uuid.uuid4()),
        product_id=product.id,
        name=f"BE6004C-5 HealthProj {suffix}",
        description="RC-5 health-scan seed.",
        mission="m",
        status="active",
        tenant_key=tenant_key,
        series_number=1,
        created_at=datetime.now(UTC),
    )
    session.add(project)

    job = AgentJob(
        job_id=str(uuid.uuid4()),
        tenant_key=tenant_key,
        project_id=project.id,
        job_type="worker",
        mission="seed job",
        status="active",
        created_at=datetime.now(UTC),
        job_metadata={},
    )
    session.add(job)

    execution = AgentExecution(
        agent_id=str(uuid.uuid4()),
        job_id=job.job_id,
        tenant_key=tenant_key,
        agent_display_name="worker",
        agent_name="Seed Worker",
        status="working",
        progress=10,
        tool_type="universal",
        started_at=started_at or datetime.now(UTC),
    )
    session.add(execution)


async def _seed_expired_deleted(session: AsyncSession, tenant_key: str) -> None:
    """Seed an expired soft-deleted Project + Product for one tenant."""
    suffix = uuid.uuid4().hex[:8]
    old = datetime.now(UTC) - timedelta(days=30)
    product = Product(
        id=str(uuid.uuid4()),
        name=f"BE6004C-5 DeletedProd {suffix}",
        description="RC-5 purge seed.",
        tenant_key=tenant_key,
        is_active=False,
        product_memory={},
        deleted_at=old,
    )
    session.add(product)

    await session.flush()  # the product must exist before the project's FK points at it

    project = Project(
        id=str(uuid.uuid4()),
        # BE-9437: binds to the soft-deleted product seeded just above, which is
        # the pairing this purge test is actually about.
        product_id=product.id,
        name=f"BE6004C-5 DeletedProj {suffix}",
        description="RC-5 purge seed.",
        mission="m",
        status="active",
        tenant_key=tenant_key,
        series_number=1,
        created_at=old,
        deleted_at=old,
    )
    session.add(project)


def _strip_session_tenant_context(session: AsyncSession) -> None:
    """Clear any flush-derived tenant stamp so the guard sees NO context.

    The seed ``flush()`` records a single-tenant context via the after_flush
    listener (``_record_single_tenant_flush``); to assert the contextless
    baseline (no tenant anywhere) we must drop that stamp -- exactly the state
    the background scans run in at lifespan startup.
    """
    session.info.pop("tenant_key", None)
    session.info.pop(TENANT_CONTEXT_SOURCE_KEY, None)
    session.info.pop(TENANT_BYPASS_MODELS_KEY, None)
    session.info.pop(TENANT_BYPASS_REASON_KEY, None)


def _all_tenants_query():
    return (
        select(AgentExecution.tenant_key)
        .distinct()
        .join(AgentJob, AgentExecution.job_id == AgentJob.job_id)
        .outerjoin(Project, AgentJob.project_id == Project.id)
        .where(
            or_(
                AgentJob.project_id.is_(None),
                and_(
                    Project.deleted_at.is_(None),
                    Project.status == ProjectStatus.ACTIVE,
                ),
            )
        )
    )


@pytest.mark.asyncio
async def test_get_all_tenants_raises_without_bypass(db_session: AsyncSession) -> None:
    """RC-5: the cross-tenant health-scan query RAISES with no tenant context.

    This is the baseline failure the bypass repairs: the discovery read touches
    {AgentExecution, AgentJob, Project} on a session with no tenant_key, so the
    fail-closed guard refuses to authorize it.
    """
    tenant_a = TenantManager.generate_tenant_key()
    await _seed_active_job(db_session, tenant_a)
    await db_session.flush()
    _strip_session_tenant_context(db_session)

    with pytest.raises(TenantIsolationError):
        await db_session.execute(_all_tenants_query())


@pytest.mark.asyncio
async def test_get_all_tenants_completes_under_bypass(db_session: AsyncSession) -> None:
    """RC-5: AgentHealthMonitor._get_all_tenants enumerates EVERY seeded tenant.

    The method wraps the discovery read in a scoped tenant_isolation_bypass, so
    it returns tenant keys across multiple tenants on a session with no ambient
    tenant context -- the exact cross-tenant behavior the scan needs.
    """
    tenant_a = TenantManager.generate_tenant_key()
    tenant_b = TenantManager.generate_tenant_key()
    await _seed_active_job(db_session, tenant_a)
    await _seed_active_job(db_session, tenant_b)
    await db_session.flush()

    monitor = AgentHealthMonitor(db_manager=None, ws_manager=None)  # type: ignore[arg-type]
    tenants = await monitor._get_all_tenants(db_session)

    assert tenant_a in tenants
    assert tenant_b in tenants
    # No tenant context leaked onto the shared ContextVar by the scan.
    assert TenantManager.get_current_tenant() is None


@pytest.mark.asyncio
async def test_scan_tenant_jobs_raises_without_context(db_session: AsyncSession) -> None:
    """RC-5 follow-on (enforce gap found live): the PER-TENANT detection scan
    RAISES with no tenant context.

    ``_get_all_tenants`` runs under a bypass, but the per-tenant detection
    queries (``_detect_waiting_timeouts`` et al.) carry explicit
    ``tenant_key ==`` predicates and so need that tenant's context on the
    session. Without it the fail-closed guard refuses the explicit predicate --
    exactly the ``Health check cycle failed: ... explicit tenant predicates do
    not provide tenant context`` seen on test.giljo.ai right after the
    enforce-flip.
    """
    tenant_a = TenantManager.generate_tenant_key()
    await _seed_active_job(db_session, tenant_a)
    await db_session.flush()
    _strip_session_tenant_context(db_session)

    monitor = AgentHealthMonitor(db_manager=None, ws_manager=None)  # type: ignore[arg-type]
    with pytest.raises(TenantIsolationError):
        await monitor._scan_tenant_jobs(db_session, tenant_a)


@pytest.mark.asyncio
async def test_run_health_check_cycle_scopes_each_tenant_under_enforce(db_session: AsyncSession) -> None:
    """RC-5 follow-on: the FULL cycle completes under enforce across tenants.

    ``_run_health_check_cycle`` enumerates tenants under a cross-tenant bypass
    and then runs each tenant's detection/handler queries inside that tenant's
    own ``tenant_session_context``. With NO ambient ContextVar and the guard in
    enforce, the cycle must complete without raising -- the regression gate for
    the live enforce gap. (Without the per-tenant scoping it raises on the first
    tenant's scan.)

    Hermetic (INF-9189): the per-tenant loop is scoped to THIS test's own
    seeded tenants, so leaked/foreign rows in a shared dev DB can never steer
    it — the real cross-tenant discovery still executes under its bypass (the
    enforce regression this test gates). Tenant_b seeds an execution past the
    abandon ceiling so the full auto-fail handler path (tenant-scoped write +
    ``broadcast_agent_auto_failed``) runs deterministically under enforce —
    previously nothing was ever unhealthy, the handler never ran, and the WS
    stub's bare-MagicMock ``broadcast_agent_auto_failed`` exploded only when
    foreign leaked rows crossed the ceiling.
    """
    from contextlib import asynccontextmanager
    from unittest.mock import AsyncMock, MagicMock

    tenant_a = TenantManager.generate_tenant_key()
    tenant_b = TenantManager.generate_tenant_key()
    ancient = datetime.now(UTC) - timedelta(days=3)  # past the 1440m abandon ceiling
    await _seed_active_job(db_session, tenant_a)
    await _seed_active_job(db_session, tenant_b, started_at=ancient)
    await db_session.flush()
    _strip_session_tenant_context(db_session)

    class _SingleSessionDB:
        """Yield the transactional test session as the cycle's 'own' session."""

        @asynccontextmanager
        async def get_session_async(self):
            yield db_session

    # Complete broadcaster stub: BOTH async broadcast methods the per-tenant
    # handler can await must be AsyncMock (a bare MagicMock raises TypeError
    # on await — the exact failure leaked foreign rows used to trigger).
    ws = MagicMock()
    ws.broadcast_health_alert = AsyncMock()
    ws.broadcast_agent_auto_failed = AsyncMock()
    monitor = AgentHealthMonitor(db_manager=_SingleSessionDB(), ws_manager=ws)  # type: ignore[arg-type]

    # Scope the per-tenant loop to this test's own tenants: the REAL discovery
    # read still runs (under its bypass, against the enforce guard), but any
    # foreign tenants present in the DB are filtered out afterwards.
    seeded = {tenant_a, tenant_b}
    real_get_all_tenants = monitor._get_all_tenants

    async def _scoped_get_all_tenants(session: AsyncSession) -> list[str]:
        return [t for t in await real_get_all_tenants(session) if t in seeded]

    monitor._get_all_tenants = _scoped_get_all_tenants  # instance-only patch
    # Skip the first-scan alert suppression so the ancient seed actually
    # reaches the handler this cycle (simulates a steady-state, non-first scan).
    monitor._first_scan = False

    # Must not raise: discovery under bypass, per-tenant scans under each
    # tenant's own context.
    await monitor._run_health_check_cycle()

    # The ancient in-scope execution crossed the abandon ceiling: the handler
    # ran its tenant-scoped write and awaited the auto-fail broadcast.
    ws.broadcast_agent_auto_failed.assert_awaited()

    # The cycle leaves no tenant context leaked on the shared ContextVar.
    assert TenantManager.get_current_tenant() is None


@pytest.mark.asyncio
async def test_purge_discovery_reads_raise_without_bypass(db_session: AsyncSession) -> None:
    """RC-5: purge tenant-discovery reads RAISE with no tenant context (baseline)."""
    tenant_a = TenantManager.generate_tenant_key()
    await _seed_expired_deleted(db_session, tenant_a)
    await db_session.flush()
    _strip_session_tenant_context(db_session)

    cutoff = datetime.now(UTC) - timedelta(days=10)
    project_stmt = (
        select(Project.tenant_key).distinct().where(Project.deleted_at.isnot(None), Project.deleted_at < cutoff)
    )
    product_stmt = (
        select(Product.tenant_key).distinct().where(Product.deleted_at.isnot(None), Product.deleted_at < cutoff)
    )

    with pytest.raises(TenantIsolationError):
        await db_session.execute(project_stmt)
    with pytest.raises(TenantIsolationError):
        await db_session.execute(product_stmt)


@pytest.mark.asyncio
async def test_purge_discovery_reads_complete_under_bypass(db_session: AsyncSession) -> None:
    """RC-5: the purge discovery reads enumerate expired-deleted tenants under the bypass.

    Mirrors the wrapped block in ``purge_expired_deleted_items``: both DISTINCT
    tenant_key reads run inside one scoped bypass covering (Project, Product),
    returning every tenant with expired deleted items across the DB.
    """
    tenant_a = TenantManager.generate_tenant_key()
    tenant_b = TenantManager.generate_tenant_key()
    await _seed_expired_deleted(db_session, tenant_a)
    await _seed_expired_deleted(db_session, tenant_b)
    await db_session.flush()

    cutoff = datetime.now(UTC) - timedelta(days=10)
    project_stmt = (
        select(Project.tenant_key).distinct().where(Project.deleted_at.isnot(None), Project.deleted_at < cutoff)
    )
    product_stmt = (
        select(Product.tenant_key).distinct().where(Product.deleted_at.isnot(None), Product.deleted_at < cutoff)
    )

    with tenant_isolation_bypass(
        db_session,
        reason="cross-tenant maintenance scan: enumerate tenants for purge",
        models=(Project, Product),
    ):
        project_tenants = {row[0] for row in (await db_session.execute(project_stmt)).fetchall()}
        product_tenants = {row[0] for row in (await db_session.execute(product_stmt)).fetchall()}

    all_tenants = project_tenants | product_tenants
    assert {tenant_a, tenant_b}.issubset(all_tenants)
    assert TenantManager.get_current_tenant() is None
