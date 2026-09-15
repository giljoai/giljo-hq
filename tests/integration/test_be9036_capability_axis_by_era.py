# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any

import httpx
import pytest

from api.endpoints.mcp_tools._harness import _protocol_capabilities


_PROTOCOL_VERSION_KEY = "io.modelcontextprotocol/protocolVersion"
_CAPABILITIES_KEY = "io.modelcontextprotocol/clientCapabilities"
_CLIENT_INFO_KEY = "io.modelcontextprotocol/clientInfo"

_LEGACY_REVISION = "2025-11-25"
_MODERN_REVISION = "2026-07-28"

_FLEET_CLIENT_INFO = {"name": "claude-code", "version": "2.1.226"}


@pytest.fixture
def neutral_authz(monkeypatch):
    from api.endpoints import mcp_sdk_server

    monkeypatch.setattr(mcp_sdk_server, "_scopes_from_request", lambda _request: None)
    monkeypatch.setattr(mcp_sdk_server, "_profile_toolset_from_request", lambda _request: None)


class _ContextObserver:

    def __init__(self) -> None:
        self.seen: list[dict[str, Any]] = []

    async def __call__(self, ctx, call_next):
        session = getattr(ctx, "session", None)
        capabilities = getattr(session, "client_capabilities", None)
        params = getattr(session, "client_params", None)
        self.seen.append(
            {
                "method": getattr(ctx, "method", None),
                "capabilities": capabilities,
                "client_params": params,
                "client_info_name": getattr(getattr(params, "client_info", None), "name", None),
                "protocol_tier": _protocol_capabilities(SimpleNamespace(client_capabilities=capabilities)),
            }
        )
        return await call_next(ctx)

    def for_method(self, method: str) -> dict[str, Any]:
        matches = [row for row in self.seen if row["method"] == method]
        assert matches, f"no {method} observed; saw {[row['method'] for row in self.seen]}"
        return matches[-1]


@pytest.fixture
def observer():
    from api.endpoints.mcp_sdk_server import mcp

    probe = _ContextObserver()
    mcp.middleware.append(probe)
    try:
        yield probe
    finally:
        mcp.middleware.remove(probe)


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


class TestLegacyEraCarriesNothingPerRequest:

    @pytest.mark.asyncio
    async def test_legacy_tools_call_has_no_capabilities_and_no_client_info(self, neutral_authz, observer):
        async with wire_client() as client:
            handshake = await _post(
                client,
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": _LEGACY_REVISION,
                        "capabilities": {"elicitation": {}},
                        "clientInfo": _FLEET_CLIENT_INFO,
                    },
                },
                {},
            )
            assert (handshake.get("result") or {}).get("protocolVersion") == _LEGACY_REVISION

            called = await _post(
                client,
                {
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "tools/call",
                    "params": {"name": "health_check", "arguments": {}},
                },
                {"MCP-Protocol-Version": _LEGACY_REVISION},
            )
            assert called.get("error") is None, f"legacy tools/call failed: {called.get('error')}"

        observed = observer.for_method("tools/call")
        assert observed["capabilities"] is None, (
            "a 2025-era tools/call now carries client capabilities. If this is real, the "
            "protocol axis reaches the live fleet and the three retained clientInfo-drop "
            "workarounds (BE-9035d / BE-9327) should be re-evaluated for deletion."
        )
        assert observed["client_params"] is None, (
            "a 2025-era tools/call now carries client_params -- the stateless_http "
            "clientInfo drop that BE-9035d works around may be gone. Re-measure before "
            "trusting the retention argument in those docstrings."
        )
        assert observed["client_info_name"] is None
        assert observed["protocol_tier"] is None


class TestModernEraCarriesCapabilitiesPerRequest:

    @pytest.mark.asyncio
    async def test_modern_tools_call_carries_declared_capabilities(self, neutral_authz, observer):
        envelope = {
            "_meta": {
                _PROTOCOL_VERSION_KEY: _MODERN_REVISION,
                _CAPABILITIES_KEY: {"elicitation": {}},
                _CLIENT_INFO_KEY: _FLEET_CLIENT_INFO,
            }
        }
        async with wire_client() as client:
            called = await _post(
                client,
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "tools/call",
                    "params": {"name": "health_check", "arguments": {}, **envelope},
                },
                {
                    "MCP-Protocol-Version": _MODERN_REVISION,
                    "Mcp-Method": "tools/call",
                    "Mcp-Name": "health_check",
                },
            )
            assert called.get("error") is None, f"modern tools/call failed: {called.get('error')}"

        observed = observer.for_method("tools/call")
        assert observed["capabilities"] is not None, (
            "the modern envelope declared capabilities but none reached the request "
            "context -- the protocol capability axis is not wired up."
        )
        assert observed["capabilities"].elicitation is not None
        assert observed["protocol_tier"] is not None
        assert observed["protocol_tier"].elicitation is not None
        assert observed["client_info_name"] == _FLEET_CLIENT_INFO["name"]

    @pytest.mark.asyncio
    async def test_capabilities_arrive_without_client_info(self, neutral_authz, observer):
        envelope = {
            "_meta": {
                _PROTOCOL_VERSION_KEY: _MODERN_REVISION,
                _CAPABILITIES_KEY: {"elicitation": {}},
            }
        }
        async with wire_client() as client:
            called = await _post(
                client,
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "tools/call",
                    "params": {"name": "health_check", "arguments": {}, **envelope},
                },
                {
                    "MCP-Protocol-Version": _MODERN_REVISION,
                    "Mcp-Method": "tools/call",
                    "Mcp-Name": "health_check",
                },
            )
            assert called.get("error") is None, f"anonymous modern tools/call failed: {called.get('error')}"

        observed = observer.for_method("tools/call")
        assert observed["client_info_name"] is None, "test setup sent no client info"
        assert observed["protocol_tier"] is not None, (
            "capabilities were declared without client info and did not reach the "
            "capability axis -- capability detection must never depend on identity."
        )
        assert observed["protocol_tier"].elicitation is not None
