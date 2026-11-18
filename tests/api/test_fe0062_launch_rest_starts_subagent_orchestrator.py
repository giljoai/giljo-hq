# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from giljo_mcp.models.agent_identity import AgentExecution, AgentJob
from giljo_mcp.models.projects import Project, ProjectStatus
from tests.api.test_be9709c_launch_reply_rest_parity import _seed_staged_project


pytestmark = pytest.mark.asyncio


async def _park_orchestrator(db_manager, seed: dict, execution_mode: str) -> str:
    async with db_manager.get_session_async(tenant_key=seed["tenant_key"]) as session:
        project = (
            await session.execute(
                select(Project).where(Project.id == seed["project_id"], Project.tenant_key == seed["tenant_key"])
            )
        ).scalar_one()
        project.execution_mode = execution_mode
        job = AgentJob(
            job_id=str(uuid4()),
            tenant_key=seed["tenant_key"],
            project_id=seed["project_id"],
            job_type="orchestrator",
            mission="orchestrate",
            status="active",
            created_at=datetime.now(UTC),
        )
        session.add(job)
        await session.flush()
        session.add(
            AgentExecution(
                id=str(uuid4()),
                agent_id=str(uuid4()),
                job_id=job.job_id,
                tenant_key=seed["tenant_key"],
                agent_display_name="orchestrator",
                status="waiting",
                result={"summary": "staged"},
            )
        )
        await session.commit()
        return job.job_id


async def _orchestrator_status(db_manager, seed: dict, job_id: str) -> str:
    async with db_manager.get_session_async(tenant_key=seed["tenant_key"]) as session:
        return (
            await session.execute(
                select(AgentExecution.status).where(
                    AgentExecution.job_id == job_id, AgentExecution.tenant_key == seed["tenant_key"]
                )
            )
        ).scalar_one()


async def test_dashboard_implement_starts_the_subagent_orchestrator(api_client: AsyncClient, db_manager):
    seed = await _seed_staged_project(db_manager, ProjectStatus.INACTIVE)
    job_id = await _park_orchestrator(db_manager, seed, "subagent")

    resp = await api_client.patch(
        f"/api/agent-jobs/projects/{seed['project_id']}/launch-implementation", headers=seed["headers"]
    )

    assert resp.status_code == 200, resp.text
    assert await _orchestrator_status(db_manager, seed, job_id) == "working"


async def test_dashboard_implement_leaves_a_multi_terminal_orchestrator_waiting(api_client: AsyncClient, db_manager):
    seed = await _seed_staged_project(db_manager, ProjectStatus.INACTIVE)
    job_id = await _park_orchestrator(db_manager, seed, "multi_terminal")

    resp = await api_client.patch(
        f"/api/agent-jobs/projects/{seed['project_id']}/launch-implementation", headers=seed["headers"]
    )

    assert resp.status_code == 200, resp.text
    assert await _orchestrator_status(db_manager, seed, job_id) == "waiting"
