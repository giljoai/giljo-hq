# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import base64
import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import pytest

from giljo_mcp.services.oauth_service import BUILTIN_CLIENT_ID


def _generate_pkce_pair() -> tuple[str, str]:
    code_verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    code_challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return code_verifier, code_challenge


def _oauth_err_text(body: dict) -> str:
    return " ".join(str(body.get(k, "")) for k in ("error", "error_description", "detail", "message"))


class TestOAuthMetadataEndpoint:

    @pytest.mark.asyncio
    async def test_metadata_endpoint_returns_correct_fields(self, api_client):
        response = await api_client.get("/api/oauth/.well-known/oauth-authorization-server")
        assert response.status_code == 200

        data = response.json()
        assert "issuer" in data
        assert data["authorization_endpoint"].endswith("/oauth/authorize")
        assert data["authorization_endpoint"].startswith(("http://", "https://"))
        assert data["token_endpoint"].endswith("/api/oauth/token")
        assert data["token_endpoint"].startswith(("http://", "https://"))
        assert data["response_types_supported"] == ["code"]
        assert data["code_challenge_methods_supported"] == ["S256"]
        assert data["grant_types_supported"] == ["authorization_code", "refresh_token"]

    @pytest.mark.asyncio
    async def test_metadata_endpoint_is_public(self, api_client):
        response = await api_client.get("/api/oauth/.well-known/oauth-authorization-server")
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_metadata_advertises_ce_dcr_endpoint(self, api_client):
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
        response = await api_client.get("/api/oauth/.well-known/oauth-authorization-server")
        assert response.status_code == 200
        data = response.json()
        scopes = data.get("scopes_supported")
        assert isinstance(scopes, list) and scopes, "scopes_supported must be a non-empty list"
        assert all(isinstance(s, str) for s in scopes), "every scope must be a string"
        from giljo_mcp.services.oauth_service import OAUTH_GRANTABLE_SCOPES

        assert scopes == sorted(OAUTH_GRANTABLE_SCOPES), "scopes_supported must equal sorted(OAUTH_GRANTABLE_SCOPES)"
        assert "mcp:agent" in scopes, "BE-6168: mcp:agent must be advertised"

    @pytest.mark.asyncio
    async def test_metadata_advertises_token_endpoint_auth_methods(self, api_client):
        response = await api_client.get("/api/oauth/.well-known/oauth-authorization-server")
        assert response.status_code == 200
        data = response.json()
        methods = data.get("token_endpoint_auth_methods_supported")
        assert methods == ["client_secret_post", "client_secret_basic", "none"]

    @pytest.mark.asyncio
    async def test_openid_configuration_returns_404(self, api_client):
        response = await api_client.get("/.well-known/openid-configuration")
        assert response.status_code == 404, (
            f"OIDC discovery must 404 (not {response.status_code}); body: {response.text[:200]}"
        )


class TestOAuthTokenEndpoint:

    @pytest.mark.asyncio
    async def test_token_endpoint_rejects_invalid_grant_type(self, api_client):
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
        body = response.json()
        assert body["error"] == "unsupported_grant_type"
        assert "grant_type" in _oauth_err_text(body).lower()

    @pytest.mark.asyncio
    async def test_token_endpoint_rejects_bad_pkce(self, api_client, db_manager):
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
        assert body.get("error") == "invalid_request", body
        detail_text = _oauth_err_text(body).lower()
        assert "pkce" not in detail_text, "Error should not leak PKCE details"
        assert "verifier" not in detail_text, "Error should not leak verifier details"

    @pytest.mark.asyncio
    async def test_token_endpoint_returns_jwt(self, api_client, db_manager):
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
        assert isinstance(data.get("refresh_token"), str) and data["refresh_token"], (
            f"public client must receive a non-empty string refresh_token: {data}"
        )
        assert isinstance(data.get("refresh_expires_in"), int) and data["refresh_expires_in"] > 0, data
        assert '"refresh_token":null' not in response.text.replace(" ", "")

    @pytest.mark.asyncio
    async def test_token_endpoint_is_public(self, api_client):
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

    @pytest.mark.asyncio
    async def test_authorize_endpoint_validates_params(self, api_client, auth_headers):
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


def _deny_body(**overrides) -> dict:
    _verifier, challenge = _generate_pkce_pair()
    body = {
        "client_id": BUILTIN_CLIENT_ID,
        "redirect_uri": "http://localhost:3000/callback",
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "scope": "mcp:read mcp:write",
        "state": "deny-state-value",
        "response_type": "code",
    }
    body.update(overrides)
    return body


