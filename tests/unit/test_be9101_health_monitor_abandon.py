# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.database import tenant_session_context
from giljo_mcp.models import Product, Project
from giljo_mcp.models.agent_identity import AgentExecution, AgentJob
from giljo_mcp.models.sequence_runs import CHAIN_TERMINAL_PROJECT_STATUSES
from giljo_mcp.monitoring.agent_health_monitor import AgentHealthMonitor
from giljo_mcp.monitoring.health_config import AgentHealthStatus, HealthCheckConfig
from giljo_mcp.tenant import TenantManager


async def _seed_execution(
    session: AsyncSession,
    tenant_key: str,
    *,
    status: str = "working",
    last_progress_minutes_ago: float = 40.0,
    agent_display_name: str = "worker",
    health_status: str = "unknown",
    project_status: str = "active",
) -> AgentExecution:
    suffix = uuid.uuid4().hex[:8]
    then = datetime.now(UTC) - timedelta(minutes=last_progress_minutes_ago)

    product = Product(
        id=str(uuid.uuid4()),
        tenant_key=tenant_key,
        name=f"BE-9101 HealthProd {suffix}",
        description="BE-9101 abandon-monitor seed.",
        is_active=False,
    )
    session.add(product)
    await session.flush()

    project = Project(
        id=str(uuid.uuid4()),
        product_id=product.id,
        name=f"BE-9101 HealthProj {suffix}",
        description="BE-9101 abandon-monitor seed.",
        mission="m",
        status=project_status,
        tenant_key=tenant_key,
        series_number=1,
        created_at=then,
    )
    session.add(project)

    job = AgentJob(
        job_id=str(uuid.uuid4()),
        tenant_key=tenant_key,
        project_id=project.id,
        job_type="worker",
        mission="seed job",
        status="active",
        created_at=then,
        job_metadata={},
    )
    session.add(job)

    execution = AgentExecution(
        agent_id=str(uuid.uuid4()),
        job_id=job.job_id,
        tenant_key=tenant_key,
        agent_display_name=agent_display_name,
        agent_name="Seed Worker",
        status=status,
        health_status=health_status,
        progress=10,
        tool_type="universal",
        started_at=then,
        last_progress_at=then,
    )
    session.add(execution)
    await session.flush()
    return execution


def _make_ws() -> MagicMock:
    ws = MagicMock()
    ws.broadcast_event_to_tenant = AsyncMock()
    return ws


def _event_call_count(ws: MagicMock, event_type: str) -> int:
    return sum(
        1
        for call in ws.broadcast_event_to_tenant.await_args_list
        if call.kwargs.get("event", {}).get("type") == event_type
    )


def _hs(execution: AgentExecution, *, health_state: str, minutes: float) -> AgentHealthStatus:
    return AgentHealthStatus(
        execution_id=execution.id,
        job_id=execution.job_id,
        agent_id=execution.agent_id,
        agent_display_name=execution.agent_display_name,
        current_status=execution.status,
        health_state=health_state,
        last_update=datetime.now(UTC),
        minutes_since_update=minutes,
        issue_description="No progress",
        recommended_action="Check agent",
    )


@pytest.mark.asyncio
async def test_abandoned_execution_decommissioned_once_and_not_rescanned(db_session: AsyncSession) -> None:
    config = HealthCheckConfig(abandon_after_minutes=30)
    ws = _make_ws()
    monitor = AgentHealthMonitor(db_manager=None, ws_manager=ws, config=config)  # type: ignore[arg-type]

    tenant = TenantManager.generate_tenant_key()
    execution = await _seed_execution(db_session, tenant, last_progress_minutes_ago=40.0)
    exec_id = execution.id

    with tenant_session_context(db_session, tenant):
        scan1 = await monitor._scan_tenant_jobs(db_session, tenant)
        assert scan1, "expected the stale execution to be detected on the first scan"
        assert all(hs.execution_id == exec_id for hs in scan1)

        for hs in scan1:
            await monitor._handle_unhealthy_job(db_session, hs, tenant)

        await db_session.refresh(execution)
        assert execution.status == "decommissioned"
        assert _event_call_count(ws, "agent:auto_failed") == 1
        assert _event_call_count(ws, "agent:health_alert") == 0

        scan2 = await monitor._scan_tenant_jobs(db_session, tenant)
        assert all(hs.execution_id != exec_id for hs in scan2), "abandoned execution must not be re-scanned"

        for hs in scan1:
            await monitor._handle_unhealthy_job(db_session, hs, tenant)
        assert _event_call_count(ws, "agent:auto_failed") == 1


