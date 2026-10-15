# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import json
import uuid
from typing import Any

import pytest
from sqlalchemy import select

from giljo_mcp.models.agent_identity import TERMINAL_EXECUTION_STATUSES, AgentExecution, AgentJob
from tests.integration.test_be6221a_start_chain_run import (  # noqa: F401 -- fixture import
    _seed_product_context,
    _seed_project,
    chain_mcp_client,
    primary_tenant_key,
)
from tests.integration.test_be9744a_split_stage_undo_mcp_boundary import (  # noqa: F401 -- fixture import
    _cleanup,
    _seed,
    be9744a_client,
)


pytestmark = pytest.mark.asyncio

PLAN = "BE-9779 plan: implementer builds the loader, documenter writes the key reference."


def _payload(result) -> dict:
    return json.loads(result.content[0].text)


def _error_text(result) -> str:
    return "\n".join(getattr(b, "text", "") or "" for b in result.content)


def _key_paths(node: Any, key: str, path: str = "$") -> list[str]:
    found: list[str] = []
    if isinstance(node, dict):
        for k, v in node.items():
            if k == key:
                found.append(f"{path}.{k}")
            found.extend(_key_paths(v, key, f"{path}.{k}"))
    elif isinstance(node, list):
        for i, v in enumerate(node):
            found.extend(_key_paths(v, key, f"{path}[{i}]"))
    return found




async def _seed_worker(db_manager, tenant_key: str, project_id: str) -> None:
    job_id = str(uuid.uuid4())
    async with db_manager.get_session_async(tenant_key=tenant_key) as session:
        session.add(
            AgentJob(
                job_id=job_id,
                tenant_key=tenant_key,
                project_id=project_id,
                job_type="implementer",
                mission="build the loader",
                status="active",
            )
        )
        session.add(
            AgentExecution(
                agent_id=str(uuid.uuid4()),
                job_id=job_id,
                tenant_key=tenant_key,
                agent_display_name="implementer",
                agent_name="implementer",
                status="waiting",
                project_phase="implementation",
            )
        )
        await session.commit()


async def _stage_plan_and_launch(client, db_manager, tenant_key: str, project_id: str, job_plan: str | None) -> str:
    async with client() as session:
        staged = _payload(await session.call_tool("stage_project", {"project_id": project_id, "mode": "subagent"}))
        orchestrator_id = staged["orchestrator_id"]
        assert not (await session.call_tool("get_staging_instructions", {"job_id": orchestrator_id})).is_error
        if job_plan is not None:
            written = await session.call_tool("update_job_mission", {"job_id": orchestrator_id, "mission": job_plan})
            assert not written.is_error, _error_text(written)
        saved = await session.call_tool("update_project_mission", {"project_id": project_id, "mission": PLAN})
        assert not saved.is_error, _error_text(saved)
    await _seed_worker(db_manager, tenant_key, project_id)
    async with client() as session:
        ended = await session.call_tool("complete_job", {"job_id": orchestrator_id, "result": {"summary": "staged"}})
        assert not ended.is_error, _error_text(ended)
        launched = await session.call_tool("launch_implementation", {"project_id": project_id})
        assert not launched.is_error, _error_text(launched)
    return orchestrator_id


class TestOrchestratorGetsItsPlan:
    async def test_project_mission_plan_reaches_get_job_mission(self, be9744a_client, db_manager):  # noqa: F811
        client, tenant_key, _ws = be9744a_client
        project_id = await _seed(db_manager, tenant_key, mission="")
        try:
            orchestrator_id = await _stage_plan_and_launch(client, db_manager, tenant_key, project_id, job_plan=None)
            async with client() as session:
                result = await session.call_tool("get_job_mission", {"job_id": orchestrator_id})

            assert not result.is_error, _error_text(result)
            mission = _payload(result)["mission"]
            assert PLAN in mission, f"the orchestrator's saved plan never reached it: {mission[-300:]!r}"
            assert "Orchestrator mission for project:" not in mission
        finally:
            await _cleanup(db_manager, tenant_key)

    async def test_a_plan_written_with_update_job_mission_still_wins(self, be9744a_client, db_manager):  # noqa: F811
        client, tenant_key, _ws = be9744a_client
        project_id = await _seed(db_manager, tenant_key, mission="")
        job_plan = "Execution strategy: implementer first, then documenter; check in every 10 minutes."
        try:
            orchestrator_id = await _stage_plan_and_launch(
                client, db_manager, tenant_key, project_id, job_plan=job_plan
            )
            async with client() as session:
                result = await session.call_tool("get_job_mission", {"job_id": orchestrator_id})

            assert not result.is_error, _error_text(result)
            mission = _payload(result)["mission"]
            assert job_plan in mission
            assert PLAN not in mission, "a plan the orchestrator wrote to its job must not be replaced"
        finally:
            await _cleanup(db_manager, tenant_key)




