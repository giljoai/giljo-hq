# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from sqlalchemy import select

from giljo_mcp.exceptions import ValidationError
from giljo_mcp.models.projects import Project
from giljo_mcp.models.user_approval import UserApproval
from giljo_mcp.schemas.service_responses import build_next_action


if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from giljo_mcp.services.job_completion_service import JobCompletionService

logger = logging.getLogger(__name__)

CLOSEOUT_MODE_HITL = "hitl"
CLOSEOUT_MODE_AUTONOMOUS = "autonomous"
CLOSEOUT_MODE_DEFAULT = CLOSEOUT_MODE_HITL

PROTECTED_SURFACE_PATTERNS: tuple[str, ...] = (
    "migrations/",
    "/auth",
    "auth/",
    "licensing",
    "jwt",
    "csrf",
    "oauth",
    "password",
    "billing",
    "polar",
    "stripe",
    "subscription",
)

_CTX_GATE = "closeout_gate"
_CTX_CHAIN_SETTLEMENT = "chain_settlement"
_CTX_RUN_ID = "sequence_run_id"
_CTX_CONDUCTOR = "conductor_agent_id"
_CTX_REASONS = "signal_reasons"


def _collect_paths(result: dict[str, Any]) -> list[str]:
    paths: list[str] = []
    files = result.get("files_changed")
    if isinstance(files, (list, tuple)):
        paths.extend(str(f) for f in files if f)
    commits = result.get("commits")
    if isinstance(commits, (list, tuple)):
        for c in commits:
            if isinstance(c, dict):
                for key in ("files", "paths", "files_changed"):
                    val = c.get(key)
                    if isinstance(val, (list, tuple)):
                        paths.extend(str(f) for f in val if f)
                if c.get("message"):
                    paths.append(str(c["message"]))
            elif c:
                paths.append(str(c))
    return paths


def detect_closeout_signal(result: dict[str, Any] | None) -> list[str]:
    reasons: list[str] = []
    if not isinstance(result, dict):
        return reasons

    deferred = result.get("deferred_findings")
    if isinstance(deferred, (list, tuple)) and len(deferred) > 0:
        reasons.append(f"{len(deferred)} deferred finding(s) awaiting a user decision")

    paths = _collect_paths(result)
    matched = sorted({pat for p in paths for pat in PROTECTED_SURFACE_PATTERNS if pat in p.lower()})
    if matched:
        reasons.append(f"protected surface(s) touched: {', '.join(matched)}")

    tests = result.get("tests")
    if not isinstance(tests, dict):
        tests = result.get("verification")
    if isinstance(tests, dict):
        failed = tests.get("failed") or 0
        skipped = tests.get("skipped") or 0
        try:
            if int(failed) > 0 or int(skipped) > 0:
                reasons.append(f"verification gap: {int(failed)} failed / {int(skipped)} skipped test(s)")
        except (TypeError, ValueError):
            pass
    gaps = result.get("verification_gaps")
    if isinstance(gaps, (list, tuple)) and len(gaps) > 0:
        reasons.append(f"{len(gaps)} verification gap(s) recorded")

    return reasons


async def read_closeout_mode(session: AsyncSession, tenant_key: str) -> str:
    from giljo_mcp.services.settings_service import SettingsService

    try:
        mode = await SettingsService(session, tenant_key).get_setting_value(
            "general", "closeout_mode", CLOSEOUT_MODE_DEFAULT
        )
    except Exception:  # noqa: BLE001 — a settings read must never break completion
        logger.warning("[BE-9153] closeout_mode read failed; defaulting", exc_info=True)
        return CLOSEOUT_MODE_DEFAULT
    if mode not in (CLOSEOUT_MODE_HITL, CLOSEOUT_MODE_AUTONOMOUS):
        return CLOSEOUT_MODE_DEFAULT
    return mode


def _is_conductor(job: Any) -> bool:
    return getattr(job, "project_id", None) is None and bool(
        (getattr(job, "job_metadata", None) or {}).get("chain_conductor")
    )


async def _gate_approvals_for_execution(
    session: AsyncSession, tenant_key: str, execution_id: Any
) -> list[UserApproval]:
    stmt = select(UserApproval).where(
        UserApproval.tenant_key == tenant_key,
        UserApproval.agent_execution_id == execution_id,
    )
    rows = (await session.execute(stmt)).scalars().all()
    return [r for r in rows if (r.context or {}).get(_CTX_GATE) is True]


async def has_pending_chain_settlement(session: AsyncSession, run_id: str, tenant_key: str) -> bool:
    from giljo_mcp.database import tenant_session_context

    stmt = select(UserApproval).where(
        UserApproval.tenant_key == tenant_key,
        UserApproval.status == "pending",
    )
    with tenant_session_context(session, tenant_key):
        rows = (await session.execute(stmt)).scalars().all()
    for r in rows:
        ctx = r.context or {}
        if ctx.get(_CTX_CHAIN_SETTLEMENT) is True and str(ctx.get(_CTX_RUN_ID)) == str(run_id):
            return True
    return False


