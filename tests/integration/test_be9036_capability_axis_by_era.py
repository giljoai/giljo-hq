# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-9036 -- what the protocol capability axis actually delivers, PER ERA.

Why this file exists
====================
SDK 2.0 carries client capabilities and client info per request, which reads like a
licence to delete the three ``stateless_http`` clientInfo-drop workarounds
(``_client_info_patch``'s resolved-harness precompute, ``_stamp_resolved_harness`` /
``_stamp_resolved_preset``, ``_persisted_harness`` / ``_persisted_preset``). It is not,
and the reason is the protocol ERA rather than the SDK version: the per-request carrier
is the 2026-07-28 reserved ``_meta`` envelope, and a handshake-era client never sends
one.

The live fleet is claude-code negotiating a 2025-era revision (see
``test_inf9371_wire_revisions.py``, which pins that the whole in-memory boundary suite
is structurally blind to legacy-revision behaviour). So the question "is the protocol
axis populated for the clients we actually serve?" cannot be answered by any existing
test -- it has to be measured over real HTTP, in both eras, against the transport
config we really ship. That is what this file does.

It is deliberately an OBSERVATION test: it asserts what the SDK hands a request handler
under ``stateless_http=True``. Those observations are the written justification quoted
in the docstrings of all three retained workaround sites, so if a future SDK bump makes
the 2025-era read start arriving populated, this file goes red and the retention
argument gets revisited on evidence instead of on a stale comment.

The companion ``tests/unit/test_be9036_protocol_capability_tier.py`` covers the other
direction: that the legacy tier still resolves a harness when the protocol axis is
empty (i.e. that deleting the workarounds actually breaks something).

Edition Scope: Both.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any

import httpx
import pytest

from api.endpoints.mcp_tools._harness import _protocol_capabilities


# The reserved 2026-07-28 request-`_meta` keys. Spelled out rather than imported so a
# rename in the SDK surfaces here as a failure instead of silently following along --
# these strings are the wire contract, not an implementation detail.
_PROTOCOL_VERSION_KEY = "io.modelcontextprotocol/protocolVersion"
_CAPABILITIES_KEY = "io.modelcontextprotocol/clientCapabilities"
_CLIENT_INFO_KEY = "io.modelcontextprotocol/clientInfo"

_LEGACY_REVISION = "2025-11-25"
_MODERN_REVISION = "2026-07-28"

# What the live fleet looks like on the wire (INF-9371 captured the revision; the
# name/version pair is the one harness_resolver recognises).
_FLEET_CLIENT_INFO = {"name": "claude-code", "version": "2.1.226"}


@pytest.fixture
def neutral_authz(monkeypatch):
    """Neutralise the two authorization resolvers, as the wire-revision suite does.

    This chain has no ``MCPAuthMiddleware``, so an unauthenticated request would resolve
    to an EMPTY scope set and advertise no tools, making every call below fail for a
    reason that has nothing to do with capabilities. Uses the seam ``mcp_sdk_server``
    documents for exactly this.
    """
    from api.endpoints import mcp_sdk_server

    monkeypatch.setattr(mcp_sdk_server, "_scopes_from_request", lambda _request: None)
    monkeypatch.setattr(mcp_sdk_server, "_profile_toolset_from_request", lambda _request: None)


class _ContextObserver:
    """A middleware that records what each inbound request's context actually carries.

    Registered on the public ``MCPServer.middleware`` seam -- the same seam the SEC-9126
    scope gate rides -- because that is where the SDK hands us the per-request context.
    Observes only; always delegates.
    """

    def __init__(self) -> None:
        self.seen: list[dict[str, Any]] = []

    async def __call__(self, ctx, call_next):
        session = getattr(ctx, "session", None)
        capabilities = getattr(session, "client_capabilities", None)
        params = getattr(session, "client_params", None)
        # `Context.client_capabilities` is defined as exactly this delegation, so
        # feeding it to the real resolver exercises production code against real SDK
        # data rather than against a hand-built double.
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
    """Install the observer for one test and always remove it again."""
    from api.endpoints.mcp_sdk_server import mcp

    probe = _ContextObserver()
    mcp.middleware.append(probe)
    try:
        yield probe
    finally:
        mcp.middleware.remove(probe)


@asynccontextmanager
async def wire_client() -> AsyncIterator[httpx.AsyncClient]:
    """An HTTP client speaking to the real MCP transport.

    Same shape and same reasons as ``test_inf9371_wire_revisions.wire_client``: a
    context manager (not a fixture) so the session manager's task group is entered and
    exited in the same task, and transport config comes from production's own
    ``_STREAMABLE_HTTP_KWARGS`` so this cannot drift into passing against a config we do
    not ship -- which matters here more than anywhere, since ``stateless_http=True`` is
    the whole subject of the test.
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


class TestLegacyEraCarriesNothingPerRequest:
    """The 2025-era fleet: the protocol axis is EMPTY on the render path."""

    @pytest.mark.asyncio
    async def test_legacy_tools_call_has_no_capabilities_and_no_client_info(self, neutral_authz, observer):
        """The measurement the three retained workarounds are justified by.

        A 2025-era client handshakes with a full clientInfo and a declared elicitation
        capability, then makes a tools/call -- the render path. Under
        ``stateless_http=True`` the connection is rebuilt per request, so NEITHER
        survives. This is why the harness must be persisted at initialize and stamped
        onto ASGI state: at this point in the request there is nothing else to read.
        """
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
        # The production resolver agrees: no protocol tier, so the legacy tier answers.
        assert observed["protocol_tier"] is None


class TestModernEraCarriesCapabilitiesPerRequest:
    """The 2026-07-28 era: capabilities (and optionally identity) ride every request."""

    @pytest.mark.asyncio
    async def test_modern_tools_call_carries_declared_capabilities(self, neutral_authz, observer):
        """The dividend: a GA client's capabilities reach a tools/call with no handshake."""
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
        # The production resolver engages its protocol tier on this data.
        assert observed["protocol_tier"] is not None
        assert observed["protocol_tier"].elicitation is not None
        # Identity rides the same envelope, which is why the modern era needs no
        # persisted-harness fallback (it is optional per spec, hence still a fallback).
        assert observed["client_info_name"] == _FLEET_CLIENT_INFO["name"]

    @pytest.mark.asyncio
    async def test_capabilities_arrive_without_client_info(self, neutral_authz, observer):
        """Capabilities must not depend on the client identifying itself (spec PR #3002).

        Pinned because it is the one place the two axes genuinely separate: a modern
        client may declare capabilities and stay anonymous. A capability read that
        reached through client info would return nothing here.
        """
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