@pytest.mark.asyncio
async def test_recoverable_stall_alerts_on_transition_only_no_repeat(db_session: AsyncSession) -> None:
    config = HealthCheckConfig()
    ws = _make_ws()
    monitor = AgentHealthMonitor(db_manager=None, ws_manager=ws, config=config)  # type: ignore[arg-type]

    tenant = TenantManager.generate_tenant_key()
    execution = await _seed_execution(db_session, tenant, health_status="unknown")

    with tenant_session_context(db_session, tenant):
        await monitor._handle_unhealthy_job(db_session, _hs(execution, health_state="warning", minutes=5), tenant)
        assert _event_call_count(ws, "agent:health_alert") == 1

        for m in (6.0, 7.0, 8.0):
            await monitor._handle_unhealthy_job(db_session, _hs(execution, health_state="warning", minutes=m), tenant)
        assert _event_call_count(ws, "agent:health_alert") == 1, "unchanged state must not re-alert across >=3 scans"

        await monitor._handle_unhealthy_job(db_session, _hs(execution, health_state="critical", minutes=9), tenant)
        assert _event_call_count(ws, "agent:health_alert") == 2
        for _ in range(3):
            await monitor._handle_unhealthy_job(db_session, _hs(execution, health_state="critical", minutes=9), tenant)
        assert _event_call_count(ws, "agent:health_alert") == 2

        await monitor._handle_unhealthy_job(db_session, _hs(execution, health_state="timeout", minutes=12), tenant)
        assert _event_call_count(ws, "agent:health_alert") == 3

    assert _event_call_count(ws, "agent:auto_failed") == 0
    await db_session.refresh(execution)
    assert execution.status == "working"
    assert execution.health_failure_count == 9


@pytest.mark.asyncio
async def test_reactivation_fresh_heartbeat_clears_detection(db_session: AsyncSession) -> None:
    config = HealthCheckConfig()
    ws = _make_ws()
    monitor = AgentHealthMonitor(db_manager=None, ws_manager=ws, config=config)  # type: ignore[arg-type]

    tenant = TenantManager.generate_tenant_key()
    execution = await _seed_execution(db_session, tenant, last_progress_minutes_ago=40.0)
    exec_id = execution.id

    with tenant_session_context(db_session, tenant):
        scan_before = await monitor._scan_tenant_jobs(db_session, tenant)
        assert any(hs.execution_id == exec_id for hs in scan_before), (
            "stale execution should be flagged before reactivation"
        )

        now = datetime.now(UTC)
        execution.last_progress_at = now
        execution.last_message_check_at = now
        execution.last_activity_at = now
        execution.health_status = "healthy"
        await db_session.flush()

        scan_after = await monitor._scan_tenant_jobs(db_session, tenant)
        assert all(hs.execution_id != exec_id for hs in scan_after), "reactivated execution must not be re-flagged"


@pytest.mark.asyncio
async def test_chain_member_abandon_does_not_terminalize_project(db_session: AsyncSession) -> None:
    config = HealthCheckConfig(abandon_after_minutes=30)
    ws = _make_ws()
    monitor = AgentHealthMonitor(db_manager=None, ws_manager=ws, config=config)  # type: ignore[arg-type]

    tenant = TenantManager.generate_tenant_key()
    execution = await _seed_execution(db_session, tenant, last_progress_minutes_ago=40.0, project_status="active")

    job = await db_session.get(AgentJob, execution.job_id)
    project = await db_session.get(Project, job.project_id)
    assert project.status not in CHAIN_TERMINAL_PROJECT_STATUSES

    with tenant_session_context(db_session, tenant):
        scan = await monitor._scan_tenant_jobs(db_session, tenant)
        for hs in scan:
            await monitor._handle_unhealthy_job(db_session, hs, tenant)
        await db_session.refresh(execution)
        await db_session.refresh(project)

    assert execution.status == "decommissioned"
    assert project.status == "active"
    assert project.status not in CHAIN_TERMINAL_PROJECT_STATUSES
