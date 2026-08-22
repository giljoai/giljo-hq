# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
Shared helpers for the project service family.

Extracted from project_service.py (Sprint 002e) to eliminate cross-import
coupling where project_lifecycle_service and project_launch_service
imported ``_build_ws_project_data`` directly from project_service.
"""

import logging
from datetime import UTC, datetime
from typing import Any

from giljo_mcp.models.sequence_runs import CHAIN_TERMINAL_PROJECT_STATUSES
from giljo_mcp.utils.log_sanitizer import sanitize


logger = logging.getLogger(__name__)


def compute_completion_percent(completed: int, total: int, decommissioned: int = 0) -> float:
    """Project completion percentage — the ONE shared computation (BE-9000k).

    The denominator EXCLUDES decommissioned agents: a decommissioned agent is
    retired, not outstanding work, so a project whose remaining agents all
    finished can still reach 100%. Previously ``workflow_status_service``
    excluded them while ``project_summary_service`` divided by the full total
    (incl. decommissioned) and could never reach 100% once any agent was
    retired. Both now route through here.

    Returns 0.0 when there is no actionable work (avoids ZeroDivision).
    """
    actionable = total - decommissioned
    if actionable <= 0:
        return 0.0
    return completed / actionable * 100.0


def _build_ws_project_data(project) -> dict:
    """Build standardized project data dict for WebSocket broadcasts.

    Single source of truth for project data sent to frontend via
    WebSocket ``broadcast_project_update`` events. All project broadcast
    sites should use this helper to ensure a consistent field structure.

    Args:
        project: Project model instance (SQLAlchemy).

    Returns:
        Dict with the fields extracted by
        ``WebSocketManager.broadcast_project_update``.
    """
    return {
        "name": project.name,
        "description": project.description,
        "status": project.status,
        "mission": project.mission,
    }


async def mark_staging_complete(
    session,
    project,
    *,
    source: str,
    websocket_manager: Any | None = None,
    agent_count: int | None = None,
) -> bool:
    """Flip ``project.staging_status`` to ``'staging_complete'`` and emit WS event.

    Idempotent — single canonical implementation of the staging→implementation
    flag transition. Three call sites converge here:

    - ``mission_service.update_job_mission`` (auto-flip when orchestrator
      persists a mission and sub-agents have been spawned).
    - ``job_completion_service.complete_job`` (orchestrator explicitly closes
      its staging session via ``complete_job``).
    - Historically ``message_routing_service`` (the broadcast magic — removed
      in this change).

    Args:
        session: Active SQLAlchemy AsyncSession. Caller is responsible for
            committing after this returns (we ``flush`` only, not ``commit``,
            so callers can batch the flip with their own writes).
        project: Project model instance (already loaded in ``session``).
        source: Free-text identifier of the caller (logged on flip and on
            idempotent no-op). Examples: ``"mission_service"``,
            ``"complete_job:staging_end"``.
        websocket_manager: Optional WebSocket manager. When provided AND the
            flag actually flipped, emits a ``project:staging_complete`` event
            to the tenant.
        agent_count: Optional sub-agent count to include in the WS payload
            (purely informational; the UI doesn't depend on it).

    Returns:
        True if the flag was flipped by this call. False if the project was
        already in ``staging_complete`` (idempotent no-op).
    """
    if project.staging_status == "staging_complete":
        logger.debug(
            "[STAGING_COMPLETE:%s] project=%s already complete — no-op",
            source,
            project.id,
        )
        return False

    project.staging_status = "staging_complete"
    project.updated_at = datetime.now(UTC)
    await session.flush()

    logger.info(
        "[STAGING_COMPLETE:%s] project=%s flag flipped",
        source,
        project.id,
    )

    if websocket_manager is not None:
        payload = {
            "project_id": str(project.id),
            "staging_status": "staging_complete",
        }
        if agent_count is not None:
            payload["agent_count"] = agent_count
        try:
            await websocket_manager.broadcast_to_tenant(
                tenant_key=project.tenant_key,
                event_type="project:staging_complete",
                data=payload,
            )
        except Exception as ws_error:  # noqa: BLE001 - WS resilience
            logger.warning(
                "[STAGING_COMPLETE:%s] WS broadcast failed: %s",
                source,
                ws_error,
            )

    return True


async def _wake_conductor_on_member_closeout(
    *,
    db_manager: Any,
    tenant_manager: Any,
    conductor_agent_id: str,
    tenant_key: str,
    project_id: str,
    test_session: Any | None = None,
    websocket_manager: Any | None = None,
) -> bool:
    """Best-effort: event-wake a chain conductor when one of its members closes out (BE-6211e).

    Strictly ADDITIVE to the conductor's ``wake_in_minutes`` poll on
    ``project_closeout_at`` (the crash-resume fallback, kept unchanged). When a chain
    member reaches ``"completed"`` we REUSE
    ``OrchestrationAgentStateService.reactivate_job`` — the existing
    blocked→working / completed→active transition — so a conductor sitting in a
    reactivatable (blocked) state resumes on the event instead of only on its next
    ~1-min poll tick. The run records the conductor by ``conductor_agent_id``;
    ``reactivate_job`` keys on ``job_id``, so we resolve the conductor's execution first.

    BEST-EFFORT / NON-FATAL: this NEVER fails the already-committed closeout. A conductor
    that is sleeping (not blocked), absent, or whose job is already terminal is a swallowed
    no-op — the poll fallback still drives the chain forward. Tenant-scoped throughout
    (the run is a tenant-scoped account concern). No new mechanism: same reactivate path,
    fired from one more (best-effort) site.

    Returns True iff ``reactivate_job`` transitioned the conductor; False on any no-op /
    swallowed error.
    """
    # Local imports avoid a module-load cycle (these import agent/project models).
    from giljo_mcp.repositories.agent_job_repository import AgentJobRepository
    from giljo_mcp.services.orchestration_agent_state_service import OrchestrationAgentStateService

    try:
        # The run stores the conductor's agent_id; reactivate_job needs its job_id.
        repo = AgentJobRepository(db_manager)
        if test_session is not None:
            execution = await repo.get_execution_by_agent_id(test_session, tenant_key, conductor_agent_id)
        else:
            async with db_manager.get_session_async(tenant_key=tenant_key) as session:
                execution = await repo.get_execution_by_agent_id(session, tenant_key, conductor_agent_id)
        if execution is None or not execution.job_id:
            return False

        state_svc = OrchestrationAgentStateService(
            db_manager=db_manager,
            tenant_manager=tenant_manager,
            test_session=test_session,
            websocket_manager=websocket_manager,
        )
        await state_svc.reactivate_job(
            job_id=str(execution.job_id),
            tenant_key=tenant_key,
            reason=f"Chain member {project_id} closed out — conductor event-wake (BE-6211e)",
        )
        logger.info(
            "[CHAIN_CONDUCTOR_WAKE] conductor=%s event-woken on member=%s closeout (tenant=%s)",
            conductor_agent_id,
            sanitize(project_id),
            tenant_key,
        )
        return True
    except Exception as exc:  # noqa: BLE001 — best-effort side-effect; never fail the caller
        # Common (sleeping conductor) path raises ResourceNotFoundError (job not in
        # 'blocked' status) -> swallow at INFO, not WARNING: it is the expected no-op,
        # not a fault. The poll fallback advances.
        logger.info(
            "[CHAIN_CONDUCTOR_WAKE] non-fatal no-op: conductor=%s not event-woken on member=%s (%s): %s",
            conductor_agent_id,
            sanitize(project_id),
            type(exc).__name__,
            exc,
        )
        return False


async def mark_chain_member_status(
    *,
    db_manager: Any,
    tenant_manager: Any,
    project_id: str,
    tenant_key: str,
    status: str,
    test_session: Any | None = None,
    websocket_manager: Any | None = None,
    not_from: frozenset[str] | None = None,
) -> bool:
    """Best-effort: set a chain member's per-project status in its active run (BE-6181).

    Single source of truth for the "a chain member reached a terminal state updates
    project_statuses" side-effect. Used by the closeout writers with
    ``status="completed"`` — the terminal signal the C1 conductor guard
    (``_guard_conductor_chain_incomplete``) keys on, which NOTHING wrote before
    BE-6181 (so a conductor could never finish its chain).

    (The launch-time advance in ``ProjectStagingService.launch_implementation``
    writes ``project_statuses[pid]="planning"`` via ``advance_chain_member_to_implementing``
    rather than via this helper, because it must also bump ``current_index`` atomically
    in the same ``SequenceRunService.update`` call.)

    Solo path (project is not a member of any active sequence run) is a clean no-op:
    ``find_active_run_for_project`` returns None ⇒ this returns False with no write,
    so solo execution stays byte-identical.

    ``not_from`` (FE-9493): an optional forward-only guard — when the member's CURRENT
    status is a member of this set, the write is skipped (returns False, no exception,
    no write) instead of overwriting it. Every existing caller passes ``status="completed"``
    with no ``not_from`` (default None preserves their exact behavior — completed is
    already the terminal write, nothing to guard against). The one caller that DOES pass
    it is ``mission_service.get_agent_mission``'s planning->implementing promotion, so a
    late/racing worker mission-fetch can never demote a member that already reached
    ``awaiting_review`` / ``completed`` (or any other terminal state) back to
    ``implementing``.

    BEST-EFFORT: this is a side-effect that must NEVER fail the primary operation
    (launch / closeout already committed). Any error is logged and swallowed; the
    caller's transaction is untouched. Tenant-scoped throughout (Teams-readiness:
    the run is a tenant-scoped account concern). All writes route through the owning
    SequenceRunService (no ad-hoc setattr).

    ``websocket_manager`` (BE-6198 live-update): when supplied, it is threaded into
    the ``SequenceRunService`` so the ``update()`` below fires the ``sequence:updated``
    WS event and the per-member chain badge live-fills. Production callers each HOLD
    the manager and pass it down; None preserves the solo no-op (no broadcast).

    Returns:
        True if a run was found and ``project_statuses[project_id]`` was set to
        ``status``; False otherwise (solo, guarded by ``not_from``, or a swallowed error).
    """
    # Local import avoids a module-load cycle (SequenceRunService imports project models).
    from giljo_mcp.services.sequence_run_service import SequenceRunService

    try:
        svc = SequenceRunService(
            db_manager=db_manager,
            tenant_manager=tenant_manager,
            session=test_session,
            websocket_manager=websocket_manager,
        )
        run = await svc.find_active_run_for_project(project_id=project_id, tenant_key=tenant_key)
        if run is None:
            return False

        merged_statuses = dict(run.get("project_statuses") or {})
        current = merged_statuses.get(project_id)
        if current == status:
            return True  # idempotent no-op — already at target status
        if not_from is not None and current in not_from:
            logger.info(
                "[CHAIN_MEMBER_STATUS] forward-only guard blocked run=%s project=%s current=%s target=%s (tenant=%s)",
                run["id"],
                sanitize(project_id),
                current,
                status,
                tenant_key,
            )
            return False

        merged_statuses[project_id] = status
        await svc.update(
            run_id=run["id"],
            tenant_key=tenant_key,
            project_statuses=merged_statuses,
        )
        logger.info(
            "[CHAIN_MEMBER_STATUS] run=%s project=%s -> %s (tenant=%s)",
            run["id"],
            sanitize(project_id),
            status,
            tenant_key,
        )

        # BE-6211e: event-wake the conductor on a member CLOSEOUT — strictly additive to
        # its wake_in_minutes poll on project_closeout_at (the crash-resume fallback, kept
        # unchanged). Fired AFTER the completed write so the run already reflects it, keyed
        # on the run's conductor_agent_id, best-effort + non-fatal: a sleeping/absent
        # conductor is a swallowed no-op (the poll still advances the chain). Gated on the
        # terminal "completed" status so an in-flight status update (e.g. "implementing")
        # never fires it.
        conductor_agent_id = run.get("conductor_agent_id")
        if status == "completed" and conductor_agent_id:
            await _wake_conductor_on_member_closeout(
                db_manager=db_manager,
                tenant_manager=tenant_manager,
                conductor_agent_id=conductor_agent_id,
                tenant_key=tenant_key,
                project_id=project_id,
                test_session=test_session,
                websocket_manager=websocket_manager,
            )
        return True
    except Exception as exc:  # noqa: BLE001 — best-effort side-effect; never fail the caller
        logger.warning(
            "[CHAIN_MEMBER_STATUS] non-fatal: failed to set project=%s status=%s: %s",
            sanitize(project_id),
            status,
            exc,
        )
        return False


async def advance_chain_member_to_implementing(
    *,
    db_manager: Any,
    tenant_manager: Any,
    project_id: str,
    tenant_key: str,
    session: Any | None = None,
    websocket_manager: Any | None = None,
) -> bool:
    """Advance the active run when a chain member ENTERS implementation (§14 gateless flow).

    Single source of truth for the "a chain member crossed staging→implementation
    advances its run" bookkeeping. Sets ``project_statuses[project_id] = "planning"``
    (FE-9493: this project's sub-orchestrator has started working it — no worker agent
    spawned yet; the conductor's "running" signal) and bumps ``current_index``
    FORWARD-ONLY to the project's index — gated on the project being LEFT BEHIND having
    closed out (``advance_index_if_committed``), so the tail is never batch-unlocked.
    A member is promoted from ``"planning"`` to ``"implementing"`` separately, when its
    first spawned worker actually starts (``mission_service.get_agent_mission``'s
    atomic-start promotion, guarded forward-only via ``mark_chain_member_status``).

    TSK-9091: also writes ``sequence_runs.status = "running"`` on every call. This is
    the semantically-true "the chain is actually driving" transition — it fires the
    first time ANY member (head or downstream) enters implementation, flipping the
    run off its ``"pending"`` create-time default. The write is unconditional (not
    just on the head project) so it is also the resume signal when a ``"stalled"``
    run's member finally advances. Idempotent once already "running". Safe because
    ``run`` was resolved via ``find_active_run_for_project``, which filters to
    active statuses (pending/running/stalled) only — this can never overwrite a
    terminal status (completed/failed/terminated/cancelled).

    Two call sites converge here:
      - ``ProjectStagingService._advance_chain_on_launch`` — the human/REST/manual
        Implement gate (solo Implement is a clean no-op: no active run).
      - ``JobCompletionService._handle_staging_end`` — the §14 gateless chain flow: with
        the per-project launch gate removed (CHAIN_ARCHITECTURE.md §9/§14), the sub-orch's
        OWN staging-end is the advance signal the conductor's ``launch_implementation``
        used to provide.

    Solo (no active run) → no-op (returns False). BEST-EFFORT: a failure NEVER propagates
    to the already-committed launch / staging-end. Tenant-scoped; every run write routes
    through the owning ``SequenceRunService``.

    ``session`` is the caller's test/None session, threaded to BOTH ``SequenceRunService``
    and ``SequenceChainContextResolver`` (the injected test session in tests for isolation;
    None in production → a fresh session, so the advance commits independently of the
    caller's in-flight transaction — matching the prior launch-path behaviour).

    ``websocket_manager`` (live-update): threaded down so the run write fires
    ``sequence:updated`` and the chain badge moves live; None preserves the solo no-op.

    Returns True iff a run was found AND the index/status write applied (False on solo or
    a swallowed error; for a status-only update with the index held by the closeout gate,
    returns the gate's verdict).
    """
    # Local imports avoid a module-load cycle (these services import project models).
    from giljo_mcp.services.sequence_chain_context import SequenceChainContextResolver
    from giljo_mcp.services.sequence_run_service import SequenceRunService

    try:
        svc = SequenceRunService(
            db_manager=db_manager,
            tenant_manager=tenant_manager,
            session=session,
            websocket_manager=websocket_manager,
        )
        run = await svc.find_active_run_for_project(project_id=project_id, tenant_key=tenant_key)
        if run is None:
            return False  # solo — no-op

        resolved_order = run.get("resolved_order") or []
        if project_id not in resolved_order:
            return False
        idx = resolved_order.index(project_id)
        forward_index = max(run.get("current_index", 0), idx)

        merged_statuses = dict(run.get("project_statuses") or {})
        # FE-9493: "planning" is the in-flight per-project status in VALID_PROJECT_STATUSES
        # for "sub-orchestrator entered, no worker yet" — distinct from "implementing"
        # ("first spawned worker started"), so the FE tab strip can show them differently.
        merged_statuses[project_id] = "planning"

        resolver = SequenceChainContextResolver(
            db_manager=db_manager,
            tenant_manager=tenant_manager,
            websocket_manager=websocket_manager,
            test_session=session,
        )

        if forward_index > 0:
            prev_pid = resolved_order[forward_index - 1] if forward_index - 1 < len(resolved_order) else None
            if prev_pid:
                # current_index only advances when the project being LEFT BEHIND has
                # closed out (the commit-SHA gate). The status update applies regardless.
                advanced = await resolver.advance_index_if_committed(
                    run_id=run["id"],
                    project_id=prev_pid,
                    tenant_key=tenant_key,
                    next_index=forward_index,
                )
                await svc.update(
                    run_id=run["id"],
                    tenant_key=tenant_key,
                    status="running",
                    project_statuses=merged_statuses,
                )
                if not advanced:
                    logger.info(
                        "[CHAIN_ADVANCE] index hold: prev project %s not closed out yet (run=%s)",
                        prev_pid,
                        run["id"],
                    )
                return advanced
            await svc.update(
                run_id=run["id"],
                tenant_key=tenant_key,
                status="running",
                current_index=forward_index,
                project_statuses=merged_statuses,
            )
            return True
        # Head project (no prior to leave behind) — advance freely.
        await svc.update(
            run_id=run["id"],
            tenant_key=tenant_key,
            status="running",
            current_index=forward_index,
            project_statuses=merged_statuses,
        )
        return True
    except Exception as exc:  # noqa: BLE001 — best-effort side-effect; never fail the caller
        logger.warning(
            "[CHAIN_ADVANCE] non-fatal: failed to advance project=%s to implementing: %s",
            sanitize(project_id),
            exc,
        )
        return False


async def heal_chain_member_statuses(
    *,
    session: Any,
    sequence_run_service: Any,
    run: dict[str, Any],
    tenant_key: str,
) -> dict[str, str]:
    """Self-heal a run's ``project_statuses`` copy from the REAL project rows (BE-9055).

    Whether a chain conductor may finish is decided from the denormalized
    ``project_statuses`` JSON — but every write to that copy is best-effort
    (errors swallowed, three writer sites), so one swallowed write used to mean
    a chain that could NEVER complete. This applies the BE-6200 read-boundary
    rule at the completion guards: when the copy says a member is NOT terminal,
    re-check the member's actual ``projects`` row and repair the copy.

    A member is really finished when its project row is soft-deleted
    (``deleted_at`` set) or its status is lifecycle-finished (completed /
    cancelled / terminated / deleted) — the BE-6200 read-boundary rule. The
    healed value maps onto the copy validator's terminal tokens: ``completed``
    and ``terminated`` map 1:1; ``cancelled`` / ``deleted`` / soft-deleted map
    to ``terminated`` (the validator's token set has no ``cancelled``).

    A member whose project ROW IS MISSING is deliberately NOT healed: unlike
    the display-side BE-6200 filter, this feeds a COMPLETION decision, and
    treating an unreadable row as terminal would let a read glitch complete a
    chain early. A missing row keeps the copy's value (chain stays blocked;
    the dashboard back-out controls remain the recovery).

    Repairs are persisted through the owning ``SequenceRunService.update`` —
    best-effort: a failed persist is logged and the HEALED in-memory dict is
    still returned, so the completion decision is correct even if the write
    fails again. A run with no stale members returns the copy untouched with
    NO project query (fast path). Tenant-scoped throughout.
    """
    from sqlalchemy import select

    from giljo_mcp.database import tenant_session_context
    from giljo_mcp.models.projects import Project

    statuses: dict[str, str] = dict(run.get("project_statuses") or {})
    member_ids = [str(pid) for pid in (run.get("resolved_order") or []) if pid]
    stale = [pid for pid in member_ids if statuses.get(pid) not in CHAIN_TERMINAL_PROJECT_STATUSES]
    if not stale:
        return statuses

    with tenant_session_context(session, tenant_key):
        rows = await session.execute(
            select(Project.id, Project.status, Project.deleted_at).where(
                Project.tenant_key == tenant_key,
                Project.id.in_(stale),
            )
        )
    found = {str(pid): (status, deleted_at) for pid, status, deleted_at in rows.all()}

    healed: dict[str, str] = {}
    for pid in stale:
        row = found.get(pid)
        if row is None:
            # Missing row: not healed (see docstring) — the guard keeps blocking.
            continue
        real_status, deleted_at = row
        if deleted_at is not None or real_status in ("deleted", "cancelled"):
            healed[pid] = "terminated"
        elif real_status in ("completed", "terminated"):
            healed[pid] = real_status
        # A genuinely unfinished member keeps the copy's value (no entry in healed).

    if not healed:
        return statuses

    statuses.update(healed)
    logger.info(
        "[CHAIN_SELF_HEAL] run=%s repaired stale member statuses from project rows: %s (tenant=%s)",
        run.get("id"),
        healed,
        tenant_key,
    )
    try:
        await sequence_run_service.update(
            run_id=run["id"],
            tenant_key=tenant_key,
            project_statuses=statuses,
        )
    except Exception as exc:  # noqa: BLE001 — the healed in-memory copy still drives the decision
        logger.warning(
            "[CHAIN_SELF_HEAL] non-fatal: failed to persist healed statuses for run=%s: %s",
            run.get("id"),
            exc,
        )
    return statuses


async def complete_chain_run_if_finished(
    *,
    db_manager: Any,
    tenant_manager: Any,
    conductor_agent_id: str,
    tenant_key: str,
    test_session: Any | None = None,
    websocket_manager: Any | None = None,
) -> bool:
    """Best-effort: PURGE a conductor's run when every project is terminal (Option A).

    Called from the conductor's complete_job success path (BE-6189): once the C1 guard
    has let the conductor's FINAL complete_job through (all projects terminal), this
    DELETES the run's ``sequence_runs`` row (plus the conductor's own project-less
    agent rows) rather than leaving a dead ``completed`` row forever. The project row
    is the durable record; the chain GROUPING is ephemeral. BE-6181 wired each
    sub-orch closeout to mark its project "completed"; BE-6177 (C1) lets the conductor
    self-complete once all projects are terminal; this unit tears the finished run down.

    Resolves the conductor's active run via find_active_run_for_conductor. If ALL
    projects in resolved_order are terminal (CHAIN_TERMINAL_PROJECT_STATUSES —
    the shared wide set, BE-9000k), purges the run
    via SequenceRunService.purge_run (the owning service — the only deleter). Solo /
    sub_orchestrator / not-all-terminal => no-op (returns False). NEVER fails the
    primary complete_job (logged + swallowed). Tenant-scoped.

    ``websocket_manager`` (BE-6198 live-update): threaded into the SequenceRunService
    so the run-finish ``purge_run()`` fires ``sequence:updated`` and the FE drops the
    run live. None preserves the no-op (no broadcast) for solo / non-conductor.

    Returns:
        True if a run was found and purged; False otherwise (solo, not-all-terminal,
        or a swallowed error).
    """
    # Local import avoids a module-load cycle (SequenceRunService imports project models).
    from giljo_mcp.services.sequence_run_service import SequenceRunService

    try:
        svc = SequenceRunService(
            db_manager=db_manager,
            tenant_manager=tenant_manager,
            session=test_session,
            websocket_manager=websocket_manager,
        )
        run = await svc.find_active_run_for_conductor(conductor_agent_id=conductor_agent_id, tenant_key=tenant_key)
        if run is None:
            return False

        resolved_order = run.get("resolved_order") or []
        statuses = run.get("project_statuses") or {}
        if not resolved_order:
            return False
        if any(statuses.get(pid) not in CHAIN_TERMINAL_PROJECT_STATUSES for pid in resolved_order):
            # BE-9055: the copy says "not finished" — don't trust it. Re-check the
            # members' REAL project rows and repair the copy before refusing.
            if test_session is not None:
                statuses = await heal_chain_member_statuses(
                    session=test_session, sequence_run_service=svc, run=run, tenant_key=tenant_key
                )
            else:
                async with db_manager.get_session_async(tenant_key=tenant_key) as heal_session:
                    statuses = await heal_chain_member_statuses(
                        session=heal_session, sequence_run_service=svc, run=run, tenant_key=tenant_key
                    )
            if any(statuses.get(pid) not in CHAIN_TERMINAL_PROJECT_STATUSES for pid in resolved_order):
                return False
        if run.get("status") == "completed":
            return True  # idempotent no-op — already terminal

        # BE-9153: settlement gate. Every project may be terminal, but if a
        # findings-bearing link was accepted PROVISIONALLY under closeout_mode='hitl'
        # its settlement approval gates the CHAIN's own closeout — hold the purge
        # until the user decides every queued settlement approval. The decide path
        # (user_approval_service.mark_decided) re-triggers this check, so the run
        # purges once the LAST settlement approval is resolved. Solo/autonomous runs
        # have no such approvals → no hold.
        from giljo_mcp.services.job_completion_closeout_gate import has_pending_chain_settlement

        if test_session is not None:
            settlement_pending = await has_pending_chain_settlement(test_session, run["id"], tenant_key)
        else:
            async with db_manager.get_session_async(tenant_key=tenant_key) as settle_session:
                settlement_pending = await has_pending_chain_settlement(settle_session, run["id"], tenant_key)
        if settlement_pending:
            logger.info(
                "[CHAIN_RUN_COMPLETE] run=%s held: settlement approval(s) still pending (tenant=%s)",
                run["id"],
                tenant_key,
            )
            return False

        await svc.purge_run(run_id=run["id"], tenant_key=tenant_key)
        logger.info(
            "[CHAIN_RUN_COMPLETE] run=%s purged on completion (conductor=%s, tenant=%s)",
            run["id"],
            conductor_agent_id,
            tenant_key,
        )
        return True
    except Exception as exc:  # noqa: BLE001 — best-effort side-effect; never fail the caller
        logger.warning(
            "[CHAIN_RUN_COMPLETE] non-fatal: failed to purge run for conductor=%s: %s",
            conductor_agent_id,
            exc,
        )
        return False


# CE-0032: spawn_implementation_orchestrator removed. Under the single-
# orchestrator-entity model the same AgentExecution row carries the
# orchestrator across the staging→implementation boundary; there is never a
# second exec to spawn. job_completion_service.complete_job leaves the row at
# status='waiting' at staging-end (see _apply_completion_status), and the
# orch's first get_job_mission call in the impl session flips it back to
# 'working' via existing logic in mission_service.py:174.
