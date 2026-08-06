# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
API endpoint tests for OAuth 2.1 Authorization Code flow with PKCE.

Tests the FastAPI endpoints that wrap the OAuthService:
- POST /api/oauth/authorize (consent processing, requires auth)
- POST /api/oauth/token (code-to-token exchange, public)
- GET /api/oauth/.well-known/oauth-authorization-server (metadata, public)

Test Strategy:
- Endpoint validation tests use the api_client fixture (httpx AsyncClient)
- Authenticated endpoints use the auth_headers fixture for JWT cookie injection
- Token endpoint tests create authorization codes via direct DB insertion
  to isolate endpoint behavior from service internals

Handover 0828 Phase 3.
"""

import base64
import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from giljo_mcp.services.oauth_service import BUILTIN_CLIENT_ID


def _generate_pkce_pair() -> tuple[str, str]:
    """Generate a valid PKCE code_verifier and code_challenge pair."""
    code_verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    code_challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return code_verifier, code_challenge


def _oauth_err_text(body: dict) -> str:
    """Flatten an OAuth error body to one searchable string.

    BE-6040: /token, /refresh and /revoke now emit the RFC 6749 §5.2 envelope
    (``{"error": ..., "error_description": ...}``); /authorize still raises the
    legacy ``{"error_code"/"message"/"detail"}`` shape. Concatenating every
    known field keeps these substring assertions shape-agnostic across both.
    """
    return " ".join(str(body.get(k, "")) for k in ("error", "error_description", "detail", "message"))


class TestOAuthMetadataEndpoint:
    """Tests for GET /api/oauth/.well-known/oauth-authorization-server."""

    @pytest.mark.asyncio
    async def test_metadata_endpoint_returns_correct_fields(self, api_client):
        """Metadata endpoint must return all required OAuth server metadata fields.

        RFC 8414 §2: endpoint URLs MUST be absolute. Pre-API-0021c-live-fix
        these were relative paths; updated when ``registration_endpoint`` was
        added so the response is fully spec-compliant.
        """
        response = await api_client.get("/api/oauth/.well-known/oauth-authorization-server")
        assert response.status_code == 200

        data = response.json()
        assert "issuer" in data
        # Absolute URLs (RFC 8414 §2)
        assert data["authorization_endpoint"].endswith("/oauth/authorize")
        assert data["authorization_endpoint"].startswith(("http://", "https://"))
        assert data["token_endpoint"].endswith("/api/oauth/token")
        assert data["token_endpoint"].startswith(("http://", "https://"))
        assert data["response_types_supported"] == ["code"]
        assert data["code_challenge_methods_supported"] == ["S256"]
        # API-0021e Phase 3: refresh_token grant added.
        assert data["grant_types_supported"] == ["authorization_code", "refresh_token"]

    @pytest.mark.asyncio
    async def test_metadata_endpoint_is_public(self, api_client):
        """Metadata endpoint must be accessible without authentication."""
        response = await api_client.get("/api/oauth/.well-known/oauth-authorization-server")
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_metadata_advertises_ce_dcr_endpoint(self, api_client):
        """REGRESSION (BE-6235): CE now ships a DCR endpoint at /api/oauth/register
        (returns the built-in public client, no new table) so OAuth harnesses can
        auto-attach. The AS metadata MUST advertise it as an absolute URL —
        otherwise an MCP client with no pre-known client_id has no way to obtain
        one and OAuth never completes. (Pre-BE-6235 CE omitted this field.)

        The handler reflects the module-global registration path, which CE wiring
        sets at app construction; set it explicitly here so the assertion is
        order-independent of the SaaS test that mutates the same global.
        """
        from api.endpoints.oauth import register_edition_registration_endpoint

        register_edition_registration_endpoint("/api/oauth/register")
        response = await api_client.get("/api/oauth/.well-known/oauth-authorization-server")
        assert response.status_code == 200
        data = response.json()
        reg = data.get("registration_endpoint")
        assert reg is not None, "CE must advertise its DCR registration_endpoint (BE-6235)"
        assert reg.endswith("/api/oauth/register")
        assert reg.startswith(("http://", "https://"))

    @pytest.mark.asyncio
    async def test_metadata_advertises_registration_endpoint_in_saas(self, api_client, monkeypatch):
        """REGRESSION (API-0021c live-fix): in SaaS mode the metadata
        response MUST advertise the absolute URL of the DCR endpoint.

        Without this, claude.ai (and other RFC 7591 clients that rely on
        spec discovery) fall back to ``<issuer>/register`` which is a 404
        on this server, causing connector setup to fail before consent.
        """
        monkeypatch.setenv("GILJO_MODE", "saas")
        from api.endpoints.oauth import register_edition_registration_endpoint

        register_edition_registration_endpoint("/private/oauth/register")
        response = await api_client.get("/api/oauth/.well-known/oauth-authorization-server")
        assert response.status_code == 200
        data = response.json()
        reg = data.get("registration_endpoint")
        assert reg is not None, "SaaS mode must advertise registration_endpoint"
        assert reg.endswith("/private/oauth/register")
        assert reg.startswith(("http://", "https://"))

    @pytest.mark.asyncio
    async def test_metadata_advertises_scopes_supported(self, api_client):
        """REGRESSION (API-0021i): RFC 8414 §3.2 RECOMMENDED ``scopes_supported``.

        AS metadata MUST advertise the OAuth scopes this server grants so
        spec-aware clients (claude.ai connector, MCP Inspector) know what
        to request at /authorize without trial-and-error. Mirrors the
        OAUTH_GRANTABLE_SCOPES frozenset already used by the protected-
        resource document.
        """
        response = await api_client.get("/api/oauth/.well-known/oauth-authorization-server")
        assert response.status_code == 200
        data = response.json()
        scopes = data.get("scopes_supported")
        assert isinstance(scopes, list) and scopes, "scopes_supported must be a non-empty list"
        assert all(isinstance(s, str) for s in scopes), "every scope must be a string"
        # BE-6168: mcp:agent is now grantable, so it joins the advertised set.
        from giljo_mcp.services.oauth_service import OAUTH_GRANTABLE_SCOPES

        assert scopes == sorted(OAUTH_GRANTABLE_SCOPES), "scopes_supported must equal sorted(OAUTH_GRANTABLE_SCOPES)"
        assert "mcp:agent" in scopes, "BE-6168: mcp:agent must be advertised"

    @pytest.mark.asyncio
    async def test_metadata_advertises_token_endpoint_auth_methods(self, api_client):
        """REGRESSION (API-0021i): RFC 8414 §3.2 ``token_endpoint_auth_methods_supported``.

        Reflects the real shape of the token endpoint after API-0021e
        Phase 1.1+1.2 (2026-05-10): JSON/form body credentials
        (``client_secret_post``), HTTP Basic Auth (``client_secret_basic``),
        and PKCE-only public clients (``none``). Without this claim,
        clients guess at auth shape and fall back to whichever method
        their library defaults to.
        """
        response = await api_client.get("/api/oauth/.well-known/oauth-authorization-server")
        assert response.status_code == 200
        data = response.json()
        methods = data.get("token_endpoint_auth_methods_supported")
        assert methods == ["client_secret_post", "client_secret_basic", "none"]

    @pytest.mark.asyncio
    async def test_openid_configuration_returns_404(self, api_client):
        """REGRESSION (API-0021i): unauthenticated GET of the OIDC discovery
        document MUST return 404 (NOT 401, NOT 403).

        We don't implement OIDC, but spec-aware clients probe this path
        opportunistically. A 401 here was misleading (it suggested the
        path existed but required auth); 404 correctly signals "OIDC not
        supported on this server" and lets clients fall back cleanly to
        plain OAuth 2.1.
        """
        response = await api_client.get("/.well-known/openid-configuration")
        assert response.status_code == 404, (
            f"OIDC discovery must 404 (not {response.status_code}); body: {response.text[:200]}"
        )


class TestOAuthTokenEndpoint:
    """Tests for POST /api/oauth/token."""

    @pytest.mark.asyncio
    async def test_token_endpoint_rejects_invalid_grant_type(self, api_client):
        """Token endpoint must reject grant types other than authorization_code."""
        response = await api_client.post(
            "/api/oauth/token",
            data={
                "grant_type": "client_credentials",
                "code": "some-code",
                "client_id": BUILTIN_CLIENT_ID,
                "code_verifier": "some-verifier",
                "redirect_uri": "http://localhost:3000/callback",
            },
        )
        assert response.status_code == 400
        # BE-6040: RFC 6749 §5.2 — wrong grant_type is the dedicated
        # `unsupported_grant_type` code, carried in the top-level `error` member.
        body = response.json()
        assert body["error"] == "unsupported_grant_type"
        assert "grant_type" in _oauth_err_text(body).lower()

    @pytest.mark.asyncio
    async def test_token_endpoint_rejects_bad_pkce(self, api_client, db_manager):
        """Token endpoint must reject requests where PKCE verification fails."""
        from giljo_mcp.models.auth import User
        from giljo_mcp.models.oauth import OAuthAuthorizationCode
        from giljo_mcp.models.organizations import Organization
        from giljo_mcp.tenant import TenantManager

        _verifier, challenge = _generate_pkce_pair()
        wrong_verifier = secrets.token_urlsafe(64)
        tenant_key = TenantManager.generate_tenant_key()
        code_value = secrets.token_urlsafe(64)

        async with db_manager.get_session_async() as session:
            org = Organization(
                name="OAuth Test Org",
                slug=f"oauth-test-{uuid4().hex[:8]}",
                tenant_key=tenant_key,
                is_active=True,
            )
            session.add(org)
            await session.flush()

            user = User(
                id=str(uuid4()),
                username=f"oauth_token_test_{uuid4().hex[:8]}",
                email=f"oauth_token_{uuid4().hex[:8]}@example.com",
                role="developer",
                tenant_key=tenant_key,
                is_active=True,
                org_id=org.id,
            )
            session.add(user)
            await session.flush()

            auth_code = OAuthAuthorizationCode(
                code=code_value,
                client_id=BUILTIN_CLIENT_ID,
                user_id=user.id,
                tenant_key=tenant_key,
                redirect_uri="http://localhost:3000/callback",
                code_challenge=challenge,
                code_challenge_method="S256",
                scope="mcp:read mcp:write",
                expires_at=datetime.now(UTC) + timedelta(minutes=10),
                used=False,
            )
            session.add(auth_code)
            await session.commit()

        response = await api_client.post(
            "/api/oauth/token",
            data={
                "grant_type": "authorization_code",
                "code": code_value,
                "client_id": BUILTIN_CLIENT_ID,
                "code_verifier": wrong_verifier,
                "redirect_uri": "http://localhost:3000/callback",
            },
        )
        assert response.status_code == 400
        body = response.json()
        # BE-6040: RFC 6749 §5.2 envelope carries the code in `error`.
        assert body.get("error") == "invalid_request", body
        # Security hardening: error detail must NOT reveal PKCE specifics
        detail_text = _oauth_err_text(body).lower()
        assert "pkce" not in detail_text, "Error should not leak PKCE details"
        assert "verifier" not in detail_text, "Error should not leak verifier details"

    @pytest.mark.asyncio
    async def test_token_endpoint_returns_jwt(self, api_client, db_manager):
        """Token endpoint must return a valid JWT on successful code exchange."""
        from giljo_mcp.models.auth import User
        from giljo_mcp.models.oauth import OAuthAuthorizationCode
        from giljo_mcp.models.organizations import Organization
        from giljo_mcp.tenant import TenantManager

        verifier, challenge = _generate_pkce_pair()
        tenant_key = TenantManager.generate_tenant_key()
        code_value = secrets.token_urlsafe(64)

        async with db_manager.get_session_async() as session:
            org = Organization(
                name="OAuth JWT Test Org",
                slug=f"oauth-jwt-{uuid4().hex[:8]}",
                tenant_key=tenant_key,
                is_active=True,
            )
            session.add(org)
            await session.flush()

            user = User(
                id=str(uuid4()),
                username=f"oauth_jwt_test_{uuid4().hex[:8]}",
                email=f"oauth_jwt_{uuid4().hex[:8]}@example.com",
                role="developer",
                tenant_key=tenant_key,
                is_active=True,
                org_id=org.id,
            )
            session.add(user)
            await session.flush()

            auth_code = OAuthAuthorizationCode(
                code=code_value,
                client_id=BUILTIN_CLIENT_ID,
                user_id=user.id,
                tenant_key=tenant_key,
                redirect_uri="http://localhost:3000/callback",
                code_challenge=challenge,
                code_challenge_method="S256",
                scope="mcp:read mcp:write",
                expires_at=datetime.now(UTC) + timedelta(minutes=10),
                used=False,
            )
            session.add(auth_code)
            await session.commit()

        response = await api_client.post(
            "/api/oauth/token",
            data={
                "grant_type": "authorization_code",
                "code": code_value,
                "client_id": BUILTIN_CLIENT_ID,
                "code_verifier": verifier,
                "redirect_uri": "http://localhost:3000/callback",
            },
        )
        assert response.status_code == 200

        data = response.json()
        assert "access_token" in data
        assert data["token_type"] == "bearer"
        assert data["expires_in"] == 86400
        assert data["access_token"].count(".") == 2

    @pytest.mark.asyncio
    async def test_token_endpoint_issues_string_refresh_token_for_public_client(self, api_client, db_manager):
        """Public (PKCE) clients now receive a rotating refresh token (BE-6161), and it
        MUST be a non-empty string — never ``"refresh_token": null`` on the wire (BE-6155a).

        BE-6161: public CLI clients (Codex/Claude Code/Gemini) get a one-time-use rotating
        refresh token so their sessions survive access-token expiry instead of forcing a
        daily re-login. The BE-6155a guard still holds: Claude Code's strict OAuth client
        rejects ``refresh_token: null`` ("expected string, received null"); a real string
        value satisfies it (and ``response_model_exclude_none`` still prevents any null
        literal for the companion ``refresh_expires_in`` field).
        """
        from giljo_mcp.models.auth import User
        from giljo_mcp.models.oauth import OAuthAuthorizationCode
        from giljo_mcp.models.organizations import Organization
        from giljo_mcp.tenant import TenantManager

        verifier, challenge = _generate_pkce_pair()
        tenant_key = TenantManager.generate_tenant_key()
        code_value = secrets.token_urlsafe(64)

        async with db_manager.get_session_async() as session:
            org = Organization(
                name="OAuth NoRefresh Test Org",
                slug=f"oauth-noref-{uuid4().hex[:8]}",
                tenant_key=tenant_key,
                is_active=True,
            )
            session.add(org)
            await session.flush()

            user = User(
                id=str(uuid4()),
                username=f"oauth_noref_test_{uuid4().hex[:8]}",
                email=f"oauth_noref_{uuid4().hex[:8]}@example.com",
                role="developer",
                tenant_key=tenant_key,
                is_active=True,
                org_id=org.id,
            )
            session.add(user)
            await session.flush()

            auth_code = OAuthAuthorizationCode(
                code=code_value,
                client_id=BUILTIN_CLIENT_ID,
                user_id=user.id,
                tenant_key=tenant_key,
                redirect_uri="http://localhost:3000/callback",
                code_challenge=challenge,
                code_challenge_method="S256",
                scope="mcp:read mcp:write",
                expires_at=datetime.now(UTC) + timedelta(minutes=10),
                used=False,
            )
            session.add(auth_code)
            await session.commit()

        response = await api_client.post(
            "/api/oauth/token",
            data={
                "grant_type": "authorization_code",
                "code": code_value,
                "client_id": BUILTIN_CLIENT_ID,
                "code_verifier": verifier,
                "redirect_uri": "http://localhost:3000/callback",
            },
        )
        assert response.status_code == 200

        data = response.json()
        assert "access_token" in data
        # BE-6161: public client now receives a rotating refresh token...
        assert isinstance(data.get("refresh_token"), str) and data["refresh_token"], (
            f"public client must receive a non-empty string refresh_token: {data}"
        )
        assert isinstance(data.get("refresh_expires_in"), int) and data["refresh_expires_in"] > 0, data
        # ...and BE-6155a still holds: never a null literal for the key on the wire.
        assert '"refresh_token":null' not in response.text.replace(" ", "")

    @pytest.mark.asyncio
    async def test_token_endpoint_is_public(self, api_client):
        """Token endpoint must be accessible without authentication (returns 400 for bad data, not 401)."""
        response = await api_client.post(
            "/api/oauth/token",
            data={
                "grant_type": "authorization_code",
                "code": "nonexistent",
                "client_id": BUILTIN_CLIENT_ID,
                "code_verifier": "verifier",
                "redirect_uri": "http://localhost:3000/callback",
            },
        )
        assert response.status_code == 400


class TestOAuthAuthorizeEndpoint:
    """Tests for POST /api/oauth/authorize."""

    @pytest.mark.asyncio
    async def test_authorize_endpoint_validates_params(self, api_client, auth_headers):
        """Authorize endpoint must validate OAuth parameters and return redirect on success."""
        _verifier, challenge = _generate_pkce_pair()
        response = await api_client.post(
            "/api/oauth/authorize",
            headers=auth_headers,
            json={
                "client_id": BUILTIN_CLIENT_ID,
                "redirect_uri": "http://localhost:3000/callback",
                "code_challenge": challenge,
                "code_challenge_method": "S256",
                "scope": "mcp:read mcp:write",
                "state": "test-state-value",
                "response_type": "code",
            },
            follow_redirects=False,
        )
        assert response.status_code in (200, 302)
        if response.status_code == 200:
            data = response.json()
            assert "redirect_uri" in data
            assert "code" in data["redirect_uri"]
            assert "test-state-value" in data["redirect_uri"]

    @pytest.mark.asyncio
    async def test_authorize_endpoint_rejects_invalid_client(self, api_client, auth_headers):
        """Authorize endpoint must reject requests with an invalid client_id."""
        _verifier, challenge = _generate_pkce_pair()
        response = await api_client.post(
            "/api/oauth/authorize",
            headers=auth_headers,
            json={
                "client_id": "invalid-client-id",
                "redirect_uri": "http://localhost:3000/callback",
                "code_challenge": challenge,
                "code_challenge_method": "S256",
                "scope": "mcp:read mcp:write",
                "state": "test-state",
                "response_type": "code",
            },
        )
        assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_authorize_endpoint_requires_auth(self, api_client):
        """Authorize POST endpoint must require authentication (no auth = 401)."""
        _verifier, challenge = _generate_pkce_pair()
        response = await api_client.post(
            "/api/oauth/authorize",
            json={
                "client_id": BUILTIN_CLIENT_ID,
                "redirect_uri": "http://localhost:3000/callback",
                "code_challenge": challenge,
                "code_challenge_method": "S256",
                "scope": "mcp:read mcp:write",
                "state": "test-state",
                "response_type": "code",
            },
        )
        assert response.status_code in (401, 403)


class TestAuthorizeRequestInputHardening:
    """SEC-5109 — control-char + max_length hardening on AuthorizeRequest.

    Closes CodeQL alert #758 (py/log-injection). AuthorizeRequest field values
    are echoed into structured logs; control characters (CR/LF/NUL) must be
    rejected at the HTTP boundary with a clean 422 before reaching the service
    or any log sink.
    """

    @pytest.mark.asyncio
    async def test_client_id_with_newline_returns_422(self, api_client, auth_headers):
        _verifier, challenge = _generate_pkce_pair()
        response = await api_client.post(
            "/api/oauth/authorize",
            headers=auth_headers,
            json={
                "client_id": "abc\nFAKE LOG ENTRY",
                "redirect_uri": "http://localhost:3000/callback",
                "code_challenge": challenge,
                "code_challenge_method": "S256",
                "scope": "mcp:read mcp:write",
                "state": "test-state",
                "response_type": "code",
            },
        )
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_client_id_with_carriage_return_returns_422(self, api_client, auth_headers):
        _verifier, challenge = _generate_pkce_pair()
        response = await api_client.post(
            "/api/oauth/authorize",
            headers=auth_headers,
            json={
                "client_id": "abc\rFAKE LOG ENTRY",
                "redirect_uri": "http://localhost:3000/callback",
                "code_challenge": challenge,
                "code_challenge_method": "S256",
                "scope": "mcp:read mcp:write",
                "state": "test-state",
                "response_type": "code",
            },
        )
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_client_id_with_null_byte_returns_422(self, api_client, auth_headers):
        _verifier, challenge = _generate_pkce_pair()
        response = await api_client.post(
            "/api/oauth/authorize",
            headers=auth_headers,
            json={
                "client_id": "abc\x00def",
                "redirect_uri": "http://localhost:3000/callback",
                "code_challenge": challenge,
                "code_challenge_method": "S256",
                "scope": "mcp:read mcp:write",
                "state": "test-state",
                "response_type": "code",
            },
        )
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_control_chars_rejected_on_state_field(self, api_client, auth_headers):
        _verifier, challenge = _generate_pkce_pair()
        response = await api_client.post(
            "/api/oauth/authorize",
            headers=auth_headers,
            json={
                "client_id": BUILTIN_CLIENT_ID,
                "redirect_uri": "http://localhost:3000/callback",
                "code_challenge": challenge,
                "code_challenge_method": "S256",
                "scope": "mcp:read mcp:write",
                "state": "abc\nFAKE LOG ENTRY",
                "response_type": "code",
            },
        )
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_client_id_max_length_enforced(self, api_client, auth_headers):
        _verifier, challenge = _generate_pkce_pair()
        response = await api_client.post(
            "/api/oauth/authorize",
            headers=auth_headers,
            json={
                "client_id": "a" * 257,
                "redirect_uri": "http://localhost:3000/callback",
                "code_challenge": challenge,
                "code_challenge_method": "S256",
                "scope": "mcp:read mcp:write",
                "state": "test-state",
                "response_type": "code",
            },
        )
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_legitimate_authorize_request_still_succeeds(self, api_client, auth_headers):
        _verifier, challenge = _generate_pkce_pair()
        response = await api_client.post(
            "/api/oauth/authorize",
            headers=auth_headers,
            json={
                "client_id": BUILTIN_CLIENT_ID,
                "redirect_uri": "http://localhost:3000/callback",
                "code_challenge": challenge,
                "code_challenge_method": "S256",
                "scope": "mcp:read mcp:write",
                "state": "test-state-value",
                "response_type": "code",
            },
            follow_redirects=False,
        )
        assert response.status_code in (200, 302)


# ---------------------------------------------------------------------------
# API-0021d Phase 2 — RFC 8707 resource indicator binding
# ---------------------------------------------------------------------------


async def _seed_user_and_code(
    db_manager,
    *,
    challenge: str,
    code_value: str,
    resource: str | None,
    redirect_uri: str = "http://localhost:3000/callback",
    client_id: str = BUILTIN_CLIENT_ID,
):
    """Insert an Organization + User + OAuthAuthorizationCode row.

    Returns the tenant_key used so callers can assert tenant isolation.
    """
    from giljo_mcp.models.auth import User
    from giljo_mcp.models.oauth import OAuthAuthorizationCode
    from giljo_mcp.models.organizations import Organization
    from giljo_mcp.tenant import TenantManager

    tenant_key = TenantManager.generate_tenant_key()

    async with db_manager.get_session_async() as session:
        org = Organization(
            name=f"Resource Test Org {uuid4().hex[:6]}",
            slug=f"res-org-{uuid4().hex[:8]}",
            tenant_key=tenant_key,
            is_active=True,
        )
        session.add(org)
        await session.flush()

        user = User(
            id=str(uuid4()),
            username=f"res_user_{uuid4().hex[:8]}",
            email=f"res_{uuid4().hex[:8]}@example.com",
            role="developer",
            tenant_key=tenant_key,
            is_active=True,
            org_id=org.id,
        )
        session.add(user)
        await session.flush()

        auth_code = OAuthAuthorizationCode(
            code=code_value,
            client_id=client_id,
            user_id=user.id,
            tenant_key=tenant_key,
            redirect_uri=redirect_uri,
            code_challenge=challenge,
            code_challenge_method="S256",
            scope="mcp:read mcp:write",
            resource=resource,
            expires_at=datetime.now(UTC) + timedelta(minutes=10),
            used=False,
        )
        session.add(auth_code)
        await session.commit()

    return tenant_key


class TestResourceIndicatorBinding:
    """API-0021d Phase 2: RFC 8707 resource indicator must bind JWT aud.

    Failing-layer tests run through the FastAPI route — same boundary the
    claude.ai connector exercises against demo. CLAUDE.md mandates a test
    at the layer the bug occurred (BE-5042 lesson).
    """

    @pytest.mark.asyncio
    async def test_token_uses_bound_resource_when_request_omits_it(self, api_client, db_manager):
        """RFC 8707 §2 (Phase 1.4): when /token omits `resource`, server SHOULD use the
        value bound at /authorize. ChatGPT compat — claude.ai echoes resource at /token,
        ChatGPT does not. Both are spec-legitimate.

        Pre-Phase-1.4: 400 invalid_request "resource is required for this token request".
        Post-Phase-1.4: 200, JWT.aud equals the auth-code's bound resource.

        Replaces the Phase-2 contract test that locked in the strict-required behavior
        (commit `f130868a2`). Demo prod evidence 2026-05-10 15:19:16 EDT.
        """
        import jwt as _jwt

        verifier, challenge = _generate_pkce_pair()
        code_value = secrets.token_urlsafe(64)
        bound_resource = "https://mcp.example.com/mcp"
        await _seed_user_and_code(
            db_manager,
            challenge=challenge,
            code_value=code_value,
            resource=bound_resource,
        )

        response = await api_client.post(
            "/api/oauth/token",
            data={
                "grant_type": "authorization_code",
                "code": code_value,
                "client_id": BUILTIN_CLIENT_ID,
                "code_verifier": verifier,
                "redirect_uri": "http://localhost:3000/callback",
                # client omits resource — server falls back to bound value
            },
        )
        assert response.status_code == 200, response.text
        body = response.json()
        decoded = _jwt.decode(body["access_token"], options={"verify_signature": False})
        assert decoded.get("aud") == bound_resource, decoded

    @pytest.mark.asyncio
    async def test_token_resource_mismatch_returns_401_invalid_grant(self, api_client, db_manager):
        """Auth-code resource ≠ client's `resource` → 401 invalid_grant (RFC 8707 §2.2)."""
        verifier, challenge = _generate_pkce_pair()
        code_value = secrets.token_urlsafe(64)
        await _seed_user_and_code(
            db_manager,
            challenge=challenge,
            code_value=code_value,
            resource="https://mcp.example.com/mcp",
        )

        response = await api_client.post(
            "/api/oauth/token",
            data={
                "grant_type": "authorization_code",
                "code": code_value,
                "client_id": BUILTIN_CLIENT_ID,
                "code_verifier": verifier,
                "redirect_uri": "http://localhost:3000/callback",
                "resource": "https://attacker.example/mcp",
            },
        )
        assert response.status_code == 401, response.text
        body = response.json()
        detail_text = _oauth_err_text(body)
        assert "invalid_grant" in detail_text.lower()

    @pytest.mark.asyncio
    async def test_token_resource_match_returns_jwt_with_aud_bound(self, api_client, db_manager):
        """Auth-code resource == client's `resource` → 200, JWT aud == that value."""
        import jwt as _jwt

        verifier, challenge = _generate_pkce_pair()
        code_value = secrets.token_urlsafe(64)
        bound_resource = "https://mcp.example.com/mcp"
        await _seed_user_and_code(
            db_manager,
            challenge=challenge,
            code_value=code_value,
            resource=bound_resource,
        )

        response = await api_client.post(
            "/api/oauth/token",
            data={
                "grant_type": "authorization_code",
                "code": code_value,
                "client_id": BUILTIN_CLIENT_ID,
                "code_verifier": verifier,
                "redirect_uri": "http://localhost:3000/callback",
                "resource": bound_resource,
            },
        )
        assert response.status_code == 200, response.text
        body = response.json()
        access_token = body["access_token"]

        # Decode unsigned to inspect aud — JWT signature already verified by service.
        decoded = _jwt.decode(access_token, options={"verify_signature": False})
        assert decoded.get("aud") == bound_resource, decoded

    @pytest.mark.asyncio
    async def test_legacy_audless_code_still_issues_token(self, api_client, db_manager):
        """REGRESSION (back-compat): pre-API-0021d codes (no resource on record)
        plus a client that doesn't send `resource` continue to issue a token
        with the canonical-MCP-URI fallback as `aud`. Locks the
        transition-window contract for one release.
        """
        import jwt as _jwt

        verifier, challenge = _generate_pkce_pair()
        code_value = secrets.token_urlsafe(64)
        await _seed_user_and_code(
            db_manager,
            challenge=challenge,
            code_value=code_value,
            resource=None,  # pre-API-0021d in-flight code
        )

        response = await api_client.post(
            "/api/oauth/token",
            data={
                "grant_type": "authorization_code",
                "code": code_value,
                "client_id": BUILTIN_CLIENT_ID,
                "code_verifier": verifier,
                "redirect_uri": "http://localhost:3000/callback",
                # no resource — legacy client
            },
        )
        assert response.status_code == 200, response.text
        body = response.json()
        access_token = body["access_token"]
        decoded = _jwt.decode(access_token, options={"verify_signature": False})
        # Falls back to canonical MCP URI passed by the route layer.
        assert "aud" in decoded, decoded
        assert decoded["aud"].endswith("/mcp"), decoded

    @pytest.mark.asyncio
    async def test_authorize_persists_resource_onto_code(self, api_client, auth_headers, db_manager):
        """POST /api/oauth/authorize with `resource` persists it onto the code row.

        Reachability test for the Phase 2 wiring: route → service →
        OAuthAuthorizationCode.resource column. Verifies the round-trip
        without coupling to the /token endpoint.
        """
        from sqlalchemy import select as _select

        from giljo_mcp.database import tenant_isolation_bypass
        from giljo_mcp.models.oauth import OAuthAuthorizationCode

        _verifier, challenge = _generate_pkce_pair()
        bound_resource = "https://mcp.example.com/mcp"

        response = await api_client.post(
            "/api/oauth/authorize",
            headers=auth_headers,
            json={
                "client_id": BUILTIN_CLIENT_ID,
                "redirect_uri": "http://localhost:3000/callback",
                "code_challenge": challenge,
                "code_challenge_method": "S256",
                "scope": "mcp:read mcp:write",
                "state": "test-state",
                "response_type": "code",
                "resource": bound_resource,
            },
            follow_redirects=False,
        )
        assert response.status_code in (200, 302), response.text
        data = response.json()
        # Extract the code from the redirect URI query
        redirect_url = data["redirect_uri"]
        assert "code=" in redirect_url
        issued_code = redirect_url.split("code=", 1)[1].split("&", 1)[0]

        # Verify the code row has the resource bound. The verification read
        # resolves a globally-unique code with no tenant context (test-only),
        # so it uses the same audited bypass the production /token path uses.
        async with db_manager.get_session_async() as session:
            with tenant_isolation_bypass(
                session,
                reason="test: verify auth-code row by globally-unique code",
                models=(OAuthAuthorizationCode,),
            ):
                row = (
                    await session.execute(
                        _select(OAuthAuthorizationCode).where(OAuthAuthorizationCode.code == issued_code)
                    )
                ).scalar_one()
            assert row.resource == bound_resource

    @pytest.mark.asyncio
    async def test_authorize_rejects_malformed_resource(self, api_client, auth_headers):
        """A malformed `resource` (no scheme) must be rejected at /authorize as 400."""
        _verifier, challenge = _generate_pkce_pair()
        response = await api_client.post(
            "/api/oauth/authorize",
            headers=auth_headers,
            json={
                "client_id": BUILTIN_CLIENT_ID,
                "redirect_uri": "http://localhost:3000/callback",
                "code_challenge": challenge,
                "code_challenge_method": "S256",
                "scope": "mcp:read mcp:write",
                "state": "test",
                "response_type": "code",
                "resource": "mcp.example.com/mcp",  # missing scheme
            },
        )
        assert response.status_code == 400, response.text


