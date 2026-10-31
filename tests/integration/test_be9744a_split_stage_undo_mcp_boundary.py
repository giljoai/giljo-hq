# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import delete, select, update

from giljo_mcp.models.agent_identity import AgentExecution, AgentJob
from giljo_mcp.models.products import Product
from giljo_mcp.models.projects import Project
from giljo_mcp.tenant import TenantManager
from tests.helpers.mcp_session_fixture import create_connected_server_and_client_session
from tests.helpers.taxonomy_seeds import next_series_number


pytestmark = pytest.mark.asyncio

RETIRED_TOOLS = ("restage_project", "cancel_project_staging")


def _error_text(call_tool_result) -> str:
    return "\n".join(t for t in (getattr(b, "text", None) for b in call_tool_result.content) if t)


def _payload(call_tool_result) -> dict:
    first_block = call_tool_result.content[0]
    text = getattr(first_block, "text", None)
    if text is None:
        raise AssertionError(f"unexpected content block: {first_block!r}")
    return json.loads(text)


@pytest_asyncio.fixture
async def be9744a_client(db_manager, monkeypatch):
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
        yield _client, tenant_key, ws_spy
    finally:
        state.tool_accessor = prior_tool_accessor
        state.tenant_manager = prior_tenant_manager
        state.db_manager = prior_db_manager


async def _seed(db_manager, tenant_key: str, *, status: str = "inactive", **project_kwargs) -> str:
    project_id = str(uuid4())
    product_id = str(uuid4())
    async with db_manager.get_session_async(tenant_key=tenant_key) as session:
        session.add(
            Product(
                id=product_id,
                name=f"BE9744a Product {uuid4().hex[:6]}",
                description="BE-9744a split-undo boundary test",
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
                name="BE-9744a project",
                description="BE-9744a split-undo boundary test project",
                mission=project_kwargs.pop("mission", "a staging mission"),
                status=status,
                series_number=next_series_number(),
                **project_kwargs,
            )
        )
        await session.commit()
    return project_id


async def _load(db_manager, tenant_key: str, project_id: str) -> Project:
    async with db_manager.get_session_async(tenant_key=tenant_key) as verify:
        return (await verify.execute(select(Project).where(Project.id == project_id))).scalar_one()


async def _job_count(db_manager, tenant_key: str, project_id: str) -> int:
    async with db_manager.get_session_async(tenant_key=tenant_key) as verify:
        rows = (await verify.execute(select(AgentJob).where(AgentJob.project_id == project_id))).scalars().all()
    return len(rows)


async def _cleanup(db_manager, *tenant_keys: str) -> None:
    for tenant_key in tenant_keys:
        async with db_manager.get_session_async(tenant_key=tenant_key) as session:
            await session.execute(delete(AgentExecution).where(AgentExecution.tenant_key == tenant_key))
            await session.execute(delete(AgentJob).where(AgentJob.tenant_key == tenant_key))
            await session.execute(delete(Project).where(Project.tenant_key == tenant_key))
            await session.execute(delete(Product).where(Product.tenant_key == tenant_key))
            await session.commit()


async def _stage_for_real(client, project_id: str) -> None:
    async with client() as session:
        result = await session.call_tool("stage_project", {"project_id": project_id, "mode": "subagent"})
    assert not result.is_error, f"staging must work: {result.content!r}"


async def _force_staging_status(db_manager, tenant_key: str, project_id: str, staging_status: str, **columns) -> None:
    async with db_manager.get_session_async(tenant_key=tenant_key) as session:
        await session.execute(
            update(Project).where(Project.id == project_id).values(staging_status=staging_status, **columns)
        )
        await session.commit()


async def _orchestrator_statuses(db_manager, tenant_key: str, project_id: str) -> list[str]:
    async with db_manager.get_session_async(tenant_key=tenant_key) as verify:
        rows = (
            (
                await verify.execute(
                    select(AgentExecution.status)
                    .join(AgentJob, AgentExecution.job_id == AgentJob.job_id)
                    .where(AgentJob.project_id == project_id, AgentJob.tenant_key == tenant_key)
                    .order_by(AgentExecution.started_at.nulls_last(), AgentExecution.id)
                )
            )
            .scalars()
            .all()
        )
    return sorted(rows)


