# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from typing import TYPE_CHECKING

from giljo_mcp.exceptions import GateRefusalError, ValidationError


if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from giljo_mcp.models.agent_identity import AgentExecution, AgentJob
    from giljo_mcp.repositories.agent_job_repository import AgentJobRepository


ORCHESTRATOR_ONLY = "ORCHESTRATOR_ONLY"
NEVER_STARTED = "JOB_NEVER_STARTED"
NEVER_STARTED_STATUSES = frozenset({"waiting", "staged"})


async def require_project_orchestrator(
    session: AsyncSession,
    repo: AgentJobRepository,
    tenant_key: str,
    target_job: AgentJob | None,
    caller_job_id: str | None,
) -> None:
    caller = await repo.get_agent_job_by_job_id(session, tenant_key, caller_job_id) if caller_job_id else None
    if (
        caller is not None
        and caller.job_type == "orchestrator"
        and target_job is not None
        and caller.project_id == target_job.project_id
    ):
        return
    raise ValidationError(
        message=(
            "Only this project's orchestrator can finalize a job. A worker ends at "
            "complete_job; the orchestrator reviews the result, then calls "
            "finalize_job(job_id, caller_job_id=<its own job_id>)."
        ),
        error_code=ORCHESTRATOR_ONLY,
        context={"caller_role": caller.job_type if caller is not None else "unknown"},
    )


def refuse_if_never_started(job: AgentJob, execution: AgentExecution) -> None:
    if job.job_type != "orchestrator" and execution.status in NEVER_STARTED_STATUSES:
        raise GateRefusalError(
            message=(
                f"This job was never started (status '{execution.status}'): no agent called "
                "get_job_mission on it, so it cannot be marked complete. If the job is not needed, "
                "call dismiss_job(job_id). If it is, have its worker call get_job_mission(job_id) "
                "first. If you meant a different job, check the job_id. The job was NOT changed."
            ),
            error_code=NEVER_STARTED,
            context={"job_id": job.job_id, "agent_status": execution.status, "next_action": "dismiss_job"},
        )
