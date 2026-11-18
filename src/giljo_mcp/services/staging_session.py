# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.models.agent_identity import AgentExecution, AgentJob
from giljo_mcp.platform_registry import is_subagent_mode
from giljo_mcp.services.orchestrator_caller_guard import NEVER_STARTED_STATUSES


logger = logging.getLogger(__name__)

PLANNING_STATUSES = frozenset({"working", "silent"})


def is_planning_session(execution: Any) -> bool:
    return execution.status in PLANNING_STATUSES and execution.result is None


async def start_staging_session(
    session: AsyncSession, execution: Any, job: Any, tenant_key: str, websocket_manager: Any | None
) -> None:
    if execution.status not in NEVER_STARTED_STATUSES or execution.result is not None:
        return
    old_status = execution.status
    now = datetime.now(UTC)
    execution.status = "working"
    execution.started_at = execution.started_at or now
    execution.last_progress_at = now
    await session.commit()
    if websocket_manager is None:
        return
    try:
        await _broadcast_started(websocket_manager, execution, job, tenant_key, old_status)
    except Exception:  # noqa: BLE001 - the dashboard refetches; never fail instruction delivery
        logger.warning("staging start broadcast failed for job %s", job.job_id, exc_info=True)


async def start_parked_orchestrator_on_launch(
    session: AsyncSession, project: Any, tenant_key: str
) -> tuple[Any, Any, str] | None:
    if not is_subagent_mode(project.execution_mode):
        return None
    rows = (
        await session.execute(
            select(AgentExecution, AgentJob)
            .join(AgentJob, AgentExecution.job_id == AgentJob.job_id)
            .where(
                AgentJob.project_id == str(project.id),
                AgentJob.job_type == "orchestrator",
                AgentJob.tenant_key == tenant_key,
                AgentExecution.tenant_key == tenant_key,
                AgentExecution.status.in_(NEVER_STARTED_STATUSES),
            )
            .order_by(AgentJob.created_at.desc().nulls_last(), AgentExecution.id.desc())
        )
    ).all()
    started = next(((e, j) for e, j in rows if e.result is not None), None)
    if started is None:
        return None
    execution, job = started
    old_status = execution.status
    now = datetime.now(UTC)
    execution.status = "working"
    execution.started_at = execution.started_at or now
    execution.last_progress_at = now
    await session.flush()
    return execution, job, old_status


async def broadcast_orchestrator_started(
    websocket_manager: Any | None, execution: Any, job: Any, tenant_key: str, old_status: str
) -> None:
    if websocket_manager is None:
        return
    try:
        await _broadcast_started(websocket_manager, execution, job, tenant_key, old_status)
    except Exception:  # noqa: BLE001 - the dashboard refetches; never fail the launch
        logger.warning("orchestrator start broadcast failed for job %s", job.job_id, exc_info=True)


async def _broadcast_started(
    websocket_manager: Any, execution: Any, job: Any, tenant_key: str, old_status: str
) -> None:
    await websocket_manager.broadcast_to_tenant(
        tenant_key=tenant_key,
        event_type="agent:status_changed",
        data={
            "job_id": job.job_id,
            "project_id": str(job.project_id) if job.project_id else None,
            "chain_conductor": bool((job.job_metadata or {}).get("chain_conductor", False)),
            "agent_id": execution.agent_id,
            "agent_display_name": execution.agent_display_name,
            "agent_name": execution.agent_name,
            "old_status": old_status,
            "status": "working",
            "started_at": execution.started_at.isoformat(),
            "duration_seconds": execution.duration_seconds,
            "working_started_at": execution.working_started_at.isoformat() if execution.working_started_at else None,
        },
    )
