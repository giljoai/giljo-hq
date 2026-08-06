# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
Silent agent detection background service (Handover 0491 Phase 3).

Periodically scans for agents in 'working' status whose last_progress_at
has exceeded the configurable silence threshold, marking them as 'silent'.

Also provides:
- auto_clear_silent(): Resets silent agents to 'working' when they make MCP calls
- clear_silent_status(): REST endpoint helper to manually clear silent status
"""

import asyncio
import contextlib
import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.database import DatabaseManager
from giljo_mcp.models.agent_identity import AgentExecution
from giljo_mcp.repositories.agent_operations_repository import AgentOperationsRepository
from giljo_mcp.repositories.configuration_repository import ConfigurationRepository
from giljo_mcp.services.settings_service import AGENT_SILENCE_THRESHOLD_KEY, MAX_AGENT_SILENCE_THRESHOLD_MINUTES


logger = logging.getLogger(__name__)

# Default silence threshold in minutes (used when no setting is configured)
DEFAULT_SILENCE_THRESHOLD_MINUTES = 10

# How often the detector runs its scan (seconds)
DEFAULT_SCAN_INTERVAL_SECONDS = 60


class SilenceDetector:
    """Background service that detects agents that have gone silent.

    Scans for agents in 'working' status whose last_progress_at timestamp
    is older than the configurable threshold, or is NULL. These agents
    are transitioned to 'silent' status with a WebSocket notification.

    Follows the same pattern as AgentHealthMonitor for lifecycle management.
    """

    def __init__(
        self,
        db_manager: DatabaseManager,
        ws_manager,
        scan_interval_seconds: int = DEFAULT_SCAN_INTERVAL_SECONDS,
    ):
        """Initialize silence detector.

        Args:
            db_manager: Database manager for session creation
            ws_manager: WebSocket manager for broadcasting status changes
            scan_interval_seconds: How often to scan (default 60s)
        """
        self.db = db_manager
        self.ws = ws_manager
        self.scan_interval_seconds = scan_interval_seconds
        self.running = False
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        """Start the background monitoring loop."""
        if self.running:
            logger.warning("Silence detector already running")
            return

        self.running = True
        self._task = asyncio.create_task(self._monitoring_loop())
        logger.info("Silence detector started (scan interval: %ds)", self.scan_interval_seconds)

    async def stop(self) -> None:
        """Stop the monitoring loop gracefully."""
        self.running = False
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
        logger.info("Silence detector stopped")

    async def _monitoring_loop(self) -> None:
        """Main monitoring loop - runs every scan_interval_seconds."""
        while self.running:
            try:
                await self._run_detection_cycle()
            except Exception as _exc:  # Broad catch: background loop resilience, prevents monitoring crash
                logger.exception("Silence detection cycle failed")

            await asyncio.sleep(self.scan_interval_seconds)

    async def _run_detection_cycle(self) -> None:
        """Execute one complete silence detection cycle."""
        async with self.db.get_session_async() as session:
            # The deployment-wide default is stored in system_settings (unchanged, CE + SaaS).
            repo = AgentOperationsRepository()
            threshold_val = await repo.get_silence_threshold_setting(session)
            default_threshold = threshold_val if threshold_val is not None else DEFAULT_SILENCE_THRESHOLD_MINUTES

            # FE-9241 (SaaS expansion): per-tenant overrides live in `configurations`,
            # loaded in ONE cross-tenant query (no N+1 — never queried per-agent
            # below). CE never writes these rows, so this is always {} on CE and
            # detection collapses to the pre-FE-9241 single-threshold behavior.
            config_repo = ConfigurationRepository(self.db)
            raw_overrides = await config_repo.get_all_values_for_key(session, AGENT_SILENCE_THRESHOLD_KEY)
            tenant_overrides = _coerce_threshold_overrides(raw_overrides)

            count = await self._detect_silent_agents(
                session, threshold_minutes=default_threshold, tenant_overrides=tenant_overrides
            )

            if count > 0:
                logger.info("Silence detection cycle: marked %d agent(s) as silent", count)

    async def _detect_silent_agents(
        self,
        session: AsyncSession,
        threshold_minutes: int = DEFAULT_SILENCE_THRESHOLD_MINUTES,
        tenant_overrides: dict[str, int] | None = None,
    ) -> int:
        """Detect and mark silent agents.

        Finds agents where, under THEIR OWN effective threshold (a SaaS
        per-tenant override from `tenant_overrides` if one exists for that
        agent's tenant, else `threshold_minutes`):
        - status == 'working'
        - last_progress_at < (now - own threshold) OR last_progress_at IS NULL

        Args:
            session: Database session
            threshold_minutes: Deployment-wide default threshold in minutes
            tenant_overrides: FE-9241 SaaS per-tenant overrides ({tenant_key: minutes}).
                Empty/None on CE (no override rows exist there), so every agent
                uses threshold_minutes — identical to pre-FE-9241 behavior.

        Returns:
            Number of agents marked as silent
        """
        tenant_overrides = tenant_overrides or {}
        now = datetime.now(UTC)

        # SQL pre-filter cutoff: the MOST LENIENT (smallest) effective threshold
        # across the deployment default and every tenant override, so the single
        # cross-tenant scan can't miss an agent that's already stale under some
        # tenant's tighter threshold. A candidate that only looks stale under a
        # SMALLER threshold than its own tenant's is dropped below, per-agent,
        # once we know which tenant it belongs to.
        min_threshold = min([threshold_minutes, *tenant_overrides.values()])
        cutoff = now - timedelta(minutes=min_threshold)

        # TENANT ISOLATION NOTE (Phase C audit, Feb 2026):
        # This query intentionally scans ALL tenants. The silence detector is a
        # system-wide background health monitor (like a database cleanup job), not
        # a tenant-facing operation. It runs on a server timer with no user/tenant
        # context. Cross-tenant scope is BY DESIGN.
        repo = AgentOperationsRepository()
        candidate_agents = await repo.find_stale_working_agents(session, cutoff)

        # Drop candidates not actually stale under THEIR OWN tenant's effective
        # threshold (only matters when that threshold is larger than
        # min_threshold — the SQL pre-filter above is intentionally wider than
        # strictly necessary so no tenant's stale agent is missed).
        stale_agents = []
        for agent in candidate_agents:
            own_threshold = tenant_overrides.get(agent.tenant_key, threshold_minutes)
            reference_time = agent.last_progress_at or agent.started_at
            if reference_time is not None and reference_time >= now - timedelta(minutes=own_threshold):
                continue
            stale_agents.append(agent)

        # BE-6190: capture each silenced agent's chain context + its own effective
        # threshold so the run-stall check can reuse the agents we already marked
        # silent (no second cross-tenant scan) and stall using the RIGHT deadline.
        silenced: list[tuple[str, str | None, datetime | None, int]] = []

        count = 0
        for agent in stale_agents:
            old_status = agent.status
            own_threshold = tenant_overrides.get(agent.tenant_key, threshold_minutes)

            # Extract project context from eagerly-loaded relationships
            project_id = str(agent.job.project_id) if agent.job and agent.job.project_id else None
            if project_id is not None:
                silenced.append((agent.tenant_key, project_id, agent.last_progress_at, own_threshold))
            project_name = agent.job.project.name if agent.job and agent.job.project else None

            logger.info(
                "Agent marked silent: agent_id=%s, job_id=%s, display_name=%s, last_progress_at=%s",
                agent.agent_id,
                agent.job_id,
                agent.agent_display_name,
                agent.last_progress_at,
            )

            # Emit WebSocket events
            try:
                await _broadcast_status_change(
                    ws_manager=self.ws,
                    agent=agent,
                    old_status=old_status,
                    new_status="silent",
                    project_id=project_id,
                )

                # Emit dedicated agent:silent event for notification bell
                from giljo_mcp.events.schemas import EventFactory

                silent_event = EventFactory.agent_silent(
                    job_id=str(agent.job_id),
                    tenant_key=agent.tenant_key,
                    agent_display_name=agent.agent_display_name or "unknown",
                    reason="Agent stopped communicating",
                    project_id=project_id,
                    project_name=project_name,
                    execution_id=str(agent.agent_id),
                )
                await self.ws.broadcast_event_to_tenant(
                    tenant_key=agent.tenant_key,
                    event=silent_event,
                )
            except Exception as _exc:  # Broad catch: WebSocket resilience, non-critical broadcast
                logger.exception(
                    "Failed to broadcast silent status for agent %s",
                    agent.agent_id,
                )

            count += 1

        if count > 0:
            await repo.mark_agents_silent(session, stale_agents)

        await self._stall_runs_for_silenced_projects(session, silenced)

        return count

    async def _stall_runs_for_silenced_projects(
        self,
        session: AsyncSession,
        silenced: list[tuple[str, str | None, datetime | None, int]],
    ) -> None:
        """Flip an active chain run to "stalled" when its CURRENT in-flight project's
        orchestrator has gone silent past ITS OWN tenant's threshold (BE-6190 — wires
        the previously dead SequenceChainContextResolver.mark_stalled_if_past_deadline;
        FE-9241 extends it to use each agent's own effective threshold instead of one
        global value, so a SaaS tenant's tighter/looser override affects its own chain's
        stall deadline). Reuses the agents _detect_silent_agents already marked silent;
        only the run whose CURRENT member (resolved_order[current_index]) is the silent
        project stalls. Solo / no active run / non-current member => no-op. Best-effort:
        never breaks the cycle.
        """
        from giljo_mcp.services.sequence_chain_context import SequenceChainContextResolver
        from giljo_mcp.services.sequence_run_service import SequenceRunService
        from giljo_mcp.tenant import TenantManager

        now = datetime.now(UTC)
        tm = TenantManager()
        for tenant_key, project_id, last_progress_at, threshold_minutes in silenced:
            if not project_id:
                continue
            try:
                run_svc = SequenceRunService(db_manager=self.db, tenant_manager=tm, session=session)
                run = await run_svc.find_active_run_for_project(project_id=project_id, tenant_key=tenant_key)
                if run is None:
                    continue
                resolved_order = run.get("resolved_order") or []
                idx = run.get("current_index", 0)
                if not (0 <= idx < len(resolved_order)) or resolved_order[idx] != project_id:
                    continue  # only the in-flight project stalls the run
                deadline = (
                    last_progress_at + timedelta(minutes=threshold_minutes)
                    if last_progress_at
                    else now - timedelta(minutes=threshold_minutes)
                )
                resolver = SequenceChainContextResolver(db_manager=self.db, tenant_manager=tm, test_session=session)
                await resolver.mark_stalled_if_past_deadline(
                    run_id=run["id"],
                    tenant_key=tenant_key,
                    deadline_iso_or_dt=deadline,
                    now=now,
                )
            except Exception:  # noqa: BLE001 — best-effort; never break the detection cycle
                logger.warning("BE-6190: non-fatal stall-check failed for project %s", project_id, exc_info=True)


async def auto_clear_silent(
    session: AsyncSession,
    job_id: str,
    ws_manager,
    tenant_key: str,
) -> None:
    """Auto-clear silent status when an agent makes an MCP call.

    If the agent associated with the given job_id is currently 'silent',
    transitions it back to 'working' and updates last_progress_at.

    This is called from the MCP tool handler after successful tool execution.

    Args:
        session: Database session
        job_id: The job_id extracted from MCP tool arguments
        ws_manager: WebSocket manager for broadcasting
        tenant_key: Tenant isolation key (required, no default)
    """
    repo = AgentOperationsRepository()
    agent, project_id = await repo.find_silent_agent_with_project(session, tenant_key, job_id)

    if agent is None:
        return

    old_status = agent.status
    await repo.clear_silent_to_working(session, agent)

    logger.info(
        "Auto-cleared silent status: agent_id=%s, job_id=%s, display_name=%s",
        agent.agent_id,
        agent.job_id,
        agent.agent_display_name,
    )

    try:
        await _broadcast_status_change(
            ws_manager=ws_manager,
            agent=agent,
            old_status=old_status,
            new_status="working",
            project_id=str(project_id) if project_id else None,
        )
    except Exception as _exc:  # Broad catch: WebSocket resilience, non-critical broadcast
        logger.exception(
            "Failed to broadcast auto-clear for agent %s",
            agent.agent_id,
        )


async def clear_silent_status(
    session: AsyncSession,
    agent_id: str,
    tenant_key: str,
    ws_manager,
) -> dict | None:
    """Clear silent status for a specific agent (REST endpoint helper).

    Used by the dashboard when a user clicks the Silent badge to
    manually acknowledge and clear the status.

    Args:
        session: Database session
        agent_id: The agent execution ID
        tenant_key: Tenant key for isolation
        ws_manager: WebSocket manager for broadcasting

    Returns:
        Dict with updated agent info if cleared, None if agent not found or not silent
    """
    repo = AgentOperationsRepository()
    agent, project_id = await repo.find_silent_agent_by_agent_id(session, tenant_key, agent_id)

    if agent is None:
        return None

    old_status = agent.status
    await repo.clear_silent_to_working(session, agent)

    logger.info(
        "Manually cleared silent status: agent_id=%s, tenant_key=%s, display_name=%s",
        agent.agent_id,
        tenant_key,
        agent.agent_display_name,
    )

    try:
        await _broadcast_status_change(
            ws_manager=ws_manager,
            agent=agent,
            old_status=old_status,
            new_status="working",
            project_id=str(project_id) if project_id else None,
        )
    except Exception as _exc:  # Broad catch: WebSocket resilience, non-critical broadcast
        logger.exception(
            "Failed to broadcast clear-silent for agent %s",
            agent.agent_id,
        )

    return {
        "agent_id": str(agent.agent_id),
        "job_id": str(agent.job_id),
        "status": agent.status,
        "last_progress_at": agent.last_progress_at.isoformat() if agent.last_progress_at else None,
    }


async def _get_silence_threshold(session: AsyncSession) -> int:
    """Get the silence threshold from system settings.

    Looks for `agent_silence_threshold_minutes` in system_settings.
    Uses the stored value or defaults.

    Args:
        session: Database session

    Returns:
        Silence threshold in minutes
    """
    try:
        repo = AgentOperationsRepository()
        threshold_val = await repo.get_silence_threshold_setting(session)
        if threshold_val is not None:
            return threshold_val
    except (SQLAlchemyError, KeyError, ValueError):
        logger.exception("Failed to read silence threshold from settings")

    return DEFAULT_SILENCE_THRESHOLD_MINUTES


def _coerce_threshold_overrides(raw: dict[str, object]) -> dict[str, int]:
    """Coerce raw per-tenant Configuration JSONB values to valid minute ints.

    Defensive (FE-9241, hardened per TSK-9271): `configurations.value` is
    schemaless JSONB, so a row written outside the validated
    TenantConfigurationService write path could in principle hold anything —
    a dict/list, None, a boolean, a non-numeric string, or a JSON number so
    large it overflows a Python float to +/-inf (e.g. a `1e400` literal).
    Every one of those is dropped rather than crashing the background
    detection cycle; the cycle proceeds using the deployment-wide default for
    any tenant whose override row is malformed.
    """
    overrides: dict[str, int] = {}
    for tenant_key, value in raw.items():
        # bool is an int subclass in Python (int(True) == 1) -- reject it
        # explicitly so a stray JSONB `true`/`false` never silently becomes a
        # 1- or 0-minute threshold.
        if isinstance(value, bool):
            continue
        try:
            minutes = int(value)
        except (TypeError, ValueError, OverflowError):
            # OverflowError: a JSON number like `1e400` decodes to a Python
            # float that overflows to +/-inf; int(inf) raises OverflowError,
            # not ValueError.
            continue
        if 1 <= minutes <= MAX_AGENT_SILENCE_THRESHOLD_MINUTES:
            overrides[tenant_key] = minutes
    return overrides


async def _broadcast_status_change(
    ws_manager,
    agent: AgentExecution,
    old_status: str,
    new_status: str,
    project_id: str | None = None,
) -> None:
    """Broadcast an agent status change event via WebSocket.

    Uses the EventFactory.agent_status_changed pattern for consistency
    with other status change events in the system.

    Args:
        ws_manager: WebSocket manager
        agent: The agent execution object
        old_status: Previous status
        new_status: New status
        project_id: Optional project UUID string for frontend filtering
    """
    if ws_manager is None:
        logger.warning(
            "WebSocket manager unavailable — skipping broadcast for agent %s (%s → %s)",
            agent.agent_id,
            old_status,
            new_status,
        )
        return

    from giljo_mcp.events.schemas import EventFactory

    event = EventFactory.agent_status_changed(
        job_id=str(agent.job_id),
        tenant_key=agent.tenant_key,
        old_status=old_status,
        new_status=new_status,
        agent_display_name=agent.agent_display_name or "unknown",
        project_id=project_id,
        duration_seconds=agent.duration_seconds,  # BE-5107
    )

    await ws_manager.broadcast_event_to_tenant(
        tenant_key=agent.tenant_key,
        event=event,
    )
