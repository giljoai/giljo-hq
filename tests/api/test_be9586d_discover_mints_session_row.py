# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import pytest
from sqlalchemy import select

from giljo_mcp.database import tenant_session_context
from giljo_mcp.models.auth import MCPSession
from tests.api.test_be9035d_harness_capture_and_stamp import _StateCapturingApp  # noqa: E402
from tests.api.test_be9586c_oauth_session_row import (  # noqa: E402
    _make_jwt,
    _seed_oauth_user,
    jwt_env,  # noqa: F401  (fixture re-export)
)
from tests.api.test_mcp_session import _drive_middleware_with_body  # noqa: E402


pytestmark = pytest.mark.asyncio

_CLIENT_INFO_META_KEY = "io.modelcontextprotocol/clientInfo"
_PROTOCOL_META_KEY = "io.modelcontextprotocol/protocolVersion"
_MODERN = "2026-07-28"


def _discover_body(client_name: str = "claude-code", version: str = "2.1.245") -> bytes:
    import json

    return json.dumps(
        {
            "jsonrpc": "2.0",
            "id": "server-discover-probe-1",
            "method": "server/discover",
            "params": {
                "_meta": {
                    _PROTOCOL_META_KEY: _MODERN,
                    _CLIENT_INFO_META_KEY: {
                        "name": client_name,
                        "title": "Claude Code",
                        "version": version,
                    },
                    "io.modelcontextprotocol/clientCapabilities": {"roots": {"listChanged": True}},
                }
            },
        }
    ).encode()


async def _drive(db_manager, *, tenant_key: str, user_id: str, body: bytes):
    from api.app_state import state
    from api.endpoints.mcp_sdk_server import MCPAuthMiddleware

    token = _make_jwt(tenant_key=tenant_key, sub=user_id)
    prior = state.db_manager
    state.db_manager = db_manager
    try:
        inner = _StateCapturingApp()
        status, headers, _b = await _drive_middleware_with_body(
            MCPAuthMiddleware(app=inner),
            headers=[
                (b"authorization", f"Bearer {token}".encode()),
                (b"content-type", b"application/json"),
                (b"mcp-protocol-version", _MODERN.encode()),
            ],
            body=body,
        )
        return status, headers, inner
    finally:
        state.db_manager = prior


async def _rows(db_manager, tenant_key: str) -> list[MCPSession]:
    async with db_manager.get_session_async(tenant_key=tenant_key) as s:
        with tenant_session_context(s, tenant_key):
            return list(
                (await s.execute(select(MCPSession).where(MCPSession.tenant_key == tenant_key))).scalars().all()
            )


async def test_a_discover_mints_a_session_row(db_manager, jwt_env):  # noqa: F811
    tenant_key, user_id = await _seed_oauth_user(db_manager)

    status, _headers, inner = await _drive(db_manager, tenant_key=tenant_key, user_id=user_id, body=_discover_body())

    assert status == 200, f"discover was rejected ({status}) — this test is about the row, not auth"
    assert inner.called is True
    assert len(await _rows(db_manager, tenant_key)) == 1


async def test_the_row_captures_clientinfo_from_the_meta_envelope(db_manager, jwt_env):  # noqa: F811
    tenant_key, user_id = await _seed_oauth_user(db_manager)

    await _drive(db_manager, tenant_key=tenant_key, user_id=user_id, body=_discover_body())

    rows = await _rows(db_manager, tenant_key)
    assert len(rows) == 1
    captured = (rows[0].session_data or {}).get("client_info") or {}
    assert captured.get("name") == "claude-code", f"clientInfo not captured from _meta: {rows[0].session_data}"


async def test_the_connected_tool_is_reported_after_a_discover(db_manager, jwt_env):  # noqa: F811
    from giljo_mcp.repositories.auth_repository import AuthRepository

    tenant_key, user_id = await _seed_oauth_user(db_manager)

    await _drive(db_manager, tenant_key=tenant_key, user_id=user_id, body=_discover_body())

    async with db_manager.get_session_async(tenant_key=tenant_key) as s:
        with tenant_session_context(s, tenant_key):
            harnesses = await AuthRepository().connected_harnesses(s, tenant_key)
    assert "claude-code" in harnesses, f"discover left no durable harness: {harnesses}"


async def test_repeated_discover_does_not_duplicate_rows(db_manager, jwt_env):  # noqa: F811
    tenant_key, user_id = await _seed_oauth_user(db_manager)

    for _ in range(3):
        await _drive(db_manager, tenant_key=tenant_key, user_id=user_id, body=_discover_body())

    assert len(await _rows(db_manager, tenant_key)) == 1


async def test_a_second_different_client_gets_its_own_row(db_manager, jwt_env):  # noqa: F811
    tenant_key, user_id = await _seed_oauth_user(db_manager)

    await _drive(db_manager, tenant_key=tenant_key, user_id=user_id, body=_discover_body("claude-code"))
    await _drive(db_manager, tenant_key=tenant_key, user_id=user_id, body=_discover_body("opencode"))

    rows = await _rows(db_manager, tenant_key)
    names = sorted(((r.session_data or {}).get("client_info") or {}).get("name") for r in rows)
    assert names == ["claude-code", "opencode"], f"expected one row per client, got {names}"
