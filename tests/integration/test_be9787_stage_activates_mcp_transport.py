# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import delete, select

from giljo_mcp.exceptions import ProjectStateError
from giljo_mcp.models.agent_identity import AgentExecution, AgentJob
from giljo_mcp.models.products import Product
from giljo_mcp.models.projects import Project
from giljo_mcp.tenant import TenantManager
from tests.helpers.mcp_session_fixture import create_connected_server_and_client_session
from tests.helpers.taxonomy_seeds import next_series_number


pytestmark = pytest.mark.asyncio


def _error_text(call_tool_result) -> str:
    return "\n".join(t for t in (getattr(b, "text", None) for b in call_tool_result.content) if t)


def _payload(call_tool_result) -> dict:
    first_block = call_tool_result.content[0]
    text = getattr(first_block, "text", None)
    if text is None:
        raise AssertionError(f"unexpected content block: {first_block!r}")
    return json.loads(text)


@pytest_asyncio.fixture
async def be9787_client(db_manager, monkeypatch):
    from api import app_state
    from api.endpoints import mcp_sdk_server
    from api.endpoints.mcp_tools import _base
    from giljo_mcp.tools.tool_accessor import ToolAccessor

    state = app_state.state
    prior_tool_accessor = state.tool_accessor
    prior_tenant_manager = state.tenant_manager
    prior_db_manager = state.db_manager

    if state.tenant_manager is None:
        state.tenant_manager = TenantManager()
    state.db_manager = db_manager

    tenant_key = TenantManager.generate_tenant_key()
    ws_spy = AsyncMock()
    state.tool_accessor = ToolAccessor(
        db_manager=db_manager, tenant_manager=state.tenant_manager, websocket_manager=ws_spy
    )

    monkeypatch.setattr(_base, "_resolve_tenant", lambda ctx: tenant_key)
    monkeypatch.setattr(_base, "_resolve_user_id", lambda ctx: None)

    def _client():
        return create_connected_server_and_client_session(mcp_sdk_server.mcp)

    try:
        yield _client, tenant_key, ws_spy, state.tool_accessor
    finally:
        state.tool_accessor = prior_tool_accessor
        state.tenant_manager = prior_tenant_manager
        state.db_manager = prior_db_manager


async def _seed(db_manager, tenant_key: str, *, status: str, mission: str = "a staging mission") -> str:
    project_id = str(uuid4())
    product_id = str(uuid4())
    async with db_manager.get_session_async(tenant_key=tenant_key) as session:
        session.add(
            Product(
                id=product_id,
                name=f"BE9787 Product {uuid4().hex[:6]}",
                description="BE-9787 stage-activates test",
                tenant_key=tenant_key,
                is_active=True,
                product_memory={},
            )
        )
        session.add(
            Project(
                id=project_id,
                tenant_key=tenant_key,
                product_id=product_id,
                name="BE-9787 project",
                description="BE-9787 stage-activates test project",
                mission=mission,
                status=status,
                series_number=next_series_number(),
            )
        )
        await session.commit()
    return project_id


async def _load(db_manager, tenant_key: str, project_id: str) -> Project:
    async with db_manager.get_session_async(tenant_key=tenant_key) as verify:
        return (await verify.execute(select(Project).where(Project.id == project_id))).scalar_one()


async def _orchestrator_job_count(db_manager, tenant_key: str, project_id: str) -> int:
    async with db_manager.get_session_async(tenant_key=tenant_key) as verify:
        rows = (await verify.execute(select(AgentJob).where(AgentJob.project_id == project_id))).scalars().all()
    return len(rows)


async def _cleanup(db_manager, tenant_key: str) -> None:
    async with db_manager.get_session_async(tenant_key=tenant_key) as session:
        await session.execute(delete(AgentExecution).where(AgentExecution.tenant_key == tenant_key))
        await session.execute(delete(AgentJob).where(AgentJob.tenant_key == tenant_key))
        await session.execute(delete(Project).where(Project.tenant_key == tenant_key))
        await session.execute(delete(Product).where(Product.tenant_key == tenant_key))
        await session.commit()