class TestOAuthDenyEndpoint:

    @pytest.mark.asyncio
    async def test_deny_rejects_unregistered_redirect_uri(self, api_client, auth_headers):
        response = await api_client.post(
            "/api/oauth/authorize/deny",
            headers=auth_headers,
            json=_deny_body(redirect_uri="https://attacker.example/steal"),
        )
        assert response.status_code == 400
        assert "redirect_uri" not in response.json()
        assert "attacker.example" not in response.text

    @pytest.mark.asyncio
    async def test_deny_rejects_unknown_client(self, api_client, auth_headers):
        response = await api_client.post(
            "/api/oauth/authorize/deny",
            headers=auth_headers,
            json=_deny_body(client_id="invalid-client-id"),
        )
        assert response.status_code == 400
        assert "redirect_uri" not in response.json()

    @pytest.mark.asyncio
    async def test_deny_registered_pair_returns_access_denied_redirect(self, api_client, auth_headers):
        response = await api_client.post(
            "/api/oauth/authorize/deny",
            headers=auth_headers,
            json=_deny_body(),
        )
        assert response.status_code == 200
        target = urlsplit(response.json()["redirect_uri"])
        assert f"{target.scheme}://{target.netloc}{target.path}" == "http://localhost:3000/callback"
        query = parse_qs(target.query)
        assert query["error"] == ["access_denied"]
        assert query["state"] == ["deny-state-value"]
        assert query["error_description"]
        assert "code" not in query

    @pytest.mark.asyncio
    async def test_deny_requires_auth(self, api_client):
        response = await api_client.post("/api/oauth/authorize/deny", json=_deny_body())
        assert response.status_code in (401, 403)


class TestAuthorizeRequestInputHardening:

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




async def _seed_user_and_code(
    db_manager,
    *,
    challenge: str,
    code_value: str,
    resource: str | None,
    redirect_uri: str = "http://localhost:3000/callback",
    client_id: str = BUILTIN_CLIENT_ID,
):
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

    @pytest.mark.asyncio
    async def test_token_uses_bound_resource_when_request_omits_it(self, api_client, db_manager):
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
            },
        )
        assert response.status_code == 200, response.text
        body = response.json()
        decoded = _jwt.decode(body["access_token"], options={"verify_signature": False})
        assert decoded.get("aud") == bound_resource, decoded

    @pytest.mark.asyncio
    async def test_token_resource_mismatch_returns_401_invalid_grant(self, api_client, db_manager):
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

        decoded = _jwt.decode(access_token, options={"verify_signature": False})
        assert decoded.get("aud") == bound_resource, decoded

    @pytest.mark.asyncio
    async def test_legacy_audless_code_still_issues_token(self, api_client, db_manager):
        import jwt as _jwt

        verifier, challenge = _generate_pkce_pair()
        code_value = secrets.token_urlsafe(64)
        await _seed_user_and_code(
            db_manager,
            challenge=challenge,
            code_value=code_value,
            resource=None,
        )

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
        assert response.status_code == 200, response.text
        body = response.json()
        access_token = body["access_token"]
        decoded = _jwt.decode(access_token, options={"verify_signature": False})
        assert "aud" in decoded, decoded
        assert decoded["aud"].endswith("/mcp"), decoded

    @pytest.mark.asyncio
    async def test_authorize_persists_resource_onto_code(self, api_client, auth_headers, db_manager):
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
        redirect_url = data["redirect_uri"]
        assert "code=" in redirect_url
        issued_code = redirect_url.split("code=", 1)[1].split("&", 1)[0]

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
                "resource": "mcp.example.com/mcp",
            },
        )
        assert response.status_code == 400, response.text


class TestProtectedResourceMetadataResourceIndicators:

    @pytest.mark.asyncio
    async def test_root_metadata_advertises_resource_indicators_supported(self, api_client):
        response = await api_client.get("/.well-known/oauth-protected-resource")
        assert response.status_code == 200, response.text
        body = response.json()
        assert body.get("resource_indicators_supported") is True, body


class TestProtectedResourceMetadataPathSuffix:

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




