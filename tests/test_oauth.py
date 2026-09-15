# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


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
    code_verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    code_challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return code_verifier, code_challenge


@pytest_asyncio.fixture(scope="function")
async def test_user(db_session, test_tenant_key) -> User:
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
    return OAuthService(db_session=db_session)


@pytest.mark.asyncio
class TestValidateAuthorizeRequest:

    async def test_valid_request_passes(self, oauth_service, test_tenant_key):
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

    def test_pkce_valid_verifier_accepted(self):
        verifier, challenge = _generate_pkce_pair()
        assert OAuthService.verify_pkce(verifier, challenge) is True

    def test_pkce_invalid_verifier_rejected(self):
        _verifier, challenge = _generate_pkce_pair()
        wrong_verifier = secrets.token_urlsafe(64)
        assert OAuthService.verify_pkce(wrong_verifier, challenge) is False

    def test_pkce_empty_verifier_rejected(self):
        _verifier, challenge = _generate_pkce_pair()
        assert OAuthService.verify_pkce("", challenge) is False


@pytest.mark.asyncio
class TestGenerateAuthorizationCode:

    async def test_generate_code_stores_in_db(self, oauth_service, test_user, test_tenant_key, db_session):
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

    async def test_exchange_valid_code_returns_jwt(self, oauth_service, test_user, test_tenant_key):
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
        assert token_response["access_token"].count(".") == 2

    async def test_exchange_expired_code_rejected(self, oauth_service, test_user, test_tenant_key, db_session):
        verifier, challenge = _generate_pkce_pair()
        code = await oauth_service.generate_authorization_code(
            user_id=test_user.id,
            tenant_key=test_tenant_key,
            client_id="giljo-mcp-default",
            redirect_uri="http://localhost:3000/callback",
            code_challenge=challenge,
        )

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
        import time as _time

        from giljo_mcp.services import oauth_token_idempotency as _idem_svc

        monkeypatch.setattr(_idem_svc, "OAUTH_TOKEN_IDEMPOTENCY_WINDOW_SECONDS", 0)

        verifier, challenge = _generate_pkce_pair()
        code = await oauth_service.generate_authorization_code(
            user_id=test_user.id,
            tenant_key=test_tenant_key,
            client_id="giljo-mcp-default",
            redirect_uri="http://localhost:3000/callback",
            code_challenge=challenge,
        )

        await oauth_service.exchange_code_for_token(
            code=code,
            client_id="giljo-mcp-default",
            code_verifier=verifier,
            redirect_uri="http://localhost:3000/callback",
        )

        _time.sleep(0.05)

        with pytest.raises(ValueError, match="used"):
            await oauth_service.exchange_code_for_token(
                code=code,
                client_id="giljo-mcp-default",
                code_verifier=verifier,
                redirect_uri="http://localhost:3000/callback",
            )

    async def test_exchange_wrong_client_id_rejected(self, oauth_service, test_user, test_tenant_key):
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
        _verifier, challenge = _generate_pkce_pair()
        code = await self._make_conf_code(oauth_service, test_user, test_tenant_key, challenge)

        with pytest.raises(ValueError, match="PKCE"):
            await oauth_service.exchange_code_for_token(
                code=code,
                client_id=_SEC9227_CONF_CLIENT_ID,
                code_verifier=secrets.token_urlsafe(64),
                redirect_uri=_SEC9227_CONF_REDIRECT,
                client_secret=_SEC9227_CONF_SECRET,
            )

    async def test_confidential_secret_with_correct_verifier_succeeds(
        self, oauth_service, test_user, test_tenant_key, confidential_client
    ):
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
        assert token_response["access_token"].count(".") == 2
        assert token_response.get("refresh_token")

    async def test_public_client_without_verifier_still_rejected(self, oauth_service, test_user, test_tenant_key):
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
        verifier, challenge = _generate_pkce_pair()
        code = await self._make_conf_code(oauth_service, test_user, test_tenant_key, challenge)

        ok = await oauth_service.exchange_code_for_token(
            code=code,
            client_id=_SEC9227_CONF_CLIENT_ID,
            code_verifier=verifier,
            redirect_uri=_SEC9227_CONF_REDIRECT,
            client_secret=_SEC9227_CONF_SECRET,
        )
        assert "access_token" in ok

        with pytest.raises(ValueError):
            await oauth_service.exchange_code_for_token(
                code=code,
                client_id=_SEC9227_CONF_CLIENT_ID,
                code_verifier=None,
                redirect_uri=_SEC9227_CONF_REDIRECT,
                client_secret=_SEC9227_CONF_SECRET,
            )

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

    async def test_cleanup_deletes_expired_codes(self, oauth_service, test_user, test_tenant_key, db_session):
        _verifier, challenge = _generate_pkce_pair()
        code = await oauth_service.generate_authorization_code(
            user_id=test_user.id,
            tenant_key=test_tenant_key,
            client_id="giljo-mcp-default",
            redirect_uri="http://localhost:3000/callback",
            code_challenge=challenge,
        )

        result = await db_session.execute(select(OAuthAuthorizationCode).where(OAuthAuthorizationCode.code == code))
        stored = result.scalar_one()
        stored.expires_at = datetime.now(UTC) - timedelta(minutes=5)
        await db_session.flush()

        deleted_count = await oauth_service.cleanup_expired_codes()
        assert deleted_count >= 1

        result = await db_session.execute(select(OAuthAuthorizationCode).where(OAuthAuthorizationCode.code == code))
        assert result.scalar_one_or_none() is None

    async def test_cleanup_deletes_used_codes(self, oauth_service, test_user, test_tenant_key, db_session):
        verifier, challenge = _generate_pkce_pair()
        code = await oauth_service.generate_authorization_code(
            user_id=test_user.id,
            tenant_key=test_tenant_key,
            client_id="giljo-mcp-default",
            redirect_uri="http://localhost:3000/callback",
            code_challenge=challenge,
        )

        await oauth_service.exchange_code_for_token(
            code=code,
            client_id="giljo-mcp-default",
            code_verifier=verifier,
            redirect_uri="http://localhost:3000/callback",
        )

        deleted_count = await oauth_service.cleanup_expired_codes()
        assert deleted_count >= 1

    async def test_cleanup_preserves_valid_codes(self, oauth_service, test_user, test_tenant_key, db_session):
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
