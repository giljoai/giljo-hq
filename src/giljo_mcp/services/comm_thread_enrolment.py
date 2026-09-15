# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any


if TYPE_CHECKING:  # pragma: no cover - import cycle guard, typing only
    from sqlalchemy.ext.asyncio import AsyncSession

    from giljo_mcp.models.agent_identity import AgentExecution, AgentJob


logger = logging.getLogger(__name__)


async def resolve_and_enrol(
    mission_service: Any,
    session: AsyncSession,
    job: AgentJob,
    execution: AgentExecution,
    tenant_key: str,
) -> str | None:
    if not job.project_id:
        return None
    comm_thread_id = await mission_service._resolve_comm_thread_id(session, job, tenant_key)
    if comm_thread_id and job.job_type == "orchestrator":
        await _join(mission_service, session, comm_thread_id, execution, tenant_key)
    return comm_thread_id


async def _join(
    mission_service: Any,
    session: AsyncSession,
    thread_id: str,
    execution: AgentExecution,
    tenant_key: str,
) -> None:
    try:
        from giljo_mcp.services.comm_thread_service import CommThreadService

        comm_service = CommThreadService(mission_service.db_manager, mission_service.tenant_manager, session=session)
        await comm_service.join_thread(
            thread_id=thread_id,
            participant_id=str(execution.agent_id),
            display_name=execution.agent_display_name,
            tenant_key=tenant_key,
        )
    except Exception:  # noqa: BLE001 - best-effort; never break mission delivery
        logger.warning(
            "[TSK-9459] comm thread join failed (non-fatal); the orchestrator is not enrolled",
            extra={"thread_id": thread_id, "agent_id": str(execution.agent_id)},
        )
