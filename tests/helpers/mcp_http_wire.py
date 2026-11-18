# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import json
from contextlib import asynccontextmanager

import httpx


_CLIENT = ("203.0.113.9", 40123)
_HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json, text/event-stream",
    "MCP-Protocol-Version": "2025-06-18",
}


def rpc(method: str, params: dict | None = None, rid: int = 1) -> dict:
    return {"jsonrpc": "2.0", "id": rid, "method": method, "params": params or {}}


def response_message(response: httpx.Response) -> dict:
    raw = response.text
    if response.headers["content-type"].startswith("text/event-stream"):
        raw = next(line[5:] for line in raw.splitlines() if line.startswith("data:"))
    return json.loads(raw)


@asynccontextmanager
async def mcp_wire(db_manager):
    from mcp.server.streamable_http_manager import StreamableHTTPASGIApp

    from api.app_state import state
    from api.endpoints.mcp_sdk_server import _STREAMABLE_HTTP_KWARGS, MCPAuthMiddleware, mcp
    from giljo_mcp.tenant import TenantManager
    from giljo_mcp.tools.tool_accessor import ToolAccessor

    prior = (state.db_manager, state.tenant_manager, state.tool_accessor)
    state.db_manager = db_manager
    if state.tenant_manager is None:
        state.tenant_manager = TenantManager()
    state.tool_accessor = ToolAccessor(db_manager=db_manager, tenant_manager=state.tenant_manager)
    mcp.streamable_http_app(**_STREAMABLE_HTTP_KWARGS)
    try:
        async with mcp.session_manager.run():
            transport = httpx.ASGITransport(
                app=MCPAuthMiddleware(StreamableHTTPASGIApp(mcp.session_manager)), client=_CLIENT
            )
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                yield client
    finally:
        state.db_manager, state.tenant_manager, state.tool_accessor = prior


class Agent:

    def __init__(self, wire: httpx.AsyncClient, api_key: str):
        self.wire = wire
        self.headers = {**_HEADERS, "X-API-Key": api_key}
        self.rid = 1

    async def connect(self) -> Agent:
        init = await self.wire.post(
            "/mcp",
            json=rpc(
                "initialize",
                {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "c", "version": "1"}},
            ),
            headers=self.headers,
        )
        assert init.status_code == 200, init.text
        self.headers["Mcp-Session-Id"] = init.headers["mcp-session-id"]
        await self.wire.post(
            "/mcp", json={"jsonrpc": "2.0", "method": "notifications/initialized"}, headers=self.headers
        )
        return self

    async def call_unchecked(self, name: str, arguments: dict | None = None) -> dict:
        self.rid += 1
        response = await self.wire.post(
            "/mcp", json=rpc("tools/call", {"name": name, "arguments": arguments or {}}, self.rid), headers=self.headers
        )
        assert response.status_code == 200, response.text
        message = response_message(response)
        assert "error" not in message, message
        return message["result"]

    async def call(self, name: str, arguments: dict | None = None) -> dict:
        result = await self.call_unchecked(name, arguments)
        assert result.get("isError") is not True, result
        return result

    async def tools_list_bytes(self) -> bytes:
        self.rid += 1
        response = await self.wire.post("/mcp", json=rpc("tools/list", rid=self.rid), headers=self.headers)
        message = response_message(response)
        message.pop("id")
        return json.dumps(message, sort_keys=True).encode()


def model_text(result: dict) -> str:
    return "\n".join(block["text"] for block in result["content"] if block["type"] == "text")
