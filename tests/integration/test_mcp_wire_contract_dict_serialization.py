# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import json

import pytest
import pytest_asyncio
from pydantic import BaseModel

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
    parts = []
    for block in call_tool_result.content:
        text = getattr(block, "text", None)
        if text:
            parts.append(text)
    return "\n".join(parts)


class _FakeMissionResponse(BaseModel):

    job_id: str
    status: str = "working"
    mission: str | None = None
    full_protocol: str | None = None


@pytest_asyncio.fixture
async def wire_contract_client(monkeypatch):
    from api import app_state
    from api.endpoints import mcp_sdk_server

    state = app_state.state
    prior_tool_accessor = state.tool_accessor
    prior_tenant_manager = state.tenant_manager

    if state.tenant_manager is None:
        state.tenant_manager = TenantManager()

    class _StubMissionService:
        async def get_agent_mission(
            self,
            job_id: str,
            tenant_key: str,
            protocol_etag: str | None = None,
            preset_name: str | None = None,
            detected_harness: str | None = None,
            section: str = "",
        ):
            return _FakeMissionResponse(
                job_id=job_id,
                status="working",
                mission="stub mission body",
                full_protocol="stub protocol body",
            )

    class _StubAccessor:
        def __init__(self) -> None:
            self._mission_service = _StubMissionService()

    state.tool_accessor = _StubAccessor()

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
        yield _new_client, tenant_key
    finally:
        state.tool_accessor = prior_tool_accessor
        state.tenant_manager = prior_tenant_manager


async def test_pydantic_response_is_serialised_to_dict_at_mcp_boundary(wire_contract_client):
    new_client, _tenant_key = wire_contract_client

    async with new_client() as session:
        result = await session.call_tool(
            "get_job_mission",
            {"job_id": "11111111-1111-1111-1111-111111111111"},
        )

    assert result.is_error is False, _error_text(result)

    payload = _payload(result)
    assert isinstance(payload, dict), f"expected dict, got {type(payload).__name__}: {payload!r}"
    assert payload["job_id"] == "11111111-1111-1111-1111-111111111111"
    assert payload["status"] == "working"
    assert payload["mission"] == "stub mission body"
    assert payload["full_protocol"] == "stub protocol body"


async def test_call_tool_helper_normalises_basemodel_to_dict():
    from unittest.mock import MagicMock

    from api import app_state
    from api.endpoints import mcp_sdk_server

    state = app_state.state
    prior_tool_accessor = state.tool_accessor
    prior_tenant_manager = state.tenant_manager

    if state.tenant_manager is None:
        state.tenant_manager = TenantManager()

    class _StubMissionService:
        async def get_agent_mission(
            self,
            job_id: str,
            tenant_key: str,
            protocol_etag: str | None = None,
            preset_name: str | None = None,
            detected_harness: str | None = None,
            section: str = "",
        ):
            return _FakeMissionResponse(job_id=job_id, mission="x")

    class _StubAccessor:
        def __init__(self) -> None:
            self._mission_service = _StubMissionService()

    state.tool_accessor = _StubAccessor()

    tenant_key = TenantManager.generate_tenant_key()
    ctx = MagicMock()
    ctx.request_context.request.scope = {"state": {"tenant_key": tenant_key}}

    try:
        result = await mcp_sdk_server._call_tool(
            ctx,
            "get_job_mission",
            {"job_id": "job-1"},
        )
    finally:
        state.tool_accessor = prior_tool_accessor
        state.tenant_manager = prior_tenant_manager

    assert isinstance(result, dict), f"_call_tool must return dict, got {type(result).__name__}"
    from api.endpoints.mcp_tools._base import _SKILLS_VERSION

    meta = result.pop("_meta", None)
    assert isinstance(meta, dict), f"_meta must be a dict, got {type(meta).__name__}"
    assert meta.get("skills_version") == _SKILLS_VERSION
    assert result == {
        "job_id": "job-1",
        "status": "working",
        "mission": "x",
        "full_protocol": None,
    }