async def _seed_confidential_dcr_code(
    db_manager,
    *,
    challenge: str,
    code_value: str,
    redirect_uri: str = "http://localhost:3000/callback",
    plaintext_secret: str | None = None,
) -> tuple[str, str, str, str]:
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
    from giljo_mcp.services import oauth_service as svc

    prior = svc.get_client_resolver()

    def _resolver(cid: str, tenant_key: str):
        assert tenant_key
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
            },
        )
        assert response.status_code == 200, response.text


    @pytest.mark.asyncio
    async def test_token_exchange_confidential_client_no_pkce_rejected(self, api_client, db_manager):
        verifier, challenge = _generate_pkce_pair()
        del verifier
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
                },
            )
        finally:
            restore()

        assert response.status_code == 400, response.text
        detail_text = _oauth_err_text(response.json())
        assert "invalid_request" in detail_text.lower(), response.text

    @pytest.mark.asyncio
    async def test_token_exchange_confidential_client_with_wrong_pkce_rejected(self, api_client, db_manager):
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
            },
        )
        assert response.status_code == 400, response.text
        body = response.json()
        detail_text = _oauth_err_text(body)
        assert "invalid_request" in detail_text.lower(), body


class TestTokenAcceptsJsonAndBasicAuth:

    @pytest.mark.asyncio
    async def test_token_exchange_accepts_json_content_type(self, api_client, db_manager):
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

    @pytest.mark.asyncio
    async def test_authorize_with_claude_com_redirect_succeeds(self, api_client, auth_headers):
        from giljo_mcp.services import oauth_service as svc

        _verifier, challenge = _generate_pkce_pair()
        prior = svc.get_client_resolver()

        def _resolver(client_id: str, tenant_key: str):
            assert tenant_key
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




class TestTokenIdempotency:

    @pytest.mark.asyncio
    async def test_concurrent_same_code_returns_same_token_pair(self, api_client, db_manager):
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
        verifier, challenge = _generate_pkce_pair()
        code_value = secrets.token_urlsafe(64)
        client_id, plaintext_secret, _tenant_key, secret_hash = await _seed_confidential_dcr_code(
            db_manager, challenge=challenge, code_value=code_value
        )

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
        import bcrypt as _bcrypt

        verifier, challenge = _generate_pkce_pair()
        code_value = secrets.token_urlsafe(64)
        from uuid import uuid4 as _uuid4

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

        assert second.status_code == 401, second.text
        body = second.json()
        detail_text = _oauth_err_text(body).lower()
        assert "invalid_grant" in detail_text, body




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

    @pytest.mark.asyncio
    async def test_missing_token_returns_400(self, api_client):
        response = await api_client.post("/api/oauth/revoke", data={})
        assert response.status_code == 400, response.text
        body = response.json()
        detail = _oauth_err_text(body).lower()
        assert "invalid_request" in detail or "token" in detail

    @pytest.mark.asyncio
    async def test_garbage_token_returns_200(self, api_client):
        response = await api_client.post(
            "/api/oauth/revoke",
            data={"token": "this-is-not-a-real-token"},
        )
        assert response.status_code == 200, response.text

    @pytest.mark.asyncio
    async def test_access_jwt_revoked_then_mcp_request_returns_401(self, api_client, db_manager, monkeypatch):
        from giljo_mcp.services.oauth_revocation_service import clear_revocation_cache

        clear_revocation_cache()

        tenant_key, user_id = await _seed_org_user(db_manager)
        canonical_aud = "http://test/mcp"
        token = _mint_access_jwt(tenant_key=tenant_key, user_id=user_id, aud=canonical_aud)


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

        from jwt import decode as _jwt_decode

        from giljo_mcp.services.oauth_revocation_service import is_access_token_jti_revoked

        jwt_b_payload = _jwt_decode(token_b, options={"verify_signature": False})
        jti_b = jwt_b_payload["jti"]
        async with db_manager.get_session_async() as _check_db:
            assert await is_access_token_jti_revoked(_check_db, tenant_key=tenant_b, jti=jti_b) is False, (
                "tenant B's jti was incorrectly marked revoked when tenant A's token was revoked"
            )