class TestProtectedResourceMetadataResourceIndicators:
    """API-0021d F3: RFC 9728 metadata MUST advertise resource_indicators_supported."""

    @pytest.mark.asyncio
    async def test_root_metadata_advertises_resource_indicators_supported(self, api_client):
        response = await api_client.get("/.well-known/oauth-protected-resource")
        assert response.status_code == 200, response.text
        body = response.json()
        assert body.get("resource_indicators_supported") is True, body


class TestProtectedResourceMetadataPathSuffix:
    """API-0021k: RFC 9728 §3.1 path-suffix discovery variant.

    Pre-fix bug: `GET /.well-known/oauth-protected-resource/mcp` returned the
    Vue SPA `index.html` (200 HTML) because no route handler matched and the
    SPA 404 exception handler in api/app.py served the SPA shell. These tests
    exercise the route at the FastAPI boundary (the failing layer) — service
    coverage would not have caught this. Tests confirm the path-suffix form
    for `/mcp` returns identical metadata to the host-only form and that any
    other suffix returns 404 (only `/mcp` is a valid protected resource).
    """

    @pytest.mark.asyncio
    async def test_pathsuffix_mcp_matches_host_only_response(self, api_client):
        host_only = await api_client.get("/.well-known/oauth-protected-resource")
        pathsuffix = await api_client.get("/.well-known/oauth-protected-resource/mcp")

        assert host_only.status_code == 200, host_only.text
        assert pathsuffix.status_code == 200, pathsuffix.text
        assert pathsuffix.headers["content-type"].startswith("application/json")
        assert pathsuffix.json() == host_only.json()

    @pytest.mark.asyncio
    async def test_pathsuffix_unknown_resource_is_404(self, api_client):
        response = await api_client.get("/.well-known/oauth-protected-resource/notmcp")
        assert response.status_code == 404, response.text

    @pytest.mark.asyncio
    async def test_pathsuffix_deeper_path_is_404(self, api_client):
        response = await api_client.get("/.well-known/oauth-protected-resource/mcp/extra")
        assert response.status_code == 404, response.text


