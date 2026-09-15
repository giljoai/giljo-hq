# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import json

import pytest
import pytest_asyncio

from giljo_mcp.tenant import TenantManager
from tests.helpers.mcp_session_fixture import create_connected_server_and_client_session


pytestmark = pytest.mark.asyncio


def _payload(call_tool_result) -> dict:
    if getattr(call_tool_result, "structuredContent", None):
        return call_tool_result.structured_content
    first_block = call_tool_result.content[0]
    text = getattr(first_block, "text", None)
    if text is None:
        raise AssertionError(f"unexpected content block: {first_block!r}")
    return json.loads(text)


def _error_text(call_tool_result) -> str:
    return "\n".join(t for t in (getattr(b, "text", None) for b in call_tool_result.content) if t)


@pytest_asyncio.fixture
async def staging_client(monkeypatch):
    from api import app_state
    from api.endpoints import mcp_sdk_server
    from giljo_mcp.tools.tool_accessor._project_tools import ProjectToolsMixin

    state = app_state.state
    prior_tool_accessor = state.tool_accessor
    prior_tenant_manager = state.tenant_manager

    if state.tenant_manager is None:
        state.tenant_manager = TenantManager()

    class _StubAccessor(ProjectToolsMixin):

        account_default = ""
        session_opened = False
        mission_writes: list = []

        async def update_project_mission(self, project_id: str, mission: str):
            type(self).mission_writes.append((project_id, mission))
            return {"status": "ok"}

        async def _resolve_stage_mode_default(self, tenant_key: str) -> str:
            return self.account_default

        def get_session_async(self):
            type(self).session_opened = True
            raise RuntimeError("no database in this test")

    accessor = _StubAccessor()
    state.tool_accessor = accessor

    tenant_key = TenantManager.generate_tenant_key()
    from api.endpoints.mcp_tools import _base

    monkeypatch.setattr(_base, "_resolve_tenant", lambda ctx: tenant_key)
    monkeypatch.setattr(_base, "_resolve_user_id", lambda ctx: None)

    async def _noop(*args, **kwargs):
        return None

    monkeypatch.setattr("giljo_mcp.services.silence_detector.auto_clear_silent", _noop)
    monkeypatch.setattr("giljo_mcp.services.heartbeat.touch_heartbeat", _noop)

    def _new_client():
        return create_connected_server_and_client_session(mcp_sdk_server.mcp)

    try:
        yield _new_client, accessor
    finally:
        state.tool_accessor = prior_tool_accessor
        state.tenant_manager = prior_tenant_manager


async def test_omitted_mode_refuses_on_the_success_path(staging_client):
    new_client, accessor = staging_client
    accessor.account_default = ""

    async with new_client() as session:
        result = await session.call_tool("stage_project", {"project_id": "p-1"})

    assert result.is_error is False, (
        "an omitted mode must come back as normal tool content carrying the remedy, not "
        f"as an isError the agent has to interpret: {_error_text(result)}"
    )

    payload = _payload(result)
    assert payload["success"] is False
    assert payload["error"] == "EXECUTION_MODE_REQUIRED"
    assert {m["mode"] for m in payload["modes"]} == {"multi_terminal", "subagent"}


async def test_the_tool_is_callable_without_mode_at_all(staging_client):
    new_client, accessor = staging_client
    accessor.account_default = ""

    async with new_client() as session:
        result = await session.call_tool("stage_project", {"project_id": "p-1"})

    assert "validation error" not in _error_text(result).lower()
    assert _payload(result)["error"] == "EXECUTION_MODE_REQUIRED"


async def test_an_account_default_answers_the_question_instead_of_refusing(staging_client):
    new_client, accessor = staging_client
    accessor.account_default = "subagent"
    type(accessor).session_opened = False

    async with new_client() as session:
        result = await session.call_tool("stage_project", {"project_id": "p-1"})

    assert "EXECUTION_MODE_REQUIRED" not in _error_text(result), (
        "an account that set a default was still asked: " + _error_text(result)
    )
    assert accessor.session_opened is True, (
        "staging never reached its transaction, so the account default was not applied -- "
        "it either refused anyway or bailed out earlier."
    )


async def test_the_refusal_short_circuits_before_the_staging_transaction(staging_client):
    new_client, accessor = staging_client
    accessor.account_default = ""
    type(accessor).session_opened = False

    async with new_client() as session:
        result = await session.call_tool("stage_project", {"project_id": "p-1"})

    assert _payload(result)["error"] == "EXECUTION_MODE_REQUIRED"
    assert accessor.session_opened is False, (
        "stage_project opened a database session after an omitted mode -- the refusal "
        "must short-circuit before the staging transaction."
    )


async def test_a_reverse_gear_action_is_never_asked_for_a_mode(staging_client):
    new_client, accessor = staging_client
    accessor.account_default = ""

    called: dict = {}

    async def _reverse(project_id: str, action: str):
        called["action"] = action
        return {"status": action}

    accessor._stage_project_reverse_gear = _reverse

    async with new_client() as session:
        result = await session.call_tool("stage_project", {"project_id": "p-1", "action": "unstage"})

    assert result.is_error is False, _error_text(result)
    assert called["action"] == "unstage"
    assert _payload(result)["status"] == "unstage"


async def test_a_mission_passed_at_staging_goes_through_the_single_writer(staging_client):
    new_client, accessor = staging_client
    accessor.account_default = "subagent"
    type(accessor).session_opened = False
    type(accessor).mission_writes = []

    async with new_client() as session:
        await session.call_tool(
            "stage_project",
            {"project_id": "p-1", "mode": "subagent", "mission": "Ship the thing."},
        )

    assert accessor.mission_writes == [("p-1", "Ship the thing.")]


async def test_the_mission_is_written_before_staging_generates_the_prompt(staging_client):
    new_client, accessor = staging_client
    accessor.account_default = "subagent"
    type(accessor).session_opened = False
    type(accessor).mission_writes = []

    async with new_client() as session:
        await session.call_tool(
            "stage_project",
            {"project_id": "p-1", "mode": "subagent", "mission": "Ship the thing."},
        )

    assert accessor.mission_writes, "the mission was never written"
    assert accessor.session_opened is True, "staging never ran, so the ordering is untested"


async def test_omitting_the_mission_touches_nothing(staging_client):
    new_client, accessor = staging_client
    accessor.account_default = "subagent"
    type(accessor).mission_writes = []

    async with new_client() as session:
        await session.call_tool("stage_project", {"project_id": "p-1", "mode": "subagent"})

    assert accessor.mission_writes == []
