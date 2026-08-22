# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""Staging-end machinery for ``complete_job`` (BE-9060 item 2 split).

Mechanically extracted VERBATIM from ``job_completion_service.py`` — the
staging→implementation transition seam its size-guardrail grandfather note
called "a clean extraction candidate": detection
(:func:`is_staging_end_orchestrator_call` / :func:`is_conductor_staging_end`),
the flag-flip + directive shaping (:func:`handle_staging_end` /
:func:`staging_directive_for`), the chain-conductor completion guard
(:func:`guard_conductor_chain_incomplete`, BE-6177 C1), and the staging-end
directive prose constants. Behavior unchanged; ``JobCompletionService`` keeps
thin delegating methods so its call sites and the existing test seams are
untouched.

Edition Scope: Both.
"""

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


# BE-6198 (Fix #2): chain SUB-ORCHESTRATOR staging-end wording. Its implementation
# gate is opened by the conductor in software (not a human click), so it must poll
# get_job_mission rather than wait for "Implement". Mirrors BE-6196's voice. Used by
# both the staging-end next_action (S2) and the StagingDirective message override (S1).
# The project-less conductor and solo projects never receive this — they keep the
# original "human presses Implement" wording.
_CHAIN_SUBORCH_STAGING_END_NEXT_ACTION = (
    "Staging is complete. Your CHAIN ORCHESTRATOR opens your implementation gate "
    "automatically -- do NOT wait for a human and do NOT return to the dashboard. "
    "Call get_job_mission ONCE now: your gate is already OPEN, so this first call "
    "normally returns your implementation protocol -- continue straight into it. "
    "ONLY if that first call does NOT yet return the implementation protocol, sleep "
    "~30s and retry, repeating until it does. Do NOT write the project closeout from "
    "the staging session."
)

# BE-6220: the schema-default StagingDirective carries action="STOP" /
# next_step="Report staging complete to user and stop." -- correct for a solo
# project (a human clicks Implement) but a direct CONTRADICTION of the chain
# message above for a chain sub-orchestrator. A literal-following sub-orch that
# obeyed action=STOP would strand the chain (the conductor waits forever). So a
# chain sub-orch overrides action + next_step too, not just message, so all three
# agree on CONTINUE. Solo + the project-less conductor keep the byte-identical
# schema defaults (SOLO IS SACRED).
_CHAIN_SUBORCH_STAGING_END_ACTION = "CONTINUE"
_CHAIN_SUBORCH_STAGING_END_NEXT_STEP = (
    "Call get_job_mission once now to continue into implementation -- your gate is "
    "already OPEN. Do NOT report to the user and do NOT stop."
)

# BE-6221e: the project-less chain CONDUCTOR's staging-end directive. Unlike the
# sub-orchestrator above (which CONTINUEs straight into implementation because the
# conductor's spawn already released it), the headless conductor must HALT after
# staging and wait for the user's EXPLICIT GO before driving -- the human-in-the-loop
# gate. Today get_job_mission hands the conductor CH_CHAIN_DRIVE ("AUTO-CONTINUE")
# ungated, so an obedient agent reasonably drives on; this directive (+ the firmed
# CH_CHAIN_STAGING / CH_CHAIN_DRIVE prose) tells it to stop and wait. So the conductor
# KEEPS action="STOP" (it does NOT continue) but firms the wording from the solo
# "a human presses Implement" to "report the staged plan and wait for the user's GO".
# Solo keeps the BYTE-IDENTICAL schema default; the sub-orch keeps its CONTINUE
# override -- ONLY the conductor (project_id is None AND chain_conductor) gets this.
_CONDUCTOR_STAGING_END_ACTION = "STOP"
_CONDUCTOR_STAGING_END_NEXT_ACTION = (
    "Report the staged chain plan and the chain mission to the user, then STOP. Do NOT "
    "self-launch, do NOT spawn a sub-orchestrator, and do NOT re-call get_job_mission "
    "to start driving. Proceed only after the user's EXPLICIT GO (they say go / "
    "implement this chain, or press 'Implement Chain' in the dashboard)."
)
_CONDUCTOR_STAGING_END_NEXT_STEP = (
    "Report the staged chain plan to the user and STOP. Do NOT self-launch and do NOT "
    "re-call get_job_mission to drive. Proceed only after the user's explicit GO (they "
    "say go / press 'Implement Chain')."
)

# BE-6186: per-project statuses that mean implementation has begun for a chain
# member. If ANY run member is in one of these, the run has left the staging
# phase, so a conductor complete_job is NOT a staging-end (it is the final
# impl-phase self-complete or a premature mid-drive call the C1 guard handles).
# FE-9493: "planning" (sub-orchestrator entered, no worker yet) is the same event
# this set always meant to catch here — advance_chain_member_to_implementing used
# to write "implementing" for it and now writes "planning" instead, with
# "implementing" reserved for the member's first spawned worker starting. Both
# values must stay in this set or a member that entered planning but has not yet
# spawned a worker would misread as "still staging" here.
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
    """Refuse a chain conductor's complete_job while its run is in flight (BE-6177 C1).

    Only an orchestrator job can be a conductor. Look up the active sequence_run
    this execution's agent is the registered conductor of; if one exists with
    projects still incomplete, reject with an agent-actionable
    CONDUCTOR_CHAIN_INCOMPLETE message (advance the chain by launching the next
    project; do not self-complete). No active conductor run → no-op (solo / sub_orchestrator /
    already-finished run all pass through unchanged, byte-identical).

    Caller guarantees this runs only in the implementation phase (not at
    staging-end, where the conductor's complete_job is the required signal).
    """
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
        # BE-9055: the denormalized copy says "not finished" — every write to it
        # is best-effort (errors swallowed), so re-check the members' REAL
        # project rows and repair the copy before refusing completion. One
        # swallowed status write must not strand a successful chain forever.
        statuses = await heal_chain_member_statuses(
            session=session, sequence_run_service=svc, run=run, tenant_key=tenant_key
        )
        remaining = [pid for pid in resolved_order if statuses.get(pid) not in CHAIN_TERMINAL_PROJECT_STATUSES]
    if not remaining:
        return  # all projects finished — the conductor may legitimately self-complete.

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
    """Tear down a finished chain run + detect the project-less conductor (BE-6189/BE-6199).

    Extracted from ``JobCompletionService.complete_job`` (BE-9153, shrink-only budget).
    Behavior-preserving.

    BE-6189: the conductor's FINAL complete_job (all projects terminal, C1 guard
    already passed) tears down the finished run — the chain's finish line.
    Best-effort; no-op for solo / sub-orch / staging-end / not-all-terminal.

    BE-6199 (#4) / BE-6221e: the project-less chain conductor (project_id None AND
    chain_conductor) needs chain-aware complete_job responses — HALT for the user's GO
    at staging-end, chain next_action at its finale. Returned so ``handle_staging_end``
    (the directive) and ``_phase_response`` (the next_action) agree. Solo / project-bound
    orchestrators return False → byte-identical.
    """
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


async def is_staging_end_orchestrator_call(
    session: AsyncSession,
    job: AgentJob,
    execution: AgentExecution,
    tenant_key: str,
    *,
    db_manager: Any,
    tenant_manager: Any,
) -> tuple[bool, Project | None]:
    """Detect whether this complete_job is the staging→implementation
    transition for an orchestrator. Single source of truth for CE-0026
    (STOP directive) and CE-0028 (preserve job.status='active').

    Returns ``(is_staging_end, project)``. When ``is_staging_end`` is True,
    callers must:
      * preserve ``job.status='active'`` (do NOT flip to 'completed'); and
      * emit a STOP ``staging_directive`` in the response.

    The Project (possibly None) is returned so callers can reuse it
    without a second lookup. A None project on a staging-end call is
    anomalous — ``handle_staging_end`` logs a warning but still returns
    the directive.
    """
    if job.job_type != "orchestrator":
        return False, None

    # BE-6186: the dedicated chain CONDUCTOR is a PROJECT-LESS orchestrator
    # (job.project_id IS NULL, project_phase="implementation") that stages the
    # whole chain then ends staging with complete_job and ZERO agents of its own.
    # It cannot be detected by the project-bound rules below (no project, wrong
    # phase). Detect its STAGING-end here: it is the conductor of an active run
    # that has NOT yet entered implementation (no project launched). Returning
    # (True, None) routes it through handle_staging_end's project-None branch,
    # which returns the STOP directive and SKIPS the no-agents gate — the
    # conductor never spawns its own agents. Its FINAL impl-phase self-complete
    # (all projects done) does NOT match this (a launched project flips the
    # pre-implementation predicate), so it falls through to the normal closeout
    # and the C1 guard, which by then passes. Solo / project-bound orchestrators
    # never reach this branch (they own a project) → byte-identical.
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
    # CE-0026 safeguard: if implementation has already been launched, this
    # complete_job is NOT a staging-end signal — it's the staging-phase
    # execution catching up (orch stayed alive across the
    # staging→implementation transition without complete_job being called
    # at the right boundary). Treat as a normal closeout; no STOP directive.
    #
    # BE-6182 (belt-and-suspenders): only treat this as an implementation
    # CLOSEOUT when BOTH implementation_launched_at is stamped AND
    # staging_status == "staging_complete". A legitimate staging-end always has
    # implementation_launched_at None (so it still falls through to staging-end),
    # and the only state this newly re-routes is the ANOMALOUS "stamped but not
    # staging_complete" — which is a staging-end being mis-classified as a
    # closeout, not the reverse. BE-6181's launch_implementation guard is the
    # primary fix; this backstops the inverse misread.
    if (
        project is not None
        and project.implementation_launched_at is not None
        and project.staging_status == "staging_complete"
    ):
        return False, project

    # BE-9165 (wall 2): a staging finale where every spawned specialist has
    # ALREADY recorded its deliverables is the project's real completion, not a
    # pause before implementation. Classifying it as a staging-end re-parked the
    # orchestrator at 'waiting' (CE-0032), which write_project_closeout then
    # blocked on forever — the retroactive-staging deadlock. Route it to the
    # normal closeout path instead (orchestrator 'complete', job finalized,
    # closeout checklist returned). A GENUINE staging end has freshly spawned
    # 'waiting' specialists (in flight) and a zero-spawn finale keeps the
    # STAGING_END_NO_AGENTS gate — both classify exactly as before.
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
    """True iff this project's staging finale has nothing left to implement (BE-9165).

    Requires at least one spawned specialist AND none in flight (statuses all in
    :data:`~giljo_mcp.models.agent_identity.TERMINAL_EXECUTION_STATUSES`).
    Chain members are EXCLUDED: their implementation gate opens in software (§14),
    so they never hit the retroactive-staging deadlock, and rerouting them would
    skip the §14 chain-advance bookkeeping — a chain lookup failure therefore
    counts as "chain member" (no reroute), the conservative side.
    """
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
    """True iff this project-less orchestrator is a chain conductor ending STAGING.

    The dedicated conductor's complete_job is a staging-end only when it is the
    live conductor of an active run that has NOT yet entered implementation: no
    member project has been launched (``current_index == 0`` AND no member status
    is in ``_RUN_IMPL_STARTED_STATUSES``). That is the staging→Implement boundary
    where the conductor stops with zero agents of its own.

    Returns False (so the caller treats the call as a normal closeout) when this
    agent is not a conductor of any active run, OR the run has already entered
    implementation — the FINAL self-complete and any premature mid-drive call,
    both correctly left to the C1 conductor-chain-incomplete guard. Tenant-scoped;
    the read routes through SequenceRunService (the owning service).
    """
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
    # Staging-end iff NO member has entered implementation.
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
    """Flip the staging flag and return the STOP directive (CE-0026).

    Detection is performed once by ``is_staging_end_orchestrator_call``
    and the result is passed in. This function only mutates and shapes the
    response. Calls the canonical ``mark_staging_complete`` helper
    (idempotent — ``mission_service`` may already have flipped the flag
    earlier in this session).

    Returns:
        StagingDirective when ``is_staging_end`` is True; otherwise None.
    """
    if not is_staging_end:
        return None

    if project is None:
        # BE-6221e: the project-less chain CONDUCTOR legitimately reaches this
        # branch at staging-end (it owns no project). is_conductor distinguishes
        # it from a genuine "project not found" anomaly: the conductor gets the
        # firm await-GO directive; the anomaly keeps the schema default (so its
        # response stays byte-identical).
        if not is_conductor:
            logger.warning(
                "[STAGING_END] Project %s not found for staging orchestrator job %s — "
                "skipping flag flip but still returning STOP directive",
                job.project_id,
                job.job_id,
            )
        return staging_directive_for(is_chain_member_suborch, is_conductor=is_conductor)

    # BE-5114: a zero-spawn staging end produces a broken downstream state
    # (Implement-click 400 "No agent jobs spawned yet"). Reject it BEFORE
    # flipping the flag so staging stays re-stageable. Reuses the canonical
    # count helper (no parallel query).
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

    # §14 (CHAIN_ARCHITECTURE.md) — gateless chain advance. The per-project launch
    # gate is gone: a released chain sub-orchestrator runs free and its OWN staging-end
    # IS the staging→implementation transition (previously the conductor's
    # launch_implementation stamped this + ran the advance). For a chain member ONLY:
    #   1. stamp implementation_launched_at HERE — STRICTLY AFTER the staging-end
    #      classification (is_staging_end_orchestrator_call) and the deliverable-TODO
    #      bypass (_validate_completion_requirements) have ALREADY read it as NULL in
    #      THIS call, so neither misclassifies; the NEXT complete_job (the impl-phase
    #      closeout) then reads it as SET + staging_complete and is correctly routed to
    #      closeout, never re-detected as staging-end. Stamping it inside
    #      mark_staging_complete would be wrong (that helper fires from 2+ sites and
    #      would corrupt the detector); it must live here, post-classification.
    #   2. run the chain-advance bookkeeping the launch path used to (status
    #      "implementing" + forward current_index), so the conductor's running-vs-done
    #      detection and crash-resume index stay accurate without a launch call.
    # is_chain_member_suborch is already gated on (is_staging_end AND project_id not
    # None AND active-run member), so the project-less conductor and every SOLO project
    # skip this entirely → solo staging-end stays byte-identical (impl_launched_at NULL,
    # waits for the human Implement press).
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
        # BE-9111: the retired conductor launch path used to broadcast
        # project:implementation_launched (source="mcp"); this §14 direct-stamp path
        # replaced it but emitted nothing, so live-follow never carried a viewer to the
        # jobs pane when a chain member entered implementation. Restore the event here
        # with launch_implementation's payload shape (project_staging_service.py:532-549).
        # Resilient like mark_staging_complete: a WS failure must NEVER fail the
        # staging-end write (the stamp + advance already committed).
        if websocket_manager is not None:
            try:
                await websocket_manager.broadcast_to_tenant(
                    tenant_key=project.tenant_key,
                    event_type="project:implementation_launched",
                    data={
                        "project_id": str(job.project_id),
                        "implementation_launched_at": launched_at.isoformat(),
                        "source": "mcp",
                    },
                )
            except Exception as ws_error:  # noqa: BLE001 — WS resilience
                logger.warning(
                    "[STAGING_END:BE-9111] implementation_launched WS broadcast failed: %s",
                    ws_error,
                )

    # CE-0032: no pre-spawn. Under the single-orchestrator-entity model
    # the same AgentExecution row carries the orchestrator across the
    # staging→implementation boundary; _apply_completion_status (called
    # earlier in this complete_job) left it at status='waiting'. The
    # Implement-click endpoint sets project.implementation_launched_at and
    # broadcasts; the user pastes the impl prompt; the orch's first
    # get_job_mission call flips this row's status back to 'working'.
    # (is_conductor is False on this project-bound path — the conductor is
    # project-less and returns via the project-None branch above.)
    return staging_directive_for(is_chain_member_suborch, is_conductor=is_conductor)


def staging_directive_for(is_chain_member_suborch: bool, is_conductor: bool = False) -> StagingDirective:
    """Build the staging-end directive (BE-6198 Fix #2 / S1, BE-6221e).

    For a chain SUB-ORCHESTRATOR, override the schema-default ``message``,
    ``action`` and ``next_action`` (which all tell the agent a human clicks
    Implement and to STOP) with the poll-the-conductor / CONTINUE wording, so the
    whole directive agrees instead of contradicting itself (BE-6220).

    For the project-less chain CONDUCTOR (BE-6221e), keep ``action='STOP'`` but
    firm the wording from the solo "a human presses Implement" to "report the
    staged plan and wait for the user's EXPLICIT GO" — the headless human-in-the-
    loop gate that stops the conductor blasting past staging into the drive loop.

    The schema defaults themselves are left untouched, so SOLO projects (and a
    genuine project-not-found anomaly) keep the original directive BYTE-IDENTICAL.
    ``is_chain_member_suborch`` and ``is_conductor`` are mutually exclusive (one
    requires a project, the other is project-less).
    """
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
