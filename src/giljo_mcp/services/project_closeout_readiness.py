# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""Closeout-readiness data structures and batch lookup helpers.

Extracted from ``ProjectCloseoutService`` (BE-9144-FIX) to keep that module
under the line cap. Pure data classes plus session-only query helpers — no
service state. The single readiness source
(``ProjectCloseoutService.evaluate_closeout_readiness``) composes these; the
dataclasses are re-exported from ``project_closeout_service`` so existing
imports of them from that module keep working.
"""

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select

from giljo_mcp.models.agent_identity import AgentTodoItem
from giljo_mcp.models.user_approval import UserApproval
from giljo_mcp.repositories.agent_operations_repository import AgentOperationsRepository


@dataclass
class AgentReadinessFinding:
    """Per-agent closeout-readiness data for one non-skipped agent.

    The SUPERSET of what the former three readiness checks each inspected. How a
    finding renders into a blocker (merged-per-agent vs per-issue, whether an
    ``awaiting_user`` agent is a distinct blocker, whether a complete agent's
    unread messages block) is the CALLER's concern — this is just the data.
    """

    job_id: str
    agent_id: str | None
    agent_name: str | None
    status: str
    messages_waiting: int
    incomplete_todos: list[str]
    incomplete_pending: int
    incomplete_in_progress: int
    awaiting_user: bool
    approval_id: str | None


@dataclass
class CloseoutReadinessReport:
    """One source of closeout-readiness truth (BE-3010c).

    Produced by :meth:`ProjectCloseoutService.evaluate_closeout_readiness`; the
    former ``_check_agent_readiness`` (rich list), ``_check_closeout_readiness``
    (envelope) and ``can_close`` (coarse counts) now all SHAPE this single report
    into their own wire format. ``findings`` covers every non-skipped agent
    (the orchestrator excluded when ``orchestrator_job_id`` is supplied); the
    orchestrator's own incomplete TODOs are gathered separately.
    """

    findings: list[AgentReadinessFinding]
    agents_checked: int
    status_counts: dict[str, Any]
    orchestrator_incomplete: list[str] = field(default_factory=list)
    orchestrator_pending: int = 0
    orchestrator_in_progress: int = 0


async def incomplete_todos_by_jobs(session: Any, job_ids: list[str], tenant_key: str) -> dict[str, list[AgentTodoItem]]:
    """Return pending/in_progress TODO rows for many jobs in ONE query (BE-9144).

    Grouped in Python by job_id — replaces the former per-job N+1. A job with
    no incomplete TODOs is simply absent from the map (callers use
    ``.get(id, [])``). Row order within each job matches the single-job query
    (the same scan filtered to that job_id), so each derived
    ``incomplete_todos`` list is unchanged.
    """
    if not job_ids:
        return {}
    stmt = select(AgentTodoItem).where(
        AgentTodoItem.job_id.in_(job_ids),
        AgentTodoItem.tenant_key == tenant_key,
        AgentTodoItem.status.in_(["pending", "in_progress"]),
    )
    rows = list((await session.execute(stmt)).scalars().all())
    todos_by_job: dict[str, list[AgentTodoItem]] = {}
    for todo in rows:
        todos_by_job.setdefault(todo.job_id, []).append(todo)
    return todos_by_job


async def live_action_required_unread_by_agent(
    session: Any, tenant_key: str, project_id: str, executions: list[Any]
) -> dict[str, int]:
    """Live ack-based action-required unread count per scanned agent (TSK-9268).

    The closeout gate's ``messages_waiting`` must read the SAME store the
    ``get_thread_history(mark_read=True)`` drain writes (a
    ``message_acknowledgments`` row per (message_id, agent_id)) — i.e. the
    complete_job gate definition (BE-9108/BE-9012b: ``requires_action=True``,
    ``auto_generated=False``, not yet acked). The former source, the
    denormalized ``AgentExecution.messages_waiting_count`` column, is
    increment-only (nothing in src/ decrements it), so a fully-drained agent
    blocked project closeout forever with a stuck count. Takes the scanned
    execution rows and extracts the agent ids itself; thin wrapper over
    ``AgentOperationsRepository.get_live_action_required_unread_counts_by_agent``
    (one batched GROUP BY across all agents, no N+1).
    """
    agent_ids = [execution.agent_id for execution in executions if execution.agent_id]
    return await AgentOperationsRepository().get_live_action_required_unread_counts_by_agent(
        session, tenant_key, project_id, agent_ids
    )


def shape_readiness_blockers(report: CloseoutReadinessReport) -> list[dict[str, Any]]:
    """Shape a :class:`CloseoutReadinessReport` into the merged-per-agent blocker
    list + trailing ``_summary`` entry every CLOSEOUT_BLOCKED-style rejection
    uses (BE-3010c / BE-9539).

    Extracted from ``tools/project_closeout.py::_check_agent_readiness`` (which
    now delegates here) so ``ProjectService.archive_project``'s closeout gate
    (BE-9539) can build the IDENTICAL blocker shape without a services -> tools
    import — this module already sits in the service layer. Output is
    unchanged from the pre-extraction inline version.
    """
    blockers: list[dict[str, Any]] = []
    summary = {
        "agents_checked": report.agents_checked,
        "still_working": 0,
        "with_unread_messages": 0,
        "with_incomplete_todos": 0,
        "awaiting_user_approval": 0,
    }

    for finding in report.findings:
        if finding.status == "complete":
            continue

        if finding.awaiting_user:
            blockers.append(
                {
                    "agent_id": finding.agent_id,
                    "agent_name": finding.agent_name,
                    "status": "awaiting_user",
                    "job_id": finding.job_id,
                    "issue_type": "awaiting_user_approval",
                    "approval_id": finding.approval_id,
                    "suggested_action": (
                        f"Resolve approval {finding.approval_id} via POST /api/approvals/{finding.approval_id}/decide."
                    ),
                }
            )
            summary["awaiting_user_approval"] += 1
            continue

        summary["still_working"] += 1
        messages_waiting = finding.messages_waiting
        if messages_waiting > 0:
            summary["with_unread_messages"] += 1

        incomplete_count = len(finding.incomplete_todos)
        incomplete_names = finding.incomplete_todos[:5]
        if incomplete_count > 0:
            summary["with_incomplete_todos"] += 1

        # Build suggested_action with all relevant remediation steps
        steps = []
        if messages_waiting > 0:
            steps.append(
                f"Drain {messages_waiting} unread messages via get_thread_history(as_participant='{finding.agent_id}')"
            )
        if incomplete_count > 0:
            steps.append(
                f"Update {incomplete_count} incomplete TODOs via "
                f"report_progress(job_id='{finding.job_id}', todo_items=[...]) "
                f"marking as completed/skipped"
            )
        steps.append(f"Force-complete via complete_job(job_id='{finding.job_id}')")
        suggested_action = ". ".join(steps) + "."

        blockers.append(
            {
                "agent_id": finding.agent_id,
                "agent_name": finding.agent_name,
                "status": finding.status,
                "job_id": finding.job_id,
                "issue_type": "still_working",
                "messages_waiting": messages_waiting,
                "incomplete_todo_count": incomplete_count,
                "incomplete_todo_names": incomplete_names,
                "suggested_action": suggested_action,
            }
        )

    if blockers:
        blockers.append({"_summary": summary})

    return blockers


async def pending_approval_ids_by_execution(
    session: Any, agent_execution_ids: list[Any], tenant_key: str
) -> dict[Any, Any]:
    """Map each agent_execution_id to its pending UserApproval id in ONE query
    (BE-9144). Replaces the former per-execution scalar lookup. At most one
    pending approval per execution is expected (the single-lookup path used
    ``scalar_one_or_none``); the value only surfaces an approval to the user.
    """
    if not agent_execution_ids:
        return {}
    stmt = select(UserApproval.id, UserApproval.agent_execution_id).where(
        UserApproval.tenant_key == tenant_key,
        UserApproval.agent_execution_id.in_(agent_execution_ids),
        UserApproval.status == "pending",
    )
    rows = (await session.execute(stmt)).all()
    return {exec_id: approval_id for approval_id, exec_id in rows}
