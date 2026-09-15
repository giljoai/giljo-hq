# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from giljo_mcp.database import tenant_session_context
from giljo_mcp.services import debounce

from tests.api.test_mcp_session import (  # noqa: E402
    _drive_middleware_with_body,
    _jsonrpc_body,
    _seed_api_key,
)


pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def _clean_debounce():
    debounce.reset()
    yield
    debounce.reset()


@pytest.fixture
def jwt_env(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "test_secret_key")
    return "test_secret_key"


@pytest.fixture
def mcp_canonical_uri_env(monkeypatch):
    monkeypatch.setenv("GILJO_MCP_CANONICAL_URI", "http://test/mcp")
    return "http://test/mcp"


async def _api_key_id(db_manager, tenant_key: str) -> str:
    from giljo_mcp.models.auth import APIKey

    async with db_manager.get_session_async() as db:
        with tenant_session_context(db, tenant_key):
            row = (await db.execute(select(APIKey).where(APIKey.tenant_key == tenant_key))).scalar_one()
            return row.id


async def _read_last_used(db_manager, tenant_key: str):
    from giljo_mcp.models.auth import APIKey

    async with db_manager.get_session_async() as db:
        with tenant_session_context(db, tenant_key):
            row = (await db.execute(select(APIKey).where(APIKey.tenant_key == tenant_key))).scalar_one()
            return row.last_used




async def test_f51_last_used_debounced_within_window(db_manager):
    from api.endpoints.mcp_session import MCPSessionManager

    raw_key, tenant_key = await _seed_api_key(db_manager)

    async def _auth():
        async with db_manager.get_session_async() as db:
            return await MCPSessionManager(db).authenticate_api_key(raw_key)

    assert await _auth() is not None
    first = await _read_last_used(db_manager, tenant_key)
    assert first is not None, "first auth must record last_used"

    async with db_manager.get_session_async() as db:
        from giljo_mcp.models.auth import APIKey

        with tenant_session_context(db, tenant_key):
            row = (await db.execute(select(APIKey).where(APIKey.tenant_key == tenant_key))).scalar_one()
            row.last_used = datetime.now(UTC) - timedelta(hours=2)
            backdated = row.last_used
            await db.commit()

    await _auth()
    assert await _read_last_used(db_manager, tenant_key) == backdated, "2nd rapid auth must NOT rewrite last_used"

    debounce.reset()
    await _auth()
    assert await _read_last_used(db_manager, tenant_key) > backdated, "post-window auth must record last_used again"




async def _mint_session(db_manager, raw_key: str) -> str:
    from api.endpoints.mcp_sdk_server import MCPAuthMiddleware

    _status, headers, _b = await _drive_middleware_with_body(
        MCPAuthMiddleware(app=_CapturingProbe()),
        headers=[(b"x-api-key", raw_key.encode()), (b"content-type", b"application/json")],
        body=_jsonrpc_body("initialize", params={"protocolVersion": "2025-06-18", "capabilities": {}}),
    )
    session_id = headers.get("mcp-session-id")
    assert session_id
    return session_id


async def _reuse(db_manager, raw_key: str, session_id: str) -> int:
    from api.endpoints.mcp_sdk_server import MCPAuthMiddleware

    status, _h, _b = await _drive_middleware_with_body(
        MCPAuthMiddleware(app=_CapturingProbe()),
        headers=[
            (b"x-api-key", raw_key.encode()),
            (b"mcp-protocol-version", b"2025-06-18"),
            (b"mcp-session-id", session_id.encode("ascii")),
            (b"content-type", b"application/json"),
        ],
        body=_jsonrpc_body("tools/list"),
    )
    return status


async def test_f52_session_extend_debounced_within_window(db_manager, jwt_env):
    from api.app_state import state
    from giljo_mcp.models import MCPSession

    raw_key, tenant_key = await _seed_api_key(db_manager)

    async def _read_last_accessed():
        async with db_manager.get_session_async() as db:
            with tenant_session_context(db, tenant_key):
                row = (await db.execute(select(MCPSession).where(MCPSession.session_id == session_id))).scalar_one()
                return row.last_accessed

    async def _backdate():
        async with db_manager.get_session_async() as db:
            with tenant_session_context(db, tenant_key):
                row = (await db.execute(select(MCPSession).where(MCPSession.session_id == session_id))).scalar_one()
                row.last_accessed = datetime.now(UTC) - timedelta(hours=2)
                marker = row.last_accessed
                await db.commit()
                return marker

    prior_db = state.db_manager
    state.db_manager = db_manager
    try:
        session_id = await _mint_session(db_manager, raw_key)

        backdated = await _backdate()
        assert await _reuse(db_manager, raw_key, session_id) == 200
        assert await _read_last_accessed() > backdated, "the FIRST extend must land"

        backdated = await _backdate()
        assert await _reuse(db_manager, raw_key, session_id) == 200
        assert await _read_last_accessed() == backdated, "rapid reuse within window must NOT extend the session"

        debounce.reset()
        assert await _reuse(db_manager, raw_key, session_id) == 200
        assert await _read_last_accessed() > backdated, "post-window reuse must extend the session"
    finally:
        state.db_manager = prior_db