class TestOAuthErrorEnvelopeConformance:

    @pytest.mark.asyncio
    async def test_token_missing_field_uses_rfc6749_error_envelope(self, api_client):
        response = await api_client.post("/api/oauth/token", data={"grant_type": "authorization_code"})
        assert response.status_code == 400, response.text
        body = response.json()
        assert body.get("error") == "invalid_request", body
        assert "error_code" not in body, body
        assert "message" not in body, body

    @pytest.mark.asyncio
    async def test_token_malformed_json_uses_rfc6749_error_envelope(self, api_client):
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
        response = await api_client.post("/api/oauth/refresh", data={"grant_type": "refresh_token"})
        assert response.status_code == 400, response.text
        body = response.json()
        assert body.get("error") == "invalid_request", body
        assert "error_code" not in body and "message" not in body, body

    @pytest.mark.asyncio
    async def test_revoke_missing_token_uses_rfc6749_error_envelope(self, api_client):
        response = await api_client.post("/api/oauth/revoke", data={})
        assert response.status_code == 400, response.text
        body = response.json()
        assert body.get("error") == "invalid_request", body
        assert "error_code" not in body and "message" not in body, body

    @pytest.mark.asyncio
    async def test_metadata_advertises_revocation_endpoint(self, api_client):
        response = await api_client.get("/api/oauth/.well-known/oauth-authorization-server")
        assert response.status_code == 200, response.text
        data = response.json()
        assert "revocation_endpoint" in data, data
        assert data["revocation_endpoint"].startswith(("http://", "https://")), data
        assert data["revocation_endpoint"].endswith("/api/oauth/revoke"), data


async def _seed_auth_code_for_client(db_manager, *, client_id: str, redirect_uri: str) -> tuple[str, str]:
    from giljo_mcp.models.auth import User
    from giljo_mcp.models.oauth import OAuthAuthorizationCode
    from giljo_mcp.models.organizations import Organization
    from giljo_mcp.tenant import TenantManager

    verifier, challenge = _generate_pkce_pair()
    code_value = secrets.token_urlsafe(64)
    tenant_key = TenantManager.generate_tenant_key()

    async with db_manager.get_session_async() as session:
        org = Organization(
            name=f"BE9409 Org {uuid4().hex[:6]}",
            slug=f"be9409-{uuid4().hex[:8]}",
            tenant_key=tenant_key,
            is_active=True,
        )
        session.add(org)
        await session.flush()

        user = User(
            id=str(uuid4()),
            username=f"be9409_{uuid4().hex[:8]}",
            email=f"be9409_{uuid4().hex[:8]}@example.com",
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
                expires_at=datetime.now(UTC) + timedelta(minutes=10),
                used=False,
            )
        )
        await session.commit()

    return code_value, verifier


