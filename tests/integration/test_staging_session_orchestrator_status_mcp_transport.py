# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from giljo_mcp.models.agent_identity import AgentExecution
from tests.integration.test_be9165_closeout_deadlock_mcp_boundary import (  # noqa: F401 -- fixture import
    _call_closeout,
    _seed_orchestrator,
    _seed_org_product,
    _seed_project,
    lifecycle_mcp_client,
)
from tests.integration.test_be9744a_split_stage_undo_mcp_boundary import (  # noqa: F401 -- fixture import
    _cleanup,
    _seed,
    be9744a_client,
)
from tests.integration.test_be9779_agent_replies_mcp_boundary import _seed_worker


pytestmark = pytest.mark.asyncio


def _payload(result) -> dict:
    return json.loads(result.content[0].text)


def _error_text(result) -> str:
    return "\n".join(getattr(b, "text", "") or "" for b in result.content)


async def _status(db_manager, tenant_key: str, job_id: str) -> str:
    async with db_manager.get_session_async(tenant_key=tenant_key) as verify:
        return await verify.scalar(
            select(AgentExecution.status).where(
                AgentExecution.tenant_key == tenant_key, AgentExecution.job_id == job_id
            )
        )


async def _call(client, tool: str, args: dict) -> dict:
    async with client() as session:
        result = await session.call_tool(tool, args)
    assert not result.is_error, f"{tool}: {_error_text(result)}"
    return _payload(result)


async def test_orchestrator_status_follows_the_staging_lifecycle(be9744a_client, db_manager):  # noqa: F811
    client, tenant_key, _ws = be9744a_client
    project_id = await _seed(db_manager, tenant_key, mission="")
    try:
        staged = await _call(client, "stage_project", {"project_id": project_id, "mode": "subagent"})
        orch = staged["orchestrator_id"]
        assert await _status(db_manager, tenant_key, orch) == "waiting"

        await _call(client, "get_staging_instructions", {"job_id": orch})
        assert await _status(db_manager, tenant_key, orch) == "working"

        todo = [{"content": "Plan the work", "status": "in_progress"}]
        await _call(client, "report_progress", {"job_id": orch, "todo_items": todo})
        await _call(client, "update_project_mission", {"project_id": project_id, "mission": "The plan."})
        assert await _status(db_manager, tenant_key, orch) == "working"

        await _seed_worker(db_manager, tenant_key, project_id)
        ended = await _call(client, "complete_job", {"job_id": orch, "result": {"summary": "staged"}})
        assert ended.get("staging_directive"), ended
        assert await _status(db_manager, tenant_key, orch) == "waiting"

        await _call(client, "launch_implementation", {"project_id": project_id})
        assert await _status(db_manager, tenant_key, orch) == "waiting"

        await _call(client, "get_job_mission", {"job_id": orch})
        assert await _status(db_manager, tenant_key, orch) == "working"
    finally:
        await _cleanup(db_manager, tenant_key)


async def test_undo_staging_still_works_while_the_orchestrator_plans(be9744a_client, db_manager):  # noqa: F811
    client, tenant_key, _ws = be9744a_client
    project_id = await _seed(db_manager, tenant_key, mission="")
    try:
        staged = await _call(client, "stage_project", {"project_id": project_id, "mode": "subagent"})
        orch = staged["orchestrator_id"]
        await _call(client, "get_staging_instructions", {"job_id": orch})
        await _call(client, "update_project_mission", {"project_id": project_id, "mission": "The plan."})
        assert await _status(db_manager, tenant_key, orch) == "working"

        await _call(client, "unstage_project", {"project_id": project_id})

        assert await _status(db_manager, tenant_key, orch) == "decommissioned"
    finally:
        await _cleanup(db_manager, tenant_key)


async def test_force_closeout_still_retires_a_planning_orchestrator(lifecycle_mcp_client):  # noqa: F811
    client, tenant_key, session = lifecycle_mcp_client
    _org, product = await _seed_org_product(session, tenant_key)
    project = await _seed_project(session, tenant_key, product.id, execution_mode="subagent", staging_status="staging")
    _job, orch_exec = await _seed_orchestrator(session, tenant_key, project.id, status="working")
    await session.commit()

    async with client() as mcp_session:
        result = await _call_closeout(mcp_session, project.id, force=True)

    assert not result.is_error, _error_text(result)
    await session.refresh(orch_exec)
    assert orch_exec.status == "decommissioned"


async def test_force_closeout_still_refuses_an_implementing_orchestrator(lifecycle_mcp_client):  # noqa: F811
    client, tenant_key, session = lifecycle_mcp_client
    _org, product = await _seed_org_product(session, tenant_key)
    project = await _seed_project(
        session,
        tenant_key,
        product.id,
        execution_mode="subagent",
        staging_status="staging_complete",
        implementation_launched_at=datetime.now(UTC),
    )
    _job, orch_exec = await _seed_orchestrator(session, tenant_key, project.id, status="working")
    await session.commit()

    async with client() as mcp_session:
        result = await _call_closeout(mcp_session, project.id, force=True)

    assert "ORCHESTRATOR_SELF_DECOMMISSION_BLOCKED" in _error_text(result)
    await session.refresh(orch_exec)
    assert orch_exec.status == "working"
