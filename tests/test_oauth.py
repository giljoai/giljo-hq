# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
Integration tests for OAuthService.

Tests OAuth 2.1 Authorization Code flow with PKCE:
- Authorization code generation and storage
- Code exchange for JWT tokens
- PKCE challenge/verifier validation
- Request validation (client_id, redirect_uri, etc.)
- Expired and used code rejection
- Cleanup of expired codes

These tests require a database session (PostgreSQL via test fixtures).
"""

import base64
import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import select

from giljo_mcp.models.auth import User
from giljo_mcp.models.oauth import OAuthAuthorizationCode
from giljo_mcp.services.oauth_service import OAuthService


def _generate_pkce_pair() -> tuple[str, str]:
    """Generate a valid PKCE code_verifier and code_challenge pair.

    Returns:
        Tuple of (code_verifier, code_challenge) where the challenge
        is the base64url-encoded SHA256 hash of the verifier.
    """
    code_verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    code_challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return code_verifier, code_challenge


@pytest_asyncio.fixture(scope="function")
async def test_user(db_session, test_tenant_key) -> User:
    """Create a test user for OAuth tests."""
    user = User(
        id=str(uuid4()),
        username=f"oauth_test_user_{uuid4().hex[:8]}",
        email=f"oauth_test_{uuid4().hex[:8]}@example.com",
        role="developer",
        tenant_key=test_tenant_key,
        is_active=True,
        is_system_user=False,
        must_change_password=False,
        must_set_pin=False,
        failed_pin_attempts=0,
    )
    db_session.add(user)
    await db_session.flush()
    return user


@pytest_asyncio.fixture(scope="function")
async def oauth_service(db_session) -> OAuthService:
    """Create an OAuthService instance for testing."""
    return OAuthService(db_session=db_session)


@pytest.mark.asyncio
class TestValidateAuthorizeRequest:
    """Tests for validate_authorize_request validation logic."""

    async def test_valid_request_passes(self, oauth_service, test_tenant_key):
        """A fully valid authorize request should not raise."""
        _verifier, challenge = _generate_pkce_pair()
        await oauth_service.validate_authorize_request(
            client_id="giljo-mcp-default",
            redirect_uri="http://localhost:3000/callback",
            code_challenge=challenge,
            code_challenge_method="S256",
            response_type="code",
            scope="mcp:read mcp:write",
            tenant_key=test_tenant_key,
        )

    async def test_invalid_client_id_rejected(self, oauth_service, test_tenant_key):
        """An unknown client_id must be rejected."""
        _verifier, challenge = _generate_pkce_pair()
        with pytest.raises(ValueError, match="client_id"):
            await oauth_service.validate_authorize_request(
                client_id="unknown-client",
                redirect_uri="http://localhost:3000/callback",
                code_challenge=challenge,
                code_challenge_method="S256",
                response_type="code",
                scope="mcp:read mcp:write",
                tenant_key=test_tenant_key,
            )

    async def test_invalid_response_type_rejected(self, oauth_service, test_tenant_key):
        """Only response_type='code' is allowed."""
        _verifier, challenge = _generate_pkce_pair()
        with pytest.raises(ValueError, match="response_type"):
            await oauth_service.validate_authorize_request(
                client_id="giljo-mcp-default",
                redirect_uri="http://localhost:3000/callback",
                code_challenge=challenge,
                code_challenge_method="S256",
                response_type="token",
                scope="mcp:read mcp:write",
                tenant_key=test_tenant_key,
            )

    async def test_invalid_challenge_method_rejected(self, oauth_service, test_tenant_key):
        """Only code_challenge_method='S256' is allowed."""
        _verifier, challenge = _generate_pkce_pair()
        with pytest.raises(ValueError, match="code_challenge_method"):
            await oauth_service.validate_authorize_request(
                client_id="giljo-mcp-default",
                redirect_uri="http://localhost:3000/callback",
                code_challenge=challenge,
                code_challenge_method="plain",
                response_type="code",
                scope="mcp:read mcp:write",
                tenant_key=test_tenant_key,
            )

    async def test_empty_code_challenge_rejected(self, oauth_service, test_tenant_key):
        """An empty code_challenge must be rejected."""
        with pytest.raises(ValueError, match="code_challenge"):
            await oauth_service.validate_authorize_request(
                client_id="giljo-mcp-default",
                redirect_uri="http://localhost:3000/callback",
                code_challenge="",
                code_challenge_method="S256",
                response_type="code",
                scope="mcp:read mcp:write",
                tenant_key=test_tenant_key,
            )

    async def test_disallowed_redirect_uri_rejected(self, oauth_service, test_tenant_key):
        """A redirect_uri not matching allowed patterns must be rejected."""
        _verifier, challenge = _generate_pkce_pair()
        with pytest.raises(ValueError, match="redirect_uri"):
            await oauth_service.validate_authorize_request(
                client_id="giljo-mcp-default",
                redirect_uri="https://evil.example.com/callback",
                code_challenge=challenge,
                code_challenge_method="S256",
                response_type="code",
                scope="mcp:read mcp:write",
                tenant_key=test_tenant_key,
            )


class TestValidateRedirectUri:
    """Tests for the static validate_redirect_uri method."""

    @pytest.mark.parametrize(
        "uri",
        [
            "http://localhost/callback",
            "http://localhost:3000/callback",
            "http://localhost:8080/auth/callback",
            "http://127.0.0.1/callback",
            "http://127.0.0.1:5173/callback",
            "http://[::1]/callback",
            "http://[::1]:3000/callback",
        ],
    )
    def test_allowed_uris_accepted(self, uri):
        assert OAuthService.validate_redirect_uri(uri) is True

    @pytest.mark.parametrize(
        "uri",
        [
            "https://evil.example.com/callback",
            "http://192.0.2.100/callback",
            "http://198.51.100.1:8080/callback",
            "ftp://localhost/callback",
            "",
        ],
    )
    def test_disallowed_uris_rejected(self, uri):
        assert OAuthService.validate_redirect_uri(uri) is False


class TestVerifyPkce:
    """Tests for the static PKCE verification method."""

    def test_pkce_valid_verifier_accepted(self):
        """A correct code_verifier must pass PKCE verification."""
        verifier, challenge = _generate_pkce_pair()
        assert OAuthService.verify_pkce(verifier, challenge) is True

    def test_pkce_invalid_verifier_rejected(self):
        """An incorrect code_verifier must fail PKCE verification."""
        _verifier, challenge = _generate_pkce_pair()
        wrong_verifier = secrets.token_urlsafe(64)
        assert OAuthService.verify_pkce(wrong_verifier, challenge) is False

    def test_pkce_empty_verifier_rejected(self):
        """An empty verifier must fail."""
        _verifier, challenge = _generate_pkce_pair()
        assert OAuthService.verify_pkce("", challenge) is False


@pytest.mark.asyncio
class TestGenerateAuthorizationCode:
    """Tests for generate_authorization_code."""

    async def test_generate_code_stores_in_db(self, oauth_service, test_user, test_tenant_key, db_session):
        """Generating a code must persist it in the database."""
        _verifier, challenge = _generate_pkce_pair()
        code = await oauth_service.generate_authorization_code(
            user_id=test_user.id,
            tenant_key=test_tenant_key,
            client_id="giljo-mcp-default",
            redirect_uri="http://localhost:3000/callback",
            code_challenge=challenge,
            scope="mcp:read mcp:write",
        )

        assert isinstance(code, str)
        assert len(code) > 32

        result = await db_session.execute(select(OAuthAuthorizationCode).where(OAuthAuthorizationCode.code == code))
        stored = result.scalar_one()
        assert stored.user_id == test_user.id
        assert stored.tenant_key == test_tenant_key
        assert stored.client_id == "giljo-mcp-default"
        assert stored.redirect_uri == "http://localhost:3000/callback"
        assert stored.code_challenge == challenge
        assert stored.code_challenge_method == "S256"
        assert stored.scope == "mcp:read mcp:write"
        assert stored.used is False
        assert stored.expires_at > datetime.now(UTC)

    async def test_generate_code_sets_expiry(self, oauth_service, test_user, test_tenant_key, db_session):
        """The code expiry must be approximately 10 minutes in the future."""
        _verifier, challenge = _generate_pkce_pair()
        before = datetime.now(UTC)
        code = await oauth_service.generate_authorization_code(
            user_id=test_user.id,
            tenant_key=test_tenant_key,
            client_id="giljo-mcp-default",
            redirect_uri="http://localhost:3000/callback",
            code_challenge=challenge,
        )
        after = datetime.now(UTC)

        result = await db_session.execute(select(OAuthAuthorizationCode).where(OAuthAuthorizationCode.code == code))
        stored = result.scalar_one()
        expected_min = before + timedelta(minutes=9, seconds=59)
        expected_max = after + timedelta(minutes=10, seconds=1)
        assert expected_min <= stored.expires_at <= expected_max


@pytest.mark.asyncio
class TestExchangeCodeForToken:
    """Tests for exchange_code_for_token."""

    async def test_exchange_valid_code_returns_jwt(self, oauth_service, test_user, test_tenant_key):
        """Exchanging a valid code with correct PKCE verifier must return a JWT."""
        verifier, challenge = _generate_pkce_pair()
        code = await oauth_service.generate_authorization_code(
            user_id=test_user.id,
            tenant_key=test_tenant_key,
            client_id="giljo-mcp-default",
            redirect_uri="http://localhost:3000/callback",
            code_challenge=challenge,
        )

        token_response = await oauth_service.exchange_code_for_token(
            code=code,
            client_id="giljo-mcp-default",
            code_verifier=verifier,
            redirect_uri="http://localhost:3000/callback",
        )

        assert "access_token" in token_response
        assert token_response["token_type"] == "bearer"
        assert token_response["expires_in"] == 86400
        assert isinstance(token_response["access_token"], str)
        assert token_response["access_token"].count(".") == 2  # JWT has 3 parts

    async def test_exchange_expired_code_rejected(self, oauth_service, test_user, test_tenant_key, db_session):
        """An expired code must be rejected."""
        verifier, challenge = _generate_pkce_pair()
        code = await oauth_service.generate_authorization_code(
            user_id=test_user.id,
            tenant_key=test_tenant_key,
            client_id="giljo-mcp-default",
            redirect_uri="http://localhost:3000/callback",
            code_challenge=challenge,
        )

        # Manually expire the code
        result = await db_session.execute(select(OAuthAuthorizationCode).where(OAuthAuthorizationCode.code == code))
        stored = result.scalar_one()
        stored.expires_at = datetime.now(UTC) - timedelta(minutes=1)
        await db_session.flush()

        with pytest.raises(ValueError, match="expired"):
            await oauth_service.exchange_code_for_token(
                code=code,
                client_id="giljo-mcp-default",
                code_verifier=verifier,
                redirect_uri="http://localhost:3000/callback",
            )

    async def test_exchange_used_code_rejected(self, oauth_service, test_user, test_tenant_key, monkeypatch):
        """A code that has already been used must be rejected OUTSIDE the
        idempotency window. API-0021l introduced a 5s in-window retry hatch
        for confidential-client races; this test asserts the strict
        single-use contract STILL applies once the window closes. Inside
        the window the retry is idempotent (covered by
        test_oauth_endpoints.TestTokenIdempotency).
        """
        import time as _time

        from giljo_mcp.services import oauth_token_idempotency as _idem_svc

        # Collapse the window so the second call falls outside.
        monkeypatch.setattr(_idem_svc, "OAUTH_TOKEN_IDEMPOTENCY_WINDOW_SECONDS", 0)

        verifier, challenge = _generate_pkce_pair()
        code = await oauth_service.generate_authorization_code(
            user_id=test_user.id,
            tenant_key=test_tenant_key,
            client_id="giljo-mcp-default",
            redirect_uri="http://localhost:3000/callback",
            code_challenge=challenge,
        )

        # First exchange succeeds
        await oauth_service.exchange_code_for_token(
            code=code,
            client_id="giljo-mcp-default",
            code_verifier=verifier,
            redirect_uri="http://localhost:3000/callback",
        )

        # Window=0 means the cache entry expires immediately; sleep a tick
        # to make sure we're past the boundary on every clock resolution.
        _time.sleep(0.05)

        # Second exchange must fail with the strict single-use error.
        with pytest.raises(ValueError, match="used"):
            await oauth_service.exchange_code_for_token(
                code=code,
                client_id="giljo-mcp-default",
                code_verifier=verifier,
                redirect_uri="http://localhost:3000/callback",
            )

    async def test_exchange_wrong_client_id_rejected(self, oauth_service, test_user, test_tenant_key):
        """A mismatched client_id must be rejected."""
        verifier, challenge = _generate_pkce_pair()
        code = await oauth_service.generate_authorization_code(
            user_id=test_user.id,
            tenant_key=test_tenant_key,
            client_id="giljo-mcp-default",
            redirect_uri="http://localhost:3000/callback",
            code_challenge=challenge,
        )

        with pytest.raises(ValueError, match="Authorization code not found"):
            await oauth_service.exchange_code_for_token(
                code=code,
                client_id="wrong-client",
                code_verifier=verifier,
                redirect_uri="http://localhost:3000/callback",
            )

    async def test_exchange_wrong_redirect_uri_rejected(self, oauth_service, test_user, test_tenant_key):
        """A mismatched redirect_uri must be rejected."""
        verifier, challenge = _generate_pkce_pair()
        code = await oauth_service.generate_authorization_code(
            user_id=test_user.id,
            tenant_key=test_tenant_key,
            client_id="giljo-mcp-default",
            redirect_uri="http://localhost:3000/callback",
            code_challenge=challenge,
        )

        with pytest.raises(ValueError, match="redirect_uri"):
            await oauth_service.exchange_code_for_token(
                code=code,
                client_id="giljo-mcp-default",
                code_verifier=verifier,
                redirect_uri="http://localhost:4000/different",
            )

    async def test_exchange_wrong_pkce_verifier_rejected(self, oauth_service, test_user, test_tenant_key):
        """An incorrect PKCE code_verifier must be rejected."""
        _verifier, challenge = _generate_pkce_pair()
        code = await oauth_service.generate_authorization_code(
            user_id=test_user.id,
            tenant_key=test_tenant_key,
            client_id="giljo-mcp-default",
            redirect_uri="http://localhost:3000/callback",
            code_challenge=challenge,
        )

        wrong_verifier = secrets.token_urlsafe(64)
        with pytest.raises(ValueError, match="PKCE"):
            await oauth_service.exchange_code_for_token(
                code=code,
                client_id="giljo-mcp-default",
                code_verifier=wrong_verifier,
                redirect_uri="http://localhost:3000/callback",
            )

    async def test_exchange_nonexistent_code_rejected(self, oauth_service):
        """A code that does not exist must be rejected."""
        with pytest.raises(ValueError, match="not found"):
            await oauth_service.exchange_code_for_token(
                code="nonexistent-code-value",
                client_id="giljo-mcp-default",
                code_verifier="some-verifier",
                redirect_uri="http://localhost:3000/callback",
            )


_SEC9227_CONF_CLIENT_ID = "sec9227-confidential-client"
_SEC9227_CONF_SECRET = "sec9227-confidential-secret-value"
_SEC9227_CONF_REDIRECT = "http://localhost:3000/callback"


@pytest.fixture
def confidential_client():
    """Install a process-wide resolver recognizing ONE confidential client.

    A confidential client is one with a ``client_secret_hash`` set (DCR
    ``client_secret_post``). The built-in resolver only knows the public
    PKCE-only client, so SEC-9227 (H2) needs a confidential one to prove the
    verifier is enforced even when a valid secret is presented. The prior
    resolver is restored on teardown so the seam does not leak across tests.
    """
    import bcrypt

    from giljo_mcp.services import oauth_service as _svc

    secret_hash = bcrypt.hashpw(_SEC9227_CONF_SECRET.encode("utf-8"), bcrypt.gensalt()).decode("ascii")
    resolved = _svc.ResolvedClient(
        client_id=_SEC9227_CONF_CLIENT_ID,
        client_name="SEC-9227 confidential test client",
        redirect_uris=[_SEC9227_CONF_REDIRECT],
        client_secret_hash=secret_hash,
    )
    prev = _svc.get_client_resolver()
    _svc.set_client_resolver(lambda cid, tk: resolved if cid == _SEC9227_CONF_CLIENT_ID else prev(cid, tk))
    try:
        yield
    finally:
        _svc.set_client_resolver(prev)


@pytest.mark.asyncio
class TestConfidentialClientPkceEnforced:
    """SEC-9227 (H2) / RFC 9700 §2.1.1: a confidential client MUST present and
    pass PKCE at token exchange, exactly like a public client — a stored
    ``code_challenge`` obliges verification for EVERY client type.

    Before this fix, the confidential branch made ``code_verifier`` optional, so
    a stolen authorization code plus the client secret redeemed a token with no
    verifier at all. These tests exercise the service method the bug lives in.
    """

    async def _make_conf_code(self, oauth_service, test_user, test_tenant_key, challenge):
        return await oauth_service.generate_authorization_code(
            user_id=test_user.id,
            tenant_key=test_tenant_key,
            client_id=_SEC9227_CONF_CLIENT_ID,
            redirect_uri=_SEC9227_CONF_REDIRECT,
            code_challenge=challenge,
        )

    async def test_confidential_secret_without_verifier_rejected(
        self, oauth_service, test_user, test_tenant_key, confidential_client
    ):
        """THE EXPLOIT SHAPE: valid secret, NO code_verifier → rejected.

        This is the case that returned a token before the fix.
        """
        _verifier, challenge = _generate_pkce_pair()
        code = await self._make_conf_code(oauth_service, test_user, test_tenant_key, challenge)

        with pytest.raises(ValueError, match="code_verifier is required"):
            await oauth_service.exchange_code_for_token(
                code=code,
                client_id=_SEC9227_CONF_CLIENT_ID,
                code_verifier=None,
                redirect_uri=_SEC9227_CONF_REDIRECT,
                client_secret=_SEC9227_CONF_SECRET,
            )

    async def test_confidential_secret_with_wrong_verifier_rejected(
        self, oauth_service, test_user, test_tenant_key, confidential_client
    ):
        """Valid secret + a code_verifier that does not match the challenge → rejected."""
        _verifier, challenge = _generate_pkce_pair()
        code = await self._make_conf_code(oauth_service, test_user, test_tenant_key, challenge)

        with pytest.raises(ValueError, match="PKCE"):
            await oauth_service.exchange_code_for_token(
                code=code,
                client_id=_SEC9227_CONF_CLIENT_ID,
                code_verifier=secrets.token_urlsafe(64),  # wrong verifier
                redirect_uri=_SEC9227_CONF_REDIRECT,
                client_secret=_SEC9227_CONF_SECRET,
            )

    async def test_confidential_secret_with_correct_verifier_succeeds(
        self, oauth_service, test_user, test_tenant_key, confidential_client
    ):
        """LOAD-BEARING happy path: valid secret + CORRECT verifier → token issued.

        The fix must not break a well-behaved confidential client that does send
        the verifier (every RFC 9700-compliant client does).
        """
        verifier, challenge = _generate_pkce_pair()
        code = await self._make_conf_code(oauth_service, test_user, test_tenant_key, challenge)

        token_response = await oauth_service.exchange_code_for_token(
            code=code,
            client_id=_SEC9227_CONF_CLIENT_ID,
            code_verifier=verifier,
            redirect_uri=_SEC9227_CONF_REDIRECT,
            client_secret=_SEC9227_CONF_SECRET,
        )

        assert token_response["token_type"] == "bearer"
        assert token_response["access_token"].count(".") == 2  # JWT
        # Confidential clients receive a rotating refresh token (API-0021e Phase 2).
        assert token_response.get("refresh_token")

    async def test_public_client_without_verifier_still_rejected(self, oauth_service, test_user, test_tenant_key):
        """Two-sided: the public-client path is unchanged — no verifier → rejected."""
        _verifier, challenge = _generate_pkce_pair()
        code = await oauth_service.generate_authorization_code(
            user_id=test_user.id,
            tenant_key=test_tenant_key,
            client_id="giljo-mcp-default",
            redirect_uri="http://localhost:3000/callback",
            code_challenge=challenge,
        )

        with pytest.raises(ValueError, match="code_verifier is required"):
            await oauth_service.exchange_code_for_token(
                code=code,
                client_id="giljo-mcp-default",
                code_verifier=None,
                redirect_uri="http://localhost:3000/callback",
            )

    async def test_confidential_replay_without_verifier_does_not_hit_idempotency_cache(
        self, oauth_service, test_user, test_tenant_key, confidential_client
    ):
        """SEC-9227 (H2), idempotency-cache path — the residual bypass.

        The idempotency cache short-circuits and returns a cached token pair
        BEFORE the mandatory-PKCE check. The cache signature must key on the
        per-request PKCE verifier, NOT the client_secret — otherwise a
        confidential client, after one correct-verifier exchange populates the
        cache, could replay the SAME code with NO verifier inside the window and
        get the cached tokens with PKCE never checked.

        Fail-first: on the pre-fix code (idem_proof keyed on client_secret) the
        no-verifier replay returned the cached pair (no raise). After the fix it
        misses the cache and fails closed.
        """
        verifier, challenge = _generate_pkce_pair()
        code = await self._make_conf_code(oauth_service, test_user, test_tenant_key, challenge)

        # 1. Legit exchange with the correct verifier + secret POPULATES the cache.
        ok = await oauth_service.exchange_code_for_token(
            code=code,
            client_id=_SEC9227_CONF_CLIENT_ID,
            code_verifier=verifier,
            redirect_uri=_SEC9227_CONF_REDIRECT,
            client_secret=_SEC9227_CONF_SECRET,
        )
        assert "access_token" in ok

        # 2. Replay the SAME code with NO verifier, same secret, INSIDE the window
        #    (window not collapsed) — must NOT return the cached tokens.
        with pytest.raises(ValueError):
            await oauth_service.exchange_code_for_token(
                code=code,
                client_id=_SEC9227_CONF_CLIENT_ID,
                code_verifier=None,
                redirect_uri=_SEC9227_CONF_REDIRECT,
                client_secret=_SEC9227_CONF_SECRET,
            )

        # 3. Replay with a WRONG verifier — also must fail closed (no cached pair).
        with pytest.raises(ValueError):
            await oauth_service.exchange_code_for_token(
                code=code,
                client_id=_SEC9227_CONF_CLIENT_ID,
                code_verifier=secrets.token_urlsafe(64),
                redirect_uri=_SEC9227_CONF_REDIRECT,
                client_secret=_SEC9227_CONF_SECRET,
            )


@pytest.mark.asyncio
class TestCleanupExpiredCodes:
    """Tests for cleanup_expired_codes."""

    async def test_cleanup_deletes_expired_codes(self, oauth_service, test_user, test_tenant_key, db_session):
        """Expired codes must be deleted by cleanup."""
        _verifier, challenge = _generate_pkce_pair()
        code = await oauth_service.generate_authorization_code(
            user_id=test_user.id,
            tenant_key=test_tenant_key,
            client_id="giljo-mcp-default",
            redirect_uri="http://localhost:3000/callback",
            code_challenge=challenge,
        )

        # Expire the code
        result = await db_session.execute(select(OAuthAuthorizationCode).where(OAuthAuthorizationCode.code == code))
        stored = result.scalar_one()
        stored.expires_at = datetime.now(UTC) - timedelta(minutes=5)
        await db_session.flush()

        deleted_count = await oauth_service.cleanup_expired_codes()
        assert deleted_count >= 1

        result = await db_session.execute(select(OAuthAuthorizationCode).where(OAuthAuthorizationCode.code == code))
        assert result.scalar_one_or_none() is None

    async def test_cleanup_deletes_used_codes(self, oauth_service, test_user, test_tenant_key, db_session):
        """Used codes must be deleted by cleanup."""
        verifier, challenge = _generate_pkce_pair()
        code = await oauth_service.generate_authorization_code(
            user_id=test_user.id,
            tenant_key=test_tenant_key,
            client_id="giljo-mcp-default",
            redirect_uri="http://localhost:3000/callback",
            code_challenge=challenge,
        )

        # Exchange the code (marks it as used)
        await oauth_service.exchange_code_for_token(
            code=code,
            client_id="giljo-mcp-default",
            code_verifier=verifier,
            redirect_uri="http://localhost:3000/callback",
        )

        deleted_count = await oauth_service.cleanup_expired_codes()
        assert deleted_count >= 1

    async def test_cleanup_preserves_valid_codes(self, oauth_service, test_user, test_tenant_key, db_session):
        """Valid, unused codes must not be deleted by cleanup."""
        _verifier, challenge = _generate_pkce_pair()
        code = await oauth_service.generate_authorization_code(
            user_id=test_user.id,
            tenant_key=test_tenant_key,
            client_id="giljo-mcp-default",
            redirect_uri="http://localhost:3000/callback",
            code_challenge=challenge,
        )

        await oauth_service.cleanup_expired_codes()

        result = await db_session.execute(select(OAuthAuthorizationCode).where(OAuthAuthorizationCode.code == code))
        assert result.scalar_one_or_none() is not None
