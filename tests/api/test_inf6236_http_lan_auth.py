# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from uuid import uuid4

import bcrypt
import pytest
from fastapi import WebSocketException

from api.auth_utils import authenticate_websocket
from giljo_mcp.auth.jwt_manager import JWTManager
from giljo_mcp.models.auth import User
from giljo_mcp.models.organizations import Organization
from giljo_mcp.tenant import TenantManager


class _CookieWebSocket:

    def __init__(self, cookie_header: str) -> None:
        self.query_params: dict[str, str] = {}
        self.headers: dict[str, str] = {"cookie": cookie_header}


async def _seed_user(db_session) -> tuple[str, str, str, str]:
    tk = TenantManager.generate_tenant_key()
    unique = uuid4().hex[:8]

    org = Organization(
        name=f"INF6236 Org {unique}",
        slug=f"inf6236-org-{unique}",
        tenant_key=tk,
        is_active=True,
    )
    db_session.add(org)
    await db_session.flush()

    user_id = str(uuid4())
    username = f"inf6236_user_{unique}"
    user = User(
        id=user_id,
        username=username,
        email=f"inf6236_{unique}@example.com",
        password_hash=bcrypt.hashpw(b"pw", bcrypt.gensalt()).decode("utf-8"),
        tenant_key=tk,
        role="developer",
        org_id=org.id,
        is_active=True,
    )
    db_session.add(user)
    await db_session.flush()

    return user_id, username, "developer", tk


class TestWebSocketAuthOverHttp:

    @pytest.mark.asyncio
    async def test_non_secure_cookie_authenticates(self, db_session):
        user_id, username, role, tk = await _seed_user(db_session)
        token = JWTManager.create_access_token(user_id=user_id, username=username, role=role, tenant_key=tk)

        ws = _CookieWebSocket(cookie_header=f"access_token={token}")

        result = await authenticate_websocket(ws, db=db_session)

        assert result["authenticated"] is True, "a valid http (non-Secure) cookie must authenticate the WS"
        assert result["user"]["tenant_key"] == tk

    @pytest.mark.asyncio
    async def test_garbage_cookie_rejected(self, db_session):
        await _seed_user(db_session)
        ws = _CookieWebSocket(cookie_header="access_token=not-a-real-jwt")

        with pytest.raises(WebSocketException):
            await authenticate_websocket(ws, db=db_session)