class TestUnstageUndoesStagingFromEveryPreLaunchState:

    async def test_unstage_from_staged_keeps_the_orchestrator_and_blanks_the_mission(self, be9744a_client, db_manager):
        client, tenant_key, _ws = be9744a_client
        project_id = await _seed(db_manager, tenant_key, mission="")
        try:
            await _stage_for_real(client, project_id)
            before = await _orchestrator_statuses(db_manager, tenant_key, project_id)
            assert (await _load(db_manager, tenant_key, project_id)).staging_status == "staged"

            async with client() as session:
                result = await session.call_tool("unstage_project", {"project_id": project_id})
            assert not result.is_error, f"unstage must succeed: {result.content!r}"
            assert _payload(result)["project_id"] == project_id

            project = await _load(db_manager, tenant_key, project_id)
            assert project.staging_status is None
            assert project.mission == ""
            assert project.implementation_launched_at is None
            assert await _orchestrator_statuses(db_manager, tenant_key, project_id) == before
        finally:
            await _cleanup(db_manager, tenant_key)

    @pytest.mark.parametrize("staging_status", ["staging", "staging_complete"])
    async def test_unstage_from_staging_states_restages_with_a_fresh_orchestrator(
        self, be9744a_client, db_manager, staging_status
    ):
        client, tenant_key, _ws = be9744a_client
        project_id = await _seed(db_manager, tenant_key, mission="")
        try:
            await _stage_for_real(client, project_id)
            await _force_staging_status(
                db_manager, tenant_key, project_id, staging_status, mission="a mission the orchestrator wrote"
            )
            assert await _orchestrator_statuses(db_manager, tenant_key, project_id) == ["waiting"]

            async with client() as session:
                result = await session.call_tool("unstage_project", {"project_id": project_id})
            assert not result.is_error, f"unstage must succeed from {staging_status}: {result.content!r}"
            assert _payload(result)["project_id"] == project_id

            project = await _load(db_manager, tenant_key, project_id)
            assert project.staging_status is None
            assert project.mission == ""
            assert project.implementation_launched_at is None
            assert await _orchestrator_statuses(db_manager, tenant_key, project_id) == ["decommissioned", "waiting"]
        finally:
            await _cleanup(db_manager, tenant_key)

    async def test_staging_can_start_again_after_unstage(self, be9744a_client, db_manager):
        client, tenant_key, _ws = be9744a_client
        project_id = await _seed(db_manager, tenant_key, mission="")
        try:
            await _stage_for_real(client, project_id)
            await _force_staging_status(db_manager, tenant_key, project_id, "staging", mission="m")
            async with client() as session:
                assert not (await session.call_tool("unstage_project", {"project_id": project_id})).is_error
            await _stage_for_real(client, project_id)
            assert (await _load(db_manager, tenant_key, project_id)).staging_status == "staged"
        finally:
            await _cleanup(db_manager, tenant_key)


class TestUnstageRefusalsAreStructured:

    async def test_after_implementation_launched_is_refused_and_nothing_changes(self, be9744a_client, db_manager):
        client, tenant_key, _ws = be9744a_client
        launched_at = datetime.now(UTC)
        project_id = await _seed(
            db_manager,
            tenant_key,
            staging_status="staging_complete",
            implementation_launched_at=launched_at,
        )
        try:
            async with client() as session:
                result = await session.call_tool("unstage_project", {"project_id": project_id})
            assert not result.is_error, f"a refusal is Tier-2 content, not isError: {result.content!r}"
            payload = _payload(result)
            assert payload["success"] is False
            assert payload["error"] == "IMPLEMENTATION_ALREADY_STARTED"
            assert "implementation" in payload["message"].lower()
            assert "update_project" in payload["message"]

            project = await _load(db_manager, tenant_key, project_id)
            assert project.staging_status == "staging_complete"
            assert project.implementation_launched_at is not None
            assert project.mission == "a staging mission"
            assert await _job_count(db_manager, tenant_key, project_id) == 0
        finally:
            await _cleanup(db_manager, tenant_key)

    async def test_on_a_never_staged_project_is_refused_as_nothing_to_undo(self, be9744a_client, db_manager):
        client, tenant_key, _ws = be9744a_client
        project_id = await _seed(db_manager, tenant_key, mission="")
        try:
            async with client() as session:
                result = await session.call_tool("unstage_project", {"project_id": project_id})
            assert not result.is_error, f"a refusal is Tier-2 content, not isError: {result.content!r}"
            payload = _payload(result)
            assert payload["success"] is False
            assert payload["error"] == "NOTHING_TO_UNSTAGE"
            assert "not staged" in payload["message"].lower()

            project = await _load(db_manager, tenant_key, project_id)
            assert project.staging_status is None
            assert await _job_count(db_manager, tenant_key, project_id) == 0
        finally:
            await _cleanup(db_manager, tenant_key)

    @pytest.mark.parametrize("staging_status", ["staged", "staging", "staging_complete"])
    async def test_other_tenants_project_is_refused_and_untouched(self, be9744a_client, db_manager, staging_status):
        client, tenant_key, _ws = be9744a_client
        other_tenant = TenantManager.generate_tenant_key()
        foreign_id = await _seed(db_manager, other_tenant, staging_status=staging_status)
        try:
            async with client() as session:
                result = await session.call_tool("unstage_project", {"project_id": foreign_id})
            assert result.is_error, f"unstage must refuse another tenant's project: {result.content!r}"
            assert "not found" in _error_text(result).lower(), _error_text(result)

            project = await _load(db_manager, other_tenant, foreign_id)
            assert project.staging_status == staging_status
            assert project.mission == "a staging mission"
            assert await _job_count(db_manager, other_tenant, foreign_id) == 0
        finally:
            await _cleanup(db_manager, tenant_key, other_tenant)


