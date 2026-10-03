# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


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
from giljo_mcp.repositories._project_enrichment_reads_mixin import project_not_trashed
from giljo_mcp.services.agent_health_ws_broadcast import broadcast_agent_auto_failed, broadcast_health_alert


logger = logging.getLogger(__name__)


class AgentHealthMonitor:

    def __init__(
        self, db_manager: DatabaseManager, ws_manager: WebSocketBroadcaster, config: HealthCheckConfig | None = None
    ):
        self.db = db_manager
        self.ws = ws_manager
        self.config = config or HealthCheckConfig()
        self.running = False
        self._task: asyncio.Task | None = None
        self._first_scan = True

    async def start(self):
        if self.running:
            logger.warning("Health monitor already running")
            return

        self.running = True
        self._task = asyncio.create_task(self._monitoring_loop())
        logger.info("Agent health monitor started")

    async def stop(self):
        self.running = False
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
        logger.info("Agent health monitor stopped")

    async def _monitoring_loop(self):
        while self.running:
            try:
                await self._run_health_check_cycle()
            except Exception as e:
                logger.error(f"Health check cycle failed: {e}", exc_info=True)

            await asyncio.sleep(self.config.scan_interval_seconds)

    async def _run_health_check_cycle(self):
        logger.debug("Starting health check cycle")

        async with self.db.get_session_async() as session:
            tenants = await self._get_all_tenants(session)

            for tenant_key in tenants:
                with tenant_session_context(session, tenant_key):
                    unhealthy_jobs = await self._scan_tenant_jobs(session, tenant_key)

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
        unhealthy = []

        waiting_timeouts = await self._detect_waiting_timeouts(session, tenant_key)
        unhealthy.extend(waiting_timeouts)

        stalled_jobs = await self._detect_stalled_jobs(session, tenant_key)
        unhealthy.extend(stalled_jobs)

        heartbeat_failures = await self._detect_heartbeat_failures(session, tenant_key)
        unhealthy.extend(heartbeat_failures)

        return unhealthy

    @staticmethod
    def _latest_instance_subquery(tenant_key: str):
        return (
            select(AgentExecution.job_id, func.max(AgentExecution.started_at).label("latest_started"))
            .where(AgentExecution.tenant_key == tenant_key)
            .group_by(AgentExecution.job_id)
            .subquery()
        )

    def _latest_instance_query(self, tenant_key: str, status_filter: str | list[str]):
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
                        AgentJob.project_id.is_(None),
                        and_(
                            project_not_trashed(),
                            Project.status == ProjectStatus.ACTIVE,
                        ),
                    ),
                )
            )
        )

    async def _detect_waiting_timeouts(self, session: AsyncSession, tenant_key: str) -> list[AgentHealthStatus]:
        timeout_threshold = datetime.now(UTC) - timedelta(minutes=self.config.waiting_timeout_minutes)

        query = self._latest_instance_query(tenant_key, "waiting").where(AgentJob.created_at < timeout_threshold)

        result = await session.execute(query)
        executions = result.unique().scalars().all()

        return [
            AgentHealthStatus(
                execution_id=execution.id,
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
        timeout_threshold = datetime.now(UTC) - timedelta(minutes=self.config.active_no_progress_minutes)

        query = self._latest_instance_query(tenant_key, "working")

        result = await session.execute(query)
        executions = result.unique().scalars().all()

        stalled = []
        for execution in executions:
            last_progress = self._get_last_progress_time(execution)
            if last_progress < timeout_threshold:
                minutes_stalled = (datetime.now(UTC) - last_progress).total_seconds() / 60

                if minutes_stalled >= self.config.heartbeat_timeout_minutes:
                    health_state = "timeout"
                elif minutes_stalled >= 7:
                    health_state = "critical"
                else:
                    health_state = "warning"

                project = execution.job.project if execution.job else None
                stalled.append(
                    AgentHealthStatus(
                        execution_id=execution.id,
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
        query = self._latest_instance_query(tenant_key, ["waiting", "working"])

        result = await session.execute(query)
        executions = result.unique().scalars().all()

        failures = []
        for execution in executions:
            timeout_minutes = self.config.get_timeout_for_agent(execution.agent_display_name)
            threshold = datetime.now(UTC) - timedelta(minutes=timeout_minutes)
            last_activity = self._get_last_activity_time(execution)

            if last_activity < threshold:
                minutes_silent = (datetime.now(UTC) - last_activity).total_seconds() / 60

                project = execution.job.project if execution.job else None
                failures.append(
                    AgentHealthStatus(
                        execution_id=execution.id,
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
        result = await session.execute(
            select(AgentExecution)
            .options(joinedload(AgentExecution.job))
            .where(AgentExecution.id == health_status.execution_id, AgentExecution.tenant_key == tenant_key)
        )
        execution = result.unique().scalar_one_or_none()
        if not execution:
            logger.error(f"Execution {health_status.execution_id} not found in database")
            return

        if execution.status in TERMINAL_EXECUTION_STATUSES:
            return

        new_health = health_status.health_state
        is_transition = execution.health_status != new_health

        execution.health_status = new_health
        execution.health_failure_count += 1
        execution.last_health_check = datetime.now(UTC)

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

        if new_health == "timeout" and self.config.auto_fail_on_timeout:
            execution.status = "silent"
            execution.block_reason = f"Auto-detected timeout: {health_status.issue_description}"

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
            await broadcast_health_alert(
                self.ws,
                tenant_key=tenant_key,
                job_id=health_status.job_id,
                agent_display_name=health_status.agent_display_name,
                health_status=health_status,
            )

        await session.commit()

    def _get_last_progress_time(self, execution: AgentExecution) -> datetime:
        if execution.last_progress_at:
            return execution.last_progress_at

        return execution.started_at or execution.job.created_at

    def _get_last_activity_time(self, execution: AgentExecution) -> datetime:
        candidates = [
            execution.job.created_at,
            execution.started_at,
            execution.last_progress_at,
            execution.last_message_check_at,
            self._get_last_progress_time(execution),
        ]

        valid_timestamps = [ts for ts in candidates if ts is not None]
        return max(valid_timestamps) if valid_timestamps else datetime.now(UTC)

    async def _get_all_tenants(self, session: AsyncSession) -> list[str]:
        query = (
            select(AgentExecution.tenant_key)
            .distinct()
            .join(AgentJob, AgentExecution.job_id == AgentJob.job_id)
            .outerjoin(Project, AgentJob.project_id == Project.id)
            .where(
                or_(
                    AgentJob.project_id.is_(None),
                    and_(
                        project_not_trashed(),
                        Project.status == ProjectStatus.ACTIVE,
                    ),
                )
            )
        )
        with tenant_isolation_bypass(
            session,
            reason="cross-tenant monitoring scan: enumerate tenants for health check",
            models=(AgentExecution, AgentJob, Project),
        ):
            result = await session.execute(query)
        return [row[0] for row in result.fetchall()]
