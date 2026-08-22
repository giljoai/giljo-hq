# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""Implementation-launch gate helpers for MissionService (BE-9073).

Verbatim split from ``mission_service.py`` to keep that module under the shrink-only
size budget. ``check_implementation_gate`` and ``is_chain_member`` take an explicit
``logger`` (mirrors the ``mission_assembly.py`` idiom) plus the already-fetched
``session``/``job`` objects and the service's ``repo``/``db_manager``/``tenant_manager``
handles — no new sessions are opened here. ``MissionService`` keeps thin back-compat
shims of unchanged name/signature that delegate here. Pure move, no behavior change.
Edition Scope: CE.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.models import AgentJob
from giljo_mcp.schemas.service_responses import MissionResponse
from giljo_mcp.services.execution_mode_gate import (
    EXECUTION_MODE_NOT_SELECTED_MESSAGE,
    execution_mode_selected,
)


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
) -> tuple[Any, MissionResponse | None]:
    """Check implementation phase gate.

    Returns:
        Tuple of (project, gate_response). gate_response is non-None if blocked.
    """
    # BE-6221c: the block message is the module constant owned by mission_service.py
    # (imported here, not defined here, so `from giljo_mcp.services.mission_service
    # import _CHAIN_WORKER_STAGING_BLOCK_MESSAGE` keeps resolving for existing
    # importers). Deferred import: mission_service.py imports this module at load
    # time, so a module-level import here would be circular.
    from giljo_mcp.services.mission_service import _CHAIN_WORKER_STAGING_BLOCK_MESSAGE

    project = await repo.get_project_by_id(session, tenant_key, job.project_id)

    # NULL-state gate: no mission until an execution mode is chosen. Backstop
    # for out-of-band / legacy rows (normal flow sets the mode at staging).
    # Fires before the implementation-launch gate and before any protocol is
    # rendered, so a NULL never reaches the HO1020 render fail-safes.
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
            # §14 deadlock-breaker (CHAIN_ARCHITECTURE.md): a released chain
            # sub-orchestrator is NEVER gated. The conductor's spawn IS the start —
            # there is no per-project "wait for a go" step on either side. Fall
            # through (return None) so get_agent_mission renders this sub-orch's
            # COMBINED CH_SUB_ORCHESTRATOR protocol immediately and it starts working
            # (the prior BLOCKED response hid the mission behind a gate the
            # orchestrator could never open, while the conductor waited for a
            # staging_complete it could never produce). Strictly chain-gated: a solo
            # project (no active run) keeps the original human-gate message below
            # byte-identical (Deletion Test on the SOLO gate holds).
            chain_member = await is_chain_member(
                logger, session, job.project_id, tenant_key, db_manager=db_manager, tenant_manager=tenant_manager
            )
            # BE-9069 (Defect A): the chain exemption releases a sub-orchestrator DURING
            # its OWN staging. A chain member reaches staging_status='staging_complete'
            # and implementation_launched_at ATOMICALLY at its staging-end (job_completion_
            # service.py:1042 mark_staging_complete + 1068-1071 stamp, one complete_job txn;
            # pinned by test_be6206 test 3), so a chain member is NEVER 'staging_complete'
            # while launch is NULL. That exact state (staging_complete + launch NULL) is
            # UNIQUELY a SOLO project parked at the human Implement gate; mere enrollment in
            # a freshly minted (pending, zero-conductor-activity) run must NOT un-gate it
            # (BE-6115a: a spawned/staging agent cannot self-unlock implementation). A
            # genuinely released member (staging_status still 'staged'/NULL) still crosses.
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
        # BE-6213 P1: a WORKER spawned during a chain sub-orch's staging is
        # inert until that sub-orch's staging-end stamps implementation_launched_at.
        # The chain has no human Implement button, so reuse is_chain_member (the
        # same predicate the orchestrator branch uses above) to hand it a
        # chain-worded message instead of the dead-end "click Implement" wording.
        # Solo workers (chain_member False) keep the legacy message byte-identical.
        chain_member = await is_chain_member(
            logger, session, job.project_id, tenant_key, db_manager=db_manager, tenant_manager=tenant_manager
        )
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


async def is_chain_member(
    logger: Any,
    session: AsyncSession,
    project_id: Any,
    tenant_key: str,
    *,
    db_manager: Any,
    tenant_manager: Any,
) -> bool:
    """Return True if this project belongs to an ACTIVE sequential chain (BE-6196).

    Used by the implementation gate to pick the chain-aware blocked message (the
    conductor crosses the gate automatically) over the solo "click Implement" one.
    Best-effort: a resolution failure returns False so the gate falls back to the
    solo message and mission delivery is NEVER broken by chain lookup.
    """
    try:
        from giljo_mcp.services.sequence_run_service import SequenceRunService

        svc = SequenceRunService(
            db_manager=db_manager,
            tenant_manager=tenant_manager,
            session=session,
        )
        run = await svc.find_active_run_for_project(project_id=str(project_id), tenant_key=tenant_key)
        return run is not None
    except Exception:  # noqa: BLE001 - best-effort chain detection; never block the gate
        logger.warning("[BE-6196] chain-member check failed (non-fatal); falling back to solo gate")
        return False


# FE-9493: a chain member that has already settled past "implementing" — a late/racing
# worker's first mission fetch must never demote it back. Passed as mark_chain_member_status's
# forward-only ``not_from`` guard from promote_chain_member_on_first_worker_start below.
_CHAIN_MEMBER_SETTLED_STATUSES: frozenset[str] = frozenset(
    {"awaiting_review", "completed", "failed", "stalled", "terminated"}
)


async def promote_chain_member_on_first_worker_start(mission_service: Any, job: AgentJob, tenant_key: str) -> None:
    """FE-9493: promote a chain member planning->implementing on its first worker's start.

    Called from ``MissionService.get_agent_mission``'s atomic waiting->working start
    block, split out here for the same size-budget reason as the rest of this module
    (see the module docstring). This IS "the first agent a chain member's
    sub-orchestrator spawned starts working" — the WORKING signal the tab strip needs,
    distinct from "planning" (the sub-orch itself entering the project, written by
    ``advance_chain_member_to_implementing``).

    ``mission_service`` is the calling ``MissionService`` instance (mirrors the rest of
    this module treating the service's handles as directly accessible — see the module
    docstring); its ``db_manager`` / ``tenant_manager`` / ``_test_session`` /
    ``_websocket_manager`` are read straight off it, keeping the call site to one line.

    Gated on ``job.job_type != "orchestrator"`` so the sub-orch's OWN first mission
    fetch (which already wrote "planning" via the staging-end/launch path) never
    re-fires this. Best-effort + forward-only guarded: solo (no active run) and
    non-chain-member projects are a clean no-op via ``find_active_run_for_project``
    returning None; a member that already settled (awaiting_review/completed/failed/
    stalled/terminated) is never demoted back to "implementing" by a late/racing worker.
    """
    if job.job_type == "orchestrator" or not job.project_id:
        return
    # Local import: project_helpers does not import this module, so no cycle risk,
    # but mirrors the local-import idiom the rest of the chain-write call sites use.
    from giljo_mcp.services.project_helpers import mark_chain_member_status

    await mark_chain_member_status(
        db_manager=mission_service.db_manager,
        tenant_manager=mission_service.tenant_manager,
        project_id=str(job.project_id),
        tenant_key=tenant_key,
        status="implementing",
        test_session=mission_service._test_session,
        websocket_manager=mission_service._websocket_manager,
        not_from=_CHAIN_MEMBER_SETTLED_STATUSES,
    )