# ---------------------------------------------------------------------------
# API-0021e Phase 1 — verify client_secret at /token for confidential clients
# ---------------------------------------------------------------------------


async def _seed_confidential_dcr_code(
    db_manager,
    *,
    challenge: str,
    code_value: str,
    redirect_uri: str = "http://localhost:3000/callback",
    plaintext_secret: str | None = None,
) -> tuple[str, str, str, str]:
    """Insert an Org + User + AuthCode bound to a synthetic confidential client.

    Returns ``(client_id, plaintext_secret, tenant_key, secret_hash)``. The
    OAuthClient row itself is NOT persisted (CE test DB has no oauth_clients
    table — that's a SaaS-only migration). Tests inject a stub resolver that
    returns a ``ResolvedClient`` with the bcrypt hash directly, mirroring
    what the SaaS resolver would have produced after a DCR registration.
    """
    from uuid import uuid4 as _uuid4

    import bcrypt as _bcrypt

    from giljo_mcp.models.auth import User
    from giljo_mcp.models.oauth import OAuthAuthorizationCode
    from giljo_mcp.models.organizations import Organization
    from giljo_mcp.tenant import TenantManager

    if plaintext_secret is None:
        plaintext_secret = secrets.token_urlsafe(48)
    secret_hash = _bcrypt.hashpw(plaintext_secret.encode("utf-8"), _bcrypt.gensalt()).decode("ascii")
    tenant_key = TenantManager.generate_tenant_key()
    client_id = str(_uuid4())

    async with db_manager.get_session_async() as session:
        org = Organization(
            name=f"DCR Test Org {_uuid4().hex[:6]}",
            slug=f"dcr-org-{_uuid4().hex[:8]}",
            tenant_key=tenant_key,
            is_active=True,
        )
        session.add(org)
        await session.flush()

        user = User(
            id=str(_uuid4()),
            username=f"dcr_user_{_uuid4().hex[:8]}",
            email=f"dcr_{_uuid4().hex[:8]}@example.com",
            role="developer",
            tenant_key=tenant_key,
            is_active=True,
            org_id=org.id,
        )
        session.add(user)
        await session.flush()

        auth_code = OAuthAuthorizationCode(
            code=code_value,
            client_id=client_id,
            user_id=user.id,
            tenant_key=tenant_key,
            redirect_uri=redirect_uri,
            code_challenge=challenge,
            code_challenge_method="S256",
            scope="mcp:read mcp:write",
            resource=None,
            expires_at=datetime.now(UTC) + timedelta(minutes=10),
            used=False,
        )
        session.add(auth_code)
        await session.commit()

    return client_id, plaintext_secret, tenant_key, secret_hash


