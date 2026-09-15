# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import pytest

from giljo_mcp.services.oauth_service import (
    ALLOWED_REDIRECT_URI_PATTERNS,
    BUILTIN_CLIENT_ID,
    OAuthService,
    ResolvedClient,
    _builtin_single_client_resolver,
    get_client_resolver,
    set_client_resolver,
)


@pytest.fixture(autouse=True)
def _restore_default_resolver():
    original = get_client_resolver()
    yield
    set_client_resolver(original)


class TestBuiltinResolver:

    def test_returns_resolved_client_for_builtin_id(self):
        resolved = _builtin_single_client_resolver(BUILTIN_CLIENT_ID, "tk_irrelevant")
        assert resolved is not None
        assert resolved.client_id == BUILTIN_CLIENT_ID
        assert resolved.client_secret_hash is None
        assert resolved.redirect_uris is None

    def test_returns_none_for_unknown_client_id(self):
        assert _builtin_single_client_resolver("unknown-client", "tk_irrelevant") is None

    def test_builtin_is_tenant_agnostic(self):
        a = _builtin_single_client_resolver(BUILTIN_CLIENT_ID, "tk_A")
        b = _builtin_single_client_resolver(BUILTIN_CLIENT_ID, "tk_B")
        assert a is not None and b is not None
        assert a.client_id == b.client_id == BUILTIN_CLIENT_ID

    def test_get_client_resolver_returns_callable(self):
        resolver = get_client_resolver()
        assert callable(resolver)
        assert resolver(BUILTIN_CLIENT_ID, "tk_irrelevant").client_id == BUILTIN_CLIENT_ID


class TestSetClientResolver:

    def test_replacement_is_used_for_lookup(self):
        sentinel = ResolvedClient(
            client_id="dcr-client-xyz",
            client_name="Claude.ai",
            redirect_uris=["https://claude.ai/oauth/callback"],
            client_secret_hash="$2b$12$dummyhash",
        )

        def custom_resolver(client_id: str, tenant_key: str):
            if client_id == sentinel.client_id and tenant_key == "tk_owner":
                return sentinel
            return None

        set_client_resolver(custom_resolver)

        assert get_client_resolver()(sentinel.client_id, "tk_owner") is sentinel
        assert get_client_resolver()("anything-else", "tk_owner") is None
        assert get_client_resolver()(sentinel.client_id, "tk_other") is None

    def test_rejects_non_callable(self):
        with pytest.raises(TypeError, match="callable"):
            set_client_resolver("not-callable")  # type: ignore[arg-type]


