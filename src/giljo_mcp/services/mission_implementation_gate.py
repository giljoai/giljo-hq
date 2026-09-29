# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.models import AgentJob
from giljo_mcp.schemas.service_responses import MissionResponse
from giljo_mcp.services.execution_mode_gate import (
    EXECUTION_MODE_NOT_SELECTED_MESSAGE,
    execution_mode_selected,
)
from giljo_mcp.services.sequence_run_service import active_chain_run


async def check_implementation_gate(
    logger: Any,
    session: AsyncSession,
    job: AgentJob,
    job_id: str,
    tenant_key: str,
    *,
    repo: Any,
    db_manager: Any,
    tenant_manager: Any,
    agent_id: str | None = None,
) -> tuple[Any, MissionResponse | None]:
    if job.project_id is None:
        hold = await check_conductor_chain_hold(
            session,
            job,
            job_id,
            tenant_key,
            agent_id=agent_id,
            repo=repo,
            db_manager=db_manager,
            tenant_manager=tenant_manager,
        )
        return None, hold

    from giljo_mcp.services.mission_service import _CHAIN_WORKER_STAGING_BLOCK_MESSAGE

    project = await repo.get_project_by_id(session, tenant_key, job.project_id)

    if project is not None and not execution_mode_selected(project):
        return project, MissionResponse(
            job_id=job_id,
            blocked=True,
            mission=None,
            full_protocol=None,
            error="BLOCKED: No execution mode selected",
            user_instruction=EXECUTION_MODE_NOT_SELECTED_MESSAGE,
        )

    if project and project.implementation_launched_at is None:
        if job.job_type == "orchestrator":
            chain_member = await active_chain_run(session, job.project_id, tenant_key) is not None
            if chain_member and project.staging_status != "staging_complete":
                return project, None
            return project, MissionResponse(
                job_id=job_id,
                blocked=True,
                mission=None,
                full_protocol=None,
                error="BLOCKED: Implementation phase not launched",
                user_instruction=(
                    "Staging is complete but implementation has not been launched. "
                    "Return to the dashboard and click Implement, then start (or paste) your "
                    "orchestrator prompt in your agent session (terminal, desktop, or web tab)."
                ),
            )
        chain_member = await active_chain_run(session, job.project_id, tenant_key) is not None
        if chain_member:
            return project, MissionResponse(
                job_id=job_id,
                blocked=True,
                mission=None,
                full_protocol=None,
                error="BLOCKED: Chain orchestrator still staging",
                user_instruction=_CHAIN_WORKER_STAGING_BLOCK_MESSAGE,
            )
        return project, MissionResponse(
            job_id=job_id,
            blocked=True,
            mission=None,
            full_protocol=None,
            error="BLOCKED: Implementation phase not started by user",
            user_instruction=(
                "Your mission is blocked. The user must click the 'Implement' "
                "button in the GiljoAI dashboard before you can receive your mission. "
                "Please inform your user of this requirement and wait."
            ),
        )

    return project, None


_CONDUCTOR_HOLD_MESSAGE = (
    "The chain is staged but has not been released. The user must press Implement on "
    "the chain in the dashboard, or approve launch_implementation for the chain's first "
    "project, before you can drive it. Report the staged plan to the user and wait."
)


async def check_conductor_chain_hold(
    session: AsyncSession,
    job: AgentJob,
    job_id: str,
    tenant_key: str,
    *,
    agent_id: str | None,
    repo: Any,
    db_manager: Any,
    tenant_manager: Any,
) -> MissionResponse | None:
    if job.job_type != "orchestrator" or not (job.job_metadata or {}).get("chain_conductor") or not agent_id:
        return None

    from giljo_mcp.services.sequence_run_service import SequenceRunService

    svc = SequenceRunService(db_manager=db_manager, tenant_manager=tenant_manager, session=session)
    run = await svc.find_active_run_for_conductor(conductor_agent_id=str(agent_id), tenant_key=tenant_key)
    if run is None or run.get("status") != "pending":
        return None
    order = run.get("resolved_order") or []
    head = await repo.get_project_by_id(session, tenant_key, order[0]) if order else None
    if head is not None and head.implementation_launched_at is not None:
        return None
    return MissionResponse(
        job_id=job_id,
        blocked=True,
        mission=None,
        full_protocol=None,
        error="BLOCKED: Implementation phase not launched",
        user_instruction=_CONDUCTOR_HOLD_MESSAGE,
    )


_CHAIN_MEMBER_SETTLED_STATUSES: frozenset[str] = frozenset(
    {"awaiting_review", "completed", "failed", "stalled", "terminated"}
)


async def promote_chain_member_on_first_worker_start(
    mission_service: Any, session: AsyncSession, job: AgentJob, tenant_key: str
) -> None:
    if job.job_type == "orchestrator" or not job.project_id:
        return
    from giljo_mcp.services.project_helpers import mark_chain_member_status

    await mark_chain_member_status(
        db_manager=mission_service.db_manager,
        tenant_manager=mission_service.tenant_manager,
        project_id=str(job.project_id),
        tenant_key=tenant_key,
        status="implementing",
        test_session=session,
        websocket_manager=mission_service._websocket_manager,
        not_from=_CHAIN_MEMBER_SETTLED_STATUSES,
    )
