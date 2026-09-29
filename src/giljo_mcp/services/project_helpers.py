# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import logging
from datetime import UTC, datetime
from typing import Any

from giljo_mcp.models.sequence_runs import CHAIN_TERMINAL_PROJECT_STATUSES
from giljo_mcp.utils.log_sanitizer import sanitize


logger = logging.getLogger(__name__)


def compute_completion_percent(completed: int, total: int, decommissioned: int = 0) -> float:
    actionable = total - decommissioned
    if actionable <= 0:
        return 0.0
    return completed / actionable * 100.0


def _build_ws_project_data(project) -> dict:
    return {
        "name": project.name,
        "description": project.description,
        "status": project.status,
        "mission": project.mission,
        "product_id": project.product_id,
    }


async def mark_staging_complete(
    session,
    project,
    *,
    source: str,
    websocket_manager: Any | None = None,
    agent_count: int | None = None,
) -> bool:
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
            "product_id": project.product_id,
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
    from giljo_mcp.repositories.agent_job_repository import AgentJobRepository
    from giljo_mcp.services.orchestration_agent_state_service import OrchestrationAgentStateService

    try:
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
    from giljo_mcp.services.sequence_run_service import SequenceRunService

    svc = SequenceRunService(
        db_manager=db_manager,
        tenant_manager=tenant_manager,
        session=test_session,
        websocket_manager=websocket_manager,
    )
    run = await svc.find_active_run_for_project(project_id=project_id, tenant_key=tenant_key, for_update=True)
    if run is None:
        return False

    merged_statuses = dict(run.get("project_statuses") or {})
    current = merged_statuses.get(project_id)
    if current == status:
        return True
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
        defer_broadcast=True,
    )
    logger.info(
        "[CHAIN_MEMBER_STATUS] run=%s project=%s -> %s (tenant=%s)",
        run["id"],
        sanitize(project_id),
        status,
        tenant_key,
    )

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


async def advance_chain_member_to_implementing(
    *,
    db_manager: Any,
    tenant_manager: Any,
    project_id: str,
    tenant_key: str,
    session: Any | None = None,
    websocket_manager: Any | None = None,
) -> bool:
    from giljo_mcp.services.sequence_chain_context import SequenceChainContextResolver
    from giljo_mcp.services.sequence_run_service import SequenceRunService

    svc = SequenceRunService(
        db_manager=db_manager,
        tenant_manager=tenant_manager,
        session=session,
        websocket_manager=websocket_manager,
    )
    run = await svc.find_active_run_for_project(project_id=project_id, tenant_key=tenant_key, for_update=True)
    if run is None:
        return False

    resolved_order = run.get("resolved_order") or []
    if project_id not in resolved_order:
        return False
    idx = resolved_order.index(project_id)
    forward_index = max(run.get("current_index", 0), idx)

    merged_statuses = dict(run.get("project_statuses") or {})
    merged_statuses[project_id] = "planning"

    resolver = SequenceChainContextResolver(db_manager=db_manager, tenant_manager=tenant_manager, test_session=session)

    if forward_index > 0:
        prev_pid = resolved_order[forward_index - 1] if forward_index - 1 < len(resolved_order) else None
        if prev_pid:
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
                defer_broadcast=True,
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
            defer_broadcast=True,
        )
        return True
    await svc.update(
        run_id=run["id"],
        tenant_key=tenant_key,
        status="running",
        current_index=forward_index,
        project_statuses=merged_statuses,
        defer_broadcast=True,
    )
    return True


async def heal_chain_member_statuses(
    *,
    session: Any,
    sequence_run_service: Any,
    run: dict[str, Any],
    tenant_key: str,
) -> dict[str, str]:
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
            continue
        real_status, deleted_at = row
        if deleted_at is not None or real_status in ("deleted", "cancelled"):
            healed[pid] = "terminated"
        elif real_status in ("completed", "terminated"):
            healed[pid] = real_status

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
            return True

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

        if run.get("review_policy") == "per_card":
            reviewed = set(run.get("reviewed_project_ids") or [])
            for pid in resolved_order:
                if pid not in reviewed:
                    run = await svc.mark_member_reviewed(
                        run_id=run["id"], project_id=pid, tenant_key=tenant_key, via="harness"
                    )

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


