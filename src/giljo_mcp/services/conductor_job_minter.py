# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.models.agent_identity import AgentExecution, AgentJob
from giljo_mcp.models.base import generate_uuid
from giljo_mcp.schemas.jsonb_validators import validate_agent_job_metadata


logger = logging.getLogger(__name__)


async def mint_conductor_job(
    session: AsyncSession,
    *,
    tenant_key: str,
    run_id: str,
    conductor_label: str | None = None,
) -> dict[str, str]:
    job_id = generate_uuid()
    agent_id = generate_uuid()

    conductor_job = AgentJob(
        job_id=job_id,
        tenant_key=tenant_key,
        project_id=None,
        mission=None,
        job_type="orchestrator",
        status="active",
        job_metadata=validate_agent_job_metadata({"chain_conductor": True, "run_id": run_id}),
    )
    session.add(conductor_job)

    conductor_execution = AgentExecution(
        agent_id=agent_id,
        job_id=job_id,
        tenant_key=tenant_key,
        agent_display_name="orchestrator",
        agent_name=conductor_label or "Chain Conductor",
        status="waiting",
        health_status="unknown",
        project_phase="implementation",
    )
    session.add(conductor_execution)

    await session.flush()
    return {"agent_id": agent_id, "job_id": job_id, "execution_id": conductor_execution.id}


async def broadcast_conductor_created(
    websocket_manager: Any | None,
    *,
    tenant_key: str,
    run_id: str,
    agent_id: str,
    job_id: str,
    execution_id: str,
    conductor_label: str | None = None,
) -> None:
    if websocket_manager is None:
        return
    await websocket_manager.broadcast_to_tenant(
        tenant_key=tenant_key,
        event_type="agent:created",
        data={
            "project_id": None,
            "execution_id": execution_id,
            "agent_id": agent_id,
            "job_id": job_id,
            "agent_display_name": "orchestrator",
            "agent_name": conductor_label or "Chain Conductor",
            "status": "waiting",
            "chain_conductor": True,
            "run_id": run_id,
            "timestamp": datetime.now(UTC).isoformat(),
        },
    )


def projectless_conductor_staging_directive(job_id: str) -> dict[str, Any]:
    return {
        "status": "CHAIN_CONDUCTOR",
        "action": "USE_RUNTIME_MISSION",
        "redirect": None,
        "identity": {"job_id": job_id, "project_id": None},
        "message": (
            "You are the dedicated chain conductor (no project of your own). There are no "
            "staging instructions for you; call get_job_mission to receive your chain-drive "
            "protocol and advance the run."
        ),
        "thin_client": True,
    }
