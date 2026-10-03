# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from api import app_state


def _session_db_manager() -> MagicMock:
    manager = MagicMock()
    manager.get_session_async.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
    manager.get_session_async.return_value.__aexit__ = AsyncMock(return_value=False)
    return manager


def _mock_db() -> AsyncMock:
    mock_db = AsyncMock()
    mock_db.execute = AsyncMock()
    mock_db.commit = AsyncMock()
    mock_db.add = MagicMock()
    mock_db.refresh = AsyncMock()
    mock_db.info = {}
    return mock_db


class TestMCPSessionManagerJWT:

    @pytest.mark.asyncio
    async def test_creates_new_session_row(self):
        from api.endpoints.mcp_session import MCPSessionManager

        user_id = str(uuid4())
        tenant_key = f"tk_{uuid4().hex[:12]}"

        mock_db = _mock_db()
        manager = MCPSessionManager(mock_db)
        session = await manager.create_session(
            tenant_key=tenant_key,
            user_id=user_id,
            auth_method="oauth_jwt",
            username="oauth_user",
        )

        assert session is not None
        mock_db.add.assert_called_once()
        added_session = mock_db.add.call_args[0][0]
        assert added_session.api_key_id is None
        assert added_session.user_id == user_id
        assert added_session.tenant_key == tenant_key

    @pytest.mark.asyncio
    async def test_no_reuse_lookup_is_performed(self):
        from api.endpoints.mcp_session import MCPSessionManager

        mock_db = _mock_db()
        manager = MCPSessionManager(mock_db)
        await manager.create_session(
            tenant_key=f"tk_{uuid4().hex[:12]}",
            user_id=str(uuid4()),
            auth_method="oauth_jwt",
            username="oauth_user",
        )

        mock_db.execute.assert_not_awaited()
        mock_db.add.assert_called_once()

    @pytest.mark.asyncio
    async def test_every_connect_mints_a_fresh_row(self):
        from api.endpoints.mcp_session import MCPSessionManager

        user_id = str(uuid4())
        tenant_key = f"tk_{uuid4().hex[:12]}"

        mock_db = _mock_db()
        manager = MCPSessionManager(mock_db)
        first = await manager.create_session(
            tenant_key=tenant_key, user_id=user_id, auth_method="oauth_jwt", username="oauth_user"
        )
        second = await manager.create_session(
            tenant_key=tenant_key, user_id=user_id, auth_method="oauth_jwt", username="oauth_user"
        )

        assert mock_db.add.call_count == 2
        assert first is not second

    @pytest.mark.asyncio
    async def test_session_data_initialized_correctly(self):
        from api.endpoints.mcp_session import MCPSessionManager

        user_id = str(uuid4())
        tenant_key = f"tk_{uuid4().hex[:12]}"

        mock_db = _mock_db()
        manager = MCPSessionManager(mock_db)
        await manager.create_session(
            tenant_key=tenant_key,
            user_id=user_id,
            auth_method="oauth_jwt",
            username="oauth_user",
        )

        added_session = mock_db.add.call_args[0][0]
        assert added_session.session_data["initialized"] is False
        assert "capabilities" in added_session.session_data
        assert "client_info" in added_session.session_data
        assert "tool_call_history" in added_session.session_data
        assert added_session.session_data["auth_method"] == "oauth_jwt"
        assert added_session.session_data["username"] == "oauth_user"


class TestMCPAuthMiddleware:

    @staticmethod
    def _http_scope(headers):
        return {
            "type": "http",
            "method": "POST",
            "path": "/mcp",
            "raw_path": b"/mcp",
            "query_string": b"",
            "scheme": "http",
            "server": ("testserver", 80),
            "client": ("127.0.0.1", 12345),
            "headers": [(b"host", b"testserver"), *headers],
        }

    @staticmethod
    async def _empty_receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    @staticmethod
    def _capture_send(messages):
        async def send(message):
            messages.append(message)

        return send

    @pytest.mark.asyncio
    async def test_no_credentials_returns_401(self):
        from api.endpoints.mcp_sdk_server import MCPAuthMiddleware

        app = AsyncMock()
        middleware = MCPAuthMiddleware(app=app)
        messages = []

        await middleware(self._http_scope([]), self._empty_receive, self._capture_send(messages))

        start = next(m for m in messages if m["type"] == "http.response.start")
        assert start["status"] == 401
        header_names = {k.lower() for k, _ in start["headers"]}
        assert b"www-authenticate" in header_names
        app.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_jwt_audience_mismatch_returns_401(self):
        from api.endpoints.mcp_sdk_server import MCPAuthMiddleware
        from giljo_mcp.auth import principal as principal_mod

        app = AsyncMock()
        middleware = MCPAuthMiddleware(app=app)
        messages = []
        scope = self._http_scope([(b"authorization", b"Bearer some.jwt.token")])
        refusal = principal_mod.PrincipalValidationError(
            principal_mod.AuthErrorReason.INVALID_AUDIENCE, "wrong audience"
        )

        with (
            patch.object(app_state.state, "db_manager", _session_db_manager()),
            patch.object(principal_mod, "validate_principal", AsyncMock(side_effect=refusal)),
        ):
            await middleware(scope, self._empty_receive, self._capture_send(messages))

        start = next(m for m in messages if m["type"] == "http.response.start")
        assert start["status"] == 401
        app.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_valid_jwt_injects_tenant_into_scope_state(self, test_tenant_key):
        from api.endpoints.mcp_sdk_server import MCPAuthMiddleware

        user_id = str(uuid4())
        tenant_key = test_tenant_key
        payload = {
            "sub": user_id,
            "username": "jwt_user",
            "role": "developer",
            "tenant_key": tenant_key,
            "type": "access",
        }
        app = AsyncMock()
        middleware = MCPAuthMiddleware(app=app)
        scope = self._http_scope([(b"authorization", b"Bearer valid.jwt.token")])
        messages = []

        from giljo_mcp.auth import principal as principal_mod

        principal = principal_mod.Principal(
            user_id=user_id,
            tenant_key=tenant_key,
            auth_method="jwt",
            user=MagicMock(must_change_password=False),
            username=payload["username"],
            role=payload["role"],
        )
        with (
            patch.object(app_state.state, "db_manager", _session_db_manager()),
            patch.object(principal_mod, "validate_principal", AsyncMock(return_value=principal)),
        ):
            await middleware(scope, self._empty_receive, self._capture_send(messages))

        app.assert_awaited_once()
        assert scope["state"]["tenant_key"] == tenant_key
        assert scope["state"]["user_id"] == user_id
        assert scope["state"]["auth_method"] == "jwt"
        assert scope["state"]["scopes"] == ["mcp:read", "mcp:write"]
        assert scope["state"]["must_change_password"] is False
