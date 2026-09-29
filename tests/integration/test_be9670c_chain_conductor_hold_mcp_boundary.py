# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
import pytest_asyncio
from sqlalchemy import select

from giljo_mcp.models.agent_identity import AgentExecution
from giljo_mcp.models.projects import Project
from giljo_mcp.tenant import TenantManager
from tests.helpers.mcp_session_fixture import create_connected_server_and_client_session
from tests.integration.test_be9500a_chain_headless_e2e import (
    _seed_product_context,
    _seed_project,
    _seed_staging_orchestrator,
)


pytestmark = pytest.mark.asyncio


def _payload(result) -> dict:
    if getattr(result, "structuredContent", None):
        return result.structured_content
    return json.loads(result.content[0].text)


@pytest_asyncio.fixture
async def tenant_key() -> str:
    return TenantManager.generate_tenant_key()


@pytest_asyncio.fixture
async def mcp_client(db_manager, db_session, tenant_key, monkeypatch):
    from api import app_state
    from api.endpoints import mcp_sdk_server
    from api.endpoints.mcp_tools import _base
    from giljo_mcp.tools.tool_accessor import ToolAccessor

    state = app_state.state
    prior = (state.tool_accessor, state.tenant_manager, state.db_manager)
    if state.tenant_manager is None:
        state.tenant_manager = TenantManager()
    state.db_manager = db_manager
    state.tool_accessor = ToolAccessor(
        db_manager=db_manager, tenant_manager=state.tenant_manager, test_session=db_session
    )
    monkeypatch.setattr(_base, "_resolve_tenant", lambda ctx: tenant_key)
    monkeypatch.setattr(_base, "_resolve_user_id", lambda ctx: "test-human-user")
    try:
        yield lambda: create_connected_server_and_client_session(mcp_sdk_server.mcp)
    finally:
        state.tool_accessor, state.tenant_manager, state.db_manager = prior


async def _staged_chain(mcp_client, db_session, tenant_key) -> dict:
    await _seed_product_context(db_session, tenant_key)
    p1 = await _seed_project(db_session, tenant_key)
    p2 = await _seed_project(db_session, tenant_key)
    await db_session.commit()
    async with mcp_client() as session:
        result = await session.call_tool("link_projects", {"project_ids": [p1, p2], "execution_mode": "subagent"})
        assert result.is_error is False
        started = _payload(result)
    conductor_job_id = (
        await db_session.execute(
            select(AgentExecution.job_id).where(
                AgentExecution.agent_id == started["conductor_agent_id"], AgentExecution.tenant_key == tenant_key
            )
        )
    ).scalar_one()
    return {"p1": p1, "p2": p2, "run_id": started["run_id"], "conductor_job_id": str(conductor_job_id)}


async def _conductor_mission(mcp_client, job_id: str) -> dict:
    async with mcp_client() as session:
        result = await session.call_tool("get_job_mission", {"job_id": job_id})
        assert result.is_error is False
        return _payload(result)


async def _head_stamp(db_session, tenant_key, project_id):
    db_session.expire_all()
    row = (
        await db_session.execute(select(Project).where(Project.id == project_id, Project.tenant_key == tenant_key))
    ).scalar_one()
    return row.implementation_launched_at


async def test_conductor_mission_refused_until_the_press(mcp_client, db_session, tenant_key):
    chain = await _staged_chain(mcp_client, db_session, tenant_key)

    blocked = await _conductor_mission(mcp_client, chain["conductor_job_id"])
    assert blocked["blocked"] is True
    assert blocked["error"] == "BLOCKED: Implementation phase not launched"
    assert blocked["mission"] is None
    assert blocked["full_protocol"] is None
    assert "Implement" in blocked["user_instruction"]

    async with mcp_client() as session:
        pressed = await session.call_tool("launch_implementation", {"project_id": chain["p1"]})
        assert pressed.is_error is False
        assert _payload(pressed)["success"] is True

    released = await _conductor_mission(mcp_client, chain["conductor_job_id"])
    assert not released.get("blocked"), released.get("error")
    assert released["full_protocol"]


async def test_member_two_needs_no_press(mcp_client, db_session, tenant_key):
    chain = await _staged_chain(mcp_client, db_session, tenant_key)
    async with mcp_client() as session:
        assert (await session.call_tool("launch_implementation", {"project_id": chain["p1"]})).is_error is False

    member2 = await _seed_staging_orchestrator(db_session, tenant_key, chain["p2"])
    await db_session.commit()
    mission = await _conductor_mission(mcp_client, member2.job_id)
    assert not mission.get("blocked"), mission.get("error")
    assert await _head_stamp(db_session, tenant_key, chain["p2"]) is None


async def test_replay_prompt_never_stamps(mcp_client, db_session, tenant_key):
    from api.endpoints.prompts import get_chain_member_prompt

    chain = await _staged_chain(mcp_client, db_session, tenant_key)
    member1 = await _seed_staging_orchestrator(db_session, tenant_key, chain["p1"])
    await db_session.commit()

    user = SimpleNamespace(tenant_key=tenant_key, username="replayer")
    replay = await get_chain_member_prompt(project_id=chain["p1"], fallback=True, current_user=user, db=db_session)
    assert replay.orchestrator_job_id == member1.job_id

    assert await _head_stamp(db_session, tenant_key, chain["p1"]) is None
    still_held = await _conductor_mission(mcp_client, chain["conductor_job_id"])
    assert still_held["blocked"] is True