async def _link(new_client, db_session, tenant_key: str) -> dict:
    await _seed_product_context(db_session, tenant_key)
    p1 = await _seed_project(db_session, tenant_key)
    p2 = await _seed_project(db_session, tenant_key)
    await db_session.commit()
    async with new_client() as session:
        result = await session.call_tool("link_projects", {"project_ids": [p1, p2], "execution_mode": "subagent"})
    assert not result.is_error, _error_text(result)
    return _payload(result)


async def _conductor(db_session, tenant_key: str, job_id: str) -> tuple[AgentJob, AgentExecution]:
    job = (
        await db_session.execute(
            select(AgentJob)
            .where(AgentJob.job_id == job_id, AgentJob.tenant_key == tenant_key)
            .execution_options(populate_existing=True)
        )
    ).scalar_one()
    execution = (
        await db_session.execute(
            select(AgentExecution)
            .where(AgentExecution.job_id == job_id, AgentExecution.tenant_key == tenant_key)
            .execution_options(populate_existing=True)
        )
    ).scalar_one()
    return job, execution


class TestChainReplies:
    async def test_link_and_unlink_replies_carry_no_tenant_key(self, chain_mcp_client, db_session, primary_tenant_key):  # noqa: F811
        new_client, _switch = chain_mcp_client
        linked = await _link(new_client, db_session, primary_tenant_key)
        async with new_client() as session:
            unlinked_result = await session.call_tool("unlink_projects", {"run_id": linked["run_id"]})
        assert not unlinked_result.is_error, _error_text(unlinked_result)
        unlinked = _payload(unlinked_result)

        assert _key_paths(linked, "tenant_key") == [], "link_projects leaks the account key"
        assert _key_paths(unlinked, "tenant_key") == [], "unlink_projects leaks the account key"
        assert primary_tenant_key not in json.dumps(linked)
        assert primary_tenant_key not in json.dumps(unlinked)

    async def test_link_reply_names_the_chain_controls(self, chain_mcp_client, db_session, primary_tenant_key):  # noqa: F811
        new_client, _switch = chain_mcp_client
        why = (await _link(new_client, db_session, primary_tenant_key))["next_action"]["why"]

        assert "Run Sequential" not in why
        assert "Stage chain" in why and "Implement chain" in why


class TestUnlinkRetiresTheConductor:
    async def test_unlink_leaves_no_waiting_conductor(self, chain_mcp_client, db_session, primary_tenant_key):  # noqa: F811
        new_client, _switch = chain_mcp_client
        linked = await _link(new_client, db_session, primary_tenant_key)
        _job, before = await _conductor(db_session, primary_tenant_key, linked["conductor_job_id"])
        assert before.status == "waiting"

        async with new_client() as session:
            result = await session.call_tool("unlink_projects", {"run_id": linked["run_id"]})
        assert not result.is_error, _error_text(result)

        job, execution = await _conductor(db_session, primary_tenant_key, linked["conductor_job_id"])
        assert execution.status in TERMINAL_EXECUTION_STATUSES, (
            f"the conductor of an unlinked chain is still {execution.status!r}"
        )
        assert job.status != "active", f"the conductor job of an unlinked chain is still {job.status!r}"

    async def test_a_finished_conductor_stays_as_it_is(self, chain_mcp_client, db_session, primary_tenant_key):  # noqa: F811
        new_client, _switch = chain_mcp_client
        linked = await _link(new_client, db_session, primary_tenant_key)
        job, execution = await _conductor(db_session, primary_tenant_key, linked["conductor_job_id"])
        execution.status = "complete"
        job.status = "completed"
        await db_session.commit()

        async with new_client() as session:
            result = await session.call_tool("unlink_projects", {"run_id": linked["run_id"]})
        assert not result.is_error, _error_text(result)

        job, execution = await _conductor(db_session, primary_tenant_key, linked["conductor_job_id"])
        assert execution.status == "complete"
        assert job.status == "completed"