def _status_changed_to_active(ws_spy: AsyncMock, project_id: str) -> list:
    return [
        call
        for call in ws_spy.broadcast_project_update.await_args_list
        if call.kwargs.get("project_id") == project_id
        and call.kwargs.get("update_type") == "status_changed"
        and call.kwargs["project_data"].get("status") == "active"
    ]


class TestStageProjectActivatesAnInactiveProject:
    async def test_mcp_door_leaves_the_project_active_and_staged(self, be9787_client, db_manager):
        client, tenant_key, _ws_spy, _accessor = be9787_client
        project_id = await _seed(db_manager, tenant_key, status="inactive")
        try:
            async with client() as session:
                result = await session.call_tool("stage_project", {"project_id": project_id, "mode": "subagent"})
            assert not result.is_error, f"staging must work: {_error_text(result)}"

            project = await _load(db_manager, tenant_key, project_id)
            assert project.staging_status == "staged"
            assert project.status == "active"
        finally:
            await _cleanup(db_manager, tenant_key)

    async def test_the_jobs_board_query_lists_the_staged_project(self, be9787_client, db_manager):
        client, tenant_key, _ws_spy, _accessor = be9787_client
        project_id = await _seed(db_manager, tenant_key, status="inactive")
        try:
            async with client() as session:
                staged = await session.call_tool("stage_project", {"project_id": project_id, "mode": "subagent"})
                assert not staged.is_error, _error_text(staged)
                listed = await session.call_tool("list_projects", {"status": "active"})
            assert not listed.is_error, _error_text(listed)
            assert project_id in _error_text(listed), "the active-projects list must include the staged project"
        finally:
            await _cleanup(db_manager, tenant_key)

    async def test_an_open_board_is_told_the_project_became_active(self, be9787_client, db_manager):
        client, tenant_key, ws_spy, _accessor = be9787_client
        project_id = await _seed(db_manager, tenant_key, status="inactive")
        try:
            async with client() as session:
                result = await session.call_tool("stage_project", {"project_id": project_id, "mode": "subagent"})
            assert not result.is_error, _error_text(result)
            assert len(_status_changed_to_active(ws_spy, project_id)) == 1
        finally:
            await _cleanup(db_manager, tenant_key)

    async def test_an_already_active_project_is_staged_without_a_second_activation(self, be9787_client, db_manager):
        client, tenant_key, ws_spy, _accessor = be9787_client
        project_id = await _seed(db_manager, tenant_key, status="active")
        try:
            async with client() as session:
                result = await session.call_tool("stage_project", {"project_id": project_id, "mode": "subagent"})
            assert not result.is_error, _error_text(result)

            project = await _load(db_manager, tenant_key, project_id)
            assert project.status == "active"
            assert project.staging_status == "staged"
            assert _status_changed_to_active(ws_spy, project_id) == []
        finally:
            await _cleanup(db_manager, tenant_key)


class TestStageProjectRefusesAProjectActivationRefuses:
    @pytest.mark.parametrize("status", ["completed", "cancelled", "terminated", "parked"])
    async def test_a_non_activatable_project_is_refused_and_nothing_changes(self, be9787_client, db_manager, status):
        client, tenant_key, ws_spy, _accessor = be9787_client
        project_id = await _seed(db_manager, tenant_key, status=status, mission="original mission")
        try:
            async with client() as session:
                result = await session.call_tool("stage_project", {"project_id": project_id, "mode": "subagent"})
            assert result.is_error, "staging a project that cannot be activated must be refused"
            assert status in _error_text(result)

            project = await _load(db_manager, tenant_key, project_id)
            assert project.status == status
            assert project.staging_status is None
            assert await _orchestrator_job_count(db_manager, tenant_key, project_id) == 0
            assert _status_changed_to_active(ws_spy, project_id) == []
        finally:
            await _cleanup(db_manager, tenant_key)

    async def test_a_refused_stage_does_not_write_the_mission_it_was_given(self, be9787_client, db_manager):
        client, tenant_key, _ws_spy, _accessor = be9787_client
        project_id = await _seed(db_manager, tenant_key, status="parked", mission="original mission")
        try:
            async with client() as session:
                result = await session.call_tool(
                    "stage_project", {"project_id": project_id, "mode": "subagent", "mission": "a new mission"}
                )
            assert result.is_error
            assert (await _load(db_manager, tenant_key, project_id)).mission == "original mission"
        finally:
            await _cleanup(db_manager, tenant_key)

    async def test_a_refused_mode_leaves_an_inactive_project_inactive(self, be9787_client, db_manager):
        client, tenant_key, _ws_spy, _accessor = be9787_client
        project_id = await _seed(db_manager, tenant_key, status="inactive")
        try:
            async with client() as session:
                result = await session.call_tool("stage_project", {"project_id": project_id, "mode": "not-a-mode"})
            assert result.is_error
            project = await _load(db_manager, tenant_key, project_id)
            assert project.status == "inactive"
            assert project.staging_status is None
        finally:
            await _cleanup(db_manager, tenant_key)


