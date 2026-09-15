# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import json

import pytest

from tests.api.test_be9498_tool_connected_every_client import (  # noqa: E402
    _connect_events,
    _initialize_body,
    _Probe,
    ws_manager,  # noqa: F401  (fixture re-export)
)
from tests.api.test_mcp_session import (  # noqa: E402
    _drive_middleware_with_body,
    _jsonrpc_body,
    _seed_api_key,
)


pytestmark = pytest.mark.asyncio

_CLIENT_INFO_META_KEY = "io.modelcontextprotocol/clientInfo"
_PROTOCOL_META_KEY = "io.modelcontextprotocol/protocolVersion"
_MODERN = "2026-07-28"


def _discover_body(client_name: str, version: str = "2.1.245") -> bytes:
    return json.dumps(
        {
            "jsonrpc": "2.0",
            "id": "server-discover-probe-1",
            "method": "server/discover",
            "params": {
                "_meta": {
                    _PROTOCOL_META_KEY: _MODERN,
                    _CLIENT_INFO_META_KEY: {"name": client_name, "version": version},
                }
            },
        }
    ).encode()


async def _drive(db_manager, raw_key: str, body: bytes, middleware=None):
    from api.endpoints.mcp_sdk_server import MCPAuthMiddleware

    mw = middleware or MCPAuthMiddleware(app=_Probe())
    await _drive_middleware_with_body(
        mw,
        headers=[
            (b"x-api-key", raw_key.encode()),
            (b"content-type", b"application/json"),
            (b"mcp-protocol-version", _MODERN.encode()),
        ],
        body=body,
    )
    return mw


async def test_a_discover_announces_live(db_manager, ws_manager, monkeypatch):  # noqa: F811
    from api.app_state import state

    raw_key, _tenant = await _seed_api_key(db_manager)
    monkeypatch.setattr(state, "db_manager", db_manager, raising=False)

    await _drive(db_manager, raw_key, _discover_body("claude-code"))

    assert len(_connect_events(ws_manager)) == 1


async def test_the_announce_names_the_tool_from_the_meta_envelope(db_manager, ws_manager, monkeypatch):  # noqa: F811
    from api.app_state import state

    raw_key, _tenant = await _seed_api_key(db_manager)
    monkeypatch.setattr(state, "db_manager", db_manager, raising=False)

    await _drive(db_manager, raw_key, _discover_body("claude-code"))

    events = _connect_events(ws_manager)
    assert len(events) == 1
    assert events[0]["data"]["tool_name"] == "claude-code", f"announced the wrong tool: {events[0]}"


async def test_a_second_different_client_also_announces(db_manager, ws_manager, monkeypatch):  # noqa: F811
    from api.app_state import state

    raw_key, _tenant = await _seed_api_key(db_manager)
    monkeypatch.setattr(state, "db_manager", db_manager, raising=False)

    await _drive(db_manager, raw_key, _discover_body("claude-code"))
    await _drive(db_manager, raw_key, _discover_body("opencode"))

    announced = [e["data"]["tool_name"] for e in _connect_events(ws_manager)]
    assert sorted(announced) == ["claude-code", "opencode"]


async def test_reconnecting_via_discover_announces_again(db_manager, ws_manager, monkeypatch):  # noqa: F811
    from api.app_state import state

    raw_key, _tenant = await _seed_api_key(db_manager)
    monkeypatch.setattr(state, "db_manager", db_manager, raising=False)

    for _ in range(3):
        await _drive(db_manager, raw_key, _discover_body("opencode"))

    assert len(_connect_events(ws_manager)) == 3


async def test_ordinary_traffic_still_does_not_announce(db_manager, ws_manager, monkeypatch):  # noqa: F811
    from api.app_state import state

    raw_key, _tenant = await _seed_api_key(db_manager)
    monkeypatch.setattr(state, "db_manager", db_manager, raising=False)

    await _drive(db_manager, raw_key, _jsonrpc_body("tools/list"))

    assert _connect_events(ws_manager) == []


async def test_initialize_still_announces_unchanged(db_manager, ws_manager, monkeypatch):  # noqa: F811
    from api.app_state import state

    raw_key, _tenant = await _seed_api_key(db_manager)
    monkeypatch.setattr(state, "db_manager", db_manager, raising=False)

    await _drive(db_manager, raw_key, _initialize_body("claude-code"))

    assert len(_connect_events(ws_manager)) == 1
