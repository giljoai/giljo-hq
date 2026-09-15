# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from datetime import UTC, datetime, timedelta
from uuid import uuid4

import bcrypt
import jwt
import pytest
import pytest_asyncio


CANONICAL_MCP_URI = "http://test/mcp"
JWT_SECRET = "test_secret_key"
JWT_ALG = "HS256"


def _make_jwt(*, aud: str | None, tenant_key: str, sub: str | None = None) -> str:
    sub_value = sub or str(uuid4())
    payload: dict = {
        "sub": sub_value,
        "username": "regression_user",
        "role": "developer",
        "tenant_key": tenant_key,
        "type": "access",
        "iat": datetime.now(UTC),
        "exp": datetime.now(UTC) + timedelta(hours=1),
    }
    if aud is not None:
        payload["aud"] = aud
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALG)


class _CapturingInnerApp:

    def __init__(self) -> None:
        self.called: bool = False
        self.tenant_key_seen: str | None = None

    async def __call__(self, scope, receive, send) -> None:
        self.called = True
        self.tenant_key_seen = scope.get("state", {}).get("tenant_key")
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"OK"})


async def _drive_middleware(middleware, headers: list[tuple[bytes, bytes]]) -> tuple[int, dict[str, str], bytes]:
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

    captured_status: dict = {"code": 0}
    captured_headers: dict[str, str] = {}
    captured_body = bytearray()

    async def receive() -> dict:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message) -> None:
        if message["type"] == "http.response.start":
            captured_status["code"] = message["status"]
            for k, v in message.get("headers", []):
                key = k.decode("latin-1") if isinstance(k, bytes) else k
                val = v.decode("latin-1") if isinstance(v, bytes) else v
                captured_headers[key.lower()] = val
        elif message["type"] == "http.response.body":
            captured_body.extend(message.get("body", b""))

    await middleware(scope, receive, send)
    return captured_status["code"], captured_headers, bytes(captured_body)