class TestTheRestDoorEndsInTheSameState:
    async def _rest_stage(self, db_manager, accessor, tenant_key: str, project_id: str):
        from api.endpoints import prompts

        current_user = MagicMock()
        current_user.id = uuid4()
        current_user.tenant_key = tenant_key
        current_user.username = "be9787-user"
        ws_dep = MagicMock()
        ws_dep.is_available.return_value = False
        token = TenantManager.set_current_tenant(tenant_key)
        try:
            async with db_manager.get_session_async(tenant_key=tenant_key) as db:
                return await prompts.generate_staging_prompt(
                    project_id=project_id,
                    tool="claude-code",
                    execution_mode="multi_terminal",
                    current_user=current_user,
                    db=db,
                    ws_dep=ws_dep,
                    project_service=accessor._project_service,
                )
        finally:
            TenantManager.clear_current_tenant()
            del token

    async def test_rest_staging_an_inactive_project_leaves_it_active_and_staged(self, be9787_client, db_manager):
        _client, tenant_key, ws_spy, accessor = be9787_client
        project_id = await _seed(db_manager, tenant_key, status="inactive")
        try:
            await self._rest_stage(db_manager, accessor, tenant_key, project_id)

            project = await _load(db_manager, tenant_key, project_id)
            assert project.staging_status == "staged"
            assert project.status == "active"
            assert len(_status_changed_to_active(ws_spy, project_id)) == 1
        finally:
            await _cleanup(db_manager, tenant_key)

    async def test_rest_staging_a_completed_project_is_refused_before_anything_is_created(
        self, be9787_client, db_manager
    ):
        _client, tenant_key, _ws_spy, accessor = be9787_client
        project_id = await _seed(db_manager, tenant_key, status="completed")
        try:
            with pytest.raises(ProjectStateError):
                await self._rest_stage(db_manager, accessor, tenant_key, project_id)

            project = await _load(db_manager, tenant_key, project_id)
            assert project.status == "completed"
            assert project.staging_status is None
            assert await _orchestrator_job_count(db_manager, tenant_key, project_id) == 0
        finally:
            await _cleanup(db_manager, tenant_key)


class TestTheActivationFixtureIsServedTheProjectPlan:

    async def test_a_freshly_activated_fixture_mission_is_the_staging_seed(self, be9787_client, db_manager):
        from giljo_mcp.models.agent_identity import is_orchestrator_placeholder_mission

        _client, tenant_key, _ws_spy, accessor = be9787_client
        project_id = await _seed(db_manager, tenant_key, status="inactive")
        try:
            TenantManager.set_current_tenant(tenant_key)
            await accessor._project_service.activate_project(project_id, tenant_key=tenant_key)
            async with db_manager.get_session_async(tenant_key=tenant_key) as verify:
                jobs = (await verify.execute(select(AgentJob).where(AgentJob.project_id == project_id))).scalars().all()
            assert len(jobs) == 1
            assert is_orchestrator_placeholder_mission(jobs[0].mission), jobs[0].mission
        finally:
            TenantManager.clear_current_tenant()
            await _cleanup(db_manager, tenant_key)

    async def test_a_fixture_seeded_before_this_fix_still_reads_as_the_staging_seed(self):
        from giljo_mcp.models.agent_identity import is_orchestrator_placeholder_mission

        assert is_orchestrator_placeholder_mission("Orchestrator for project: Old Play Project")
        assert not is_orchestrator_placeholder_mission("Orchestrator for project: X\nreal plan on a second line")
        assert not is_orchestrator_placeholder_mission("Build the loader.")
