# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.exceptions import ResourceNotFoundError
from giljo_mcp.models.agent_identity import AgentJob
from giljo_mcp.repositories.agent_completion_repository import AgentCompletionRepository
from giljo_mcp.repositories.agent_job_repository import AgentJobRepository
from giljo_mcp.schemas.responses.orchestration import CompleteJobResult
from giljo_mcp.services._error_helpers import not_found_or_wrong_state_error
from giljo_mcp.services._session_helpers import optional_tenant_session
from giljo_mcp.services.agent_job_manager import AgentJobManager
from giljo_mcp.services.closeout_ws_broadcast import broadcast_agent_status_changed


CHAIN_FINISHED_MESSAGE = (
    "The chain has ended (it finished or was stopped), so there is nothing left for the conductor to do."
)


async def retire_chain_conductor(
    db_manager: Any,
    tenant_manager: Any,
    conductor_agent_id: str,
    tenant_key: str,
    test_session: Any | None = None,
    websocket_manager: Any | None = None,
) -> None:
    async with optional_tenant_session(db_manager, tenant_key, test_session) as session:
        conductor = await AgentJobRepository(None).get_execution_by_agent_id(session, tenant_key, conductor_agent_id)
        if conductor is None:
            return
        events = await AgentJobManager(db_manager, tenant_manager, test_session=session).decommission_job(
            conductor.job_id, tenant_key
        )
    for event in events:
        await broadcast_agent_status_changed(websocket_manager, tenant_key=tenant_key, project_id=None, event=event)


async def is_chain_conductor_job(session: AsyncSession, tenant_key: str, job_id: str) -> bool:
    job = (
        await session.execute(select(AgentJob).where(AgentJob.job_id == job_id, AgentJob.tenant_key == tenant_key))
    ).scalar_one_or_none()
    return job is not None and job.project_id is None and bool((job.job_metadata or {}).get("chain_conductor"))


async def complete_job_without_active_execution(
    session: AsyncSession, tenant_key: str, job_id: str, *, db_manager: Any
) -> CompleteJobResult:
    if await AgentCompletionRepository().find_decommissioned_execution(session, tenant_key, job_id):
        if await is_chain_conductor_job(session, tenant_key, job_id):
            return CompleteJobResult(job_id=job_id, message=CHAIN_FINISHED_MESSAGE, phase="closeout")
        raise ResourceNotFoundError(
            message=(
                f"Job {job_id} was decommissioned and cannot transition to 'completed'. "
                f"This typically happens when write_project_closeout(force=true) "
                f"was called before complete_job()."
            ),
            context={
                "job_id": job_id,
                "method": "complete_job",
                "execution_status": "decommissioned",
                "cause": "Project was force-closed before this job called complete_job()",
            },
        )
    raise await not_found_or_wrong_state_error(
        session, tenant_key, job_id, expected_status="active", method="complete_job", db_manager=db_manager
    )
