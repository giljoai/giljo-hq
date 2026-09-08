# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-9586d — a modern client announces itself with ``server/discover``, and we must hear it.

THE REGRESSION. The MCP spec grew a second way for a client to attach. A
2026-07-28 client opens with ``server/discover``; if the server answers it
completely -- ours does, ``resultType: "complete"`` -- the client has everything
it needs and **never sends ``initialize``**. We mint the ``mcp_sessions`` row only
on ``initialize``, so a modern client leaves no row: no harness recorded, no
per-tool connect status, no green dot. Tool calls continue to work without a
session row, so the gap is not user-visible as an error -- only as a missing
connection record.

NOT AUTH-SPECIFIC. The gate is ``method == "initialize"`` in BOTH auth branches, so
API-key and OAuth clients are affected identically.

THE clientInfo LIVES SOMEWHERE ELSE, and missing that would make this fix look like
it worked while recording nothing useful:

    initialize      -> params.clientInfo
    server/discover -> params._meta["io.modelcontextprotocol/clientInfo"]

Captured off the wire from Claude Code 2.1.245. Read only the first location and
every harness resolves to ``generic``: the dot lights up but the Connect page still
cannot say WHICH tool attached.

ONE ROW PER CLIENT, NOT PER CALL. BE-3011 and BE-9066 both exist because this table
grew unbounded once. A modern client may re-discover (our reply advertises
``ttlMs: 0``), so minting per discover would re-create exactly that. The row is
touch-or-insert per (tenant, user, client) -- which is also all
``connected_harnesses`` needs, since it groups by harness and takes the newest
timestamp.

Failing-layer discipline (CLAUDE.md): every case drives a real JSON-RPC frame through
``MCPAuthMiddleware`` -- the transport boundary where the branch skips.

Edition Scope: Both.
"""

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
    """The EXACT frame shape Claude Code 2.1.245 opens with.

    Captured off the wire rather than composed from the spec: the identity rides
    ``params._meta``, not ``params.clientInfo``, and a test that put it in the
    familiar place would pass against an implementation that never reads the real one.
    """
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
    """THE DEFECT: today this leaves nothing behind."""
    tenant_key, user_id = await _seed_oauth_user(db_manager)

    status, _headers, inner = await _drive(db_manager, tenant_key=tenant_key, user_id=user_id, body=_discover_body())

    assert status == 200, f"discover was rejected ({status}) — this test is about the row, not auth"
    assert inner.called is True
    assert len(await _rows(db_manager, tenant_key)) == 1


async def test_the_row_captures_clientinfo_from_the_meta_envelope(db_manager, jwt_env):  # noqa: F811
    """The trap: read ``params.clientInfo`` and this row exists but names nobody.

    ``connected_harnesses`` resolves the harness FROM ``session_data['client_info']``,
    so a row minted without it satisfies a count and still leaves the Connect page
    blank — the failure mode that looks fixed.
    """
    tenant_key, user_id = await _seed_oauth_user(db_manager)

    await _drive(db_manager, tenant_key=tenant_key, user_id=user_id, body=_discover_body())

    rows = await _rows(db_manager, tenant_key)
    assert len(rows) == 1
    captured = (rows[0].session_data or {}).get("client_info") or {}
    assert captured.get("name") == "claude-code", f"clientInfo not captured from _meta: {rows[0].session_data}"


async def test_the_connected_tool_is_reported_after_a_discover(db_manager, jwt_env):  # noqa: F811
    """The operator's surface: the dot and the Connect page read this, not the row count."""
    from giljo_mcp.repositories.auth_repository import AuthRepository

    tenant_key, user_id = await _seed_oauth_user(db_manager)

    await _drive(db_manager, tenant_key=tenant_key, user_id=user_id, body=_discover_body())

    async with db_manager.get_session_async(tenant_key=tenant_key) as s:
        with tenant_session_context(s, tenant_key):
            harnesses = await AuthRepository().connected_harnesses(s, tenant_key)
    assert "claude-code" in harnesses, f"discover left no durable harness: {harnesses}"


async def test_repeated_discover_does_not_duplicate_rows(db_manager, jwt_env):  # noqa: F811
    """ONE row per client, not per call — the BE-3011 / BE-9066 growth invariant.

    Our discover reply advertises ``ttlMs: 0``, so a client is entitled to re-ask as
    often as it likes. Minting per call would re-create the unbounded growth both of
    those projects removed. Three discovers, one row.
    """
    tenant_key, user_id = await _seed_oauth_user(db_manager)

    for _ in range(3):
        await _drive(db_manager, tenant_key=tenant_key, user_id=user_id, body=_discover_body())

    assert len(await _rows(db_manager, tenant_key)) == 1


async def test_a_second_different_client_gets_its_own_row(db_manager, jwt_env):  # noqa: F811
    """The negative control for the dedupe above.

    Without this, a fix that collapsed every discover onto one row per TENANT would
    pass the duplicate test while making the Connect page unable to show two tools —
    the multi-harness case the per-tool cards exist for.
    """
    tenant_key, user_id = await _seed_oauth_user(db_manager)

    await _drive(db_manager, tenant_key=tenant_key, user_id=user_id, body=_discover_body("claude-code"))
    await _drive(db_manager, tenant_key=tenant_key, user_id=user_id, body=_discover_body("opencode"))

    rows = await _rows(db_manager, tenant_key)
    names = sorted(((r.session_data or {}).get("client_info") or {}).get("name") for r in rows)
    assert names == ["claude-code", "opencode"], f"expected one row per client, got {names}"