class TestAbandoningIsUpdateProjectCancelled:

    _COMPARED = ("status", "staging_status", "mission", "implementation_launched_at", "cancellation_reason")

    async def test_matches_what_cancel_staging_leaves_behind(self, be9744a_client, db_manager):
        from api import app_state
        from giljo_mcp.tenant import set_current_tenant

        client, tenant_key, ws_spy = be9744a_client
        via_tool = await _seed(db_manager, tenant_key, staging_status="staging")
        via_writer = await _seed(db_manager, tenant_key, staging_status="staging")
        try:
            async with client() as session:
                result = await session.call_tool("update_project", {"project_id": via_tool, "status": "cancelled"})
            assert not result.is_error, f"cancel through update_project must work: {result.content!r}"
            tool_broadcasts = list(ws_spy.broadcast_project_update.await_args_list)
            ws_spy.reset_mock()

            set_current_tenant(tenant_key)
            lifecycle = app_state.state.tool_accessor._project_service.lifecycle
            await lifecycle.cancel_staging(via_writer, websocket_manager=ws_spy)

            a = await _load(db_manager, tenant_key, via_tool)
            b = await _load(db_manager, tenant_key, via_writer)
            assert a.status == b.status == "cancelled"
            for column in self._COMPARED:
                assert getattr(a, column) == getattr(b, column), column
            assert a.completed_at is not None and b.completed_at is not None

            assert any(
                call.kwargs["project_id"] == via_tool and call.kwargs["tenant_key"] == tenant_key
                for call in tool_broadcasts
            ), f"update_project(cancelled) must tell the dashboard: {tool_broadcasts!r}"
        finally:
            await _cleanup(db_manager, tenant_key)


class TestStageProjectPointsAtTheReplacements:

    @pytest.mark.parametrize(
        ("action", "replacement", "staging_status"),
        [
            ("unstage", "unstage_project", "staged"),
            ("restage", "unstage_project", "staging"),
            ("cancel_staging", "update_project with status='cancelled'", "staging"),
        ],
    )
    async def test_retired_action_gets_the_pointer_and_changes_nothing(
        self, be9744a_client, db_manager, action, replacement, staging_status
    ):
        client, tenant_key, _ws = be9744a_client
        project_id = await _seed(db_manager, tenant_key, staging_status=staging_status)
        try:
            async with client() as session:
                result = await session.call_tool("stage_project", {"project_id": project_id, "action": action})
            assert not result.is_error, f"a pointer is Tier-2 content, not isError: {result.content!r}"
            payload = _payload(result)
            assert payload["success"] is False
            assert payload["error"] == "VALIDATION_ERROR"
            assert payload["field"] == "action"
            assert replacement in payload["message"]

            project = await _load(db_manager, tenant_key, project_id)
            assert project.staging_status == staging_status
            assert project.status == "inactive"
            assert project.mission == "a staging mission"
            assert project.implementation_launched_at is None
            assert await _job_count(db_manager, tenant_key, project_id) == 0
        finally:
            await _cleanup(db_manager, tenant_key)

    async def test_unknown_action_value_names_both_replacements(self, be9744a_client, db_manager):
        client, tenant_key, _ws = be9744a_client
        project_id = await _seed(db_manager, tenant_key, staging_status="staged")
        try:
            async with client() as session:
                result = await session.call_tool("stage_project", {"project_id": project_id, "action": "purge"})
            assert not result.is_error
            payload = _payload(result)
            assert payload["error"] == "VALIDATION_ERROR"
            assert payload["field"] == "action"
            assert "unstage_project" in payload["message"]
            assert "update_project" in payload["message"]
            assert (await _load(db_manager, tenant_key, project_id)).staging_status == "staged"
        finally:
            await _cleanup(db_manager, tenant_key)

    @pytest.mark.parametrize("arguments", [{"action": "stage"}, {}])
    async def test_stage_with_or_without_action_still_stages(self, be9744a_client, db_manager, arguments):
        client, tenant_key, _ws = be9744a_client
        project_id = await _seed(db_manager, tenant_key, mission="")
        try:
            async with client() as session:
                result = await session.call_tool(
                    "stage_project", {"project_id": project_id, "mode": "subagent", **arguments}
                )
            assert not result.is_error, f"staging must still work: {result.content!r}"
            payload = _payload(result)
            assert payload.get("error") != "VALIDATION_ERROR", payload

            project = await _load(db_manager, tenant_key, project_id)
            assert project.staging_status == "staged"
            assert project.implementation_launched_at is None
        finally:
            await _cleanup(db_manager, tenant_key)


