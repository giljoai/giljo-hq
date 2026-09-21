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

from giljo_mcp.exceptions import ValidationError
from giljo_mcp.models import AgentExecution, AgentJob
from giljo_mcp.models.projects import Project
from giljo_mcp.models.sequence_runs import CHAIN_TERMINAL_PROJECT_STATUSES
from giljo_mcp.repositories.mission_repository import MissionRepository
from giljo_mcp.schemas.service_responses import StagingDirective, build_next_action
from giljo_mcp.services.project_helpers import (
    advance_chain_member_to_implementing,
    complete_chain_run_if_finished,
    heal_chain_member_statuses,
    mark_staging_complete,
)


logger = logging.getLogger(__name__)


_CHAIN_SUBORCH_STAGING_END_NEXT_ACTION = (
    "Staging is complete. Your CHAIN ORCHESTRATOR opens your implementation gate "
    "automatically -- do NOT wait for a human and do NOT return to the dashboard. "
    "Call get_job_mission ONCE now: your gate is already OPEN, so this first call "
    "normally returns your implementation protocol -- continue straight into it. "
    "ONLY if that first call does NOT yet return the implementation protocol, sleep "
    "~30s and retry, repeating until it does. Do NOT write the project closeout from "
    "the staging session."
)

_CHAIN_SUBORCH_STAGING_END_ACTION = "CONTINUE"
_CHAIN_SUBORCH_STAGING_END_NEXT_STEP = (
    "Call get_job_mission once now to continue into implementation -- your gate is "
    "already OPEN. Do NOT report to the user and do NOT stop."
)

_CONDUCTOR_STAGING_END_ACTION = "STOP"
_CONDUCTOR_STAGING_END_NEXT_ACTION = (
    "Report the staged chain plan and the chain mission to the user, then ASK THE USER "
    "ONE question: do they want to run this chain here (they say go, and you drive it in "
    "this session) or from the dashboard (they press 'Implement Chain')? Then STOP and "
    "wait -- do not answer it for them. Do NOT self-launch, do NOT spawn a "
    "sub-orchestrator, and do NOT re-call get_job_mission to start driving. Proceed only "
    "after the user's EXPLICIT GO."
)
_CONDUCTOR_STAGING_END_NEXT_STEP = (
    "Report the staged chain plan to the user, then ask the user ONE question: run it "
    "here (they say go) or from the dashboard (they press 'Implement Chain')? Then STOP "
    "and wait. Do NOT self-launch and do NOT re-call get_job_mission to drive. Proceed "
    "only after the user's explicit GO."
)

_RUN_IMPL_STARTED_STATUSES: frozenset[str] = frozenset(
    {"planning", "implementing", "awaiting_review", "completed", "failed", "stalled", "terminated"}
)


async def guard_conductor_chain_incomplete(
    session: AsyncSession,
    job: AgentJob,
    execution: AgentExecution,
    tenant_key: str,
    job_id: str,
    *,
    db_manager: Any,
    tenant_manager: Any,
) -> None:
    if getattr(job, "job_type", "") != "orchestrator":
        return
    agent_id = getattr(execution, "agent_id", None)
    if not agent_id:
        return

    from giljo_mcp.services.sequence_run_service import SequenceRunService

    svc = SequenceRunService(
        db_manager=db_manager,
        tenant_manager=tenant_manager,
        session=session,
    )
    run = await svc.find_active_run_for_conductor(conductor_agent_id=agent_id, tenant_key=tenant_key)
    if run is None:
        return

    resolved_order = run.get("resolved_order") or []
    statuses = run.get("project_statuses") or {}
    remaining = [pid for pid in resolved_order if statuses.get(pid) not in CHAIN_TERMINAL_PROJECT_STATUSES]
    if remaining:
        statuses = await heal_chain_member_statuses(
            session=session, sequence_run_service=svc, run=run, tenant_key=tenant_key
        )
        remaining = [pid for pid in resolved_order if statuses.get(pid) not in CHAIN_TERMINAL_PROJECT_STATUSES]
    if not remaining:
        return

    raise ValidationError(
        message=(
            f"You are the CONDUCTOR of chain run {run['id']} with "
            f"{len(remaining)} project(s) still incomplete. Do NOT complete_job yet. "
            "From your driving session advance the chain by spawning the next project's "
            "sub-orchestrator and waiting for its closeout. To end the chain early, use the "
            "dashboard back-out controls (Deactivate Chain / Reset / Cancel). complete_job "
            "is only valid after the FINAL project closes out; this protects the chain from "
            "being orphaned mid-drive."
        ),
        error_code="CONDUCTOR_CHAIN_INCOMPLETE",
        context={"run_id": run["id"], "remaining_projects": len(remaining), "job_id": job_id},
    )


