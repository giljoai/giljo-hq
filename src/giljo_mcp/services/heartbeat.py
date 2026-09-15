# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import logging

from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.database import tenant_session_context
from giljo_mcp.repositories.agent_operations_repository import AgentOperationsRepository


logger = logging.getLogger(__name__)

DEBOUNCE_SECONDS = 30


async def touch_heartbeat(session: AsyncSession, job_id: str, tenant_key: str) -> None:
    repo = AgentOperationsRepository()
    with tenant_session_context(session, tenant_key):
        updated = await repo.touch_heartbeat(session, job_id, tenant_key, DEBOUNCE_SECONDS)
    if updated:
        logger.debug("Heartbeat updated for job_id=%s", job_id)