class TestAdvertisedSurface:
    async def test_stage_project_schema_no_longer_advertises_action(self):
        from api.endpoints.mcp_sdk_server import mcp

        tool = mcp._tool_manager.get_tool("stage_project")
        assert set(tool.parameters["properties"]) == {"project_id", "mode", "mission"}

    async def test_unstage_project_has_explicit_hints_and_tight_schema(self):
        from api.endpoints.mcp_sdk_server import mcp

        tool = mcp._tool_manager.get_tool("unstage_project")
        assert tool is not None, "unstage_project is not registered"
        assert set(tool.parameters["properties"]) == {"project_id"}
        assert tool.parameters["required"] == ["project_id"]
        assert tool.parameters["properties"]["project_id"]["maxLength"] == 64
        assert tool.annotations.read_only_hint is False
        assert tool.annotations.open_world_hint is False
        assert tool.annotations.destructive_hint is True

    @pytest.mark.parametrize("name", RETIRED_TOOLS)
    async def test_the_two_extra_undo_tools_are_gone(self, name):
        from api.endpoints.mcp_sdk_server import mcp

        assert mcp._tool_manager.get_tool(name) is None, f"{name} must not be registered"

    async def test_unstage_project_description_says_what_it_undoes_and_where_cancel_went(self):
        from api.endpoints.mcp_sdk_server import mcp

        description = mcp._tool_manager.get_tool("unstage_project").description
        assert "before implementation" in description
        assert "stage_project again" in description
        assert "update_project" in description
        assert "cancelled" in description


class TestRetiredArgumentHelper:

    async def test_accepted_value_and_absent_argument_dispatch(self):
        from api.endpoints.mcp_tools._retired_arguments import retired_argument_rejection

        assert retired_argument_rejection("stage_project", {"project_id": "p", "action": "stage"}) is None
        assert retired_argument_rejection("stage_project", {"project_id": "p"}) is None
        assert retired_argument_rejection("update_project", {"action": "unstage"}) is None

    async def test_known_value_names_exactly_its_replacement(self):
        from api.endpoints.mcp_tools._retired_arguments import retired_argument_rejection

        rejection = retired_argument_rejection("stage_project", {"action": "restage"})
        assert rejection["error"] == "VALIDATION_ERROR"
        assert rejection["field"] == "action"
        assert rejection["constraint"] == "retired_argument"
        assert "unstage_project" in rejection["message"]
        assert "update_project" not in rejection["message"]

        cancel = retired_argument_rejection("stage_project", {"action": "cancel_staging"})
        assert "update_project" in cancel["message"]
        assert "cancelled" in cancel["message"]
        assert "unstage_project" not in cancel["message"]

    @pytest.mark.parametrize("value", ["purge", "", None, ["unstage"], {"a": 1}, 7])
    async def test_unrecognised_or_unhashable_value_names_all_replacements(self, value):
        from api.endpoints.mcp_tools._retired_arguments import retired_argument_rejection

        rejection = retired_argument_rejection("stage_project", {"action": value})
        assert rejection is not None
        assert "unstage_project" in rejection["message"]
        assert "update_project" in rejection["message"]
