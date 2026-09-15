# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.models import AgentJob


logger = logging.getLogger(__name__)


async def mirror_chain_mission_for_conductor(
    *,
    session: AsyncSession,
    job: AgentJob,
    tenant_key: str,
    mission: str,
    db_manager: Any,
    tenant_manager: Any,
    repo: Any,
    websocket_manager: Any | None = None,
) -> None:
    metadata = job.job_metadata or {}
    if not metadata.get("chain_conductor"):
        return

    try:
        from giljo_mcp.services.sequence_run_service import SequenceRunService

        svc = SequenceRunService(
            db_manager=db_manager,
            tenant_manager=tenant_manager,
            session=session,
            websocket_manager=websocket_manager,
        )

        run_id = metadata.get("run_id")
        if not run_id:
            execution = await repo.get_execution_with_job(session, tenant_key, job.job_id)
            agent_id = str(execution.agent_id) if execution is not None else None
            if agent_id is not None:
                run = await svc.find_active_run_for_conductor(conductor_agent_id=agent_id, tenant_key=tenant_key)
                run_id = run.get("id") if run is not None else None
        if not run_id:
            return

        await svc.update(run_id=run_id, tenant_key=tenant_key, chain_mission=mission)
        logger.info(
            "[BE-6186] Mirrored chain conductor mission into sequence_runs.chain_mission",
            extra={"job_id": job.job_id, "run_id": run_id, "tenant_key": tenant_key},
        )
    except Exception as exc:  # noqa: BLE001 - best-effort mirror, never break the primary write
        logger.warning(
            "[BE-6186] chain_mission mirror failed (non-fatal) for job %s: %s",
            job.job_id,
            exc,
        )
