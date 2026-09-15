# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


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

_HANDSHAKE_DECLARED = [v for v in MCP_SPEC_VERSIONS_SUPPORTED if v != "2026-07-28"]

_LATEST_HANDSHAKE = "2025-11-25"


@pytest.fixture
def neutral_authz(monkeypatch):
    from api.endpoints import mcp_sdk_server

    monkeypatch.setattr(mcp_sdk_server, "_scopes_from_request", lambda _request: None)
    monkeypatch.setattr(mcp_sdk_server, "_profile_toolset_from_request", lambda _request: None)


@asynccontextmanager
async def wire_client() -> AsyncIterator[httpx.AsyncClient]:
    from mcp.server.streamable_http_manager import StreamableHTTPASGIApp

    from api.endpoints.mcp_sdk_server import _STREAMABLE_HTTP_KWARGS, mcp

    mcp.streamable_http_app(**_STREAMABLE_HTTP_KWARGS)
    async with mcp.session_manager.run():
        transport = httpx.ASGITransport(app=StreamableHTTPASGIApp(mcp.session_manager))
        async with httpx.AsyncClient(transport=transport, base_url="http://mcp.test") as client:
            yield client


def _body(response: httpx.Response) -> dict[str, Any]:
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
        async with wire_client() as client:
            negotiated = await _handshake(client, "1999-01-01")

        assert negotiated == _LATEST_HANDSHAKE
        assert negotiated != "1999-01-01"


class TestModernEraRevisionIsServed:

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
        async with wire_client() as client:
            negotiated = await _handshake(client, "2026-07-28")

        assert negotiated == _LATEST_HANDSHAKE