@pytest_asyncio.fixture
async def jwt_env(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", JWT_SECRET)
    yield JWT_SECRET




class TestR1ApiKeyStillAuthenticates:

    @pytest.mark.asyncio
    async def test_api_key_via_x_api_key_header_authenticates(
        self,
        db_manager,
        jwt_env,
    ):
        from api.app_state import state
        from api.endpoints.mcp_sdk_server import MCPAuthMiddleware
        from giljo_mcp.api_key_utils import hash_api_key
        from giljo_mcp.models.auth import APIKey, User
        from giljo_mcp.models.organizations import Organization
        from giljo_mcp.tenant import TenantManager

        tenant_key = TenantManager.generate_tenant_key()
        unique = uuid4().hex[:8]
        raw_key = f"gk_apikeyR1_{uuid4().hex}"
        key_hash = hash_api_key(raw_key)

        async with db_manager.get_session_async() as session:
            org = Organization(
                name=f"R1 Org {unique}",
                slug=f"r1-org-{unique}",
                tenant_key=tenant_key,
                is_active=True,
            )
            session.add(org)
            await session.flush()

            user = User(
                username=f"r1_user_{unique}",
                email=f"r1_{unique}@example.com",
                password_hash=bcrypt.hashpw(b"pw", bcrypt.gensalt()).decode("utf-8"),
                tenant_key=tenant_key,
                role="developer",
                org_id=org.id,
                is_active=True,
            )
            session.add(user)
            await session.flush()

            api_key = APIKey(
                id=str(uuid4()),
                tenant_key=tenant_key,
                user_id=user.id,
                name=f"R1 Key {unique}",
                key_hash=key_hash,
                key_prefix=f"{raw_key[:12]}...",
                permissions=["*"],
                is_active=True,
                created_at=datetime.now(UTC),
            )
            session.add(api_key)
            await session.commit()

        prior_db_manager = state.db_manager
        state.db_manager = db_manager
        try:
            inner = _CapturingInnerApp()
            mw = MCPAuthMiddleware(app=inner)
            status, _headers, _body = await _drive_middleware(mw, headers=[(b"x-api-key", raw_key.encode())])
            assert status == 200, f"API-key auth returned {status}"
            assert inner.called is True
            assert inner.tenant_key_seen == tenant_key
        finally:
            state.db_manager = prior_db_manager




class TestR2LegacyAudlessJwtRejected:

    @pytest.mark.asyncio
    async def test_audless_jwt_returns_401_with_www_authenticate(
        self,
        jwt_env,
    ):
        from api.endpoints.mcp_sdk_server import MCPAuthMiddleware
        from giljo_mcp.tenant import TenantManager

        tenant_key = TenantManager.generate_tenant_key()
        token = _make_jwt(aud=None, tenant_key=tenant_key)

        inner = _CapturingInnerApp()
        mw = MCPAuthMiddleware(app=inner)
        status, headers, _body = await _drive_middleware(mw, headers=[(b"authorization", f"Bearer {token}".encode())])

        assert status == 401, f"aud-less JWT must hard-reject, got {status}"
        assert inner.called is False, "inner app must NOT be invoked for aud-less JWT"

        www_auth = headers.get("www-authenticate", "")
        assert www_auth, "WWW-Authenticate header missing on 401"
        assert "Bearer" in www_auth and 'realm="MCP"' in www_auth
        assert "/.well-known/oauth-protected-resource" in www_auth, (
            f"resource_metadata pointer missing from WWW-Authenticate: {www_auth}"
        )




class TestR3AudBoundJwtAccepted:

    @pytest.mark.asyncio
    async def test_aud_bound_jwt_authenticates(self, db_manager, jwt_env):
        from api.app_state import state
        from api.endpoints.mcp_sdk_server import MCPAuthMiddleware
        from giljo_mcp.models.auth import User
        from giljo_mcp.models.organizations import Organization
        from giljo_mcp.tenant import TenantManager

        tenant_key = TenantManager.generate_tenant_key()
        unique = uuid4().hex[:8]

        async with db_manager.get_session_async(tenant_key=tenant_key) as session:
            org = Organization(name=f"R3 Org {unique}", slug=f"r3-org-{unique}", tenant_key=tenant_key, is_active=True)
            session.add(org)
            await session.flush()
            user = User(
                id=str(uuid4()),
                username=f"r3_user_{unique}",
                email=f"r3_{unique}@example.com",
                password_hash=bcrypt.hashpw(b"pw", bcrypt.gensalt()).decode("utf-8"),
                tenant_key=tenant_key,
                role="developer",
                org_id=org.id,
                is_active=True,
            )
            session.add(user)
            await session.commit()
            user_id = user.id

        token = _make_jwt(aud=CANONICAL_MCP_URI, tenant_key=tenant_key, sub=user_id)

        prior_db = state.db_manager
        state.db_manager = db_manager
        try:
            inner = _CapturingInnerApp()
            mw = MCPAuthMiddleware(app=inner)
            status, _headers, _body = await _drive_middleware(
                mw, headers=[(b"authorization", f"Bearer {token}".encode())]
            )
            assert status == 200, f"aud-bound JWT returned {status}"
            assert inner.called is True
            assert inner.tenant_key_seen == tenant_key
        finally:
            state.db_manager = prior_db




class TestR4WrongAudRejected:

    @pytest.mark.asyncio
    async def test_wrong_aud_returns_401_with_www_authenticate(self, jwt_env):
        from api.endpoints.mcp_sdk_server import MCPAuthMiddleware
        from giljo_mcp.tenant import TenantManager

        tenant_key = TenantManager.generate_tenant_key()
        token = _make_jwt(aud="https://attacker.example/mcp", tenant_key=tenant_key)

        inner = _CapturingInnerApp()
        mw = MCPAuthMiddleware(app=inner)
        status, headers, _body = await _drive_middleware(mw, headers=[(b"authorization", f"Bearer {token}".encode())])
        assert status == 401, f"wrong-aud JWT returned {status}"
        assert inner.called is False, "inner app must NOT be invoked for wrong-aud"

        www_auth = headers.get("www-authenticate", "")
        assert www_auth, "WWW-Authenticate header missing on 401"
        assert "Bearer" in www_auth and 'realm="MCP"' in www_auth
        assert "/.well-known/oauth-protected-resource" in www_auth, (
            f"resource_metadata pointer missing from WWW-Authenticate: {www_auth}"
        )




class TestR5UnauthenticatedReturns401WithHeader:

    @pytest.mark.asyncio
    async def test_unauthenticated_returns_401_with_www_authenticate(self, jwt_env):
        from api.endpoints.mcp_sdk_server import MCPAuthMiddleware

        inner = _CapturingInnerApp()
        mw = MCPAuthMiddleware(app=inner)
        status, headers, _body = await _drive_middleware(mw, headers=[])

        assert status == 401
        assert inner.called is False
        www_auth = headers.get("www-authenticate", "")
        assert www_auth, "WWW-Authenticate header missing on 401"
        assert "Bearer" in www_auth and 'realm="MCP"' in www_auth
        assert "/.well-known/oauth-protected-resource" in www_auth




class TestR6ProtectedResourceMetadata:

    @pytest.mark.asyncio
    async def test_returns_200_with_required_fields(self, api_client):
        response = await api_client.get("/.well-known/oauth-protected-resource")
        assert response.status_code == 200, response.text
        body = response.json()

        assert "resource" in body, body
        assert body["resource"].endswith("/mcp"), body["resource"]
        assert "authorization_servers" in body
        assert isinstance(body["authorization_servers"], list)
        assert len(body["authorization_servers"]) >= 1
        assert "bearer_methods_supported" in body
        assert "header" in body["bearer_methods_supported"]
        assert "scopes_supported" in body
        assert isinstance(body["scopes_supported"], list)




class TestR7AuthorizationServerRootMirror:

    @pytest.mark.asyncio
    async def test_root_mirror_matches_api_oauth_body(self, api_client):
        api_resp = await api_client.get("/api/oauth/.well-known/oauth-authorization-server")
        assert api_resp.status_code == 200

        root_resp = await api_client.get("/.well-known/oauth-authorization-server")
        assert root_resp.status_code == 200, root_resp.text

        assert root_resp.json() == api_resp.json(), (
            "root mirror body must match /api/oauth/.well-known/oauth-authorization-server"
        )




class TestR8ProtectedResourceScopesSupported:
    @pytest.mark.asyncio
    async def test_scopes_supported_advertises_grantable_scopes(self, api_client):
        from giljo_mcp.services.oauth_service import OAUTH_GRANTABLE_SCOPES

        response = await api_client.get("/.well-known/oauth-protected-resource")
        assert response.status_code == 200
        body = response.json()
        scopes = set(body.get("scopes_supported", []))
        assert scopes == set(OAUTH_GRANTABLE_SCOPES), (
            f"scopes_supported must equal OAUTH_GRANTABLE_SCOPES, got: {sorted(scopes)}"
        )
        assert "mcp:agent" in scopes, "BE-6168: mcp:agent must be advertised as grantable"




class TestR9AudlessJwtHardRejectedAtMcpRoute:
    @pytest.mark.asyncio
    async def test_audless_jwt_post_mcp_returns_401_with_www_authenticate(
        self,
        api_client,
        jwt_env,
    ):
        from giljo_mcp.tenant import TenantManager

        tenant_key = TenantManager.generate_tenant_key()
        token = _make_jwt(aud=None, tenant_key=tenant_key)

        response = await api_client.post(
            "/mcp",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream",
            },
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
        )

        assert response.status_code == 401, (
            f"aud-less JWT must be hard-rejected at /mcp, got {response.status_code}: {response.text[:200]}"
        )
        www_auth = response.headers.get("www-authenticate", "")
        assert www_auth, "WWW-Authenticate header missing on 401"
        assert "Bearer" in www_auth and 'realm="MCP"' in www_auth, www_auth
        assert "/.well-known/oauth-protected-resource" in www_auth, (
            f"resource_metadata pointer missing from WWW-Authenticate: {www_auth}"
        )
