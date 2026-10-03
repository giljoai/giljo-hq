# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import json
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy.exc import OperationalError


def _db_down() -> OperationalError:
    return OperationalError("SELECT 1", {}, Exception("connection refused"))


class _InnerOk:
    async def __call__(self, scope, receive, send) -> None:
        await receive()
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"{}"})


async def _drive(mw, *, path: str, headers: list[tuple[bytes, bytes]]) -> tuple[int, bytes]:
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}).encode()
    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "method": "POST",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "headers": [*headers, (b"content-type", b"application/json")],
        "client": (f"2001:db8::{uuid4().hex[:4]}", 12345),
        "server": ("api.example.test", 443),
        "scheme": "https",
        "root_path": "",
    }
    captured: dict = {"code": 0, "body": bytearray()}
    sent = {"done": False}

    async def receive() -> dict:
        if sent["done"]:
            return {"type": "http.disconnect"}
        sent["done"] = True
        return {"type": "http.request", "body": body, "more_body": False}

    async def send(message) -> None:
        if message["type"] == "http.response.start":
            captured["code"] = message["status"]
        elif message["type"] == "http.response.body":
            captured["body"].extend(message.get("body", b""))

    await mw(scope, receive, send)
    return captured["code"], bytes(captured["body"])


class TestMcpApiKeyTransport:
    @pytest.mark.asyncio
    async def test_session_manager_lets_the_database_error_raise(self, db_manager, monkeypatch):
        from api.endpoints.mcp_session import MCPSessionManager
        from giljo_mcp.auth import principal

        async def _boom(db, key):
            raise _db_down()

        monkeypatch.setattr(principal, "_resolve_api_key", _boom)
        async with db_manager.get_session_async() as db:
            with pytest.raises(OperationalError):
                await MCPSessionManager(db).authenticate_api_key(f"gk_{uuid4().hex}")

    @pytest.mark.asyncio
    async def test_middleware_answers_503_and_does_not_count_the_ip(self, db_manager, monkeypatch):
        from api.app_state import state
        from api.endpoints import mcp_auth_middleware as mw_module
        from api.endpoints.mcp_sdk_server import MCPAuthMiddleware
        from giljo_mcp.auth import principal

        async def _boom(db, key):
            raise _db_down()

        counted: list[object] = []

        async def _count(request):
            counted.append(request)

        monkeypatch.setattr(principal, "_resolve_api_key", _boom)
        monkeypatch.setattr("api.middleware.auth_rate_limiter.enforce_api_key_auth_failure", _count, raising=True)
        assert mw_module is not None
        prior_db = state.db_manager
        state.db_manager = db_manager
        try:
            status, body = await _drive(
                MCPAuthMiddleware(app=_InnerOk()),
                path="/mcp",
                headers=[(b"x-api-key", f"gk_{uuid4().hex}".encode())],
            )
        finally:
            state.db_manager = prior_db
        assert status == 503, f"a database fault must be a 503, got {status}: {body!r}"
        assert counted == [], "a server fault is not a failed login and must not count against the IP"


class TestRestAuthPath:
    @pytest.mark.asyncio
    async def test_api_key_user_lookup_fault_raises(self, db_manager, monkeypatch):
        from giljo_mcp.auth_manager import AuthManager

        class _Session:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc):
                return False

            info: dict = {}

            async def execute(self, stmt):
                raise _db_down()

        class _DbManager:
            def get_session_async(self):
                return _Session()

        request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(db_manager=_DbManager())))

        manager = AuthManager.__new__(AuthManager)
        key_info = {"name": "k", "tenant_key": "t", "user_id": str(uuid4()), "permissions": ["*"]}
        with pytest.raises(OperationalError):
            await manager._build_api_key_result(key_info, request)

    @pytest.mark.asyncio
    async def test_middleware_answers_503_on_a_database_fault(self, monkeypatch):
        from api.middleware.auth import AuthMiddleware

        class _Auth:
            async def authenticate_request(self, request):
                raise _db_down()

        auth = _Auth()
        mw = AuthMiddleware(app=_InnerOk(), auth_manager=lambda: auth)
        status, body = await _drive(mw, path="/api/products", headers=[(b"x-api-key", b"gk_x")])
        assert status == 503, f"expected 503, got {status}: {body!r}"
        assert b"unavailable" in body.lower()

    def test_missing_jwt_secret_is_not_an_invalid_token(self, monkeypatch):
        from giljo_mcp.auth.jwt_manager import JWTManager

        def _no_secret():
            raise RuntimeError("JWT secret is not configured")

        monkeypatch.setattr(JWTManager, "_get_secret_key", staticmethod(_no_secret))
        with pytest.raises(RuntimeError):
            JWTManager.verify_token_allow_expired("not-a-token")