async def finalize_conductor_chain(
    session: AsyncSession,
    job: AgentJob,
    execution: AgentExecution,
    tenant_key: str,
    *,
    is_staging_end: bool,
    db_manager: Any,
    tenant_manager: Any,
    websocket_manager: Any | None = None,
) -> bool:
    if job.job_type == "orchestrator" and not is_staging_end:
        agent_id = getattr(execution, "agent_id", None)
        if agent_id:
            await complete_chain_run_if_finished(
                db_manager=db_manager,
                tenant_manager=tenant_manager,
                conductor_agent_id=str(agent_id),
                tenant_key=tenant_key,
                test_session=session,
                websocket_manager=websocket_manager,
            )
    return getattr(job, "project_id", None) is None and bool(
        (getattr(job, "job_metadata", None) or {}).get("chain_conductor")
    )


def is_staging_phase_orchestrator(job: Any, project: Any) -> bool:
    if job is None or project is None or getattr(job, "job_type", None) != "orchestrator":
        return False
    if getattr(project, "staging_status", None) not in ("staging", "staged", "staging_complete"):
        return False
    launched = getattr(project, "implementation_launched_at", None) is not None
    return not (launched and project.staging_status == "staging_complete")


async def is_staging_end_orchestrator_call(
    session: AsyncSession,
    job: AgentJob,
    execution: AgentExecution,
    tenant_key: str,
    *,
    db_manager: Any,
    tenant_manager: Any,
) -> tuple[bool, Project | None]:
    if job.job_type != "orchestrator":
        return False, None

    if job.project_id is None:
        conductor_staging_end = await is_conductor_staging_end(
            session, execution, tenant_key, db_manager=db_manager, tenant_manager=tenant_manager
        )
        return conductor_staging_end, None

    if getattr(execution, "project_phase", None) != "staging":
        return False, None
    if not job.project_id:
        return False, None

    stmt = select(Project).where(
        Project.id == str(job.project_id),
        Project.tenant_key == tenant_key,
    )
    project = (await session.execute(stmt)).scalar_one_or_none()
    if (
        project is not None
        and project.implementation_launched_at is not None
        and project.staging_status == "staging_complete"
    ):
        return False, project

    if project is not None and await _finale_deliverables_recorded(
        session,
        tenant_key,
        str(job.project_id),
        db_manager=db_manager,
        tenant_manager=tenant_manager,
    ):
        return False, project

    return True, project


async def _finale_deliverables_recorded(
    session: AsyncSession,
    tenant_key: str,
    project_id: str,
    *,
    db_manager: Any,
    tenant_manager: Any,
) -> bool:
    from giljo_mcp.repositories.mission_repository import MissionRepository

    total, in_flight = await MissionRepository().count_non_orchestrator_agents_by_liveness(
        session, tenant_key, project_id
    )
    if total == 0 or in_flight > 0:
        return False

    try:
        from giljo_mcp.services.sequence_run_service import SequenceRunService

        svc = SequenceRunService(
            db_manager=db_manager,
            tenant_manager=tenant_manager,
            session=session,
        )
        run = await svc.find_active_run_for_project(project_id=project_id, tenant_key=tenant_key)
    except Exception:  # noqa: BLE001 — on lookup failure keep the staging-end classification unchanged
        logger.warning("[BE-9165] chain-member check failed (non-fatal); keeping staging-end classification")
        return False
    return run is None