async def test_f52_n_rapid_calls_bounded_to_one_extend(db_manager, jwt_env):
    from api.app_state import state
    from giljo_mcp.models import MCPSession

    raw_key, tenant_key = await _seed_api_key(db_manager)

    prior_db = state.db_manager
    state.db_manager = db_manager
    try:
        session_id = await _mint_session(db_manager, raw_key)
        assert await _reuse(db_manager, raw_key, session_id) == 200

        async with db_manager.get_session_async() as db:
            with tenant_session_context(db, tenant_key):
                row = (await db.execute(select(MCPSession).where(MCPSession.session_id == session_id))).scalar_one()
                row.last_accessed = datetime.now(UTC) - timedelta(hours=2)
                backdated = row.last_accessed
                await db.commit()

        for _ in range(20):
            assert await _reuse(db_manager, raw_key, session_id) == 200

        async with db_manager.get_session_async() as db:
            with tenant_session_context(db, tenant_key):
                row = (await db.execute(select(MCPSession).where(MCPSession.session_id == session_id))).scalar_one()
                assert row.last_accessed == backdated, "20 rapid reuses must issue ZERO extra extends"
    finally:
        state.db_manager = prior_db




async def test_f53_ip_log_sampled_within_window(db_manager):
    from api.endpoints.mcp_session import MCPSessionManager
    from giljo_mcp.models.auth import ApiKeyIpLog

    _raw_key, tenant_key = await _seed_api_key(db_manager)
    api_key_id = await _api_key_id(db_manager, tenant_key)
    ip = "203.0.113.7"

    async def _log(addr):
        async with db_manager.get_session_async() as db:
            await MCPSessionManager(db).log_ip(api_key_id, addr)

    async def _count(addr):
        async with db_manager.get_session_async() as db:
            with tenant_session_context(db, tenant_key):
                row = (
                    await db.execute(
                        select(ApiKeyIpLog).where(ApiKeyIpLog.api_key_id == api_key_id, ApiKeyIpLog.ip_address == addr)
                    )
                ).scalar_one_or_none()
                return row.request_count if row else 0

    await _log(ip)
    assert await _count(ip) == 1, "first contact logs the IP"
    await _log(ip)
    assert await _count(ip) == 1, "rapid repeat from same (key, ip) must be sampled out"

    other = "203.0.113.99"
    await _log(other)
    assert await _count(other) == 1, "a new (key, ip) pair must log on first contact"

    debounce.reset()
    await _log(ip)
    assert await _count(ip) == 2, "post-window repeat increments the audit count"




async def test_f54_within_window_does_not_advance_last_accessed(db_manager, jwt_env, mcp_canonical_uri_env):
    from api.app_state import state
    from api.endpoints.mcp_sdk_server import MCPAuthMiddleware
    from giljo_mcp.models import MCPSession

    raw_key, tenant_key = await _seed_api_key(db_manager)

    def _reuse_request():
        return _drive_middleware_with_body(
            MCPAuthMiddleware(app=_CapturingProbe()),
            headers=[
                (b"x-api-key", raw_key.encode()),
                (b"mcp-protocol-version", b"2025-06-18"),
                (b"mcp-session-id", session_id.encode("ascii")),
                (b"content-type", b"application/json"),
            ],
            body=_jsonrpc_body("tools/list"),
        )

    prior_db = state.db_manager
    state.db_manager = db_manager
    try:
        _status, init_headers, _b = await _drive_middleware_with_body(
            MCPAuthMiddleware(app=_CapturingProbe()),
            headers=[(b"x-api-key", raw_key.encode()), (b"content-type", b"application/json")],
            body=_jsonrpc_body("initialize", params={"protocolVersion": "2025-06-18", "capabilities": {}}),
        )
        session_id = init_headers.get("mcp-session-id")
        assert session_id

        status, _h, _b = await _reuse_request()
        assert status == 200

        async with db_manager.get_session_async() as db:
            with tenant_session_context(db, tenant_key):
                row = (await db.execute(select(MCPSession).where(MCPSession.session_id == session_id))).scalar_one()
                row.last_accessed = datetime.now(UTC) - timedelta(hours=1)
                backdated = row.last_accessed
                await db.commit()

        status, _h, _b = await _reuse_request()
        assert status == 200

        async with db_manager.get_session_async() as db:
            with tenant_session_context(db, tenant_key):
                row = (await db.execute(select(MCPSession).where(MCPSession.session_id == session_id))).scalar_one()
                assert row.last_accessed == backdated, "reuse within window must NOT extend the session"
    finally:
        state.db_manager = prior_db


class _CapturingProbe:

    async def __call__(self, scope, receive, send) -> None:
        await receive()
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b'{"jsonrpc":"2.0","id":1,"result":{}}'})