def _install_confidential_resolver(client_id: str, secret_hash: str, redirect_uri: str):
    """Install a resolver that returns a confidential ``ResolvedClient``.

    Returns a ``(prior_resolver, restore)`` pair; tests should call
    ``restore()`` in a ``finally`` to revert. Mirrors the pattern used by
    ``TestAuthorizeAcceptsClaudeComRedirectUri``.
    """
    from giljo_mcp.services import oauth_service as svc

    prior = svc.get_client_resolver()

    def _resolver(cid: str, tenant_key: str):
        assert tenant_key  # tenant filter still mandatory
        if cid != client_id:
            return None
        return svc.ResolvedClient(
            client_id=cid,
            client_name="DCR Confidential Test Client",
            redirect_uris=[redirect_uri],
            client_secret_hash=secret_hash,
        )

    svc.set_client_resolver(_resolver)

    def _restore() -> None:
        svc.set_client_resolver(prior)

    return _restore


class TestTokenClientSecretVerification:
    """API-0021e Phase 1: confidential DCR clients MUST present a valid
    client_secret at /token. Public PKCE-only clients (built-in CE) MUST
    NOT carry a client_secret. Failing-layer = the FastAPI route, same
    boundary the claude.ai connector exercises (CLAUDE.md regression-test
    rule)."""

    @pytest.mark.asyncio
    async def test_token_exchange_rejects_wrong_client_secret(self, api_client, db_manager):
        verifier, challenge = _generate_pkce_pair()
        code_value = secrets.token_urlsafe(64)
        client_id, _correct, _tenant_key, secret_hash = await _seed_confidential_dcr_code(
            db_manager, challenge=challenge, code_value=code_value
        )

        restore = _install_confidential_resolver(client_id, secret_hash, "http://localhost:3000/callback")
        try:
            response = await api_client.post(
                "/api/oauth/token",
                data={
                    "grant_type": "authorization_code",
                    "code": code_value,
                    "client_id": client_id,
                    "code_verifier": verifier,
                    "redirect_uri": "http://localhost:3000/callback",
                    "client_secret": "totally-wrong-secret",
                },
            )
        finally:
            restore()

        assert response.status_code == 401, response.text
        body = response.json()
        # BE-6040: RFC 6749 §5.2 — failed client auth carries the code in the
        # top-level `error` member, NOT the legacy `error_code`/`message` shape,
        # and a 401 SHOULD include WWW-Authenticate.
        assert body.get("error") == "invalid_client", body
        assert "error_code" not in body and "message" not in body, body
        assert response.headers.get("www-authenticate", "").lower().startswith("basic"), dict(response.headers)

    @pytest.mark.asyncio
    async def test_token_exchange_accepts_correct_client_secret(self, api_client, db_manager):
        verifier, challenge = _generate_pkce_pair()
        code_value = secrets.token_urlsafe(64)
        client_id, plaintext_secret, _tenant_key, secret_hash = await _seed_confidential_dcr_code(
            db_manager, challenge=challenge, code_value=code_value
        )

        restore = _install_confidential_resolver(client_id, secret_hash, "http://localhost:3000/callback")
        try:
            response = await api_client.post(
                "/api/oauth/token",
                data={
                    "grant_type": "authorization_code",
                    "code": code_value,
                    "client_id": client_id,
                    "code_verifier": verifier,
                    "redirect_uri": "http://localhost:3000/callback",
                    "client_secret": plaintext_secret,
                },
            )
        finally:
            restore()

        assert response.status_code == 200, response.text
        data = response.json()
        assert "access_token" in data
        assert data["token_type"] == "bearer"
        assert data["access_token"].count(".") == 2

    @pytest.mark.asyncio
    async def test_token_exchange_rejects_confidential_client_with_no_secret(self, api_client, db_manager):
        """A confidential DCR client (client_secret_hash present) MUST NOT be
        able to exchange a code without a client_secret — that would defeat the
        Phase 1 fix entirely. The pre-API-0021e bug shipped this path as 200.
        """
        verifier, challenge = _generate_pkce_pair()
        code_value = secrets.token_urlsafe(64)
        client_id, _secret, _tenant_key, secret_hash = await _seed_confidential_dcr_code(
            db_manager, challenge=challenge, code_value=code_value
        )

        restore = _install_confidential_resolver(client_id, secret_hash, "http://localhost:3000/callback")
        try:
            response = await api_client.post(
                "/api/oauth/token",
                data={
                    "grant_type": "authorization_code",
                    "code": code_value,
                    "client_id": client_id,
                    "code_verifier": verifier,
                    "redirect_uri": "http://localhost:3000/callback",
                    # no client_secret
                },
            )
        finally:
            restore()

        assert response.status_code == 401, response.text
        body = response.json()
        detail_text = _oauth_err_text(body)
        assert "invalid_client" in detail_text.lower(), body

    @pytest.mark.asyncio
    async def test_token_exchange_public_pkce_client_no_secret_succeeds(self, api_client, db_manager):
        """REGRESSION: the built-in CE PKCE-only client (no client_secret_hash)
        MUST keep working without a client_secret. PKCE remains the
        proof-of-possession mechanism for public clients."""
        verifier, challenge = _generate_pkce_pair()
        code_value = secrets.token_urlsafe(64)
        await _seed_user_and_code(db_manager, challenge=challenge, code_value=code_value, resource=None)

        response = await api_client.post(
            "/api/oauth/token",
            data={
                "grant_type": "authorization_code",
                "code": code_value,
                "client_id": BUILTIN_CLIENT_ID,
                "code_verifier": verifier,
                "redirect_uri": "http://localhost:3000/callback",
                # no client_secret — PKCE-only public client
            },
        )
        assert response.status_code == 200, response.text

    # API-0021e Phase 1.1: code_verifier is OPTIONAL for confidential clients
    # per RFC 6749 §6 (client_secret is the alternative authentication). The
    # original Phase 1 work shipped with code_verifier still required at the
    # FastAPI Form level, so ChatGPT (which sends client_secret_post but no
    # PKCE per RFC 6749 §4.1.3) was hitting HTTP 422 from Pydantic before any
    # handler logic ran. Live evidence on mcp.example.com 2026-05-10 09:28:06
    # UTC: ChatGPT POSTed /token twice with no code_verifier and got
    # {"loc":["body","code_verifier"],"msg":"Field required","type":"missing"}.

    @pytest.mark.asyncio
    async def test_token_exchange_confidential_client_no_pkce_rejected(self, api_client, db_manager):
        """SEC-9227 (H2) / RFC 9700 §2.1.1, at the /token boundary: a confidential
        client authenticating with client_secret MUST STILL present a matching
        code_verifier — the auth-code carries an S256 challenge, so the verifier
        is required for every client type.

        This previously SUCCEEDED (the confidential branch made the verifier
        optional), which meant a stolen authorization code plus the client secret
        redeemed a token with no proof-of-possession. It must now be rejected as
        invalid_request (400). The earlier "client_secret as an alternative to
        PKCE" reading (RFC 6749 §6) is superseded by RFC 9700.
        """
        verifier, challenge = _generate_pkce_pair()
        del verifier  # We deliberately do NOT send a verifier; challenge stays on the auth-code row.
        code_value = secrets.token_urlsafe(64)
        client_id, plaintext_secret, _tenant_key, secret_hash = await _seed_confidential_dcr_code(
            db_manager, challenge=challenge, code_value=code_value
        )

        restore = _install_confidential_resolver(client_id, secret_hash, "http://localhost:3000/callback")
        try:
            response = await api_client.post(
                "/api/oauth/token",
                data={
                    "grant_type": "authorization_code",
                    "code": code_value,
                    "client_id": client_id,
                    "redirect_uri": "http://localhost:3000/callback",
                    "client_secret": plaintext_secret,
                    # no code_verifier — a valid secret must NOT substitute for PKCE
                },
            )
        finally:
            restore()

        assert response.status_code == 400, response.text
        detail_text = _oauth_err_text(response.json())
        assert "invalid_request" in detail_text.lower(), response.text

    @pytest.mark.asyncio
    async def test_token_exchange_confidential_client_with_wrong_pkce_rejected(self, api_client, db_manager):
        """Defense-in-depth: if a confidential client DOES present a
        code_verifier, it MUST verify against the stored challenge. Sending
        client_secret + a wrong verifier is suspicious and rejected as
        invalid_grant. Belt-and-suspenders is fine; mismatched belt is not.
        """
        _good_verifier, challenge = _generate_pkce_pair()
        code_value = secrets.token_urlsafe(64)
        client_id, plaintext_secret, _tenant_key, secret_hash = await _seed_confidential_dcr_code(
            db_manager, challenge=challenge, code_value=code_value
        )

        wrong_verifier, _wrong_challenge = _generate_pkce_pair()

        restore = _install_confidential_resolver(client_id, secret_hash, "http://localhost:3000/callback")
        try:
            response = await api_client.post(
                "/api/oauth/token",
                data={
                    "grant_type": "authorization_code",
                    "code": code_value,
                    "client_id": client_id,
                    "code_verifier": wrong_verifier,
                    "redirect_uri": "http://localhost:3000/callback",
                    "client_secret": plaintext_secret,
                },
            )
        finally:
            restore()

        assert response.status_code == 400, response.text
        body = response.json()
        detail_text = _oauth_err_text(body)
        assert "invalid_request" in detail_text.lower() or "invalid_grant" in detail_text.lower(), body

    @pytest.mark.asyncio
    async def test_token_exchange_public_client_no_pkce_rejected(self, api_client, db_manager):
        """A public PKCE-only client (no client_secret_hash) MUST still
        present a code_verifier — without it, nothing authenticates the
        client. The pre-Phase-1.1 wire surfaced this as HTTP 422 from
        Pydantic; post-fix it MUST be a clean OAuth invalid_request (400).
        """
        _verifier, challenge = _generate_pkce_pair()
        code_value = secrets.token_urlsafe(64)
        await _seed_user_and_code(db_manager, challenge=challenge, code_value=code_value, resource=None)

        response = await api_client.post(
            "/api/oauth/token",
            data={
                "grant_type": "authorization_code",
                "code": code_value,
                "client_id": BUILTIN_CLIENT_ID,
                "redirect_uri": "http://localhost:3000/callback",
                # no code_verifier — public client has no other auth, must fail
            },
        )
        assert response.status_code == 400, response.text
        body = response.json()
        detail_text = _oauth_err_text(body)
        assert "invalid_request" in detail_text.lower(), body


