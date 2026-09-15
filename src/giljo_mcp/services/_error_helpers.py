# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from typing import TYPE_CHECKING

from giljo_mcp.exceptions import ResourceNotFoundError
from giljo_mcp.models.agent_identity import TERMINAL_EXECUTION_STATUSES
from giljo_mcp.repositories.agent_job_repository import AgentJobRepository
from giljo_mcp.schemas.service_responses import build_next_action


M_REACTIVATE = "service.reactivate_job"
M_DISMISS = "service.dismiss_reactivation"
M_CLOSE = "service.close_job"


if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from giljo_mcp.database import DatabaseManager


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
