# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""INF-9371 -- every DECLARED protocol revision is actually served, over HTTP.

Why this file exists, and why it cannot be a boundary test
==========================================================
The 78 in-memory boundary tests reach the server through ``ClientSession``, whose
``initialize()`` hardcodes ``LATEST_HANDSHAKE_VERSION``. They therefore exercise
2025-11-25 and ONLY 2025-11-25, no matter which revision the live fleet speaks.
That makes the entire boundary suite structurally blind to a legacy-revision
regression: the prod fleet is claude-code negotiating a 2025-era revision, and not
one existing test would notice if we stopped serving it.

So this file drives the real ASGI stack over real HTTP and asserts, per revision,
that a client can not only handshake but LIST AND CALL TOOLS -- the operator's
standing commitment is that legacy harnesses keep WORKING, not merely connecting.

Two eras, deliberately both
===========================
- HANDSHAKE era (2024-11-05 .. 2025-11-25): client sends ``initialize`` and the
  server echoes the negotiated revision.
- MODERN era (2026-07-28): there is no handshake. The client carries the
  ``_meta`` envelope keys and the ``Mcp-Method`` header on every request.

``test_an_unknown_revision_is_not_silently_honoured`` is the control that gives the
rest their meaning: an unrecognised revision falls back to 2025-11-25, so an
HONOURED request and a SILENT FALLBACK are distinguishable. Without it, a server
that ignored the requested revision entirely would pass every other test here.

MCPAuthMiddleware is deliberately NOT in this chain: this file pins the PROTOCOL
surface. Auth is covered by test_mcp_authz_fail_closed / test_sec9423_*.

Edition Scope: Both.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import httpx
import pytest

from api.endpoints.oauth import MCP_SPEC_VERSIONS_SUPPORTED


_MODERN_ENVELOPE: dict[str, Any] = {
    "_meta": {
        "io.modelcontextprotocol/protocolVersion": "2026-07-28",
        "io.modelcontextprotocol/clientCapabilities": {},
    }
}

# The revisions a client may HANDSHAKE (declared minus the modern-era one).
_HANDSHAKE_DECLARED = [v for v in MCP_SPEC_VERSIONS_SUPPORTED if v != "2026-07-28"]

_LATEST_HANDSHAKE = "2025-11-25"


@pytest.fixture
def neutral_authz(monkeypatch):
    """Neutralise the two authorization resolvers to their no-restriction posture.

    Necessary, not convenient: this chain has no ``MCPAuthMiddleware``, so an
    unauthenticated request resolves to an EMPTY scope set and an EMPTY profile and
    correctly advertises nothing -- which would make every tool assertion below
    vacuous. Uses the seam ``mcp_sdk_server`` documents for exactly this, and that
    the profile-tier tests already use. This file pins the PROTOCOL axis; the
    authorization axis is pinned by test_mcp_authz_fail_closed / test_sec9423_*.
    """
    from api.endpoints import mcp_sdk_server

    monkeypatch.setattr(mcp_sdk_server, "_scopes_from_request", lambda _request: None)
    monkeypatch.setattr(mcp_sdk_server, "_profile_toolset_from_request", lambda _request: None)


@asynccontextmanager
async def wire_client() -> AsyncIterator[httpx.AsyncClient]:
    """An HTTP client speaking to the real MCP transport.

    A context manager rather than a fixture on purpose: the session manager's task
    group must be entered and exited in the SAME task, and a yielding async fixture
    hands teardown to a different one ("Attempted to exit cancel scope in a different
    task"). Entering it inside the test body keeps both ends together.

    Transport config comes from production's own ``_STREAMABLE_HTTP_KWARGS`` rather
    than being restated here, so this test cannot drift into passing against a shape
    we do not ship. A FRESH session manager is built per use:
    ``StreamableHTTPSessionManager.run()`` may be entered only once per instance, and
    ``streamable_http_app()`` mints a new one on every call. In production the
    FastAPI lifespan enters it via ``start_mcp_session_manager``.
    """
    from mcp.server.streamable_http_manager import StreamableHTTPASGIApp

    from api.endpoints.mcp_sdk_server import _STREAMABLE_HTTP_KWARGS, mcp

    mcp.streamable_http_app(**_STREAMABLE_HTTP_KWARGS)
    async with mcp.session_manager.run():
        transport = httpx.ASGITransport(app=StreamableHTTPASGIApp(mcp.session_manager))
        async with httpx.AsyncClient(transport=transport, base_url="http://mcp.test") as client:
            yield client