class TestTokenAcceptsJsonAndBasicAuth:
    """API-0021e Phase 1.2: /token accepts JSON body and HTTP Basic Auth.

    ChatGPT connector posts ``application/json`` to /token (verified live on
    mcp.example.com 2026-05-10 10:06:12 EDT, Azure 172.212.159.67/.68). The
    pre-Phase-1.2 handler used FastAPI ``Form(...)`` parameters which only
    parse ``application/x-www-form-urlencoded`` -- every JSON request
    surfaced as a 422 with "Field required" on every field.

    RFC 6749 §3.2 specifies form-encoded for /token, but the major OAuth
    providers (Google, GitHub, Auth0, Okta) accept both. claude.ai still
    sends form-encoded; we must keep that path working AND start accepting
    JSON. We also accept HTTP Basic Auth for ``client_secret_basic`` clients
    per RFC 6749 §2.3.1.
    """

    @pytest.mark.asyncio
    async def test_token_exchange_accepts_json_content_type(self, api_client, db_manager):
        """POST /token with Content-Type: application/json + JSON body must succeed.

        MUST FAIL before Phase 1.2 fix: pre-fix returns 422 because Form(...)
        parameters don't parse JSON.
        """
        verifier, challenge = _generate_pkce_pair()
        code_value = secrets.token_urlsafe(64)
        client_id, plaintext_secret, _tenant_key, secret_hash = await _seed_confidential_dcr_code(
            db_manager, challenge=challenge, code_value=code_value
        )

        restore = _install_confidential_resolver(client_id, secret_hash, "http://localhost:3000/callback")
        try:
            response = await api_client.post(
                "/api/oauth/token",
                json={
                    "grant_type": "authorization_code",
                    "code": code_value,
                    "client_id": client_id,
                    "code_verifier": verifier,
                    "redirect_uri": "http://localhost:3000/callback",
                    "client_secret": plaintext_secret,
                },
            )
        finally:
            restore()

        assert response.status_code == 200, response.text
        data = response.json()
        assert "access_token" in data
        assert data["token_type"] == "bearer"
        assert data["access_token"].count(".") == 2

    @pytest.mark.asyncio
    async def test_token_exchange_accepts_basic_auth_header(self, api_client, db_manager):
        """POST /token with Authorization: Basic <b64(client_id:client_secret)> works.

        Body carries grant_type+code+redirect_uri only; credentials live
        in the header per RFC 6749 §2.3.1 (``client_secret_basic``).

        MUST FAIL before Phase 1.2 fix: handler ignored Authorization header
        so the request looked like a confidential client missing its
        secret -> 401 invalid_client.
        """
        import base64 as _b64

        verifier, challenge = _generate_pkce_pair()
        code_value = secrets.token_urlsafe(64)
        client_id, plaintext_secret, _tenant_key, secret_hash = await _seed_confidential_dcr_code(
            db_manager, challenge=challenge, code_value=code_value
        )

        basic = _b64.b64encode(f"{client_id}:{plaintext_secret}".encode("ascii")).decode("ascii")

        restore = _install_confidential_resolver(client_id, secret_hash, "http://localhost:3000/callback")
        try:
            response = await api_client.post(
                "/api/oauth/token",
                data={
                    "grant_type": "authorization_code",
                    "code": code_value,
                    "client_id": client_id,
                    "code_verifier": verifier,
                    "redirect_uri": "http://localhost:3000/callback",
                },
                headers={"Authorization": f"Basic {basic}"},
            )
        finally:
            restore()

        assert response.status_code == 200, response.text
        data = response.json()
        assert "access_token" in data
        assert data["token_type"] == "bearer"

    @pytest.mark.asyncio
    async def test_token_exchange_form_encoded_still_works(self, api_client, db_manager):
        """REGRESSION: form-encoded path must NOT regress (claude.ai compat)."""
        verifier, challenge = _generate_pkce_pair()
        code_value = secrets.token_urlsafe(64)
        client_id, plaintext_secret, _tenant_key, secret_hash = await _seed_confidential_dcr_code(
            db_manager, challenge=challenge, code_value=code_value
        )

        restore = _install_confidential_resolver(client_id, secret_hash, "http://localhost:3000/callback")
        try:
            response = await api_client.post(
                "/api/oauth/token",
                data={
                    "grant_type": "authorization_code",
                    "code": code_value,
                    "client_id": client_id,
                    "code_verifier": verifier,
                    "redirect_uri": "http://localhost:3000/callback",
                    "client_secret": plaintext_secret,
                },
            )
        finally:
            restore()

        assert response.status_code == 200, response.text
        assert response.json()["token_type"] == "bearer"

    @pytest.mark.asyncio
    async def test_token_exchange_basic_auth_header_overrides_body(self, api_client, db_manager):
        """RFC 6749 §2.3.1: Basic Auth header takes precedence over body.

        Body contains a WRONG client_secret; header has the correct one.
        Header should win -> 200.

        MUST FAIL before Phase 1.2 fix: handler reads body only, sees the
        wrong secret -> 401 invalid_client.
        """
        import base64 as _b64

        verifier, challenge = _generate_pkce_pair()
        code_value = secrets.token_urlsafe(64)
        client_id, plaintext_secret, _tenant_key, secret_hash = await _seed_confidential_dcr_code(
            db_manager, challenge=challenge, code_value=code_value
        )

        basic = _b64.b64encode(f"{client_id}:{plaintext_secret}".encode("ascii")).decode("ascii")

        restore = _install_confidential_resolver(client_id, secret_hash, "http://localhost:3000/callback")
        try:
            response = await api_client.post(
                "/api/oauth/token",
                data={
                    "grant_type": "authorization_code",
                    "code": code_value,
                    "client_id": client_id,
                    "code_verifier": verifier,
                    "redirect_uri": "http://localhost:3000/callback",
                    "client_secret": "wrong-secret-in-body",
                },
                headers={"Authorization": f"Basic {basic}"},
            )
        finally:
            restore()

        assert response.status_code == 200, response.text

    @pytest.mark.asyncio
    async def test_token_exchange_malformed_json_body(self, api_client):
        """Content-Type: application/json + malformed JSON -> 400 invalid_request.

        Must NOT be 422 (Pydantic schema artifact) and MUST NOT be 500.
        """
        response = await api_client.post(
            "/api/oauth/token",
            content=b"{not json",
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == 400, response.text
        body = response.json()
        detail_text = _oauth_err_text(body)
        assert "invalid_request" in detail_text.lower(), body


class TestAuthorizeAcceptsClaudeComRedirectUri:
    """API-0021d Phase 3: /authorize accepts a claude.com redirect when the
    resolver knows the client. Pairs with the SaaS-side DCR test in
    tests/saas/test_oauth_dcr_endpoint.py that locks the registration path."""

    @pytest.mark.asyncio
    async def test_authorize_with_claude_com_redirect_succeeds(self, api_client, auth_headers):
        """POST /api/oauth/authorize with a claude.com redirect_uri completes
        when the resolver knows the client.

        For the built-in CE client the localhost regex matcher would reject
        claude.com — so we install a temporary resolver that returns a DCR
        client registered with both URIs, then restore on teardown.
        """
        from giljo_mcp.services import oauth_service as svc

        _verifier, challenge = _generate_pkce_pair()
        prior = svc.get_client_resolver()

        def _resolver(client_id: str, tenant_key: str):
            assert tenant_key  # tenant filter still mandatory
            return svc.ResolvedClient(
                client_id=client_id,
                client_name="Claude Connector",
                redirect_uris=[
                    "https://claude.ai/api/mcp/auth_callback",
                    "https://claude.com/api/mcp/auth_callback",
                ],
                client_secret_hash=None,
            )

        svc.set_client_resolver(_resolver)
        try:
            response = await api_client.post(
                "/api/oauth/authorize",
                headers=auth_headers,
                json={
                    "client_id": "11111111-1111-1111-1111-111111111111",
                    "redirect_uri": "https://claude.com/api/mcp/auth_callback",
                    "code_challenge": challenge,
                    "code_challenge_method": "S256",
                    "scope": "mcp:read mcp:write",
                    "state": "test-state",
                    "response_type": "code",
                    "resource": "https://mcp.example.com/mcp",
                },
                follow_redirects=False,
            )
        finally:
            svc.set_client_resolver(prior)

        assert response.status_code in (200, 302), response.text
        data = response.json()
        assert data["redirect_uri"].startswith("https://claude.com/api/mcp/auth_callback")


# ---------------------------------------------------------------------------
# API-0021l — 5-second idempotency window for confidential-client retry races
# ---------------------------------------------------------------------------
#
# Live evidence: mcp.example.com 2026-05-10 15:41:48 EDT logs show ChatGPT's
# connector backend issuing TWO concurrent POST /api/oauth/token from
# different Azure egress IPs (20.169.78.85, 20.169.78.90) within the same
# second using the same auth-code. Spec-strict single-use enforcement
# returned 200 for the first and 400 "Authorization code has already been
# used" for the second. The second response made the UI flash "Something
# went wrong" before reading success. Auth0/Okta/AWS Cognito all implement
# a short idempotency window for confidential clients to absorb honest
# retries — this class locks in our equivalent at the FastAPI layer
# (CLAUDE.md: regression test at the failing layer).


class TestTokenIdempotency:
    """API-0021l: confidential-client retries inside the cache window must
    succeed with the SAME token pair. Outside the window OR with mismatched
    bound parameters they must fail closed exactly like before.

    Tests run through the FastAPI route — the bug occurred at the HTTP
    boundary (two concurrent POSTs from different Azure egress IPs), so
    the regression must exercise that boundary, not the service directly.
    """

    @pytest.mark.asyncio
    async def test_concurrent_same_code_returns_same_token_pair(self, api_client, db_manager):
        """Two near-simultaneous POSTs with identical bodies → both 200 with
        byte-identical access_token + refresh_token. Reproduces the ChatGPT
        connector race verbatim.
        """
        verifier, challenge = _generate_pkce_pair()
        code_value = secrets.token_urlsafe(64)
        client_id, plaintext_secret, _tenant_key, secret_hash = await _seed_confidential_dcr_code(
            db_manager, challenge=challenge, code_value=code_value
        )

        restore = _install_confidential_resolver(client_id, secret_hash, "http://localhost:3000/callback")
        try:
            payload = {
                "grant_type": "authorization_code",
                "code": code_value,
                "client_id": client_id,
                "code_verifier": verifier,
                "redirect_uri": "http://localhost:3000/callback",
                "client_secret": plaintext_secret,
            }
            first = await api_client.post("/api/oauth/token", data=payload)
            second = await api_client.post("/api/oauth/token", data=payload)
        finally:
            restore()

        assert first.status_code == 200, first.text
        assert second.status_code == 200, second.text
        body1 = first.json()
        body2 = second.json()
        assert body1["access_token"] == body2["access_token"], (body1, body2)
        assert body1.get("refresh_token") == body2.get("refresh_token"), (body1, body2)

    @pytest.mark.asyncio
    async def test_post_window_same_code_rejected(self, api_client, db_manager, monkeypatch):
        """Outside the idempotency window the second POST must fail closed.
        TTL is monkeypatched to 1 second so the test sleeps 1.5s then retries.
        """
        import time as _time

        from giljo_mcp.services import oauth_token_idempotency as _idem_svc

        monkeypatch.setattr(_idem_svc, "OAUTH_TOKEN_IDEMPOTENCY_WINDOW_SECONDS", 1)

        verifier, challenge = _generate_pkce_pair()
        code_value = secrets.token_urlsafe(64)
        client_id, plaintext_secret, _tenant_key, secret_hash = await _seed_confidential_dcr_code(
            db_manager, challenge=challenge, code_value=code_value
        )

        restore = _install_confidential_resolver(client_id, secret_hash, "http://localhost:3000/callback")
        try:
            payload = {
                "grant_type": "authorization_code",
                "code": code_value,
                "client_id": client_id,
                "code_verifier": verifier,
                "redirect_uri": "http://localhost:3000/callback",
                "client_secret": plaintext_secret,
            }
            first = await api_client.post("/api/oauth/token", data=payload)
            assert first.status_code == 200, first.text
            _time.sleep(1.5)
            second = await api_client.post("/api/oauth/token", data=payload)
        finally:
            restore()

        assert second.status_code == 400, second.text
        body0 = second.json()
        detail_text0 = _oauth_err_text(body0).lower()
        assert "invalid_request" in detail_text0 or "already been used" in detail_text0, body0

    @pytest.mark.asyncio
    async def test_same_code_different_secret_rejected_in_window(self, api_client, db_manager):
        """Inside the window with a WRONG client_secret on the second POST
        must NOT serve the cached 200 — body_signature mismatches, the cache
        is bypassed, and the existing fail-closed path returns 401
        invalid_client (the auth-code is already consumed, but
        client-authentication runs first and rejects).
        """
        verifier, challenge = _generate_pkce_pair()
        code_value = secrets.token_urlsafe(64)
        client_id, plaintext_secret, _tenant_key, secret_hash = await _seed_confidential_dcr_code(
            db_manager, challenge=challenge, code_value=code_value
        )

        restore = _install_confidential_resolver(client_id, secret_hash, "http://localhost:3000/callback")
        try:
            base_payload = {
                "grant_type": "authorization_code",
                "code": code_value,
                "client_id": client_id,
                "code_verifier": verifier,
                "redirect_uri": "http://localhost:3000/callback",
            }
            first = await api_client.post(
                "/api/oauth/token",
                data={**base_payload, "client_secret": plaintext_secret},
            )
            assert first.status_code == 200, first.text
            second = await api_client.post(
                "/api/oauth/token",
                data={**base_payload, "client_secret": "totally-wrong-secret"},
            )
        finally:
            restore()

        assert second.status_code == 401, second.text
        body = second.json()
        detail_text = _oauth_err_text(body).lower()
        assert "invalid_client" in detail_text, body

    @pytest.mark.asyncio
    async def test_same_code_different_redirect_rejected_in_window(self, api_client, db_manager):
        """Inside the window with a different redirect_uri must fail closed.
        The cache key is (tenant, code) but the body_signature includes
        redirect_uri, so a mismatch falls through to the existing logic which
        rejects (auth-code already consumed → invalid_request 400).
        """
        verifier, challenge = _generate_pkce_pair()
        code_value = secrets.token_urlsafe(64)
        client_id, plaintext_secret, _tenant_key, secret_hash = await _seed_confidential_dcr_code(
            db_manager, challenge=challenge, code_value=code_value
        )

        # Resolver has to recognize BOTH redirect URIs as registered, otherwise
        # the second call would fail at /token with "redirect_uri mismatch"
        # for the wrong reason (validation-against-registered-list, not
        # idempotency-bypass). The bug we're guarding against is the cache
        # serving a 200 even though the asserted redirect_uri changed.
        from giljo_mcp.services import oauth_service as svc

        prior = svc.get_client_resolver()

        def _resolver(cid: str, tenant_key: str):
            assert tenant_key
            if cid != client_id:
                return None
            return svc.ResolvedClient(
                client_id=cid,
                client_name="DCR Confidential Test Client",
                redirect_uris=[
                    "http://localhost:3000/callback",
                    "http://localhost:3000/other",
                ],
                client_secret_hash=secret_hash,
            )

        svc.set_client_resolver(_resolver)
        try:
            base_payload = {
                "grant_type": "authorization_code",
                "code": code_value,
                "client_id": client_id,
                "code_verifier": verifier,
                "client_secret": plaintext_secret,
            }
            first = await api_client.post(
                "/api/oauth/token",
                data={**base_payload, "redirect_uri": "http://localhost:3000/callback"},
            )
            assert first.status_code == 200, first.text
            second = await api_client.post(
                "/api/oauth/token",
                data={**base_payload, "redirect_uri": "http://localhost:3000/other"},
            )
        finally:
            svc.set_client_resolver(prior)

        assert second.status_code == 400, second.text
        body = second.json()
        detail_text = _oauth_err_text(body).lower()
        assert "invalid_request" in detail_text, body

    @pytest.mark.asyncio
    async def test_concurrent_refresh_returns_same_new_pair(self, api_client, db_manager):
        """/refresh equivalent of test #1: a confidential client that retries
        the same refresh_token inside the window must get the SAME rotated
        pair, not a second rotation that revokes the first.
        """
        import bcrypt as _bcrypt

        verifier, challenge = _generate_pkce_pair()
        code_value = secrets.token_urlsafe(64)
        from uuid import uuid4 as _uuid4

        client_id = str(_uuid4())
        plaintext_secret = secrets.token_urlsafe(48)
        secret_hash = _bcrypt.hashpw(plaintext_secret.encode("utf-8"), _bcrypt.gensalt()).decode("ascii")
        redirect_uri = "http://localhost:3000/callback"

        # Seed user + auth-code via the existing helper (it accepts client_id).
        from giljo_mcp.models.auth import User
        from giljo_mcp.models.oauth import OAuthAuthorizationCode
        from giljo_mcp.models.organizations import Organization
        from giljo_mcp.tenant import TenantManager

        tenant_key = TenantManager.generate_tenant_key()
        async with db_manager.get_session_async() as session:
            org = Organization(
                name=f"Idem Refresh Org {_uuid4().hex[:6]}",
                slug=f"idem-refresh-{_uuid4().hex[:8]}",
                tenant_key=tenant_key,
                is_active=True,
            )
            session.add(org)
            await session.flush()

            user = User(
                id=str(_uuid4()),
                username=f"idem_refresh_{_uuid4().hex[:8]}",
                email=f"idem_refresh_{_uuid4().hex[:8]}@example.com",
                role="developer",
                tenant_key=tenant_key,
                is_active=True,
                org_id=org.id,
            )
            session.add(user)
            await session.flush()

            session.add(
                OAuthAuthorizationCode(
                    code=code_value,
                    client_id=client_id,
                    user_id=user.id,
                    tenant_key=tenant_key,
                    redirect_uri=redirect_uri,
                    code_challenge=challenge,
                    code_challenge_method="S256",
                    scope="mcp:read mcp:write",
                    resource=None,
                    expires_at=datetime.now(UTC) + timedelta(minutes=10),
                    used=False,
                )
            )
            await session.commit()

        restore = _install_confidential_resolver(client_id, secret_hash, redirect_uri)
        try:
            initial = await api_client.post(
                "/api/oauth/token",
                data={
                    "grant_type": "authorization_code",
                    "code": code_value,
                    "client_id": client_id,
                    "code_verifier": verifier,
                    "redirect_uri": redirect_uri,
                    "client_secret": plaintext_secret,
                },
            )
            assert initial.status_code == 200, initial.text
            r1 = initial.json()["refresh_token"]

            refresh_payload = {
                "grant_type": "refresh_token",
                "refresh_token": r1,
                "client_id": client_id,
                "client_secret": plaintext_secret,
            }
            first = await api_client.post("/api/oauth/refresh", data=refresh_payload)
            second = await api_client.post("/api/oauth/refresh", data=refresh_payload)
        finally:
            restore()

        assert first.status_code == 200, first.text
        assert second.status_code == 200, second.text
        body1 = first.json()
        body2 = second.json()
        assert body1["access_token"] == body2["access_token"], (body1, body2)
        assert body1["refresh_token"] == body2["refresh_token"], (body1, body2)

    @pytest.mark.asyncio
    async def test_post_window_refresh_triggers_reuse_detection(self, api_client, db_manager, monkeypatch):
        """/refresh equivalent of test #2: outside the window the second
        POST hits the existing reuse-detection path (the first call already
        rotated and revoked r1) and returns 401 invalid_grant.
        """
        import time as _time
        from uuid import uuid4 as _uuid4

        import bcrypt as _bcrypt

        from giljo_mcp.services import oauth_refresh_service as _refresh_svc

        monkeypatch.setattr(_refresh_svc, "OAUTH_REFRESH_IDEMPOTENCY_WINDOW_SECONDS", 1)

        verifier, challenge = _generate_pkce_pair()
        code_value = secrets.token_urlsafe(64)
        client_id = str(_uuid4())
        plaintext_secret = secrets.token_urlsafe(48)
        secret_hash = _bcrypt.hashpw(plaintext_secret.encode("utf-8"), _bcrypt.gensalt()).decode("ascii")
        redirect_uri = "http://localhost:3000/callback"

        from giljo_mcp.models.auth import User
        from giljo_mcp.models.oauth import OAuthAuthorizationCode
        from giljo_mcp.models.organizations import Organization
        from giljo_mcp.tenant import TenantManager

        tenant_key = TenantManager.generate_tenant_key()
        async with db_manager.get_session_async() as session:
            org = Organization(
                name=f"Idem Refresh Window Org {_uuid4().hex[:6]}",
                slug=f"idem-refresh-win-{_uuid4().hex[:8]}",
                tenant_key=tenant_key,
                is_active=True,
            )
            session.add(org)
            await session.flush()

            user = User(
                id=str(_uuid4()),
                username=f"idem_refresh_win_{_uuid4().hex[:8]}",
                email=f"idem_refresh_win_{_uuid4().hex[:8]}@example.com",
                role="developer",
                tenant_key=tenant_key,
                is_active=True,
                org_id=org.id,
            )
            session.add(user)
            await session.flush()

            session.add(
                OAuthAuthorizationCode(
                    code=code_value,
                    client_id=client_id,
                    user_id=user.id,
                    tenant_key=tenant_key,
                    redirect_uri=redirect_uri,
                    code_challenge=challenge,
                    code_challenge_method="S256",
                    scope="mcp:read mcp:write",
                    resource=None,
                    expires_at=datetime.now(UTC) + timedelta(minutes=10),
                    used=False,
                )
            )
            await session.commit()

        restore = _install_confidential_resolver(client_id, secret_hash, redirect_uri)
        try:
            initial = await api_client.post(
                "/api/oauth/token",
                data={
                    "grant_type": "authorization_code",
                    "code": code_value,
                    "client_id": client_id,
                    "code_verifier": verifier,
                    "redirect_uri": redirect_uri,
                    "client_secret": plaintext_secret,
                },
            )
            assert initial.status_code == 200, initial.text
            r1 = initial.json()["refresh_token"]

            refresh_payload = {
                "grant_type": "refresh_token",
                "refresh_token": r1,
                "client_id": client_id,
                "client_secret": plaintext_secret,
            }
            first = await api_client.post("/api/oauth/refresh", data=refresh_payload)
            assert first.status_code == 200, first.text

            _time.sleep(1.5)
            second = await api_client.post("/api/oauth/refresh", data=refresh_payload)
        finally:
            restore()

        # Outside the window r1 has been rotated + revoked, so the second
        # call hits the existing reuse-detection path: 401 invalid_grant.
        assert second.status_code == 401, second.text
        body = second.json()
        detail_text = _oauth_err_text(body).lower()
        assert "invalid_grant" in detail_text, body


# ---------------------------------------------------------------------------
# API-0022: RFC 7009 /oauth/revoke endpoint tests.
#
# Boundary tests go through TestClient (not direct service calls) per the
# BE-5042 rule: test at the layer where the bug would occur. Revocation
# state is asserted by attempting a follow-up /mcp request and looking for
# 401 + WWW-Authenticate. The endpoint is idempotent (RFC 7009 §2.2): all
# happy-path and error-path responses are 200 OK except `token` missing
# (400 invalid_request — the one spec-allowed non-200 path).
# ---------------------------------------------------------------------------


async def _seed_org_user(db_manager):
    from giljo_mcp.models.auth import User
    from giljo_mcp.models.organizations import Organization
    from giljo_mcp.tenant import TenantManager

    tenant_key = TenantManager.generate_tenant_key()
    async with db_manager.get_session_async() as session:
        org = Organization(
            name=f"Revoke Test Org {uuid4().hex[:6]}",
            slug=f"revoke-org-{uuid4().hex[:8]}",
            tenant_key=tenant_key,
            is_active=True,
        )
        session.add(org)
        await session.flush()

        user = User(
            id=str(uuid4()),
            username=f"revoke_user_{uuid4().hex[:8]}",
            email=f"revoke_{uuid4().hex[:8]}@example.com",
            role="developer",
            tenant_key=tenant_key,
            is_active=True,
            org_id=org.id,
        )
        session.add(user)
        await session.commit()
        return tenant_key, str(user.id)


def _mint_access_jwt(*, tenant_key: str, user_id: str, aud: str | None = None) -> str:
    """Issue an access JWT through JWTManager so it carries a real jti."""
    from uuid import UUID as _UUID

    from giljo_mcp.auth.jwt_manager import JWTManager

    return JWTManager.create_access_token(
        user_id=_UUID(user_id),
        username="revoke_user",
        role="developer",
        tenant_key=tenant_key,
        audience=aud,
        scope="mcp:read mcp:write",
    )


class TestOAuthRevokeEndpoint:
    """RFC 7009 /api/oauth/revoke endpoint (API-0022)."""

    @pytest.mark.asyncio
    async def test_missing_token_returns_400(self, api_client):
        """RFC 7009 §2.1: token is REQUIRED; absent returns invalid_request."""
        response = await api_client.post("/api/oauth/revoke", data={})
        assert response.status_code == 400, response.text
        body = response.json()
        detail = _oauth_err_text(body).lower()
        assert "invalid_request" in detail or "token" in detail

    @pytest.mark.asyncio
    async def test_garbage_token_returns_200(self, api_client):
        """RFC 7009 section 2.2: unknown/foreign tokens MUST still 200 (no leak)."""
        response = await api_client.post(
            "/api/oauth/revoke",
            data={"token": "this-is-not-a-real-token"},
        )
        assert response.status_code == 200, response.text

    @pytest.mark.asyncio
    async def test_access_jwt_revoked_then_mcp_request_returns_401(self, api_client, db_manager, monkeypatch):
        """Happy path: revoke an access JWT, subsequent /mcp request 401s.

        Boundary test through TestClient: proves the jti makes it into
        oauth_revoked_tokens AND that the MCP middleware enforces it.
        """
        from giljo_mcp.services.oauth_revocation_service import clear_revocation_cache

        clear_revocation_cache()

        tenant_key, user_id = await _seed_org_user(db_manager)
        canonical_aud = "http://test/mcp"
        token = _mint_access_jwt(tenant_key=tenant_key, user_id=user_id, aud=canonical_aud)

        # No pre-revoke /mcp probe: the MCP SDK inner app needs an active
        # session_manager (lifespan run()) that the test ASGITransport does
        # not start, so requests that PASS auth crash inside the inner app.
        # The post-revocation 401 below is asserted at the middleware layer
        # — that's the layer the bug would live in (BE-5042 rule).

        revoke_response = await api_client.post(
            "/api/oauth/revoke",
            data={"token": token, "token_type_hint": "access_token"},
        )
        assert revoke_response.status_code == 200, revoke_response.text

        clear_revocation_cache()

        post = await api_client.post(
            "/mcp",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream",
            },
            json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        )
        assert post.status_code == 401, f"post-revoke /mcp must 401, got {post.status_code}: {post.text[:200]}"
        www_auth = post.headers.get("www-authenticate", "")
        assert "Bearer" in www_auth and 'realm="MCP"' in www_auth, www_auth

    @pytest.mark.asyncio
    async def test_revoke_is_idempotent(self, api_client, db_manager):
        """Already-revoked tokens revoke cleanly (200 OK, no duplicate row)."""
        from sqlalchemy import select

        from giljo_mcp.database import tenant_isolation_bypass
        from giljo_mcp.models.oauth import OAuthRevokedToken
        from giljo_mcp.services.oauth_revocation_service import clear_revocation_cache

        clear_revocation_cache()

        tenant_key, user_id = await _seed_org_user(db_manager)
        token = _mint_access_jwt(tenant_key=tenant_key, user_id=user_id, aud="http://test/mcp")

        first = await api_client.post("/api/oauth/revoke", data={"token": token})
        assert first.status_code == 200, first.text

        second = await api_client.post("/api/oauth/revoke", data={"token": token})
        assert second.status_code == 200, second.text

        # Test-only verification read on a bare session; use the audited bypass.
        async with db_manager.get_session_async() as session:
            with tenant_isolation_bypass(
                session,
                reason="test: verify single revocation row for tenant",
                models=(OAuthRevokedToken,),
            ):
                result = await session.execute(
                    select(OAuthRevokedToken).where(OAuthRevokedToken.tenant_key == tenant_key)
                )
                rows = result.scalars().all()
        assert len(rows) == 1, f"expected single revocation row, got {len(rows)}"

    @pytest.mark.asyncio
    async def test_tenant_isolation_revoked_in_a_does_not_affect_b(self, api_client, db_manager, monkeypatch):
        """CLAUDE.md tenant-isolation: revocation is tenant-scoped."""
        from giljo_mcp.services.oauth_revocation_service import clear_revocation_cache

        clear_revocation_cache()

        canonical_aud = "http://test/mcp"

        tenant_a, user_a = await _seed_org_user(db_manager)
        tenant_b, user_b = await _seed_org_user(db_manager)
        token_a = _mint_access_jwt(tenant_key=tenant_a, user_id=user_a, aud=canonical_aud)
        token_b = _mint_access_jwt(tenant_key=tenant_b, user_id=user_b, aud=canonical_aud)

        revoke_a = await api_client.post("/api/oauth/revoke", data={"token": token_a})
        assert revoke_a.status_code == 200

        clear_revocation_cache()

        post_a = await api_client.post(
            "/mcp",
            headers={
                "Authorization": f"Bearer {token_a}",
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream",
            },
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
        )
        assert post_a.status_code == 401, post_a.text

        # Tenant B's token must NOT be revoked. The /mcp inner app crashes
        # in tests when auth passes (no session_manager lifespan), so we
        # assert at the service layer instead. is_access_token_jti_revoked
        # is the function the /mcp middleware actually calls; a False here
        # means the middleware would let tenant B through.
        from jwt import decode as _jwt_decode

        from giljo_mcp.services.oauth_revocation_service import is_access_token_jti_revoked

        jwt_b_payload = _jwt_decode(token_b, options={"verify_signature": False})
        jti_b = jwt_b_payload["jti"]
        async with db_manager.get_session_async() as _check_db:
            assert await is_access_token_jti_revoked(_check_db, tenant_key=tenant_b, jti=jti_b) is False, (
                "tenant B's jti was incorrectly marked revoked when tenant A's token was revoked"
            )