async def _find_active_run(svc: JobCompletionService, session: AsyncSession, project_id: Any, tenant_key: str):
    try:
        from giljo_mcp.services.sequence_run_service import SequenceRunService

        run_svc = SequenceRunService(
            db_manager=svc.db_manager,
            tenant_manager=svc.tenant_manager,
            session=session,
        )
        return await run_svc.find_active_run_for_project(project_id=str(project_id), tenant_key=tenant_key)
    except Exception:  # noqa: BLE001 — chain lookup must never break completion; treat as solo
        logger.warning("[BE-9153] chain-run lookup failed; treating closeout as solo", exc_info=True)
        return None


async def _resolve_project_name(session: AsyncSession, tenant_key: str, project_id: Any) -> str | None:
    try:
        stmt = select(Project.name).where(
            Project.tenant_key == tenant_key,
            Project.id == str(project_id),
        )
        return (await session.execute(stmt)).scalar_one_or_none()
    except Exception:  # noqa: BLE001 — the name is an enrichment; the bell is not
        logger.warning("[BE-9436b] project-name lookup for the approval bell failed", exc_info=True)
        return None


async def _emit_approval_bell(
    svc: JobCompletionService,
    *,
    session: AsyncSession,
    tenant_key: str,
    approval: UserApproval,
    reasons: list[str],
) -> None:
    try:
        from giljo_mcp.services.notification_service import NotificationService

        project_name = await _resolve_project_name(session, tenant_key, approval.project_id)
        detail = "; ".join(reasons) if reasons else "A closeout is awaiting your review."
        body = f"{project_name}: {detail}" if project_name else detail
        title = f"{project_name}: closeout requires approval" if project_name else "Closeout requires approval"

        service = NotificationService(
            db_manager=svc.db_manager,
            websocket_manager=svc._websocket_manager,
            session=svc._test_session,
        )
        await service.create(
            tenant_key=tenant_key,
            notification_type="closeout.approval_required",
            severity="warning",
            title=title[:255],
            body=body[:500],
            dedupe_key=f"closeout.approval_required:{approval.id}",
            surface="both",
            cta_label="Review",
            cta_route="Projects",
            dismissible=True,
            payload={
                "project_id": str(approval.project_id),
                "approval_id": str(approval.id),
                "reason_count": len(reasons),
                "project_name": project_name,
            },
        )
    except Exception:  # noqa: BLE001 — the approval is the load-bearing part; the bell is a nicety
        logger.warning("[BE-9153] closeout approval bell emit failed (non-fatal)", exc_info=True)


def _block_error(job_id: str, approval_id: Any, reasons: list[str]) -> ValidationError:
    return ValidationError(
        message=(
            "CLOSEOUT_APPROVAL_REQUIRED: closeout_mode='hitl' and this closeout carries signal "
            f"({'; '.join(reasons)}). A user_approval was created — resolve it via "
            "POST /api/approvals/{id}/decide, then call complete_job() again."
        ),
        error_code="CLOSEOUT_APPROVAL_REQUIRED",
        context={
            "job_id": job_id,
            "approval_id": approval_id,
            "agent_status": "awaiting_user",
            "reasons": reasons,
        },
    )


def build_completion_blocked_error(
    *,
    job_id: str,
    unread_messages: list,
    incomplete_todos: list,
) -> ValidationError:
    reasons: list[str] = []
    if unread_messages:
        unread_ids = [str(msg.id) for msg in unread_messages[:5]]
        blocked_threads = sorted({str(t) for t in (getattr(m, "thread_id", None) for m in unread_messages) if t})
        reasons.append(
            f"Acknowledge {len(unread_messages)} action-required message(s) before completing. "
            f"They are on thread(s) {blocked_threads} — not necessarily the thread this job has "
            f"been posting on. On EACH, call get_thread_history(thread_id=<that thread>, "
            f"as_participant=<the agent id of job {job_id}>, mark_read=true) with NO "
            f"directed_only/action_required_only/tail filter (join_thread first if that id is not "
            f"a participant) — that ack is what clears this gate. Pending: {unread_ids}"
        )
    if incomplete_todos:
        todo_names = [todo.content for todo in incomplete_todos[:5]]
        reasons.append(
            f"{len(incomplete_todos)} TODO item(s) not completed: {todo_names}. Settle the ledger "
            f'with report_progress(job_id="{job_id}", todo_items=[...], replace=true) — replace=true '
            f"overwrites the whole list, so an orchestrator accepting a stalled agent's work records "
            f"what it ACTUALLY finished rather than marking abandoned items done."
        )

    if incomplete_todos:
        next_action = build_next_action(
            tool="report_progress",
            args_hint={"job_id": job_id, "todo_items": ["<honest final state>"], "replace": True},
            why=(
                "Completion is blocked by TODO items still open on this job. Rewrite the "
                "ledger to its honest final state with replace=true, then retry complete_job. "
                "If you are an orchestrator accepting a stalled agent's verified work, this "
                "is the prerequisite step — record what it actually delivered."
            ),
        )
    else:
        next_action = build_next_action(
            tool="get_thread_history",
            args_hint={
                "thread_id": "<each thread named in the reason above>",
                "as_participant": "<the agent id of this job>",
                "mark_read": True,
            },
            why=(
                "Completion is blocked by unacknowledged action-required messages. Read each "
                "named thread with mark_read=true and no filters — that ack is what clears the "
                "gate. A filtered read acks only what it returns and never advances your cursor."
            ),
        )

    return ValidationError(
        message="COMPLETION_BLOCKED: Complete all TODO items and read all messages before calling complete_job()",
        error_code="COMPLETION_BLOCKED",
        context={
            "job_id": job_id,
            "reasons": reasons,
            "unread_messages": len(unread_messages),
            "incomplete_todos": len(incomplete_todos),
            "next_action": next_action,
        },
    )