@pytest.mark.asyncio
class TestValidateAuthorizeWithResolver:

    def _make_pkce(self):
        import base64
        import hashlib
        import secrets

        verifier = secrets.token_urlsafe(64)
        digest = hashlib.sha256(verifier.encode("ascii")).digest()
        challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
        return verifier, challenge

    async def test_builtin_client_with_localhost_uri_passes(self):
        svc = OAuthService(db_session=None)  # type: ignore[arg-type]
        _v, challenge = self._make_pkce()
        await svc.validate_authorize_request(
            client_id=BUILTIN_CLIENT_ID,
            redirect_uri="http://localhost:3000/callback",
            code_challenge=challenge,
            code_challenge_method="S256",
            response_type="code",
            scope="mcp:read",
            tenant_key="tk_seam_test",
        )

    async def test_unknown_client_rejected_by_default_resolver(self):
        svc = OAuthService(db_session=None)  # type: ignore[arg-type]
        _v, challenge = self._make_pkce()
        with pytest.raises(ValueError, match="client_id"):
            await svc.validate_authorize_request(
                client_id="unregistered-client",
                redirect_uri="http://localhost:3000/callback",
                code_challenge=challenge,
                code_challenge_method="S256",
                response_type="code",
                scope="mcp:read",
                tenant_key="tk_seam_test",
            )

    async def test_missing_tenant_key_rejected(self):
        svc = OAuthService(db_session=None)  # type: ignore[arg-type]
        _v, challenge = self._make_pkce()
        with pytest.raises(ValueError, match="tenant_key"):
            await svc.validate_authorize_request(
                client_id=BUILTIN_CLIENT_ID,
                redirect_uri="http://localhost:3000/callback",
                code_challenge=challenge,
                code_challenge_method="S256",
                response_type="code",
                scope="mcp:read",
                tenant_key="",
            )

    async def test_injected_resolver_returning_none_causes_validate_to_raise(self):

        def always_none_resolver(client_id: str, tenant_key: str):
            return None

        set_client_resolver(always_none_resolver)
        svc = OAuthService(db_session=None)  # type: ignore[arg-type]
        _v, challenge = self._make_pkce()
        with pytest.raises(ValueError, match="client_id"):
            await svc.validate_authorize_request(
                client_id=BUILTIN_CLIENT_ID,
                redirect_uri="http://localhost:3000/callback",
                code_challenge=challenge,
                code_challenge_method="S256",
                response_type="code",
                scope="mcp:read",
                tenant_key="tk_seam_test",
            )

    async def test_async_resolver_is_awaited(self):
        sentinel = ResolvedClient(
            client_id="async-client",
            client_name="Async Test Client",
            redirect_uris=["https://async.example/cb"],
            client_secret_hash=None,
        )

        async def async_resolver(client_id: str, tenant_key: str):
            if client_id == sentinel.client_id and tenant_key == "tk_async":
                return sentinel
            return None

        set_client_resolver(async_resolver)
        svc = OAuthService(db_session=None)  # type: ignore[arg-type]
        _v, challenge = self._make_pkce()

        await svc.validate_authorize_request(
            client_id="async-client",
            redirect_uri="https://async.example/cb",
            code_challenge=challenge,
            code_challenge_method="S256",
            response_type="code",
            scope="mcp:read",
            tenant_key="tk_async",
        )

        with pytest.raises(ValueError, match="client_id"):
            await svc.validate_authorize_request(
                client_id="async-client",
                redirect_uri="https://async.example/cb",
                code_challenge=challenge,
                code_challenge_method="S256",
                response_type="code",
                scope="mcp:read",
                tenant_key="tk_other_tenant",
            )

    async def test_custom_resolver_with_exact_uri_match(self):

        def resolver(client_id: str, tenant_key: str):
            if client_id == "claudeai-client" and tenant_key == "tk_owner":
                return ResolvedClient(
                    client_id="claudeai-client",
                    client_name="Claude.ai",
                    redirect_uris=["https://claude.ai/oauth/callback"],
                    client_secret_hash="$2b$12$x",
                )
            return None

        set_client_resolver(resolver)
        svc = OAuthService(db_session=None)  # type: ignore[arg-type]
        _v, challenge = self._make_pkce()

        await svc.validate_authorize_request(
            client_id="claudeai-client",
            redirect_uri="https://claude.ai/oauth/callback",
            code_challenge=challenge,
            code_challenge_method="S256",
            response_type="code",
            scope="mcp:read",
            tenant_key="tk_owner",
        )

        with pytest.raises(ValueError, match="redirect_uri"):
            await svc.validate_authorize_request(
                client_id="claudeai-client",
                redirect_uri="https://attacker.example/callback",
                code_challenge=challenge,
                code_challenge_method="S256",
                response_type="code",
                scope="mcp:read",
                tenant_key="tk_owner",
            )

    async def test_constants_remain_exported_for_internal_use(self):
        assert BUILTIN_CLIENT_ID == "giljo-mcp-default"
        assert isinstance(ALLOWED_REDIRECT_URI_PATTERNS, list)
        assert any("localhost" in p for p in ALLOWED_REDIRECT_URI_PATTERNS)


class TestResolvedClientDataClass:

    def test_required_fields(self):
        rc = ResolvedClient(
            client_id="cid",
            client_name="Test",
            redirect_uris=None,
            client_secret_hash=None,
        )
        assert rc.client_id == "cid"
        assert rc.redirect_uris is None
        assert rc.client_secret_hash is None

    def test_concrete_redirect_uris(self):
        rc = ResolvedClient(
            client_id="cid",
            client_name="Test",
            redirect_uris=["https://a.example/cb", "https://b.example/cb"],
            client_secret_hash="$2b$12$h",
        )
        assert rc.redirect_uris == ["https://a.example/cb", "https://b.example/cb"]
