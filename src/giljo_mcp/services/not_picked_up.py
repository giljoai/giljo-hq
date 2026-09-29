# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import logging
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.models.agent_identity import TERMINAL_EXECUTION_STATUSES, AgentExecution, AgentJob
from giljo_mcp.models.projects import Project
from giljo_mcp.services.sequence_run_service import active_chain_run
from giljo_mcp.services.settings_service import DEFAULT_AGENT_CHECKIN_CADENCE_MINUTES


logger = logging.getLogger(__name__)

NOT_PICKED_UP_WHY = (
    "An agent is still waiting well after launch, so nobody started it: "
    "launch it with the stored prompt (the agent_prompt spawn_job returned), verbatim."
)


def _aware(value: datetime | None) -> datetime | None:
    if value is None or value.tzinfo is not None:
        return value
    return value.replace(tzinfo=UTC)


async def _chain_reached_at(session: AsyncSession, tenant_key: str, project_id: str) -> datetime | None:
    run = await active_chain_run(session, project_id, tenant_key)
    order: list[str] = (run or {}).get("resolved_order") or []
    if project_id not in order:
        return None
    index = order.index(project_id)
    if index > 0:
        closed_at = (
            await session.execute(
                select(Project.closeout_executed_at).where(
                    Project.id == order[index - 1], Project.tenant_key == tenant_key
                )
            )
        ).scalar_one_or_none()
        return _aware(closed_at)
    conductor_agent_id = run.get("conductor_agent_id")
    if not conductor_agent_id:
        return None
    started_at = (
        await session.execute(
            select(AgentExecution.started_at)
            .where(AgentExecution.agent_id == conductor_agent_id, AgentExecution.tenant_key == tenant_key)
            .limit(1)
        )
    ).scalar_one_or_none()
    return _aware(started_at)


async def _project_job_rows(session: AsyncSession, tenant_key: str, project_id: str) -> list[Any]:
    result = await session.execute(
        select(
            AgentJob.job_id,
            AgentJob.job_type,
            AgentJob.created_at,
            AgentJob.phase,
            AgentExecution.status,
            AgentExecution.completed_at,
        )
        .join(AgentJob, AgentExecution.job_id == AgentJob.job_id)
        .where(AgentExecution.tenant_key == tenant_key, AgentJob.project_id == project_id)
    )
    return list(result.all())


def _phase_turn_started(phase: int | None, project_rows: list[Any]) -> tuple[bool, datetime | None]:
    if phase is None:
        return True, None
    lower = [row for row in project_rows if row.phase is not None and row.phase < phase]
    if any(row.status not in TERMINAL_EXECUTION_STATUSES for row in lower):
        return False, None
    finished = [_aware(row.completed_at) for row in lower if row.completed_at is not None]
    return True, max(finished) if finished else None


async def not_picked_up_job_ids(
    session: AsyncSession,
    tenant_key: str,
    project: Any,
    rows: Iterable[tuple[str, str | None, str]],
    cadence_minutes: int | None,
    now: datetime | None = None,
) -> set[str]:
    waiting = [(key, job_id) for key, status, job_id in rows if status == "waiting"]
    if not waiting or project is None:
        return set()

    project_rows = await _project_job_rows(session, tenant_key, str(project.id))
    jobs = {row.job_id: row for row in project_rows}
    now = now or datetime.now(UTC)
    threshold = timedelta(minutes=cadence_minutes or DEFAULT_AGENT_CHECKIN_CADENCE_MINUTES)
    launched_at = _aware(getattr(project, "implementation_launched_at", None))
    chain_reached_at: datetime | None = None
    if launched_at is None and any(getattr(jobs.get(j), "job_type", None) == "orchestrator" for _k, j in waiting):
        chain_reached_at = await _chain_reached_at(session, tenant_key, str(project.id))

    flagged: set[str] = set()
    for key, job_id in waiting:
        job = jobs.get(job_id)
        if job is None:
            continue
        start = launched_at or (chain_reached_at if job.job_type == "orchestrator" else None)
        is_its_turn, turn_began = _phase_turn_started(job.phase, project_rows)
        if start is None or not is_its_turn:
            continue
        for later in (_aware(job.created_at), turn_began):
            if later is not None and later > start:
                start = later
        if now - start > threshold:
            flagged.add(key)
    return flagged