class TestTokenEndpointRefreshGrant:

    REDIRECT_URI = "http://localhost:3000/callback"

    async def _mint_public_refresh_token(self, api_client, db_manager) -> str:
        code_value, verifier = await _seed_auth_code_for_client(
            db_manager, client_id=BUILTIN_CLIENT_ID, redirect_uri=self.REDIRECT_URI
        )
        response = await api_client.post(
            "/api/oauth/token",
            data={
                "grant_type": "authorization_code",
                "code": code_value,
                "client_id": BUILTIN_CLIENT_ID,
                "code_verifier": verifier,
                "redirect_uri": self.REDIRECT_URI,
            },
        )
        assert response.status_code == 200, response.text
        refresh_token = response.json()["refresh_token"]
        assert isinstance(refresh_token, str) and refresh_token, response.text
        return refresh_token

    @pytest.mark.asyncio
    async def test_token_endpoint_serves_refresh_grant_for_public_client(self, api_client, db_manager):
        original = await self._mint_public_refresh_token(api_client, db_manager)

        response = await api_client.post(
            "/api/oauth/token",
            data={
                "grant_type": "refresh_token",
                "refresh_token": original,
                "client_id": BUILTIN_CLIENT_ID,
            },
        )

        assert response.status_code == 200, response.text
        body = response.json()
        assert isinstance(body.get("access_token"), str) and body["access_token"], body
        assert body.get("token_type"), body
        assert isinstance(body.get("expires_in"), int), body
        assert isinstance(body.get("refresh_token"), str) and body["refresh_token"], body
        assert body["refresh_token"] != original, "refresh token was not rotated"

    @pytest.mark.asyncio
    async def test_token_endpoint_refresh_grant_rejects_unknown_token(self, api_client):
        response = await api_client.post(
            "/api/oauth/token",
            data={
                "grant_type": "refresh_token",
                "refresh_token": secrets.token_urlsafe(48),
                "client_id": BUILTIN_CLIENT_ID,
            },
        )
        assert response.status_code == 401, response.text
        assert response.json().get("error") == "invalid_grant", response.text

    @pytest.mark.asyncio
    async def test_token_endpoint_unknown_grant_type_is_unsupported_not_missing_fields(self, api_client):
        response = await api_client.post(
            "/api/oauth/token",
            data={"grant_type": "client_credentials", "client_id": BUILTIN_CLIENT_ID},
        )
        assert response.status_code == 400, response.text
        body = response.json()
        assert body.get("error") == "unsupported_grant_type", body
        assert "missing required field" not in _oauth_err_text(body).lower(), body

    @pytest.mark.asyncio
    async def test_token_endpoint_absent_grant_type_stays_invalid_request(self, api_client):
        response = await api_client.post("/api/oauth/token", data={"client_id": BUILTIN_CLIENT_ID})
        assert response.status_code == 400, response.text
        body = response.json()
        assert body.get("error") == "invalid_request", body
        assert "grant_type" in _oauth_err_text(body), body

    @pytest.mark.asyncio
    async def test_token_endpoint_refresh_grant_rejects_wrong_client_secret(self, api_client, db_manager):
        import bcrypt as _bcrypt

        client_id = str(uuid4())
        plaintext_secret = secrets.token_urlsafe(48)
        secret_hash = _bcrypt.hashpw(plaintext_secret.encode("utf-8"), _bcrypt.gensalt()).decode("ascii")
        code_value, verifier = await _seed_auth_code_for_client(
            db_manager, client_id=client_id, redirect_uri=self.REDIRECT_URI
        )

        restore = _install_confidential_resolver(client_id, secret_hash, self.REDIRECT_URI)
        try:
            initial = await api_client.post(
                "/api/oauth/token",
                data={
                    "grant_type": "authorization_code",
                    "code": code_value,
                    "client_id": client_id,
                    "code_verifier": verifier,
                    "redirect_uri": self.REDIRECT_URI,
                    "client_secret": plaintext_secret,
                },
            )
            assert initial.status_code == 200, initial.text
            refresh_token = initial.json()["refresh_token"]

            response = await api_client.post(
                "/api/oauth/token",
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": refresh_token,
                    "client_id": client_id,
                    "client_secret": f"wrong-{plaintext_secret}",
                },
            )
        finally:
            restore()

        assert response.status_code == 401, response.text
        assert response.json().get("error") == "invalid_client", response.text
        assert response.headers.get("WWW-Authenticate") == 'Basic realm="oauth"', dict(response.headers)

    @pytest.mark.asyncio
    async def test_token_endpoint_refresh_grant_accepts_basic_auth_credentials(self, api_client, db_manager):
        import bcrypt as _bcrypt

        client_id = str(uuid4())
        plaintext_secret = secrets.token_urlsafe(48)
        secret_hash = _bcrypt.hashpw(plaintext_secret.encode("utf-8"), _bcrypt.gensalt()).decode("ascii")
        code_value, verifier = await _seed_auth_code_for_client(
            db_manager, client_id=client_id, redirect_uri=self.REDIRECT_URI
        )
        basic = base64.b64encode(f"{client_id}:{plaintext_secret}".encode()).decode("ascii")

        restore = _install_confidential_resolver(client_id, secret_hash, self.REDIRECT_URI)
        try:
            initial = await api_client.post(
                "/api/oauth/token",
                data={
                    "grant_type": "authorization_code",
                    "code": code_value,
                    "client_id": client_id,
                    "code_verifier": verifier,
                    "redirect_uri": self.REDIRECT_URI,
                    "client_secret": plaintext_secret,
                },
            )
            assert initial.status_code == 200, initial.text
            refresh_token = initial.json()["refresh_token"]

            response = await api_client.post(
                "/api/oauth/token",
                data={"grant_type": "refresh_token", "refresh_token": refresh_token},
                headers={"Authorization": f"Basic {basic}"},
            )
        finally:
            restore()

        assert response.status_code == 200, response.text
        body = response.json()
        assert isinstance(body.get("access_token"), str) and body["access_token"], body
        assert body.get("refresh_token") != refresh_token, "refresh token was not rotated"

    @pytest.mark.asyncio
    async def test_refresh_grant_envelope_matches_refresh_route(self, api_client):
        payload = {
            "grant_type": "refresh_token",
            "refresh_token": secrets.token_urlsafe(48),
            "client_id": BUILTIN_CLIENT_ID,
        }
        via_refresh = await api_client.post("/api/oauth/refresh", data=payload)
        via_token = await api_client.post("/api/oauth/token", data=payload)

        assert via_token.status_code == via_refresh.status_code, (
            f"/token returned {via_token.status_code} {via_token.text}; "
            f"/refresh returned {via_refresh.status_code} {via_refresh.text}"
        )
        assert via_token.json().get("error") == via_refresh.json().get("error"), (
            via_token.text,
            via_refresh.text,
        )
        assert via_token.headers.get("WWW-Authenticate") == via_refresh.headers.get("WWW-Authenticate"), (
            dict(via_token.headers),
            dict(via_refresh.headers),
        )
