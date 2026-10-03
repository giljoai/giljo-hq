# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import asyncio
import contextlib
import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from giljo_mcp.database import DatabaseManager
from giljo_mcp.domain.job_activity import HOLDING, WORKING, activity_word
from giljo_mcp.models.agent_identity import AgentExecution, AgentJob
from giljo_mcp.repositories.agent_operations_repository import AgentOperationsRepository
from giljo_mcp.repositories.configuration_repository import ConfigurationRepository
from giljo_mcp.schemas.responses.orchestration import OrchestratorDisplayState
from giljo_mcp.services.settings_service import AGENT_SILENCE_THRESHOLD_KEY, MAX_AGENT_SILENCE_THRESHOLD_MINUTES


logger = logging.getLogger(__name__)

DEFAULT_SILENCE_THRESHOLD_MINUTES = 10

DEFAULT_SCAN_INTERVAL_SECONDS = 60


class SilenceDetector:

    def __init__(
        self,
        db_manager: DatabaseManager,
        ws_manager,
        scan_interval_seconds: int = DEFAULT_SCAN_INTERVAL_SECONDS,
    ):
        self.db = db_manager
        self.ws = ws_manager
        self.scan_interval_seconds = scan_interval_seconds
        self.running = False
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        if self.running:
            logger.warning("Silence detector already running")
            return

        self.running = True
        self._task = asyncio.create_task(self._monitoring_loop())
        logger.info("Silence detector started (scan interval: %ds)", self.scan_interval_seconds)

    async def stop(self) -> None:
        self.running = False
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
        logger.info("Silence detector stopped")

    async def _monitoring_loop(self) -> None:
        while self.running:
            try:
                await self._run_detection_cycle()
            except Exception as _exc:
                logger.exception("Silence detection cycle failed")

            await asyncio.sleep(self.scan_interval_seconds)

    async def _run_detection_cycle(self) -> None:
        async with self.db.get_session_async() as session:
            repo = AgentOperationsRepository()
            threshold_val = await repo.get_silence_threshold_setting(session)
            default_threshold = threshold_val if threshold_val is not None else DEFAULT_SILENCE_THRESHOLD_MINUTES

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
        tenant_overrides = tenant_overrides or {}
        now = datetime.now(UTC)

        min_threshold = min([threshold_minutes, *tenant_overrides.values()])
        cutoff = now - timedelta(minutes=min_threshold)

        repo = AgentOperationsRepository()
        candidate_agents = await repo.find_stale_working_agents(session, cutoff)

        stale_agents = []
        for agent in candidate_agents:
            own_threshold = tenant_overrides.get(agent.tenant_key, threshold_minutes)
            reference_time = agent.last_progress_at or agent.started_at
            if reference_time is not None and reference_time >= now - timedelta(minutes=own_threshold):
                continue
            stale_agents.append(agent)

        silenced: list[tuple[str, str | None, datetime | None, int]] = []

        count = 0
        for agent in stale_agents:
            old_status = agent.status
            own_threshold = tenant_overrides.get(agent.tenant_key, threshold_minutes)

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

            try:
                await _broadcast_status_change(
                    ws_manager=self.ws,
                    agent=agent,
                    old_status=old_status,
                    new_status="silent",
                    project_id=project_id,
                )

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
            except Exception as _exc:
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
                    continue
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
    except Exception as _exc:
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
    except Exception as _exc:
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


def _minutes_since(moment: datetime | None, now: datetime) -> int:
    return max(0, int((now - moment).total_seconds() // 60)) if moment else 0


def _display_state(orchestrator, workers: list, counts: dict, now: datetime) -> OrchestratorDisplayState:
    running = [w for w in workers if activity_word(w.status, counts.get(w.job_id)) == WORKING]
    waiting = [w for w in workers if w.status == "complete"]
    own = counts.get(orchestrator.job_id, {})
    common = {
        "stale_minutes": _minutes_since(orchestrator.last_progress_at or orchestrator.started_at, now),
        "todos_done": own.get("completed", 0),
        "todos_total": sum(own.values()),
    }
    if running:
        noun = "agent" if len(running) == 1 else "agents"
        label = f"Monitoring ({len(running)} {noun} running)"
        return OrchestratorDisplayState(state="monitoring", label=label, agents=len(running), **common)
    if waiting:
        oldest = min((w.completed_at for w in waiting if w.completed_at), default=None)
        minutes = _minutes_since(oldest, now)
        label = f"Result waiting, not picked up ({minutes} min)"
        return OrchestratorDisplayState(
            state="result_waiting", label=label, agents=len(waiting), minutes=minutes, **common
        )
    return OrchestratorDisplayState(state="silent", label="Silent", **common)


async def stale_orchestrator_states(
    session: AsyncSession,
    tenant_key: str,
    project_ids: list[str] | None = None,
    job_id: str | None = None,
    now: datetime | None = None,
) -> dict[str, OrchestratorDisplayState]:
    if job_id:
        owner = aliased(AgentJob)
        scope = (
            AgentJob.project_id
            == select(owner.project_id).where(owner.job_id == job_id, owner.tenant_key == tenant_key).scalar_subquery()
        )
    elif project_ids:
        scope = AgentJob.project_id.in_(project_ids)
    else:
        return {}

    rows = (
        await session.execute(
            select(
                AgentJob.project_id,
                AgentJob.job_id,
                AgentJob.job_type,
                AgentJob.job_metadata["chain_conductor"].as_boolean().label("conductor"),
                AgentExecution.status,
                AgentExecution.last_progress_at,
                AgentExecution.started_at,
                AgentExecution.completed_at,
            )
            .join(AgentJob, AgentExecution.job_id == AgentJob.job_id)
            .where(
                AgentExecution.tenant_key == tenant_key,
                AgentJob.tenant_key == tenant_key,
                AgentExecution.status.in_(("working", "silent", "complete")),
                scope,
            )
        )
    ).all()
    stale = [r for r in rows if r.job_type == "orchestrator" and not r.conductor and r.status == "silent"]
    if not stale:
        return {}

    counts = await AgentOperationsRepository().get_todo_counts_by_job(session, tenant_key, [r.job_id for r in rows])
    now = now or datetime.now(UTC)
    states: dict[str, OrchestratorDisplayState] = {}
    for orchestrator in stale:
        if activity_word(orchestrator.status, counts.get(orchestrator.job_id)) == HOLDING:
            continue
        workers = [r for r in rows if r.project_id == orchestrator.project_id and r.job_type != "orchestrator"]
        states[orchestrator.job_id] = _display_state(orchestrator, workers, counts, now)
    return states


async def _get_silence_threshold(session: AsyncSession) -> int:
    try:
        repo = AgentOperationsRepository()
        threshold_val = await repo.get_silence_threshold_setting(session)
        if threshold_val is not None:
            return threshold_val
    except (SQLAlchemyError, KeyError, ValueError):
        logger.exception("Failed to read silence threshold from settings")

    return DEFAULT_SILENCE_THRESHOLD_MINUTES


def _coerce_threshold_overrides(raw: dict[str, object]) -> dict[str, int]:
    overrides: dict[str, int] = {}
    for tenant_key, value in raw.items():
        if isinstance(value, bool):
            continue
        try:
            minutes = int(value)
        except (TypeError, ValueError, OverflowError):
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
        duration_seconds=agent.duration_seconds,
    )

    await ws_manager.broadcast_event_to_tenant(
        tenant_key=agent.tenant_key,
        event=event,
    )
