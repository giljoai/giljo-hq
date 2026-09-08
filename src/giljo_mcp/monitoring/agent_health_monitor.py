# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
Agent Health Monitor - Background monitoring service for agent job health.

Provides automatic detection of:
- Waiting timeouts (jobs never acknowledged)
- Stalled jobs (active jobs without progress)
- Heartbeat failures (extended silence)

Implements three-tier escalation (warning → critical → timeout) and
WebSocket event integration for real-time alerting.
"""

import asyncio
import contextlib
import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from giljo_mcp.database import DatabaseManager, tenant_isolation_bypass, tenant_session_context
from giljo_mcp.domain.project_status import ProjectStatus
from giljo_mcp.models import Project
from giljo_mcp.models.agent_identity import TERMINAL_EXECUTION_STATUSES, AgentExecution, AgentJob
from giljo_mcp.monitoring.health_config import AgentHealthStatus, HealthCheckConfig
from giljo_mcp.protocols.websocket import WebSocketBroadcaster
from giljo_mcp.services.agent_health_ws_broadcast import broadcast_agent_auto_failed, broadcast_health_alert


logger = logging.getLogger(__name__)


class AgentHealthMonitor:
    """
    Background task for agent health monitoring.

    Continuously scans agent jobs for health issues and triggers
    alerts or auto-recovery actions based on configuration.
    """

    def __init__(
        self, db_manager: DatabaseManager, ws_manager: WebSocketBroadcaster, config: HealthCheckConfig | None = None
    ):
        """
        Initialize health monitor.

        Args:
            db_manager: Database manager for job queries
            ws_manager: WebSocket manager for broadcasting alerts
            config: Health check configuration (uses defaults if None)
        """
        self.db = db_manager
        self.ws = ws_manager
        self.config = config or HealthCheckConfig()
        self.running = False
        self._task: asyncio.Task | None = None
        self._first_scan = True  # Suppress verbose logging on first scan

    async def start(self):
        """Start background monitoring loop."""
        if self.running:
            logger.warning("Health monitor already running")
            return

        self.running = True
        self._task = asyncio.create_task(self._monitoring_loop())
        logger.info("Agent health monitor started")

    async def stop(self):
        """Stop monitoring loop gracefully."""
        self.running = False
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
        logger.info("Agent health monitor stopped")

    async def _monitoring_loop(self):
        """Main monitoring loop."""
        while self.running:
            try:
                await self._run_health_check_cycle()
            except Exception as e:  # Broad catch: monitoring loop resilience
                logger.error(f"Health check cycle failed: {e}", exc_info=True)

            await asyncio.sleep(self.config.scan_interval_seconds)

    async def _run_health_check_cycle(self):
        """Execute one complete health check cycle."""
        logger.debug("Starting health check cycle")

        async with self.db.get_session_async() as session:
            # Get all tenants
            tenants = await self._get_all_tenants(session)

            for tenant_key in tenants:
                # Scope the shared session to this tenant so the per-tenant scan
                # and handler queries (explicit tenant_key predicates / primary-key
                # reads) are authorized under the fail-closed guard. The cross-tenant
                # discovery above runs under tenant_isolation_bypass; the per-tenant
                # work runs under that tenant's own context (RC-5 follow-on).
                with tenant_session_context(session, tenant_key):
                    # Scan for unhealthy jobs per tenant
                    unhealthy_jobs = await self._scan_tenant_jobs(session, tenant_key)

                    # On first scan, just log a summary instead of individual alerts
                    if self._first_scan and unhealthy_jobs:
                        logger.info(
                            f"Initial health scan: Found {len(unhealthy_jobs)} stale jobs (alerts suppressed on first scan)"
                        )
                        self._first_scan = False
                        continue

                    for health_status in unhealthy_jobs:
                        await self._handle_unhealthy_job(session, health_status, tenant_key)

        logger.debug("Health check cycle completed")

    async def _scan_tenant_jobs(self, session: AsyncSession, tenant_key: str) -> list[AgentHealthStatus]:
        """
        Scan all jobs for a tenant and detect unhealthy states.

        Args:
            session: Database session
            tenant_key: Tenant to scan

        Returns:
            List of unhealthy job statuses
        """
        unhealthy = []

        # Detection 1: Waiting timeout (never acknowledged)
        waiting_timeouts = await self._detect_waiting_timeouts(session, tenant_key)
        unhealthy.extend(waiting_timeouts)

        # Detection 2: Active no progress (stalled execution)
        stalled_jobs = await self._detect_stalled_jobs(session, tenant_key)
        unhealthy.extend(stalled_jobs)

        # Detection 3: Heartbeat timeout (complete silence)
        heartbeat_failures = await self._detect_heartbeat_failures(session, tenant_key)
        unhealthy.extend(heartbeat_failures)

        return unhealthy

    @staticmethod
    def _latest_instance_subquery(tenant_key: str):
        """Subquery: the latest ``started_at`` per ``job_id`` for one tenant.

        BE-6073 (m6): the three latest-instance detectors (waiting timeouts,
        stalled jobs, heartbeat failures) all need "only the most recent
        execution instance of each job" so an old, already-finished execution
        can't trigger a false alert. They built this identical
        ``max(started_at) GROUP BY job_id`` subquery inline; centralised here so
        there is one definition. Backed by ``idx_agent_executions_tenant_job_started``
        (ce_0051), which turns the per-tenant aggregate into an index range read.
        """
        return (
            select(AgentExecution.job_id, func.max(AgentExecution.started_at).label("latest_started"))
            .where(AgentExecution.tenant_key == tenant_key)
            .group_by(AgentExecution.job_id)
            .subquery()
        )

    def _latest_instance_query(self, tenant_key: str, status_filter: str | list[str]):
        """Query builder: the latest execution instance per job, filtered by
        tenant, status, and active-project (BE-8000d item 7).

        The three detectors below (waiting timeouts, stalled jobs, heartbeat
        failures) built this identical outer query -- joined to
        ``_latest_instance_subquery`` so a finished old execution can't trigger
        a false alert, left-joined to ``Project`` so an orphaned (project-less)
        job still scans, filtered to active/non-deleted projects otherwise --
        three times, differing only in the status filter. ``status_filter`` may
        be a single status (equality) or a list (``IN``). Callers needing an
        extra condition (e.g. the waiting-timeout's ``created_at`` cutoff) chain
        an additional ``.where()`` onto the returned select.
        """
        latest_instance_subq = self._latest_instance_subquery(tenant_key)
        status_condition = (
            AgentExecution.status.in_(status_filter)
            if isinstance(status_filter, list)
            else AgentExecution.status == status_filter
        )
        return (
            select(AgentExecution)
            .options(joinedload(AgentExecution.job).joinedload(AgentJob.project))
            .join(AgentJob, AgentExecution.job_id == AgentJob.job_id)
            .join(
                latest_instance_subq,
                and_(
                    AgentExecution.job_id == latest_instance_subq.c.job_id,
                    AgentExecution.started_at == latest_instance_subq.c.latest_started,
                ),
            )
            .outerjoin(Project, AgentJob.project_id == Project.id)
            .where(
                and_(
                    AgentExecution.tenant_key == tenant_key,
                    status_condition,
                    or_(
                        AgentJob.project_id.is_(None),  # Jobs without project (orphaned)
                        and_(
                            Project.deleted_at.is_(None),
                            Project.status == ProjectStatus.ACTIVE,  # Only active projects
                        ),
                    ),
                )
            )
        )

    async def _detect_waiting_timeouts(self, session: AsyncSession, tenant_key: str) -> list[AgentHealthStatus]:
        """
        Find jobs stuck in 'waiting' state.

        Args:
            session: Database session
            tenant_key: Tenant to scan

        Returns:
            List of jobs with waiting timeouts
        """
        timeout_threshold = datetime.now(UTC) - timedelta(minutes=self.config.waiting_timeout_minutes)

        # Handover 0424: Only monitor jobs from active projects; only the latest
        # execution instance per job (shared query builder, BE-8000d item 7).
        query = self._latest_instance_query(tenant_key, "waiting").where(AgentJob.created_at < timeout_threshold)

        result = await session.execute(query)
        executions = result.unique().scalars().all()

        return [
            AgentHealthStatus(
                execution_id=execution.id,  # Primary key - guaranteed unique
                job_id=execution.job_id,
                agent_id=execution.agent_id,
                agent_display_name=execution.agent_display_name,
                current_status="waiting",
                health_state="critical",
                last_update=execution.job.created_at,
                minutes_since_update=(
                    (datetime.now(UTC) - execution.job.created_at).total_seconds() / 60
                    if execution.job.created_at
                    else float(self.config.waiting_timeout_minutes)
                ),
                issue_description=f"Job never acknowledged after {self.config.waiting_timeout_minutes} minutes",
                recommended_action="Check if agent received job, manual intervention may be required",
                project_id=str(execution.job.project.id) if execution.job.project else "",
                project_name=execution.job.project.name if execution.job.project else "",
                product_id=str(execution.job.project.product_id) if execution.job.project else "",
            )
            for execution in executions
        ]

    async def _detect_stalled_jobs(self, session: AsyncSession, tenant_key: str) -> list[AgentHealthStatus]:
        """
        Find active jobs without progress updates.

        Args:
            session: Database session
            tenant_key: Tenant to scan

        Returns:
            List of stalled jobs
        """
        timeout_threshold = datetime.now(UTC) - timedelta(minutes=self.config.active_no_progress_minutes)

        # Handover 0424: Only monitor jobs from active projects; only the latest
        # execution instance per job (shared query builder, BE-8000d item 7).
        query = self._latest_instance_query(tenant_key, "working")

        result = await session.execute(query)
        executions = result.unique().scalars().all()

        stalled = []
        for execution in executions:
            last_progress = self._get_last_progress_time(execution)
            if last_progress < timeout_threshold:
                minutes_stalled = (datetime.now(UTC) - last_progress).total_seconds() / 60

                # Determine health state based on duration
                if minutes_stalled >= self.config.heartbeat_timeout_minutes:
                    health_state = "timeout"
                elif minutes_stalled >= 7:
                    health_state = "critical"
                else:
                    health_state = "warning"

                project = execution.job.project if execution.job else None
                stalled.append(
                    AgentHealthStatus(
                        execution_id=execution.id,  # Primary key - guaranteed unique
                        job_id=execution.job_id,
                        agent_id=execution.agent_id,
                        agent_display_name=execution.agent_display_name,
                        current_status="working",
                        health_state=health_state,
                        last_update=last_progress,
                        minutes_since_update=minutes_stalled,
                        issue_description=f"No progress update for {minutes_stalled:.1f} minutes",
                        recommended_action="Check agent logs, may need manual restart",
                        project_id=str(project.id) if project else "",
                        project_name=project.name if project else "",
                        product_id=str(project.product_id) if project else "",
                    )
                )

        return stalled

    async def _detect_heartbeat_failures(self, session: AsyncSession, tenant_key: str) -> list[AgentHealthStatus]:
        """
        Find jobs with extended silence (heartbeat timeout).

        Args:
            session: Database session
            tenant_key: Tenant to scan

        Returns:
            List of jobs with heartbeat failures
        """
        # Handover 0424: Only monitor jobs from active projects; only the latest
        # execution instance per job (shared query builder, BE-8000d item 7).
        query = self._latest_instance_query(tenant_key, ["waiting", "working"])

        result = await session.execute(query)
        executions = result.unique().scalars().all()

        failures = []
        for execution in executions:
            # Apply agent-type-specific timeouts
            timeout_minutes = self.config.get_timeout_for_agent(execution.agent_display_name)
            threshold = datetime.now(UTC) - timedelta(minutes=timeout_minutes)
            last_activity = self._get_last_activity_time(execution)

            if last_activity < threshold:
                minutes_silent = (datetime.now(UTC) - last_activity).total_seconds() / 60

                project = execution.job.project if execution.job else None
                failures.append(
                    AgentHealthStatus(
                        execution_id=execution.id,  # Primary key - guaranteed unique
                        job_id=execution.job_id,
                        agent_id=execution.agent_id,
                        agent_display_name=execution.agent_display_name,
                        current_status=execution.status,
                        health_state="timeout",
                        last_update=last_activity,
                        minutes_since_update=minutes_silent,
                        issue_description=f"Complete silence for {minutes_silent:.1f} minutes (timeout: {timeout_minutes}m)",
                        recommended_action="Auto-fail job or manual intervention required",
                        project_id=str(project.id) if project else "",
                        project_name=project.name if project else "",
                        product_id=str(project.product_id) if project else "",
                    )
                )

        return failures

    async def _handle_unhealthy_job(self, session: AsyncSession, health_status: AgentHealthStatus, tenant_key: str):
        """
        Handle detected unhealthy job.

        BE-9101: an abandoned execution (one that will never resume) used to be
        re-alerted on EVERY scan forever — the WARNING log + WS health broadcast
        fired each cycle for the same still-unhealthy execution, with no terminal
        give-up and no dedup. This handler now:
          1. Terminal cutoff — past ``config.abandon_after_minutes`` of continuous
             silence, transition the execution to the EXISTING terminal status
             ``'decommissioned'`` (the canonical inactive set every active-execution
             query already excludes) so it DROPS OUT of the waiting/working detector
             scan set and stops alerting. Chain-safe: only ``execution.status`` is
             touched, never ``project.status``, so CHAIN_TERMINAL_PROJECT_STATUSES-
             keyed purge_run / conductor advancement are unaffected.
          2. Dedup — emit the WARNING + broadcast ONLY on a health-state TRANSITION
             (compare persisted ``execution.health_status`` to the new state); an
             unchanged repeat refreshes bookkeeping silently.
          3. Log level — a first transition is WARNING; an already-known repeat is
             DEBUG.

        Args:
            session: Database session
            health_status: Health status of unhealthy job
            tenant_key: Tenant key
        """
        # Get execution from database by primary key (guaranteed unique)
        # NOTE: Use execution_id (primary key) not agent_id which may have duplicates
        result = await session.execute(
            select(AgentExecution)
            .options(joinedload(AgentExecution.job))
            .where(AgentExecution.id == health_status.execution_id)
        )
        execution = result.unique().scalar_one_or_none()
        if not execution:
            logger.error(f"Execution {health_status.execution_id} not found in database")
            return

        # BE-9101: already terminal (e.g. decommissioned by an overlapping detector
        # earlier this cycle, or completed between scan and handle) — nothing to
        # alert. Guards both double-detection within a cycle and the give-up
        # transition below. BE-9304: reads the shared constant; this module used to
        # keep a private frozenset under an all-but-identical name.
        if execution.status in TERMINAL_EXECUTION_STATUSES:
            return

        new_health = health_status.health_state
        is_transition = execution.health_status != new_health

        # Refresh health bookkeeping every scan (state stays current; NOT an
        # alert — the alert/broadcast is gated on a transition below).
        execution.health_status = new_health
        execution.health_failure_count += 1
        execution.last_health_check = datetime.now(UTC)

        # (1) Terminal cutoff: abandoned past the hard ceiling. Decommission once
        # so the next scan no longer detects it (detectors filter waiting/working).
        if health_status.minutes_since_update >= self.config.abandon_after_minutes:
            execution.status = "decommissioned"
            execution.block_reason = (
                f"Auto-decommissioned (BE-9101): abandoned {health_status.minutes_since_update:.0f}m "
                f"(ceiling {self.config.abandon_after_minutes}m): {health_status.issue_description}"
            )
            logger.warning(
                f"Abandoned execution decommissioned: {health_status.execution_id} (job: {health_status.job_id})",
                extra={
                    "execution_id": health_status.execution_id,
                    "agent_id": health_status.agent_id,
                    "job_id": health_status.job_id,
                    "agent_display_name": health_status.agent_display_name,
                    "minutes_since_update": health_status.minutes_since_update,
                    "abandon_after_minutes": self.config.abandon_after_minutes,
                },
            )
            await broadcast_agent_auto_failed(
                self.ws,
                tenant_key=tenant_key,
                job_id=health_status.job_id,
                agent_display_name=health_status.agent_display_name,
                reason=f"Abandoned {health_status.minutes_since_update:.0f}m — auto-decommissioned",
                product_id=health_status.product_id or None,
                project_id=health_status.project_id or None,
            )
            await session.commit()
            return

        # (2)+(3) Dedup: alert only on a health-state TRANSITION; an unchanged
        # repeat refreshes bookkeeping (above) and logs at DEBUG, no broadcast.
        if not is_transition:
            logger.debug(
                f"Unhealthy execution {health_status.execution_id} unchanged ({new_health}) — repeat alert suppressed"
            )
            await session.commit()
            return

        logger.warning(
            f"Unhealthy execution detected: {health_status.execution_id} (job: {health_status.job_id})",
            extra={
                "execution_id": health_status.execution_id,
                "agent_id": health_status.agent_id,
                "job_id": health_status.job_id,
                "agent_display_name": health_status.agent_display_name,
                "health_state": new_health,
                "minutes_since_update": health_status.minutes_since_update,
            },
        )

        # Handover 0491: Auto-silent on timeout (if configured)
        # Silent status indicates detected inactivity - agent may have disconnected
        if new_health == "timeout" and self.config.auto_fail_on_timeout:
            execution.status = "silent"
            execution.block_reason = f"Auto-detected timeout: {health_status.issue_description}"

            # Broadcast auto-silent event
            await broadcast_agent_auto_failed(
                self.ws,
                tenant_key=tenant_key,
                job_id=health_status.job_id,
                agent_display_name=health_status.agent_display_name,
                reason=health_status.issue_description,
                product_id=health_status.product_id or None,
                project_id=health_status.project_id or None,
            )
        else:
            # Broadcast health alert
            await broadcast_health_alert(
                self.ws,
                tenant_key=tenant_key,
                job_id=health_status.job_id,
                agent_display_name=health_status.agent_display_name,
                health_status=health_status,
            )

        await session.commit()

    def _get_last_progress_time(self, execution: AgentExecution) -> datetime:
        """
        Get last progress update time from execution.

        Args:
            execution: Agent execution to check

        Returns:
            Datetime of last progress update
        """
        # AgentExecution has last_progress_at as a direct field
        if execution.last_progress_at:
            return execution.last_progress_at

        # Fallback to started_at or job.created_at
        return execution.started_at or execution.job.created_at

    def _get_last_activity_time(self, execution: AgentExecution) -> datetime:
        """
        Get most recent activity timestamp.

        Args:
            execution: Agent execution to check

        Returns:
            Most recent activity timestamp
        """
        candidates = [
            execution.job.created_at,
            execution.started_at,
            execution.last_progress_at,
            execution.last_message_check_at,
            self._get_last_progress_time(execution),
        ]

        # Filter out None values and return max
        valid_timestamps = [ts for ts in candidates if ts is not None]
        return max(valid_timestamps) if valid_timestamps else datetime.now(UTC)

    async def _get_all_tenants(self, session: AsyncSession) -> list[str]:
        """
        Get list of all tenant keys.

        Args:
            session: Database session

        Returns:
            List of unique tenant keys from active projects
        """
        # Only get tenant keys from executions that don't belong to deleted projects or inactive projects
        # Handover 0424: Only monitor jobs from active projects
        query = (
            select(AgentExecution.tenant_key)
            .distinct()
            .join(AgentJob, AgentExecution.job_id == AgentJob.job_id)
            .outerjoin(Project, AgentJob.project_id == Project.id)
            .where(
                or_(
                    AgentJob.project_id.is_(None),  # Jobs without project (orphaned)
                    and_(
                        Project.deleted_at.is_(None),
                        Project.status == ProjectStatus.ACTIVE,  # Only active projects
                    ),
                )
            )
        )
        # BE6004C-5: this scan enumerates EVERY tenant's executions by design --
        # there is no single tenant to scope to before the query. The audited,
        # model-scoped bypass is the correct mechanism; per-tenant health work
        # that follows runs tenant-scoped, not under this bypass.
        with tenant_isolation_bypass(
            session,
            reason="cross-tenant monitoring scan: enumerate tenants for health check",
            models=(AgentExecution, AgentJob, Project),
        ):
            result = await session.execute(query)
        return [row[0] for row in result.fetchall()]
