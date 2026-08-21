# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""MCP-transport boundary regression test for BE-6003 error-contract fix.

CLAUDE.md mandates a regression test at the FAILING layer. The bug lived in the
FastMCP @mcp.tool wrapper `get_job_mission`: when called with a placeholder
job_id it RETURNED a {"error": "no_job_context"} dict (isError:false on the
wire) instead of raising, violating the post-0480 raise-everywhere contract.

A service-layer test is insufficient — the placeholder guard lives in the
@mcp.tool wrapper itself, not in any service. This drives the wrapper through
the in-memory MCP transport and asserts the missing-context case now surfaces
as isError:true (the FastMCP wrapper converts a raised ValidationError into an
error CallToolResult).

Pattern reference: tests/integration/test_complete_job_mcp_boundary.py.
"""

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
    """In-memory MCP client with tenant resolution stubbed.

    The placeholder-job_id branch raises before touching any service or the DB,
    so no shared-session rebinding is needed — only a resolvable tenant so the
    wrapper's pre-dispatch context setup does not itself error.
    """
    from api.endpoints import mcp_sdk_server
    from api.endpoints.mcp_tools import _base

    tenant_key = TenantManager.generate_tenant_key()
    # BE-6042d: _resolve_tenant/_resolve_user_id moved to mcp_tools._base (the
    # _call_tool call site reads them there). Patch _base, not mcp_sdk_server.
    monkeypatch.setattr(_base, "_resolve_tenant", lambda ctx: tenant_key)
    monkeypatch.setattr(_base, "_resolve_user_id", lambda ctx: None)

    def _new_client():
        return create_connected_server_and_client_session(mcp_sdk_server.mcp)

    return _new_client


@pytest.mark.parametrize("placeholder", ["unknown", "none", "null", "", "undefined", "placeholder"])
async def test_get_job_mission_no_context_raises_via_mcp(mission_mcp_client, placeholder):
    """BE-6003: placeholder job_id must surface as isError:true, not a dict result."""
    async with mission_mcp_client() as mcp_session:
        result = await mcp_session.call_tool("get_job_mission", {"job_id": placeholder})

    assert result.is_error is True, (
        f"BE-6003: placeholder job_id {placeholder!r} must raise (isError:true), not return a no_job_context dict"
    )
    # Old contract leaked this key in a success payload — it must not appear now.
    assert "no_job_context" not in _error_text(result)


async def test_get_job_mission_valid_job_id_not_blocked_by_guard(mission_mcp_client):
    """A real (non-placeholder) job_id passes the guard and is dispatched.

    It will error downstream (no such job in this empty test context), but the
    guard itself must not be what rejects it — proving the placeholder check is
    scoped to placeholders only.
    """
    async with mission_mcp_client() as mcp_session:
        result = await mcp_session.call_tool("get_job_mission", {"job_id": "real-looking-job-id-1234"})

    # Whatever the downstream outcome, it must not be the placeholder-guard message.
    assert "launched without orchestration context" not in _error_text(result)
