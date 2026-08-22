# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-9153 — signal-gated ``closeout_mode`` enforcement for ``complete_job``.

Edition Scope: Both (CE core: approvals + job completion + chain runtime).

Wires the "Require approval before closeout" toggle (``general.closeout_mode``,
written by ``TemplateManager.vue``) into the orchestrator's closeout-phase
``complete_job``. The 2026-04 first attempt (c879182c4, reverted next day by
c89173156) blocked EVERY orchestrator closeout with no resume path and
deadlocked. This one avoids both flaws:

* **signal-gated** — only a closeout that CARRIES SIGNAL blocks; a clean closeout
  never blocks, chain or not. See :func:`detect_closeout_signal`.
* **resumable** — the block rides the ``user_approvals`` + ``awaiting_user``
  primitive, whose decide path (BE-9054) restores the pre-approval status, and a
  *decided* gate-approval satisfies the gate on the re-call (no re-block loop).
* **chain-aware** — a findings-bearing link INSIDE a chain is accepted
  PROVISIONALLY (its settlement approval is created without parking the agent; the
  conductor advances), and the chain's own closeout is held until every settlement
  approval is decided (see ``project_helpers.complete_chain_run_if_finished``).

The gate lives here (not in ``job_completion_service``) because that module is at
its shrink-only line budget; this also co-locates the whole closeout-approval
concern (signal predicate + gate + agent-facing checklist).
"""

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

# The two recognized values. Anything else (missing key, legacy/garbage) is
# tolerated by falling back to the default (data-facing DoD — code tolerates the
# old shape). Default = 'hitl': the 2026-07-12 "default on" call — the toggle
# is honest on a fresh install (the UI already displays hitl), and the impact is
# bounded because a CLEAN closeout never gates.
CLOSEOUT_MODE_HITL = "hitl"
CLOSEOUT_MODE_AUTONOMOUS = "autonomous"
CLOSEOUT_MODE_DEFAULT = CLOSEOUT_MODE_HITL

# BE-9153: substrings that mark a "protected surface" in a closeout's changed-file
# set. A closeout whose result touches any of these is SIGNAL-bearing under
# closeout_mode='hitl' and auto-creates a blocking user_approval. This tuple is the
# SINGLE source of truth for the protected-surface half of the signal predicate —
# reviewers extend it HERE (auth / licensing / billing / migrations today).
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

# Server-reserved context marker keys on a gate-created user_approval. Agent-
# supplied values for these keys are never trusted to drive the gate (the gate
# only writes them itself).
_CTX_GATE = "closeout_gate"
_CTX_CHAIN_SETTLEMENT = "chain_settlement"
_CTX_RUN_ID = "sequence_run_id"
_CTX_CONDUCTOR = "conductor_agent_id"
_CTX_REASONS = "signal_reasons"


def _collect_paths(result: dict[str, Any]) -> list[str]:
    """Best-effort collection of changed-file path strings from a closeout result.

    Reads the documented ``files_changed`` list plus any string form of
    ``commits`` entries (which may be plain messages or dicts). Never raises.
    """
    paths: list[str] = []
    files = result.get("files_changed")
    if isinstance(files, (list, tuple)):
        paths.extend(str(f) for f in files if f)
    commits = result.get("commits")
    if isinstance(commits, (list, tuple)):
        for c in commits:
            if isinstance(c, dict):
                # a commit dict may carry files/paths and a message
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
    """Return the human-readable reasons a closeout ``result`` carries signal.

    Empty list == a CLEAN closeout (never blocks). Reads ONLY the closeout
    ``result`` payload (extra="allow"), so detection is available at
    ``complete_job`` time (which precedes ``write_project_closeout``):

    1. **deferred findings** — a non-empty ``result["deferred_findings"]`` list.
    2. **protected surfaces** — any path in ``result["files_changed"]`` /
       ``result["commits"]`` matching :data:`PROTECTED_SURFACE_PATTERNS`.
    3. **verification gaps** — ``result["tests"]`` / ``result["verification"]``
       reporting failed>0 or skipped>0, or a non-empty
       ``result["verification_gaps"]`` list.
    """
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
    """Read the tenant's ``general.closeout_mode`` (tenant-scoped), tolerantly.

    Missing key → :data:`CLOSEOUT_MODE_DEFAULT` (the documented default). An
    unrecognized stored value is also tolerated to the default (never raises,
    never crashes an existing install — data-facing DoD).
    """
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
    """Project-less chain conductor (project_id None + chain_conductor metadata)."""
    return getattr(job, "project_id", None) is None and bool(
        (getattr(job, "job_metadata", None) or {}).get("chain_conductor")
    )


async def _gate_approvals_for_execution(
    session: AsyncSession, tenant_key: str, execution_id: Any
) -> list[UserApproval]:
    """All gate-created approvals bound to this execution (any status), tenant-scoped."""
    stmt = select(UserApproval).where(
        UserApproval.tenant_key == tenant_key,
        UserApproval.agent_execution_id == execution_id,
    )
    rows = (await session.execute(stmt)).scalars().all()
    return [r for r in rows if (r.context or {}).get(_CTX_GATE) is True]


async def has_pending_chain_settlement(session: AsyncSession, run_id: str, tenant_key: str) -> bool:
    """True if any provisional-completion settlement approval for ``run_id`` is still pending.

    The chain's own closeout (run purge) is held while this is True — a
    findings-bearing link was accepted provisionally and the user has not yet
    decided its settlement approval. Tenant-scoped (explicit ``tenant_key`` filter
    + ambient tenant context, matching the chain self-heal read boundary).
    """
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
    """Resolve the active chain run for a project, or None (solo). Best-effort."""
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
    """Tenant-scoped read of a project's name, or None if it cannot be resolved.

    BE-9436b. Fail-open on its own, separately from the caller's try/except: an
    unnamed bell row is a degraded row, but a lost bell row is a lost row. The
    operator must never be told nothing because a name lookup went wrong.
    """
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
    """Best-effort bell+banner notification when the gate creates an approval (design item 3).

    Non-fatal: a notification failure must never break the closeout gate.

    BE-9436b: the row NAMES its project. The title is a constant and the payload
    carried only ids, so an operator with two closeouts in flight could not tell
    which one was waiting on them. The name leads BOTH the title and the body, as
    ``_prelaunch_workproduct_detector`` already does: the title is the prominent
    line in ``NotificationDropdown`` and the body is rendered generically for
    every type, so a payload key alone would leave the row as anonymous as before.

    Both strings fall back to today's exact text when the name does not resolve.
    """
    try:
        from giljo_mcp.services.notification_service import NotificationService

        project_name = await _resolve_project_name(session, tenant_key, approval.project_id)
        detail = "; ".join(reasons) if reasons else "A closeout is awaiting your review."
        body = f"{project_name}: {detail}" if project_name else detail
        # Notification.title is String(255); project_name is capped at 255 on its
        # own, so the composed title has to be bounded or a long name overflows it.
        title = f"{project_name}: closeout requires approval" if project_name else "Closeout requires approval"

        # Thread the test session when present so tests don't persist a stray row on
        # a real session; production (test_session None) opens its own session.
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
    """Build complete_job's COMPLETION_BLOCKED rejection (BE-9292b).

    Lives beside :func:`_block_error` -- the other complete_job gate rejection --
    and out of ``job_completion_service``, which sits at its shrink-only size budget.

    This gate is reached by TWO callers: the agent completing its own job, and an
    ORCHESTRATOR completing a stalled agent's job on its behalf (the accepting exit
    for a 'silent' worker). So it addresses the JOB, never "your" ledger -- an
    orchestrator acting for a dead agent has to drain that agent's thread under that
    agent's id, not its own -- and every reason names the tool that clears it instead
    of only listing what is stuck. AUDIT_9292B F2: this wall is the one an orchestrator
    hits while running the documented stalled-agent recovery, and it previously named
    no tool at all.
    """
    reasons: list[str] = []
    if unread_messages:
        unread_ids = [str(msg.id) for msg in unread_messages[:5]]
        # The gate is PROJECT-scoped while the drain is THREAD-scoped, so the blocking
        # posts are not necessarily on the thread this job has been talking on — naming
        # only "that job's coordination thread" sent agents to drain the wrong thread and
        # read the resulting no-op as a broken gate. Name the threads, and name the
        # UNFILTERED call: a narrowed read acks what it returns but leaves the cursor
        # where it was, so unread_only keeps re-serving the same posts.
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

    # The stranded-TODO half is the one the recovery walks into, so it points at the
    # settling call; a messages-only block points at the drain, which clears THAT half.
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
    """Signal-gated closeout approval enforcement. Returns the resolved closeout_mode.

    Called from ``complete_job`` after the completion-requirements gate and before
    the status is applied. No-op (returns the module default) for anything that is
    not an orchestrator closeout — workers and staging-end stay byte-identical.

    Behavior when ``closeout_mode == 'hitl'`` AND the closeout carries signal:
    * **conductor** — skip (the chain's oversight is the settlement queue, drained
      at the conductor's chain closeout, not a self-approval).
    * **chain-member sub-orch** — create a settlement approval WITHOUT parking the
      agent and return (provisional completion; the conductor advances).
    * **solo** — if a *decided* gate-approval already exists, proceed (the re-call
      after the user decided); otherwise create a parking approval and RAISE
      ``CLOSEOUT_APPROVAL_REQUIRED``.

    ``autonomous`` mode and a clean (no-signal) closeout both return without any
    side effect — byte-identical to pre-BE-9153 behavior.
    """
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
        # Chain member — provisional completion. Create the settlement approval once
        # (idempotent: skip if a gate approval already exists for this execution).
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

    # Solo closeout.
    if any(a.status == "decided" for a in existing):
        # The user already decided this closeout (BE-9054 restored the status) —
        # the gate is satisfied; do NOT re-block (this is what April lacked).
        return mode
    if any(a.status == "pending" for a in existing):
        # Defensive: a pending gate approval means the agent is parked; the
        # completion-requirements gate normally catches this first.
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
    """Closeout checklist returned to the orchestrator (moved from JobCompletionService).

    BE-9153 (instruction-loop repair, item 4): surface the tenant's ``closeout_mode``
    and the documented signal keys so the agent SEES the setting and knows what makes
    a closeout gate under hitl.
    """
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
