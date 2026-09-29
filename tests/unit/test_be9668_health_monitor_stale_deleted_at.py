# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.database import tenant_session_context
from giljo_mcp.models import Product, Project
from giljo_mcp.models.agent_identity import AgentExecution, AgentJob
from giljo_mcp.monitoring.agent_health_monitor import AgentHealthMonitor
from giljo_mcp.monitoring.health_config import HealthCheckConfig
from giljo_mcp.tenant import TenantManager


pytestmark = pytest.mark.asyncio


async def _seed_waiting_job(session: AsyncSession, tenant_key: str, *, stale_deleted_at: bool) -> AgentJob:
    suffix = uuid.uuid4().hex[:8]
    created = datetime.now(UTC) - timedelta(minutes=10)

    product = Product(
        id=str(uuid.uuid4()),
        tenant_key=tenant_key,
        name=f"BE-9668 HealthProd {suffix}",
        description="seed",
        is_active=False,
    )
    session.add(product)
    await session.flush()

    project = Project(
        id=str(uuid.uuid4()),
        product_id=product.id,
        name=f"BE-9668 HealthProj {suffix}",
        description="seed",
        mission="m",
        status="active",
        tenant_key=tenant_key,
        series_number=1,
        created_at=created,
        deleted_at=datetime.now(UTC) if stale_deleted_at else None,
    )
    session.add(project)
    await session.flush()

    job = AgentJob(
        job_id=str(uuid.uuid4()),
        tenant_key=tenant_key,
        project_id=project.id,
        job_type="worker",
        mission="seed job",
        status="active",
        created_at=created,
        job_metadata={},
    )
    session.add(job)

    execution = AgentExecution(
        agent_id=str(uuid.uuid4()),
        job_id=job.job_id,
        tenant_key=tenant_key,
        agent_display_name="worker",
        agent_name="Seed Worker",
        status="waiting",
        health_status="unknown",
        progress=0,
        tool_type="universal",
        started_at=created,
        last_progress_at=created,
    )
    session.add(execution)
    await session.commit()
    return job


async def test_waiting_timeout_alerts_on_a_stale_deleted_at_project(db_session: AsyncSession) -> None:
    config = HealthCheckConfig(waiting_timeout_minutes=2)
    monitor = AgentHealthMonitor(db_manager=None, ws_manager=None, config=config)  # type: ignore[arg-type]

    tenant = TenantManager.generate_tenant_key()
    job = await _seed_waiting_job(db_session, tenant, stale_deleted_at=True)

    with tenant_session_context(db_session, tenant):
        results = await monitor._detect_waiting_timeouts(db_session, tenant)

    matched = [r for r in results if r.job_id == job.job_id]
    assert matched, "a stale-shape live project's waiting job must still be detected and alerted"
