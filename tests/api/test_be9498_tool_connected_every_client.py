# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-9498: ``setup:tool_connected`` must fire for EVERY client, not just the first.

Reported against a hosted deployment: OpenCode authenticated successfully
(``giljo_hq_health_check`` answered from its terminal) while the setup wizard's
Connect step sat on "Waiting for OpenCode to connect..." forever.

The emit used to be gated on a first-sight memo keyed
``f"{tenant_key}:{api_key_id or user_id}"``. ``api_key_id`` is assigned only on
the API-key branch, so every OAuth client collapsed onto ``tenant:user`` -- a key
carrying no client identity. The first client a user ever connected consumed the
announcement and every client after it was silenced. It now fires on the
JSON-RPC ``initialize`` handshake, which the protocol sends once per client
connection.

Failing-layer discipline (per CLAUDE.md): the defect lives in the ASGI auth
middleware, so these drive real JSON-RPC payloads through ``MCPAuthMiddleware``
-- the same boundary a real MCP client hits -- and assert on what the WebSocket
manager was actually handed.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from tests.api.test_mcp_session import (  # noqa: E402
    _drive_middleware_with_body,
    _jsonrpc_body,
    _seed_api_key,
)


class _Probe:
    """Minimal inner ASGI app: 200 with an empty JSON body."""

    async def __call__(self, scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": [(b"content-type", b"application/json")]})
        await send({"type": "http.response.body", "body": b"{}"})


def _initialize_body(client_name: str) -> bytes:
    return _jsonrpc_body(
        "initialize",
        params={
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": client_name, "version": "1.0.0"},
        },
    )


def _connect_events(ws_manager: AsyncMock) -> list[dict]:
    """Every setup:tool_connected event handed to the broadcaster."""
    return [
        call.kwargs["event"]
        for call in ws_manager.broadcast_event_to_tenant.await_args_list
        if call.kwargs.get("event", {}).get("type") == "setup:tool_connected"
    ]


@pytest.fixture
def ws_manager(monkeypatch):
    """Swap in a capturing websocket manager for the duration of a test."""
    from api.app_state import state

    manager = AsyncMock()
    monkeypatch.setattr(state, "websocket_manager", manager, raising=False)
    return manager


@pytest.mark.asyncio
async def test_second_client_initialize_still_announces(db_manager, ws_manager, monkeypatch):
    """THE REPORTED BUG: a user's SECOND tool must still be announced.

    Both clients authenticate as the same principal, which is exactly the case
    the old first-sight memo collapsed and silenced.
    """
    from api.app_state import state
    from api.endpoints.mcp_sdk_server import MCPAuthMiddleware

    raw_key, tenant_key = await _seed_api_key(db_manager)
    monkeypatch.setattr(state, "db_manager", db_manager, raising=False)

    middleware = MCPAuthMiddleware(app=_Probe())
    headers = [(b"x-api-key", raw_key.encode()), (b"content-type", b"application/json")]

    for client in ("claude_code", "opencode"):
        status, _headers, _body = await _drive_middleware_with_body(
            middleware, headers=headers, body=_initialize_body(client)
        )
        assert status == 200, f"{client} initialize returned {status}"

    events = _connect_events(ws_manager)
    assert len(events) == 2, f"expected an announcement per client, got {len(events)}"
    assert all(e["data"]["tenant_key"] == tenant_key for e in events)


@pytest.mark.asyncio
async def test_reconnecting_the_same_tool_announces_again(db_manager, ws_manager, monkeypatch):
    """Re-running the wizard with an already-connected tool must still flip it."""
    from api.app_state import state
    from api.endpoints.mcp_sdk_server import MCPAuthMiddleware

    raw_key, _tenant_key = await _seed_api_key(db_manager)
    monkeypatch.setattr(state, "db_manager", db_manager, raising=False)

    middleware = MCPAuthMiddleware(app=_Probe())
    headers = [(b"x-api-key", raw_key.encode()), (b"content-type", b"application/json")]

    for _ in range(3):
        await _drive_middleware_with_body(middleware, headers=headers, body=_initialize_body("opencode"))

    assert len(_connect_events(ws_manager)) == 3


@pytest.mark.asyncio
async def test_ordinary_traffic_does_not_announce(db_manager, ws_manager, monkeypatch):
    """Only the handshake announces -- a tools/call must not spam the wizard."""
    from api.app_state import state
    from api.endpoints.mcp_sdk_server import MCPAuthMiddleware

    raw_key, _tenant_key = await _seed_api_key(db_manager)
    monkeypatch.setattr(state, "db_manager", db_manager, raising=False)

    middleware = MCPAuthMiddleware(app=_Probe())
    headers = [(b"x-api-key", raw_key.encode()), (b"content-type", b"application/json")]

    for _ in range(5):
        await _drive_middleware_with_body(middleware, headers=headers, body=_jsonrpc_body("tools/list", params={}))

    assert _connect_events(ws_manager) == []


@pytest.mark.asyncio
async def test_announcement_names_the_resolved_harness(db_manager, ws_manager, monkeypatch):
    """FE-9500 INVERSION of BE-9498's "the event stays GENERIC by design".

    That contract said per-client attribution was out of scope and the frontend
    should flip whichever tool the user was walking. It shipped as a hardcoded
    ``tool_name="mcp_connected"``. The operator then hit the consequence on
    production: connecting ONE tool lit every tool card, including tools not
    installed on the machine, because nothing downstream could tell them apart.

    The capability was never missing -- ``harness_resolver.harness_from_client_info``
    already existed and this very test drives the middleware with a real clientInfo
    name. The event now carries the RESOLVED harness. The assertion is inverted
    rather than deleted so the old expectation stays on record as the thing that
    must not come back.
    """
    from api.app_state import state
    from api.endpoints.mcp_sdk_server import MCPAuthMiddleware

    raw_key, _tenant_key = await _seed_api_key(db_manager)
    monkeypatch.setattr(state, "db_manager", db_manager, raising=False)

    middleware = MCPAuthMiddleware(app=_Probe())
    headers = [(b"x-api-key", raw_key.encode()), (b"content-type", b"application/json")]

    await _drive_middleware_with_body(middleware, headers=headers, body=_initialize_body("opencode"))

    events = _connect_events(ws_manager)
    assert len(events) == 1
    assert events[0]["data"]["tool_name"] == "opencode", (
        "the announcement must name the harness that connected; 'mcp_connected' was "
        "the placeholder that made every tool card light up"
    )


@pytest.mark.asyncio
async def test_unidentified_client_announces_generic_rather_than_guessing(db_manager, ws_manager, monkeypatch):
    """A client that self-identifies with nothing must report ``generic``.

    FE-9500: 'generic' is a REAL connect, not an error -- the frontend renders it on
    the Generic MCP client card and, mid-wizard, falls back to the tool being walked.
    What it must never do is get attributed to a specific tool it did not come from.
    """
    from api.app_state import state
    from api.endpoints.mcp_sdk_server import MCPAuthMiddleware

    raw_key, _tenant_key = await _seed_api_key(db_manager)
    monkeypatch.setattr(state, "db_manager", db_manager, raising=False)

    middleware = MCPAuthMiddleware(app=_Probe())
    headers = [(b"x-api-key", raw_key.encode()), (b"content-type", b"application/json")]

    await _drive_middleware_with_body(middleware, headers=headers, body=_initialize_body("a-client-we-have-never-seen"))

    events = _connect_events(ws_manager)
    assert len(events) == 1
    assert events[0]["data"]["tool_name"] == "generic"
