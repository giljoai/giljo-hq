# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.models.agent_identity import AgentExecution, AgentJob
from giljo_mcp.services.conductor_job_minter import (
    broadcast_conductor_created,
    mint_conductor_job,
    projectless_conductor_staging_directive,
)
from giljo_mcp.tenant import TenantManager


@pytest.mark.asyncio
async def test_mint_conductor_job_creates_projectless_orchestrator(db_session: AsyncSession) -> None:
    tenant = TenantManager.generate_tenant_key()

    identity = await mint_conductor_job(db_session, tenant_key=tenant, run_id="run-abc")

    assert identity["agent_id"], "mint must return a fresh agent_id"
    assert identity["job_id"], "mint must return the job_id"
    assert identity["execution_id"], "mint must return the execution row id"

    agent_id = identity["agent_id"]

    job = (
        await db_session.execute(
            select(AgentJob).where(
                AgentJob.tenant_key == tenant,
                AgentJob.job_type == "orchestrator",
            )
        )
    ).scalar_one()
    assert job.project_id is None, "the conductor owns NO project (project_id must be NULL)"
    assert job.job_metadata.get("chain_conductor") is True
    assert job.job_metadata.get("run_id") == "run-abc"

    execution = (
        await db_session.execute(
            select(AgentExecution).where(
                AgentExecution.agent_id == agent_id,
                AgentExecution.tenant_key == tenant,
            )
        )
    ).scalar_one()
    assert execution.job_id == job.job_id
    assert execution.agent_display_name == "orchestrator"
    assert execution.project_phase == "implementation"
    assert execution.status == "waiting"


def test_projectless_conductor_staging_directive_shape() -> None:
    directive = projectless_conductor_staging_directive("job-xyz")

    assert directive["status"] == "CHAIN_CONDUCTOR"
    assert directive["action"] == "USE_RUNTIME_MISSION"
    assert directive["identity"] == {"job_id": "job-xyz", "project_id": None}
    assert "get_job_mission" in directive["message"]
    assert directive["thin_client"] is True


class _RecordingWebsocketManager:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def broadcast_to_tenant(self, *, tenant_key, event_type, data):
        self.calls.append({"tenant_key": tenant_key, "event_type": event_type, "data": data})


@pytest.mark.asyncio
async def test_broadcast_conductor_created_emits_agent_created() -> None:
    ws = _RecordingWebsocketManager()

    await broadcast_conductor_created(
        ws,
        tenant_key="tenant-1",
        run_id="run-abc",
        agent_id="agent-1",
        job_id="job-1",
        execution_id="exec-1",
    )

    assert len(ws.calls) == 1, "a freshly minted conductor must broadcast exactly one agent:created"
    call = ws.calls[0]
    assert call["event_type"] == "agent:created"
    assert call["tenant_key"] == "tenant-1"
    data = call["data"]
    assert data["project_id"] is None, "the conductor owns NO project"
    assert data["agent_id"] == "agent-1"
    assert data["job_id"] == "job-1"
    assert data["execution_id"] == "exec-1"
    assert data["agent_display_name"] == "orchestrator"
    assert data["agent_name"] == "Chain Conductor"
    assert data["status"] == "waiting"
    assert data["chain_conductor"] is True
    assert data["run_id"] == "run-abc"


@pytest.mark.asyncio
async def test_broadcast_conductor_created_noop_without_websocket_manager() -> None:
    await broadcast_conductor_created(
        None,
        tenant_key="tenant-1",
        run_id="run-abc",
        agent_id="agent-1",
        job_id="job-1",
        execution_id="exec-1",
    )
