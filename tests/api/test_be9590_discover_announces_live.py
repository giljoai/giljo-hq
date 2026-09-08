# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-9590 — the LIVE announce must fire for ``server/discover`` too.

THE DEFECT, from the operator's live OAuth look on the hosted test environment
(build including BE-9586d): a new user connects, the setup wizard's "waiting for
connection" does NOT flip -- and a page REFRESH shows it green.

That split is the diagnosis. BE-9586d gave ``server/discover`` a durable session
row, so the reload-time read (``connected_harnesses``) is correct. But the LIVE
``setup:tool_connected`` broadcast is still gated on ``initialize`` alone, and a
2026-07-28 client never sends one -- so nothing announces while the wizard is
open. Durable half fixed, live half still deaf.

THE GATE IS THE NAMED SET, not a second method comparison. BE-9586d introduced
``announces_client()`` precisely so the two places that answer "is a client
attaching?" cannot drift apart again; this is the second place.

NO DEDUPE, DELIBERATELY -- and this is the part worth reading before "improving" it.

``initialize`` has no de-dup guard, by design: BE-9498 REMOVED the memo (keyed
``tenant:api_key_id or user_id``, carrying no client identity, so the first client
a user connected consumed the announcement and every later one was silenced) and
its docblock says "Do not reintroduce it". The established contract is that
reconnecting announces AGAIN -- pinned by
``test_be9498_tool_connected_every_client::test_reconnecting_the_same_tool_announces_again``,
which drives three initializes and asserts three announces.

So a "only announce when the session row was newly created" dedupe would be wrong
twice over: it would break that reconnect semantics for discover, and it would
re-introduce exactly the class of state BE-9498 removed. Mirroring initialize
means mirroring its ABSENCE of a guard.

Reconnecting announces again, by design -- that contract is pinned by BE-9498's
tests. Repeat announcements are idempotent at the UI: the dot goes green again.
Any future rate-shaping must be durable and client-keyed, never the in-process
memo.

Failing-layer discipline: drives real JSON-RPC frames through ``MCPAuthMiddleware``
and asserts on what the WebSocket manager was actually handed. Edition Scope: Both.
"""

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
    """The frame shape Claude Code 2.1.245 actually opens with.

    Identity rides ``params._meta``, NOT ``params.clientInfo`` -- a body built the
    familiar way would pass against an announce that never learned to read the real
    location, and the wizard would flip to a GENERIC card instead of the tool's own.
    """
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
    """THE DEFECT: today a modern client attaches and the wizard hears nothing."""
    from api.app_state import state

    raw_key, _tenant = await _seed_api_key(db_manager)
    monkeypatch.setattr(state, "db_manager", db_manager, raising=False)

    await _drive(db_manager, raw_key, _discover_body("claude-code"))

    assert len(_connect_events(ws_manager)) == 1


async def test_the_announce_names_the_tool_from_the_meta_envelope(db_manager, ws_manager, monkeypatch):  # noqa: F811
    """The trap: read ``params.clientInfo`` and the wizard lights the GENERIC card.

    ``toolIdForHarness('generic')`` maps to a real "Generic MCP client" card, so a
    nameless announce is not a no-op -- it turns the wrong dot green while the user's
    actual tool stays grey.
    """
    from api.app_state import state

    raw_key, _tenant = await _seed_api_key(db_manager)
    monkeypatch.setattr(state, "db_manager", db_manager, raising=False)

    await _drive(db_manager, raw_key, _discover_body("claude-code"))

    events = _connect_events(ws_manager)
    assert len(events) == 1
    assert events[0]["data"]["tool_name"] == "claude-code", f"announced the wrong tool: {events[0]}"


async def test_a_second_different_client_also_announces(db_manager, ws_manager, monkeypatch):  # noqa: F811
    """The BE-9498 guarantee, preserved under the widened gate.

    That project exists because a first-sight memo silenced every client after the
    first. Widening the gate to discover must not resurrect that shape.
    """
    from api.app_state import state

    raw_key, _tenant = await _seed_api_key(db_manager)
    monkeypatch.setattr(state, "db_manager", db_manager, raising=False)

    await _drive(db_manager, raw_key, _discover_body("claude-code"))
    await _drive(db_manager, raw_key, _discover_body("opencode"))

    announced = [e["data"]["tool_name"] for e in _connect_events(ws_manager)]
    assert sorted(announced) == ["claude-code", "opencode"]


async def test_reconnecting_via_discover_announces_again(db_manager, ws_manager, monkeypatch):  # noqa: F811
    """Mirrors initialize's contract exactly: reconnecting flips the dot again.

    This is what a "only announce when the row was newly created" dedupe would
    break, and why this fix mirrors initialize's ABSENCE of a guard rather than
    inventing one.
    """
    from api.app_state import state

    raw_key, _tenant = await _seed_api_key(db_manager)
    monkeypatch.setattr(state, "db_manager", db_manager, raising=False)

    for _ in range(3):
        await _drive(db_manager, raw_key, _discover_body("opencode"))

    assert len(_connect_events(ws_manager)) == 3


async def test_ordinary_traffic_still_does_not_announce(db_manager, ws_manager, monkeypatch):  # noqa: F811
    """The control. Without it, a fix that announced on EVERY authenticated request
    would satisfy every test above while spamming the wizard on each tools/call."""
    from api.app_state import state

    raw_key, _tenant = await _seed_api_key(db_manager)
    monkeypatch.setattr(state, "db_manager", db_manager, raising=False)

    await _drive(db_manager, raw_key, _jsonrpc_body("tools/list"))

    assert _connect_events(ws_manager) == []


async def test_initialize_still_announces_unchanged(db_manager, ws_manager, monkeypatch):  # noqa: F811
    """The old handshake is untouched -- the fix widens the gate, it does not move it."""
    from api.app_state import state

    raw_key, _tenant = await _seed_api_key(db_manager)
    monkeypatch.setattr(state, "db_manager", db_manager, raising=False)

    await _drive(db_manager, raw_key, _initialize_body("claude-code"))

    assert len(_connect_events(ws_manager)) == 1
