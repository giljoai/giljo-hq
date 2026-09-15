# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


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
    suffix = uuid.uuid4().hex[:8]
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

    await session.flush()

    project = Project(
        id=str(uuid.uuid4()),
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
    tenant_a = TenantManager.generate_tenant_key()
    await _seed_active_job(db_session, tenant_a)
    await db_session.flush()
    _strip_session_tenant_context(db_session)

    with pytest.raises(TenantIsolationError):
        await db_session.execute(_all_tenants_query())


@pytest.mark.asyncio
async def test_get_all_tenants_completes_under_bypass(db_session: AsyncSession) -> None:
    tenant_a = TenantManager.generate_tenant_key()
    tenant_b = TenantManager.generate_tenant_key()
    await _seed_active_job(db_session, tenant_a)
    await _seed_active_job(db_session, tenant_b)
    await db_session.flush()

    monitor = AgentHealthMonitor(db_manager=None, ws_manager=None)  # type: ignore[arg-type]
    tenants = await monitor._get_all_tenants(db_session)

    assert tenant_a in tenants
    assert tenant_b in tenants
    assert TenantManager.get_current_tenant() is None


@pytest.mark.asyncio
async def test_scan_tenant_jobs_raises_without_context(db_session: AsyncSession) -> None:
    tenant_a = TenantManager.generate_tenant_key()
    await _seed_active_job(db_session, tenant_a)
    await db_session.flush()
    _strip_session_tenant_context(db_session)

    monitor = AgentHealthMonitor(db_manager=None, ws_manager=None)  # type: ignore[arg-type]
    with pytest.raises(TenantIsolationError):
        await monitor._scan_tenant_jobs(db_session, tenant_a)


@pytest.mark.asyncio
async def test_run_health_check_cycle_scopes_each_tenant_under_enforce(db_session: AsyncSession) -> None:
    from contextlib import asynccontextmanager
    from unittest.mock import AsyncMock, MagicMock

    tenant_a = TenantManager.generate_tenant_key()
    tenant_b = TenantManager.generate_tenant_key()
    ancient = datetime.now(UTC) - timedelta(days=3)
    await _seed_active_job(db_session, tenant_a)
    await _seed_active_job(db_session, tenant_b, started_at=ancient)
    await db_session.flush()
    _strip_session_tenant_context(db_session)

    class _SingleSessionDB:

        @asynccontextmanager
        async def get_session_async(self):
            yield db_session

    ws = MagicMock()
    ws.broadcast_event_to_tenant = AsyncMock()
    monitor = AgentHealthMonitor(db_manager=_SingleSessionDB(), ws_manager=ws)  # type: ignore[arg-type]

    seeded = {tenant_a, tenant_b}
    real_get_all_tenants = monitor._get_all_tenants

    async def _scoped_get_all_tenants(session: AsyncSession) -> list[str]:
        return [t for t in await real_get_all_tenants(session) if t in seeded]

    monitor._get_all_tenants = _scoped_get_all_tenants
    monitor._first_scan = False

    await monitor._run_health_check_cycle()

    auto_failed_calls = [
        call
        for call in ws.broadcast_event_to_tenant.await_args_list
        if call.kwargs.get("event", {}).get("type") == "agent:auto_failed"
    ]
    assert auto_failed_calls, "expected an agent:auto_failed broadcast for the ancient execution"

    assert TenantManager.get_current_tenant() is None


@pytest.mark.asyncio
async def test_purge_discovery_reads_raise_without_bypass(db_session: AsyncSession) -> None:
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