async def is_conductor_staging_end(
    session: AsyncSession,
    execution: AgentExecution,
    tenant_key: str,
    *,
    db_manager: Any,
    tenant_manager: Any,
) -> bool:
    agent_id = getattr(execution, "agent_id", None)
    if not agent_id:
        return False

    from giljo_mcp.services.sequence_run_service import SequenceRunService

    svc = SequenceRunService(
        db_manager=db_manager,
        tenant_manager=tenant_manager,
        session=session,
    )
    run = await svc.find_active_run_for_conductor(conductor_agent_id=str(agent_id), tenant_key=tenant_key)
    if run is None:
        return False

    if run.get("current_index", 0) != 0:
        return False
    statuses = (run.get("project_statuses") or {}).values()
    return not any(s in _RUN_IMPL_STARTED_STATUSES for s in statuses)


async def handle_staging_end(
    session: AsyncSession,
    job: AgentJob,
    execution: AgentExecution,
    tenant_key: str,
    *,
    is_staging_end: bool,
    project: Project | None,
    is_chain_member_suborch: bool = False,
    is_conductor: bool = False,
    db_manager: Any,
    tenant_manager: Any,
    websocket_manager: Any | None,
    test_session: AsyncSession | None,
) -> StagingDirective | None:
    if not is_staging_end:
        return None

    if project is None:
        if not is_conductor:
            logger.warning(
                "[STAGING_END] Project %s not found for staging orchestrator job %s — "
                "skipping flag flip but still returning STOP directive",
                job.project_id,
                job.job_id,
            )
        return staging_directive_for(is_chain_member_suborch, is_conductor=is_conductor)

    mission_repo = MissionRepository()
    non_orchestrator_count = await mission_repo.count_non_orchestrator_agents(session, tenant_key, job.project_id)
    if non_orchestrator_count == 0:
        raise ValidationError(
            message=(
                "COMPLETION_BLOCKED: staging cannot end without at least one spawned "
                "specialist agent. Spawn a single implementer for trivial work (a 4-line "
                "mission is fine), then retry complete_job."
            ),
            error_code="STAGING_END_NO_AGENTS",
        )

    await mark_staging_complete(
        session,
        project,
        source="complete_job:staging_end",
        websocket_manager=websocket_manager,
    )

    if is_chain_member_suborch:
        launched_at = datetime.now(UTC)
        project.implementation_launched_at = launched_at
        project.updated_at = launched_at
        await session.flush()
        await advance_chain_member_to_implementing(
            db_manager=db_manager,
            tenant_manager=tenant_manager,
            project_id=str(job.project_id),
            tenant_key=tenant_key,
            session=test_session,
            websocket_manager=websocket_manager,
        )
        if websocket_manager is not None:
            try:
                await websocket_manager.broadcast_to_tenant(
                    tenant_key=project.tenant_key,
                    event_type="project:implementation_launched",
                    data={
                        "project_id": str(job.project_id),
                        "product_id": project.product_id,
                        "implementation_launched_at": launched_at.isoformat(),
                        "source": "mcp",
                    },
                )
            except Exception as ws_error:  # noqa: BLE001 — WS resilience
                logger.warning(
                    "[STAGING_END:BE-9111] implementation_launched WS broadcast failed: %s",
                    ws_error,
                )

    return staging_directive_for(is_chain_member_suborch, is_conductor=is_conductor)


def staging_directive_for(is_chain_member_suborch: bool, is_conductor: bool = False) -> StagingDirective:
    if is_chain_member_suborch:
        return StagingDirective(
            action=_CHAIN_SUBORCH_STAGING_END_ACTION,
            message=_CHAIN_SUBORCH_STAGING_END_NEXT_ACTION,
            next_action=build_next_action(tool="get_job_mission", why=_CHAIN_SUBORCH_STAGING_END_NEXT_STEP),
        )
    if is_conductor:
        return StagingDirective(
            action=_CONDUCTOR_STAGING_END_ACTION,
            message=_CONDUCTOR_STAGING_END_NEXT_ACTION,
            next_action=build_next_action(why=_CONDUCTOR_STAGING_END_NEXT_STEP),
        )
    return StagingDirective()
