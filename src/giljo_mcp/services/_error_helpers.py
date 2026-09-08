# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""Shared "not found or wrong state" error builder for job/execution lookups.

TSK-9003 (follow-up from BE-8003b, PR #261): ``OrchestrationAgentStateService``
disambiguated its status-filtered lookup misses (unknown job_id vs exists-but-
wrong-state) via a private ``_not_found_or_wrong_state_error`` method, but the
three siblings that hit the exact same ambiguity -- ``job_completion_service``,
``mission_service``, ``progress_service`` -- each kept their own copy of the old
ambiguous "No active execution found for job {id}" message. Lifted here (a
service-instance method can't be imported across services without pulling in
that service's whole state) so every site shares one message + one
``build_next_action`` envelope.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from giljo_mcp.exceptions import ResourceNotFoundError
from giljo_mcp.models.agent_identity import TERMINAL_EXECUTION_STATUSES
from giljo_mcp.repositories.agent_job_repository import AgentJobRepository
from giljo_mcp.schemas.service_responses import build_next_action


# BE-9563: ``method`` labels that would otherwise read as a callable tool.
#
# These strings reach the AGENT, which is not obvious from the call site:
# ``BaseGiljoError.__str__`` renders its context dict into the message, and
# ``_base.py`` re-RAISES a sub-500 ``BaseGiljoError`` verbatim, so the SDK puts
# ``str(e)`` on the wire. An agent calling ``resume_or_dismiss_job`` on a
# wrong-state job was shown ``'method': 'dismiss_reactivation'`` -- a name that is
# not a tool. Observed on prod.
#
# The SERVICE METHODS keep their names: they are the single writer and BE-9554
# deliberately left the accessor layer alone. Only the LABEL is qualified, which
# keeps it accurate for an operator reading logs while no longer reading as
# something an agent could call. The dotted form matches the convention already in
# use at ~50 of the ~180 label sites (``comm_thread.post``, ``taxonomy.validate``).
#
# They live HERE rather than in the calling service because that service sits at
# 799 of its 800-line cap and cannot hold them, and because this module is where
# ``method`` is defined and documented in the first place. Names are short
# deliberately -- the call sites they appear on are already near the line limit.
M_REACTIVATE = "service.reactivate_job"
M_DISMISS = "service.dismiss_reactivation"
M_CLOSE = "service.close_job"


if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from giljo_mcp.database import DatabaseManager


# BE-9292b: statuses meaning "this agent has not reported in long enough that an
# orchestrator completing the job on its behalf is legitimate". 'silent' is set by
# the health monitor's inactivity timeout, so it means UNRESPONSIVE FOR AT LEAST THE
# SILENCE THRESHOLD -- not "stopped". A live agent inside one long uninterrupted
# operation is silent and entirely alive, which is why every surface that offers this
# recovery tells the orchestrator to verify the deliverable independently first: that
# verification, not the status, is what makes accepting the work honest.
_UNATTENDED_STATUSES = frozenset({"silent"})


async def not_found_or_wrong_state_error(
    session: AsyncSession,
    tenant_key: str,
    job_id: str,
    *,
    expected_status: str,
    method: str,
    db_manager: DatabaseManager,
    job_repo: AgentJobRepository | None = None,
) -> ResourceNotFoundError:
    """Disambiguate a status-filtered lookup miss (BE-8003b).

    A status-filtered execution lookup (e.g. "the active one", "the blocked
    one") returns None for TWO different reasons that used to collapse into one
    ambiguous "not found or not in status X" message: the job_id does not exist
    in this tenant at all, or it exists but its latest execution is in a
    different status. The field report (2026-06-28) measured ~5 recovery calls
    burned resolving that ambiguity by trial and error. Split it here so the
    message names which case it is and points at ``diagnose_project_state`` for
    recovery.

    ``job_repo``: a caller that already OWNS an ``AgentJobRepository`` instance
    (OrchestrationAgentStateService's ``self._job_repo`` -- the seam its tests
    mock) passes it so lookups go through that instance; callers without one
    (the three siblings) omit it and a repo is built from ``db_manager``.
    """
    if job_repo is None:
        job_repo = AgentJobRepository(db_manager)
    latest = await job_repo.get_latest_execution_for_job(session, tenant_key, job_id)
    if latest is None:
        return ResourceNotFoundError(
            message=(
                f"No job found with ID {job_id} in this tenant. The job_id may be "
                "mistyped, belong to a different tenant, or never have been spawned."
            ),
            context={
                "job_id": job_id,
                "method": method,
                "reason": "unknown_job_id",
                "next_action": build_next_action(
                    tool="diagnose_project_state",
                    why=(
                        "job_id not found in this tenant. If you know which project owns "
                        "it, call diagnose_project_state(project_id=...) to see its agents' "
                        "current job_ids and statuses."
                    ),
                ),
            },
        )

    job = await job_repo.get_agent_job_by_job_id(session, tenant_key, job_id)
    project_id = str(job.project_id) if job and job.project_id else None
    return ResourceNotFoundError(
        message=(
            f"Job {job_id} exists but its latest execution is in '{latest.status}' status, not '{expected_status}'."
        ),
        context={
            "job_id": job_id,
            "method": method,
            "reason": "wrong_state",
            "actual_status": latest.status,
            "expected_status": expected_status,
            "next_action": _wrong_state_next_action(
                job_id=job_id,
                project_id=project_id,
                actual_status=latest.status,
                expected_status=expected_status,
            ),
        },
    )


def _wrong_state_next_action(
    *,
    job_id: str,
    project_id: str | None,
    actual_status: str,
    expected_status: str,
) -> dict:
    """Pick the forward guidance for a wrong-state miss (BE-9292b).

    The generic answer is "go look at the project state". For ONE pairing that is
    a dead end, and it is the pairing an orchestrator hits when a worker stalls:
    ``close_job`` needs 'complete', the execution is 'silent' (the health
    monitor's inactivity timeout), and the agent that would normally call
    ``complete_job`` is never coming back. ``diagnose_project_state`` reports
    that state accurately and suggests nothing that resolves it, so the
    orchestrator's only VISIBLE exit was ``write_project_closeout(force=true)``
    — which decommissions, labelling an audited, committed contributor
    "failed/replaced/abandoned".

    The accepting exit already existed: ``complete_job`` accepts any non-terminal
    execution, 'silent' included, and takes the verified deliverable as its
    ``result``; ``close_job`` then reaches 'closed'. Name it here, because an
    error that refuses without naming the remedy is where the orchestrator
    actually stands when it gives up.

    Both halves of the condition are load-bearing, and they are different facts:

    * ``_UNATTENDED_STATUSES`` — nobody else will make this call. Deliberately
      NOT extended to 'working' / 'blocked' / 'idle' / 'sleeping' / 'waiting':
      those agents are alive and reachable, and telling an orchestrator to
      complete a live agent's job out from under it would be worse advice than
      the dead end this replaces. They keep the generic guidance.
    * ``TERMINAL_EXECUTION_STATUSES`` — ``complete_job`` would actually accept
      it. This is the same predicate its lookup uses, so if 'silent' is ever
      reclassified as terminal the hint stops being offered instead of becoming
      a lie. An error payload that advertises a remedy that does not work is the
      exact defect this project was opened to fix; it must not reintroduce one.
    """
    if (
        expected_status == "complete"
        and actual_status in _UNATTENDED_STATUSES
        and actual_status not in TERMINAL_EXECUTION_STATUSES
    ):
        return build_next_action(
            tool="complete_job",
            args_hint={"job_id": job_id, "result": {"summary": "<the deliverable you verified>"}},
            why=(
                f"This agent stopped responding (status '{actual_status}') and will not report its own "
                "completion. 'closed' is reachable only from 'complete', but complete_job DOES accept a "
                f"'{actual_status}' execution — so if you have VERIFIED this agent's deliverable, call "
                "complete_job(job_id, result={...}) yourself to record it, then finalize_job again. "
                "If complete_job returns COMPLETION_BLOCKED, settle its leftover ledger "
                "first: report_progress(job_id, todo_items=[...], replace=true) and drain any "
                "action-required messages. Do NOT reach for write_project_closeout(force=true) to "
                "get past this — force DECOMMISSIONS the agent, which records accepted work as "
                "failed/replaced/abandoned."
            ),
        )
    return build_next_action(
        tool="diagnose_project_state",
        args_hint={"project_id": project_id} if project_id else None,
        why=(
            f"Job is in '{actual_status}' status, not '{expected_status}'. Call "
            "diagnose_project_state to see the current agent/job state and the "
            "suggested recovery step."
        ),
    )
