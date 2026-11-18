# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import importlib
import json
from contextlib import asynccontextmanager

import httpx
import pytest
from sqlalchemy import select

from giljo_mcp.database import tenant_session_context
from tests.api.test_mcp_session import _seed_api_key


pytestmark = pytest.mark.asyncio

_CLIENT = ("203.0.113.9", 40123)
_HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json, text/event-stream",
    "MCP-Protocol-Version": "2025-06-18",
}


@pytest.fixture(autouse=True)
def _limits_live(real_rate_limiter, monkeypatch):
    try:
        limits = importlib.import_module("api.endpoints.mcp_rate_limits")
    except ImportError:
        return
    pinned = (int(limits._clock()) // 60) * 60 + 1
    monkeypatch.setattr(limits, "_clock", lambda: pinned)


def _chain(db_manager):
    from mcp.server.streamable_http_manager import StreamableHTTPASGIApp

    from api.endpoints.mcp_sdk_server import _STREAMABLE_HTTP_KWARGS, MCPAuthMiddleware, mcp

    mcp.streamable_http_app(**_STREAMABLE_HTTP_KWARGS)
    return mcp, MCPAuthMiddleware(StreamableHTTPASGIApp(mcp.session_manager))


@asynccontextmanager
async def mcp_wire(db_manager, client=_CLIENT):
    from api.app_state import state

    prior = state.db_manager
    state.db_manager = db_manager
    mcp, app = _chain(db_manager)
    try:
        async with mcp.session_manager.run():
            transport = httpx.ASGITransport(app=app, client=client)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as wire:
                yield wire
    finally:
        state.db_manager = prior


def _rpc(method: str, params: dict | None = None, rid: int = 1) -> dict:
    return {"jsonrpc": "2.0", "id": rid, "method": method, "params": params or {}}


def _initialize(client_info: dict | None = None, capabilities: dict | None = None) -> dict:
    return _rpc(
        "initialize",
        {
            "protocolVersion": "2025-06-18",
            "capabilities": capabilities or {},
            "clientInfo": client_info or {"name": "claude-code", "version": "2.1.0"},
        },
    )


async def _session_rows(db_manager, tenant_key: str) -> list:
    from giljo_mcp.models import MCPSession

    async with db_manager.get_session_async() as db:
        with tenant_session_context(db, tenant_key):
            rows = (
                (
                    await db.execute(
                        select(MCPSession).where(MCPSession.tenant_key == tenant_key).order_by(MCPSession.created_at)
                    )
                )
                .scalars()
                .all()
            )
            for row in rows:
                db.expunge(row)
            return rows


class TestUnauthenticatedTraffic:
    async def test_credentialless_request_is_refused_without_reading_the_body(self, db_manager):
        from api.app_state import state

        prior = state.db_manager
        state.db_manager = db_manager
        mcp, app = _chain(db_manager)
        reads = {"count": 0}

        async def receive():
            reads["count"] += 1
            return {"type": "http.request", "body": json.dumps(_rpc("tools/list")).encode(), "more_body": False}

        sent: list[dict] = []

        async def send(message):
            sent.append(message)

        scope = {
            "type": "http",
            "asgi": {"version": "3.0", "spec_version": "2.3"},
            "method": "POST",
            "path": "/mcp",
            "raw_path": b"/mcp",
            "query_string": b"",
            "headers": [(b"content-type", b"application/json")],
            "client": _CLIENT,
            "server": ("test", 80),
            "scheme": "http",
            "root_path": "",
        }
        try:
            async with mcp.session_manager.run():
                await app(scope, receive, send)
        finally:
            state.db_manager = prior

        assert sent[0]["status"] == 401
        assert reads["count"] == 0, "the body of a credential-less request must never be read"

    async def test_an_address_flooding_without_credentials_gets_429(self, db_manager, monkeypatch):
        monkeypatch.setenv("GILJO_MCP_RL_UNAUTHENTICATED_PER_IP", "5")
        async with mcp_wire(db_manager, client=("203.0.113.21", 40000)) as wire:
            statuses = [
                (await wire.post("/mcp", json=_rpc("tools/list"), headers=_HEADERS)).status_code for _ in range(7)
            ]

        assert statuses[:5] == [401] * 5, statuses
        assert statuses[5:] == [429, 429], statuses

    async def test_bad_credentials_count_against_the_same_budget(self, db_manager, monkeypatch):
        monkeypatch.setenv("GILJO_MCP_RL_UNAUTHENTICATED_PER_IP", "3")
        headers = {**_HEADERS, "Authorization": "Bearer not-a-real-token"}
        async with mcp_wire(db_manager, client=("203.0.113.22", 40000)) as wire:
            statuses = [
                (await wire.post("/mcp", json=_rpc("tools/list"), headers=headers)).status_code for _ in range(5)
            ]

        assert statuses[-1] == 429, statuses
        assert 429 not in statuses[:3], statuses

    async def test_another_address_keeps_its_own_budget(self, db_manager, monkeypatch):
        monkeypatch.setenv("GILJO_MCP_RL_UNAUTHENTICATED_PER_IP", "2")
        async with mcp_wire(db_manager, client=("203.0.113.23", 40000)) as wire:
            for _ in range(3):
                await wire.post("/mcp", json=_rpc("tools/list"), headers=_HEADERS)
        async with mcp_wire(db_manager, client=("203.0.113.24", 40000)) as other:
            response = await other.post("/mcp", json=_rpc("tools/list"), headers=_HEADERS)
        assert response.status_code == 401


class TestAccountBudgets:
    async def test_an_account_over_its_per_minute_budget_gets_429(self, db_manager, monkeypatch):
        monkeypatch.setenv("GILJO_MCP_RL_PER_TENANT", "4")
        raw_key, _tenant_key = await _seed_api_key(db_manager)
        headers = {**_HEADERS, "X-API-Key": raw_key}
        async with mcp_wire(db_manager) as wire:
            statuses = [
                (await wire.post("/mcp", json=_rpc("tools/list", rid=i), headers=headers)).status_code for i in range(6)
            ]

        assert statuses[:4] == [200] * 4, statuses
        assert statuses[4:] == [429, 429], statuses

    async def test_handshakes_have_a_smaller_budget(self, db_manager, monkeypatch):
        monkeypatch.setenv("GILJO_MCP_RL_INITIALIZE_PER_TENANT", "2")
        raw_key, tenant_key = await _seed_api_key(db_manager)
        headers = {**_HEADERS, "X-API-Key": raw_key}
        async with mcp_wire(db_manager) as wire:
            statuses = [(await wire.post("/mcp", json=_initialize(), headers=headers)).status_code for _ in range(4)]
            after = await wire.post("/mcp", json=_rpc("tools/list"), headers=headers)

        assert statuses == [200, 200, 429, 429], statuses
        assert after.status_code == 200, "ordinary calls keep working while handshakes are throttled"
        assert len(await _session_rows(db_manager, tenant_key)) == 2

    async def test_discover_is_not_a_handshake(self, db_manager, monkeypatch):
        monkeypatch.setenv("GILJO_MCP_RL_INITIALIZE_PER_TENANT", "1")
        raw_key, _tenant_key = await _seed_api_key(db_manager)
        headers = {**_HEADERS, "X-API-Key": raw_key}
        meta = {"_meta": {"io.modelcontextprotocol/clientInfo": {"name": "modern-client", "version": "1"}}}
        async with mcp_wire(db_manager) as wire:
            statuses = [
                (await wire.post("/mcp", json=_rpc("server/discover", meta, rid=i), headers=headers)).status_code
                for i in range(3)
            ]
        assert 429 not in statuses, statuses

    async def test_a_busy_agent_session_is_never_throttled_at_the_defaults(self, db_manager):
        raw_key, _tenant_key = await _seed_api_key(db_manager)
        headers = {**_HEADERS, "X-API-Key": raw_key}
        async with mcp_wire(db_manager) as wire:
            init = await wire.post("/mcp", json=_initialize(), headers=headers)
            assert init.status_code == 200, init.text
            session = {**headers, "Mcp-Session-Id": init.headers["mcp-session-id"]}
            statuses = {
                (await wire.post("/mcp", json=_rpc("tools/list", rid=i), headers=session)).status_code
                for i in range(150)
            }
        assert statuses == {200}


class TestBoundedSessionRows:
    async def test_initialize_stores_a_bounded_client_record(self, db_manager):
        raw_key, tenant_key = await _seed_api_key(db_manager)
        headers = {**_HEADERS, "X-API-Key": raw_key}
        bulky_info = {"name": "n" * 5000, "version": "v" * 5000, "junk": "x" * 200_000, "giljo_tool_profile": "core"}
        bulky_caps = {f"cap{i}": {"blob": "y" * 2000} for i in range(100)}
        async with mcp_wire(db_manager) as wire:
            init = await wire.post("/mcp", json=_initialize(bulky_info, bulky_caps), headers=headers)
        assert init.status_code == 200, init.text

        (row,) = await _session_rows(db_manager, tenant_key)
        stored = json.dumps(row.session_data)
        assert len(stored) < 8_192, f"session_data is {len(stored)} bytes; the client payload was stored verbatim"
        info = row.session_data["client_info"]
        assert set(info) <= {"name", "version", "giljo_tool_profile"}
        assert info["name"] == "n" * 128
        assert info["version"] == "v" * 64
        assert info["giljo_tool_profile"] == "core", "the declared tool profile is read back on later calls"

    async def test_small_capabilities_are_kept_whole(self, db_manager):
        raw_key, tenant_key = await _seed_api_key(db_manager)
        headers = {**_HEADERS, "X-API-Key": raw_key}
        caps = {"elicitation": {}, "roots": {"listChanged": True}}
        async with mcp_wire(db_manager) as wire:
            assert (await wire.post("/mcp", json=_initialize(capabilities=caps), headers=headers)).status_code == 200
        (row,) = await _session_rows(db_manager, tenant_key)
        assert row.session_data["client_capabilities"] == caps
        assert row.session_data["client_info"] == {"name": "claude-code", "version": "2.1.0"}

    async def test_an_account_keeps_a_bounded_number_of_live_sessions(self, db_manager, monkeypatch):
        from api.endpoints.mcp_session import MCPSessionManager

        monkeypatch.setattr(MCPSessionManager, "MAX_SESSIONS_PER_TENANT", 3, raising=False)
        raw_key, tenant_key = await _seed_api_key(db_manager)
        headers = {**_HEADERS, "X-API-Key": raw_key}
        minted = []
        async with mcp_wire(db_manager) as wire:
            for i in range(5):
                info = {"name": f"client-{i}", "version": "1"}
                minted.append(
                    (await wire.post("/mcp", json=_initialize(info), headers=headers)).headers["mcp-session-id"]
                )

        rows = await _session_rows(db_manager, tenant_key)
        assert [row.session_id for row in rows] == minted[-3:], "the oldest sessions are evicted first"

    async def test_the_cap_never_touches_another_account(self, db_manager, monkeypatch):
        from api.endpoints.mcp_session import MCPSessionManager

        monkeypatch.setattr(MCPSessionManager, "MAX_SESSIONS_PER_TENANT", 2, raising=False)
        key_a, tenant_a = await _seed_api_key(db_manager)
        key_b, tenant_b = await _seed_api_key(db_manager)
        async with mcp_wire(db_manager) as wire:
            await wire.post("/mcp", json=_initialize(), headers={**_HEADERS, "X-API-Key": key_b})
            for _ in range(4):
                await wire.post("/mcp", json=_initialize(), headers={**_HEADERS, "X-API-Key": key_a})

        assert len(await _session_rows(db_manager, tenant_a)) == 2
        assert len(await _session_rows(db_manager, tenant_b)) == 1
