# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import pytest
import pytest_asyncio

from giljo_mcp.tenant import TenantManager
from tests.helpers.mcp_session_fixture import create_connected_server_and_client_session


pytestmark = pytest.mark.asyncio


def _error_text(call_tool_result) -> str:
    parts = []
    for block in call_tool_result.content:
        text = getattr(block, "text", None)
        if text:
            parts.append(text)
    return "\n".join(parts)


@pytest_asyncio.fixture
async def mission_mcp_client(monkeypatch):
    from api.endpoints import mcp_sdk_server
    from api.endpoints.mcp_tools import _base

    tenant_key = TenantManager.generate_tenant_key()
    monkeypatch.setattr(_base, "_resolve_tenant", lambda ctx: tenant_key)
    monkeypatch.setattr(_base, "_resolve_user_id", lambda ctx: None)

    def _new_client():
        return create_connected_server_and_client_session(mcp_sdk_server.mcp)

    return _new_client


@pytest.mark.parametrize("placeholder", ["unknown", "none", "null", "", "undefined", "placeholder"])
async def test_get_job_mission_no_context_raises_via_mcp(mission_mcp_client, placeholder):
    async with mission_mcp_client() as mcp_session:
        result = await mcp_session.call_tool("get_job_mission", {"job_id": placeholder})

    assert result.is_error is True, (
        f"BE-6003: placeholder job_id {placeholder!r} must raise (isError:true), not return a no_job_context dict"
    )
    assert "no_job_context" not in _error_text(result)


async def test_get_job_mission_valid_job_id_not_blocked_by_guard(mission_mcp_client):
    async with mission_mcp_client() as mcp_session:
        result = await mcp_session.call_tool("get_job_mission", {"job_id": "real-looking-job-id-1234"})

    assert "launched without orchestration context" not in _error_text(result)
