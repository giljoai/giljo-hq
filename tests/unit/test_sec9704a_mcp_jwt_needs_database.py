# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from api.app_state import state
from api.endpoints.mcp_auth_middleware import MCPAuthMiddleware
from giljo_mcp.auth.jwt_manager import JWTManager
from giljo_mcp.tenant import TenantManager


def _scope() -> dict:
    return {
        "type": "http",
        "method": "POST",
        "path": "/mcp",
        "raw_path": b"/mcp",
        "query_string": b"",
        "scheme": "http",
        "server": ("testserver", 80),
        "client": ("127.0.0.1", 12345),
        "headers": [(b"host", b"testserver"), (b"authorization", b"Bearer valid.jwt.token")],
    }


async def _receive():
    return {"type": "http.request", "body": b"", "more_body": False}


@pytest.mark.asyncio
async def test_a_valid_jwt_without_a_database_is_refused(monkeypatch):
    payload = {
        "sub": str(uuid4()),
        "username": "jwt_user",
        "role": "developer",
        "tenant_key": TenantManager.generate_tenant_key(),
        "type": "access",
    }
    monkeypatch.setattr(state, "db_manager", None)
    monkeypatch.setattr(JWTManager, "verify_token", lambda *a, **k: payload)
    inner = AsyncMock()
    messages: list[dict] = []

    async def _send(message):
        messages.append(message)

    await MCPAuthMiddleware(app=inner)(_scope(), _receive, _send)

    inner.assert_not_awaited()
    start = next(m for m in messages if m["type"] == "http.response.start")
    assert start["status"] == 503