def _body(response: httpx.Response) -> dict[str, Any]:
    """Read a JSON-RPC response, tolerating SSE framing."""
    if response.headers.get("content-type", "").startswith("application/json"):
        return response.json()
    for line in response.text.splitlines():
        if line.startswith("data:"):
            return json.loads(line[5:].strip())
    return {}


async def _post(client: httpx.AsyncClient, payload: dict[str, Any], headers: dict[str, str]) -> dict[str, Any]:
    base = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
    return _body(await client.post("/", json=payload, headers={**base, **headers}))


async def _handshake(client: httpx.AsyncClient, requested: str) -> str | None:
    result = await _post(
        client,
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": requested,
                "capabilities": {},
                "clientInfo": {"name": "inf9371-wire-test", "version": "1.0"},
            },
        },
        {},
    )
    return (result.get("result") or {}).get("protocolVersion")


class TestDeclaredHandshakeRevisionsAreServed:
    """Every declared handshake revision negotiates AS ASKED and can run tools."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("requested", _HANDSHAKE_DECLARED)
    async def test_declared_revision_is_honoured_and_tools_work(self, neutral_authz, requested):
        async with wire_client() as client:
            negotiated = await _handshake(client, requested)
            assert negotiated == requested, (
                f"a client asking for {requested} was served {negotiated!r}. Every revision in "
                "MCP_SPEC_VERSIONS_SUPPORTED must be honoured, or we are advertising one we do not serve."
            )

            version_header = {"MCP-Protocol-Version": negotiated}
            listed = await _post(
                client, {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}, version_header
            )
            tools = (listed.get("result") or {}).get("tools", [])
            assert tools, f"{requested} handshakes but advertises no tools: {listed.get('error')}"

            called = await _post(
                client,
                {
                    "jsonrpc": "2.0",
                    "id": 3,
                    "method": "tools/call",
                    "params": {"name": "health_check", "arguments": {}},
                },
                version_header,
            )
            assert called.get("error") is None, f"tools/call failed at {requested}: {called['error']}"
            assert (called.get("result") or {}).get("content"), f"tools/call returned no content at {requested}"

    @pytest.mark.asyncio
    async def test_an_unknown_revision_is_not_silently_honoured(self, neutral_authz):
        """The control: an unknown revision falls back, so 'honoured' above means something.

        If this ever starts returning the requested string, the tests above stop
        proving anything -- they would pass against a server that echoes whatever
        it is asked for.
        """
        async with wire_client() as client:
            negotiated = await _handshake(client, "1999-01-01")

        assert negotiated == _LATEST_HANDSHAKE
        assert negotiated != "1999-01-01"


class TestModernEraRevisionIsServed:
    """2026-07-28 is declared, and the modern era is how it is actually reached."""

    @pytest.mark.asyncio
    async def test_modern_era_lists_and_calls_without_a_handshake(self, neutral_authz):
        assert "2026-07-28" in MCP_SPEC_VERSIONS_SUPPORTED
        headers = {"MCP-Protocol-Version": "2026-07-28", "Mcp-Method": "tools/list"}
        async with wire_client() as client:
            listed = await _post(
                client,
                {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": dict(_MODERN_ENVELOPE)},
                headers,
            )
            assert listed.get("error") is None, f"modern-era tools/list failed: {listed['error']}"

            called = await _post(
                client,
                {
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "tools/call",
                    "params": {"name": "health_check", "arguments": {}, **_MODERN_ENVELOPE},
                },
                {"MCP-Protocol-Version": "2026-07-28", "Mcp-Method": "tools/call", "Mcp-Name": "health_check"},
            )
            assert called.get("error") is None, f"modern-era tools/call failed: {called['error']}"
            assert (called.get("result") or {}).get("content")

    @pytest.mark.asyncio
    async def test_modern_era_is_not_reachable_through_the_handshake(self, neutral_authz):
        """Asking for 2026-07-28 at initialize negotiates DOWN -- it is a separate era.

        Pinned because it is counter-intuitive: the revision is declared and served,
        but NOT via ``initialize``. A future reader must not "fix" the handshake list
        by adding it there.
        """
        async with wire_client() as client:
            negotiated = await _handshake(client, "2026-07-28")

        assert negotiated == _LATEST_HANDSHAKE