class TestOAuthErrorEnvelopeConformance:
    """BE-6040: RFC 6749 §5.2 token-endpoint error envelope + metadata hardening.

    The token/refresh/revoke error surface must carry the machine-readable code
    in a top-level ``error`` member (the legacy global handler serialised it
    under ``error_code``/``message``, which spec-strict OAuth clients ignore).
    Boundary tests through the HTTP layer — the layer where the bug occurred.
    """

    @pytest.mark.asyncio
    async def test_token_missing_field_uses_rfc6749_error_envelope(self, api_client):
        """A /token request missing required fields → RFC 6749 §5.2 envelope."""
        response = await api_client.post("/api/oauth/token", data={"grant_type": "authorization_code"})
        assert response.status_code == 400, response.text
        body = response.json()
        assert body.get("error") == "invalid_request", body
        # Legacy shape must be gone — no error_code / message top-level members.
        assert "error_code" not in body, body
        assert "message" not in body, body

    @pytest.mark.asyncio
    async def test_token_malformed_json_uses_rfc6749_error_envelope(self, api_client):
        """A malformed JSON /token body → 400 with a top-level `error` member.

        Exercises the body-parse path (raised inside _parse_oauth_body), which
        previously escaped to the legacy global handler shape.
        """
        response = await api_client.post(
            "/api/oauth/token",
            content=b"{not json",
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == 400, response.text
        body = response.json()
        assert body.get("error") == "invalid_request", body
        assert "error_code" not in body and "message" not in body, body

    @pytest.mark.asyncio
    async def test_refresh_missing_field_uses_rfc6749_error_envelope(self, api_client):
        """A /refresh request missing required fields → RFC 6749 §5.2 envelope."""
        response = await api_client.post("/api/oauth/refresh", data={"grant_type": "refresh_token"})
        assert response.status_code == 400, response.text
        body = response.json()
        assert body.get("error") == "invalid_request", body
        assert "error_code" not in body and "message" not in body, body

    @pytest.mark.asyncio
    async def test_revoke_missing_token_uses_rfc6749_error_envelope(self, api_client):
        """RFC 7009 §3: the lone /revoke 400 path uses the RFC 6749 §5.2 envelope."""
        response = await api_client.post("/api/oauth/revoke", data={})
        assert response.status_code == 400, response.text
        body = response.json()
        assert body.get("error") == "invalid_request", body
        assert "error_code" not in body and "message" not in body, body

    @pytest.mark.asyncio
    async def test_metadata_advertises_revocation_endpoint(self, api_client):
        """BE-6040: RFC 8414 — advertise the RFC 7009 revocation_endpoint (absolute)."""
        response = await api_client.get("/api/oauth/.well-known/oauth-authorization-server")
        assert response.status_code == 200, response.text
        data = response.json()
        assert "revocation_endpoint" in data, data
        assert data["revocation_endpoint"].startswith(("http://", "https://")), data
        assert data["revocation_endpoint"].endswith("/api/oauth/revoke"), data
