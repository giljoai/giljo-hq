# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import asyncio
import json
import uuid
from uuid import uuid4

import pytest
from sqlalchemy.exc import TimeoutError as PoolTimeoutError

from giljo_mcp.auth.jwt_manager import JWTManager
from giljo_mcp.http.url_resolver import get_canonical_mcp_resource_uri_from_scope
from giljo_mcp.tenant import TenantManager


pytestmark = pytest.mark.asyncio

SERVER_BUSY_BODY = {"error_code": "SERVER_BUSY", "message": "The server is busy. Try again in a moment."}


class _InnerApp:
    def __init__(self) -> None:
        self.reached = False

    async def __call__(self, scope, receive, send) -> None:
        self.reached = True
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"{}"})


class _FailingSession:

    def __init__(self, fault: BaseException) -> None:
        self._fault = fault
        self.info: dict = {}

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def execute(self, *args, **kwargs):
        raise self._fault

    async def commit(self):
        raise self._fault

    async def rollback(self):
        return None


class _FailingDbManager:
    def __init__(self, fault: BaseException) -> None:
        self._fault = fault

    def get_session_async(self):
        return _FailingSession(self._fault)


def _scope(headers: list[tuple[bytes, bytes]]) -> dict:
    return {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "method": "POST",
        "path": "/mcp",
        "raw_path": b"/mcp",
        "query_string": b"",
        "headers": [*headers, (b"content-type", b"application/json"), (b"accept", b"application/json")],
        "client": (f"2001:db8::{uuid4().hex[:4]}", 12345),
        "server": ("api.example.test", 443),
        "scheme": "https",
        "root_path": "",
    }


async def _drive(mw, *, method: str, headers: list[tuple[bytes, bytes]]) -> tuple[int, dict, bytes]:
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": {}}).encode()
    scope = _scope(headers)
    captured: dict = {"code": 0, "headers": {}, "body": bytearray()}
    sent = {"done": False}

    async def receive() -> dict:
        if sent["done"]:
            return {"type": "http.disconnect"}
        sent["done"] = True
        return {"type": "http.request", "body": body, "more_body": False}

    async def send(message) -> None:
        if message["type"] == "http.response.start":
            captured["code"] = message["status"]
            captured["headers"] = {k.decode().lower(): v.decode() for k, v in message.get("headers", [])}
        elif message["type"] == "http.response.body":
            captured["body"].extend(message.get("body", b""))

    await mw(scope, receive, send)
    return captured["code"], captured["headers"], bytes(captured["body"])


@pytest.fixture
def failing_db(monkeypatch):
    from api.app_state import state

    counted: list[object] = []

    async def _count(request):
        counted.append(request)

    monkeypatch.setattr("api.middleware.auth_rate_limiter.enforce_api_key_auth_failure", _count, raising=True)

    def _install(fault: BaseException) -> list[object]:
        monkeypatch.setattr(state, "db_manager", _FailingDbManager(fault))
        return counted

    return _install


def _api_key_headers() -> list[tuple[bytes, bytes]]:
    return [(b"x-api-key", f"gk_{uuid4().hex}".encode())]


def _jwt_headers() -> list[tuple[bytes, bytes]]:
    token = JWTManager.create_access_token(
        user_id=uuid.uuid4(),
        username="be9853",
        role="admin",
        tenant_key=TenantManager.generate_tenant_key(),
        audience=get_canonical_mcp_resource_uri_from_scope(_scope([])),
    )
    return [(b"authorization", f"Bearer {token}".encode())]


@pytest.mark.parametrize("method", ["initialize", "tools/list"])
@pytest.mark.parametrize("headers", [_api_key_headers, _jwt_headers], ids=["api_key", "jwt"])
@pytest.mark.parametrize("fault", [TimeoutError, PoolTimeoutError], ids=["connect_timeout", "pool_timeout"])
async def test_timeout_is_server_busy_and_never_dispatches(failing_db, fault, method, headers):
    from api.endpoints.mcp_sdk_server import MCPAuthMiddleware

    counted = failing_db(fault())
    inner = _InnerApp()

    status, response_headers, body = await _drive(MCPAuthMiddleware(app=inner), method=method, headers=headers())

    assert status == 503, f"a connect timeout must be the SERVER_BUSY 503, got {status}: {body!r}"
    assert json.loads(body) == SERVER_BUSY_BODY
    assert response_headers.get("retry-after") == "5"
    assert inner.reached is False, "an unauthenticated request must never reach the MCP app"
    assert counted == [], "a server fault is not a failed login and must not count against the IP"


async def test_cancellation_is_not_swallowed(failing_db):
    from api.endpoints.mcp_sdk_server import MCPAuthMiddleware

    failing_db(asyncio.CancelledError())
    inner = _InnerApp()

    with pytest.raises(asyncio.CancelledError):
        await _drive(MCPAuthMiddleware(app=inner), method="initialize", headers=_api_key_headers())
    assert inner.reached is False
