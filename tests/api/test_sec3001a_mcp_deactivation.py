# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import json
from uuid import uuid4

import bcrypt
import pytest
import pytest_asyncio


_CANONICAL_AUD = "http://test/mcp"


async def _drive_middleware(
    middleware,
    *,
    headers: list[tuple[bytes, bytes]],
    body: bytes,
) -> tuple[int, bool]:
    inner_called = {"flag": False}

    async def inner_app(scope, receive, send) -> None:
        inner_called["flag"] = True
        await receive()
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b'{"jsonrpc":"2.0","id":1,"result":{}}'})

    mw = middleware(inner_app)

    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "method": "POST",
        "path": "/mcp",
        "raw_path": b"/mcp",
        "query_string": b"",
        "headers": headers,
        "client": ("127.0.0.1", 12345),
        "server": ("test", 80),
        "scheme": "http",
        "root_path": "",
    }

    captured = {"code": 0}
    body_sent = {"done": False}

    async def receive() -> dict:
        if body_sent["done"]:
            return {"type": "http.disconnect"}
        body_sent["done"] = True
        return {"type": "http.request", "body": body, "more_body": False}

    async def send(message) -> None:
        if message["type"] == "http.response.start":
            captured["code"] = message["status"]

    await mw(scope, receive, send)
    return captured["code"], inner_called["flag"]


def _jsonrpc(method: str) -> bytes:
    return json.dumps({"jsonrpc": "2.0", "id": 1, "method": method}).encode("utf-8")


@pytest_asyncio.fixture
async def jwt_env(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "test_secret_key")
    yield "test_secret_key"


async def _seed_user(db_manager) -> tuple[str, str, str]:
    from giljo_mcp.models.auth import User
    from giljo_mcp.models.organizations import Organization
    from giljo_mcp.tenant import TenantManager

    tk = TenantManager.generate_tenant_key()
    unique = uuid4().hex[:8]

    async with db_manager.get_session_async(tenant_key=tk) as session:
        org = Organization(
            name=f"SEC3001a Org {unique}",
            slug=f"sec3001a-org-{unique}",
            tenant_key=tk,
            is_active=True,
        )
        session.add(org)
        await session.flush()

        user = User(
            id=str(uuid4()),
            username=f"sec3001a_user_{unique}",
            email=f"sec3001a_{unique}@example.com",
            password_hash=bcrypt.hashpw(b"pw", bcrypt.gensalt()).decode("utf-8"),
            tenant_key=tk,
            role="developer",
            org_id=org.id,
            is_active=True,
        )
        session.add(user)
        await session.commit()

    return user.id, user.username, tk


def _mint_jwt(*, user_id: str, username: str, tenant_key: str) -> str:
    from giljo_mcp.auth.jwt_manager import JWTManager

    return JWTManager.create_access_token(
        user_id=user_id,
        username=username,
        role="developer",
        tenant_key=tenant_key,
        audience=_CANONICAL_AUD,
        scope="mcp:read mcp:write",
    )


class TestDeactivatedUserJwtIs401:

    @pytest.mark.asyncio
    async def test_active_then_deactivated_jwt(self, db_manager, jwt_env):
        from sqlalchemy import update

        from api.app_state import state
        from api.endpoints.mcp_sdk_server import MCPAuthMiddleware
        from giljo_mcp.models.auth import User

        user_id, username, tenant_key = await _seed_user(db_manager)
        token = _mint_jwt(user_id=user_id, username=username, tenant_key=tenant_key)

        headers = [
            (b"authorization", f"Bearer {token}".encode()),
            (b"host", b"test"),
            (b"content-type", b"application/json"),
        ]
        body = _jsonrpc("tools/list")

        prior_db = state.db_manager
        state.db_manager = db_manager
        try:
            status, inner_called = await _drive_middleware(MCPAuthMiddleware, headers=headers, body=body)
            assert status == 200, f"active user's JWT must authenticate on /mcp, got {status}"
            assert inner_called is True, "active user's request must reach the inner SDK app"

            async with db_manager.get_session_async(tenant_key=tenant_key) as session:
                await session.execute(update(User).where(User.id == user_id).values(is_active=False))
                await session.commit()

            status2, inner_called2 = await _drive_middleware(MCPAuthMiddleware, headers=headers, body=body)
            assert status2 == 401, (
                f"deactivated user's still-valid JWT must 401 on /mcp (deactivation propagation), got {status2}"
            )
            assert inner_called2 is False, "a deactivated user's request must never reach the inner SDK app"
        finally:
            state.db_manager = prior_db