async def enforce_closeout_approval_mode(
    svc: JobCompletionService,
    *,
    session: AsyncSession,
    job: Any,
    execution: Any,
    tenant_key: str,
    result: dict[str, Any],
    is_closeout_phase: bool,
) -> str:
    if not is_closeout_phase:
        return CLOSEOUT_MODE_DEFAULT

    mode = await read_closeout_mode(session, tenant_key)
    if mode != CLOSEOUT_MODE_HITL:
        return mode

    reasons = detect_closeout_signal(result)
    if not reasons:
        return mode

    if _is_conductor(job):
        return mode

    from giljo_mcp.services.user_approval_service import UserApprovalService

    existing = await _gate_approvals_for_execution(session, tenant_key, execution.id)
    run = await _find_active_run(svc, session, getattr(job, "project_id", None), tenant_key)

    approval_svc = UserApprovalService(
        db_manager=svc.db_manager,
        tenant_manager=svc.tenant_manager,
        websocket_manager=svc._websocket_manager,
        test_session=svc._test_session,
    )

    if run is not None:
        if not existing:
            approval = await approval_svc.create_pending(
                tenant_key=tenant_key,
                job_id=execution.job_id,
                project_id=str(job.project_id),
                reason=f"Chain-link closeout carries signal: {'; '.join(reasons)}",
                options=[
                    {"id": "approve", "label": "Approve link closeout"},
                    {"id": "reject", "label": "Send back for rework"},
                ],
                context={
                    _CTX_GATE: True,
                    _CTX_CHAIN_SETTLEMENT: True,
                    _CTX_RUN_ID: str(run.get("id")),
                    _CTX_CONDUCTOR: run.get("conductor_agent_id"),
                    _CTX_REASONS: reasons,
                },
                park_execution=False,
            )
            await _emit_approval_bell(svc, session=session, tenant_key=tenant_key, approval=approval, reasons=reasons)
        return mode

    if any(a.status == "decided" for a in existing):
        return mode
    if any(a.status == "pending" for a in existing):
        pending = next(a for a in existing if a.status == "pending")
        raise _block_error(execution.job_id, pending.id, reasons)

    approval = await approval_svc.create_pending(
        tenant_key=tenant_key,
        job_id=execution.job_id,
        project_id=str(job.project_id),
        reason=f"Closeout carries signal: {'; '.join(reasons)}",
        options=[
            {"id": "approve", "label": "Approve and close out"},
            {"id": "reject", "label": "Send back for rework"},
        ],
        context={_CTX_GATE: True, _CTX_REASONS: reasons},
        park_execution=True,
    )
    await _emit_approval_bell(svc, session=session, tenant_key=tenant_key, approval=approval, reasons=reasons)
    raise _block_error(execution.job_id, approval.id, reasons)


def build_closeout_checklist(closeout_mode: str = CLOSEOUT_MODE_DEFAULT) -> dict[str, Any]:
    gate_line = (
        "closeout_mode='hitl': complete_job will require a user approval when your "
        "result carries signal — a non-empty 'deferred_findings' list, changed files on "
        "a protected surface (auth/licensing/billing/migrations), or a verification gap "
        "('tests'/'verification' with failed/skipped > 0). A clean closeout never blocks."
        if closeout_mode == CLOSEOUT_MODE_HITL
        else "closeout_mode='autonomous': closeouts complete without an approval gate."
    )
    return {
        "closeout_mode": closeout_mode,
        "follow_up_items": ("Create tasks/projects for any deferred work via create_task() or create_project()."),
        "instruction": (
            "Deferred findings that need a user decision are reviewed BEFORE "
            "complete_job: call request_approval(...) first -- your status "
            "flips to awaiting_user and complete_job refuses until the user "
            "decides. If a decision surfaces only now (after completion), "
            "request_approval is still safe: once the user decides, your "
            "status is restored and write_project_closeout proceeds. "
            f"{gate_line}"
        ),
    }
