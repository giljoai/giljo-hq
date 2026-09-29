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


async def project_thread_ref(session: AsyncSession, tenant_key: str, project_id: str) -> dict[str, str]:
    from giljo_mcp.services.comm_thread_service import CommThreadService
    from giljo_mcp.tenant import TenantManager

    service = CommThreadService(None, TenantManager(), session=session)
    try:
        async with session.begin_nested():
            thread = await service.resolve_or_create_bound_thread(project_id=str(project_id), tenant_key=tenant_key)
    except Exception:  # noqa: BLE001 -- best-effort: never fail staging or launch over the Hub
        logger.warning(
            "[BE-9709b] project thread resolution failed (non-fatal); reply carries no thread address",
            extra={"project_id": str(project_id)},
            exc_info=True,
        )
        return {}
    return {"thread_id": thread["thread_id"], "chat_id": thread["chat_id"]}


async def resolve_and_enrol(
    mission_service: Any,
    session: AsyncSession,
    job: AgentJob,
    execution: AgentExecution,
    tenant_key: str,
) -> dict[str, Any] | None:
    if not job.project_id:
        return None
    comm_thread = await mission_service._resolve_comm_thread(session, job, tenant_key)
    if comm_thread and job.job_type == "orchestrator":
        await _join(mission_service, session, comm_thread["thread_id"], execution, tenant_key)
    return comm_thread


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
