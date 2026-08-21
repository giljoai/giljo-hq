# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""Regression tests for BE-9101 — health monitor re-alerts abandoned executions.

Bug: ``AgentHealthMonitor._handle_unhealthy_job`` re-logged a WARNING and re-fired
the WebSocket health broadcast on EVERY scan for the same still-unhealthy
execution — no terminal give-up, no dedup. An abandoned execution (default
``auto_fail_on_timeout=False`` leaves it in waiting/working, permanently inside
the scan set) was therefore re-alerted every ``scan_interval_seconds`` forever.

Fix (all three, one coherent change) exercised at the MONITOR layer here:
  (a) terminal cutoff — past ``abandon_after_minutes`` the execution is
      transitioned to the existing terminal status ``'decommissioned'`` exactly
      once and is NOT re-scanned/re-alerted afterward;
  (b) dedup — a stalled-but-recoverable execution alerts on each health-state
      TRANSITION but does NOT re-emit an unchanged state (proof: no repeat alert
      for an unchanged state across >=3 scans);
  (c) reactivation — a fresh heartbeat clears the detection and stops alerts;
  (d) chain safety — a chain member's execution auto-decommission touches only
      execution.status (never project.status), so the CHAIN_TERMINAL_PROJECT_STATUSES-
      keyed conductor advancement / purge_run decision is unaffected.

Parallel-safe (BE-9101): each test runs inside the transactional ``db_session``
fixture (rolled back at teardown) and seeds a unique ``tk_...`` tenant; no
module-level mutable state; no ordering dependency.

