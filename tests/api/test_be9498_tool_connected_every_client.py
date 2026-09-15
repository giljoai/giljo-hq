# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from tests.api.test_mcp_session import (  # noqa: E402
    _drive_middleware_with_body,
    _jsonrpc_body,
    _seed_api_key,
)


class _Probe:

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
    return [
        call.kwargs["event"]
        for call in ws_manager.broadcast_event_to_tenant.await_args_list
        if call.kwargs.get("event", {}).get("type") == "setup:tool_connected"
    ]


@pytest.fixture
def ws_manager(monkeypatch):
    from api.app_state import state

    manager = AsyncMock()
    monkeypatch.setattr(state, "websocket_manager", manager, raising=False)
    return manager


@pytest.mark.asyncio
async def test_second_client_initialize_still_announces(db_manager, ws_manager, monkeypatch):
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
