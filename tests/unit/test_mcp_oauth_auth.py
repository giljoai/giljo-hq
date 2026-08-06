# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""Tests for MCP authentication (Handover 0828 + 0846; BE-9066 re-target).

Test coverage:
- MCPSessionManager.create_session mints one row per connection (no reuse lookup)
- MCPAuthMiddleware extracts JWT and API key credentials from headers
"""

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest


def _mock_db() -> AsyncMock:
    """A mock AsyncSession for the pure-INSERT create_session path (BE-9066)."""
    mock_db = AsyncMock()
    mock_db.execute = AsyncMock()
    mock_db.commit = AsyncMock()
    mock_db.add = MagicMock()
    mock_db.refresh = AsyncMock()
    mock_db.info = {}  # tenant_session_context save/restore target
    return mock_db


class TestMCPSessionManagerJWT:
    """Tests for MCPSessionManager.create_session() on the JWT (key-less) path.

    BE-9066 re-target: the old ``get_or_create_session_from_jwt`` reused one row
    per (user, tenant) — the last-writer-wins contamination. ``create_session``
    is an unconditional INSERT: no reuse SELECT, one row per connection.
    """

    @pytest.mark.asyncio
    async def test_creates_new_session_row(self):
        """Should create a new MCPSession with api_key_id=None for JWT auth."""
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
        # Verify db.add was called (new session created)
        mock_db.add.assert_called_once()
        added_session = mock_db.add.call_args[0][0]
        assert added_session.api_key_id is None
        assert added_session.user_id == user_id
        assert added_session.tenant_key == tenant_key

    @pytest.mark.asyncio
    async def test_no_reuse_lookup_is_performed(self):
        """BE-9066: minting must be a pure INSERT — no reuse SELECT, no dedup
        DELETE (the old per-principal lookup is the removed behavior)."""
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
        """Two connects for the SAME (user, tenant) mint TWO rows — the old code
        returned the first row for both (per-connection re-target)."""
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
        """New JWT session should have proper session_data defaults."""
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
    """Tests for MCPAuthMiddleware ASGI dispatch (Handover 0846 — SDK auth layer).

    These drive the real middleware __call__ through a minimal ASGI harness:
    empty body (method peeks as None), no MCP-Protocol-Version header (version
    validation passes), no Mcp-Session-Id (non-initialize lifecycle is a
    passthrough), and no jti in the JWT payload (revocation check skipped). That
    exercises the actual auth dispatch — credential extraction, JWT verification,
    RFC 8707 audience rejection, and tenant injection into scope state — instead
    of re-testing Starlette's header parsing.
    """

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
        """No Authorization/X-API-Key header -> 401 with WWW-Authenticate; inner app not called."""
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
        """A JWT for a different resource server is rejected (RFC 8707) with no API-key fallback."""
        from api.endpoints import mcp_sdk_server
        from api.endpoints.mcp_sdk_server import MCPAuthMiddleware

        app = AsyncMock()
        middleware = MCPAuthMiddleware(app=app)
        messages = []
        scope = self._http_scope([(b"authorization", b"Bearer some.jwt.token")])

        with patch.object(
            mcp_sdk_server.JWTManager,
            "verify_token",
            side_effect=mcp_sdk_server.JWTAudienceMismatchError("wrong audience"),
        ):
            await middleware(scope, self._empty_receive, self._capture_send(messages))

        start = next(m for m in messages if m["type"] == "http.response.start")
        assert start["status"] == 401
        app.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_valid_jwt_injects_tenant_into_scope_state(self, test_tenant_key):
        """A valid JWT injects tenant_key/user_id/auth_method/scopes into the ASGI scope state."""
        from api.endpoints import mcp_sdk_server
        from api.endpoints.mcp_sdk_server import MCPAuthMiddleware

        user_id = str(uuid4())
        tenant_key = test_tenant_key  # properly-formatted key (TenantManager validates the format)
        payload = {
            "sub": user_id,
            "username": "jwt_user",
            "role": "developer",
            "tenant_key": tenant_key,
            "type": "access",
            # no jti -> revocation check skipped; no scope claim -> defaults to read+write
        }
        app = AsyncMock()
        middleware = MCPAuthMiddleware(app=app)
        scope = self._http_scope([(b"authorization", b"Bearer valid.jwt.token")])
        messages = []

        # This unit test isolates the claims -> scope-state mapping. SEC-3001a
        # added a DB-backed is_active re-check on the JWT path; null db_manager
        # here so the middleware deterministically skips that DB read (the
        # is_active enforcement is covered end-to-end by
        # tests/api/test_sec3001a_mcp_deactivation.py). Without this the result
        # would depend on whatever db_manager another xdist sibling left on the
        # shared module-level state.
        from api.app_state import state as _app_state

        prior_db = _app_state.db_manager
        _app_state.db_manager = None
        try:
            with patch.object(mcp_sdk_server.JWTManager, "verify_token", return_value=payload):
                await middleware(scope, self._empty_receive, self._capture_send(messages))
        finally:
            _app_state.db_manager = prior_db

        app.assert_awaited_once()  # request passed through to the inner SDK app
        assert scope["state"]["tenant_key"] == tenant_key
        assert scope["state"]["user_id"] == user_id
        assert scope["state"]["auth_method"] == "jwt"
        assert scope["state"]["scopes"] == ["mcp:read", "mcp:write"]