Edition Scope: Both (agent_health_monitor is CE core; runs identically on SaaS).
"""

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
    """Seed an active Project + AgentJob + AgentExecution for one tenant.

    ``last_progress_minutes_ago`` positions ``last_progress_at`` / ``started_at``
    in the past so the detectors flag the execution as stalled/silent.
    """
    suffix = uuid.uuid4().hex[:8]
    then = datetime.now(UTC) - timedelta(minutes=last_progress_minutes_ago)

    # BE-9437: a project belongs to a product. Its own, so an ACTIVE seed cannot
    # collide with another under idx_project_single_active_per_product.
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
    ws.broadcast_agent_auto_failed = AsyncMock()
    ws.broadcast_health_alert = AsyncMock()
    return ws


def _hs(execution: AgentExecution, *, health_state: str, minutes: float) -> AgentHealthStatus:
    """Craft an AgentHealthStatus targeting a seeded execution."""
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
    """(a) Past the abandon ceiling the execution goes terminal exactly once and
    is NOT re-detected/re-alerted on the next scan."""
    config = HealthCheckConfig(abandon_after_minutes=30)
    ws = _make_ws()
    monitor = AgentHealthMonitor(db_manager=None, ws_manager=ws, config=config)  # type: ignore[arg-type]

    tenant = TenantManager.generate_tenant_key()
    # 40m silent > 30m ceiling.
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
        # Decommission fires the auto-failed broadcast EXACTLY once even though
        # both the stalled + heartbeat detectors matched this execution.
        assert ws.broadcast_agent_auto_failed.await_count == 1
        assert ws.broadcast_health_alert.await_count == 0

        # Next scan: a decommissioned execution is filtered out of the scan set.
        scan2 = await monitor._scan_tenant_jobs(db_session, tenant)
        assert all(hs.execution_id != exec_id for hs in scan2), "abandoned execution must not be re-scanned"

        # And even a (defensive) re-handle produces no further alert.
        for hs in scan1:
            await monitor._handle_unhealthy_job(db_session, hs, tenant)
        assert ws.broadcast_agent_auto_failed.await_count == 1


@pytest.mark.asyncio
async def test_recoverable_stall_alerts_on_transition_only_no_repeat(db_session: AsyncSession) -> None:
    """(b) A recoverable stall alerts on each escalation TRANSITION but emits NO
    repeat alert for an unchanged state across >=3 scans (the core dedup proof)."""
    config = HealthCheckConfig()  # abandon ceiling 1440m — never terminal here.
    ws = _make_ws()
    monitor = AgentHealthMonitor(db_manager=None, ws_manager=ws, config=config)  # type: ignore[arg-type]

    tenant = TenantManager.generate_tenant_key()
    execution = await _seed_execution(db_session, tenant, health_status="unknown")

    with tenant_session_context(db_session, tenant):
        # First detection: unknown -> warning is a TRANSITION -> one alert.
        await monitor._handle_unhealthy_job(db_session, _hs(execution, health_state="warning", minutes=5), tenant)
        assert ws.broadcast_health_alert.await_count == 1

        # Same 'warning' state across 3 more scans -> NO repeat alert.
        for m in (6.0, 7.0, 8.0):
            await monitor._handle_unhealthy_job(db_session, _hs(execution, health_state="warning", minutes=m), tenant)
        assert ws.broadcast_health_alert.await_count == 1, "unchanged state must not re-alert across >=3 scans"

        # Escalation warning -> critical is a new TRANSITION -> one alert.
        await monitor._handle_unhealthy_job(db_session, _hs(execution, health_state="critical", minutes=9), tenant)
        assert ws.broadcast_health_alert.await_count == 2
        # ...then unchanged 'critical' across scans -> still no repeat.
        for _ in range(3):
            await monitor._handle_unhealthy_job(db_session, _hs(execution, health_state="critical", minutes=9), tenant)
        assert ws.broadcast_health_alert.await_count == 2

        # Escalation critical -> timeout is a new TRANSITION -> one alert.
        await monitor._handle_unhealthy_job(db_session, _hs(execution, health_state="timeout", minutes=12), tenant)
        assert ws.broadcast_health_alert.await_count == 3

    # A recoverable stall is never auto-failed/decommissioned.
    assert ws.broadcast_agent_auto_failed.await_count == 0
    await db_session.refresh(execution)
    assert execution.status == "working"
    # Bookkeeping still advanced every scan (9 handled scans: 1+3+1+3+1).
    assert execution.health_failure_count == 9


@pytest.mark.asyncio
async def test_reactivation_fresh_heartbeat_clears_detection(db_session: AsyncSession) -> None:
    """(c) A fresh heartbeat (reactivation) removes the execution from the scan
    set so no further alerts are produced."""
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

        # Reactivation: fresh heartbeat timestamps + health reset to healthy.
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
    """(d) Auto-decommissioning a chain member's EXECUTION does not change the
    member's PROJECT status, so the CHAIN_TERMINAL_PROJECT_STATUSES-keyed
    conductor-advancement / purge_run decision is unaffected (no premature purge,
    no wedge)."""
    config = HealthCheckConfig(abandon_after_minutes=30)
    ws = _make_ws()
    monitor = AgentHealthMonitor(db_manager=None, ws_manager=ws, config=config)  # type: ignore[arg-type]

    tenant = TenantManager.generate_tenant_key()
    execution = await _seed_execution(db_session, tenant, last_progress_minutes_ago=40.0, project_status="active")

    # The chain-finished predicate (from complete_chain_run_if_finished) keys on
    # the member PROJECT status against the real shared terminal set. Resolve the
    # project via explicit gets (no lazy relationship IO in the test).
    job = await db_session.get(AgentJob, execution.job_id)
    project = await db_session.get(Project, job.project_id)
    assert project.status not in CHAIN_TERMINAL_PROJECT_STATUSES  # member is "remaining" before

    with tenant_session_context(db_session, tenant):
        scan = await monitor._scan_tenant_jobs(db_session, tenant)
        for hs in scan:
            await monitor._handle_unhealthy_job(db_session, hs, tenant)
        await db_session.refresh(execution)
        await db_session.refresh(project)

    # Execution went terminal...
    assert execution.status == "decommissioned"
    # ...but the PROJECT status is untouched, so the chain still counts this
    # member as non-terminal exactly as before — decommission neither purges the
    # run early nor wedges advancement.
    assert project.status == "active"
    assert project.status not in CHAIN_TERMINAL_PROJECT_STATUSES
