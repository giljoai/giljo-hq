# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import base64
import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import bcrypt
import pytest

from giljo_mcp.services import _idem_crypto, cache_backends
from giljo_mcp.services import oauth_refresh_service as _refresh_svc
from giljo_mcp.services import oauth_token_idempotency as _idem
from giljo_mcp.services.cache_backends import (
    OAUTH_IDEMPOTENCY_BACKEND_NAME,
    OAUTH_REFRESH_BACKEND_NAME,
    get_cache_backend,
)
from giljo_mcp.services.oauth_refresh_service import (
    hash_refresh_token,
    issue_refresh_token,
    new_family_id,
)
from giljo_mcp.services.oauth_service import BUILTIN_CLIENT_ID, OAuthService


@pytest.fixture(autouse=True)
def _isolated_cache_registry():
    cache_backends.reset_registry_for_tests()
    _idem_crypto.reset_key_cache_for_tests()
    yield
    cache_backends.reset_registry_for_tests()
    _idem_crypto.reset_key_cache_for_tests()


def _assert_no_readable_token_material(raw: str, response_body: dict) -> None:
    access_leaked = response_body["access_token"] in raw
    refresh_leaked = response_body.get("refresh_token", "") and response_body["refresh_token"] in raw
    assert not access_leaked, "raw cache value contains the live access_token"
    assert not refresh_leaked, "raw cache value contains the live refresh_token"
    assert '"access_token"' not in raw, "raw cache value contains plaintext JSON key access_token"
    assert '"response_body"' not in raw, "raw cache value contains plaintext JSON key response_body"
    assert '"body_signature"' not in raw, "raw cache value contains plaintext JSON key body_signature"


async def _seed_user(db_manager) -> tuple[str, str]:
    from giljo_mcp.models.auth import User
    from giljo_mcp.models.organizations import Organization
    from giljo_mcp.tenant import TenantManager

    tk = TenantManager.generate_tenant_key()
    unique = uuid4().hex[:8]
    user_id = str(uuid4())

    async with db_manager.get_session_async(tenant_key=tk) as session:
        org = Organization(
            name=f"SEC9227f Org {unique}",
            slug=f"sec9227f-org-{unique}",
            tenant_key=tk,
            is_active=True,
        )
        session.add(org)
        await session.flush()
        session.add(
            User(
                id=user_id,
                username=f"sec9227f_user_{unique}",
                email=f"sec9227f_{unique}@example.com",
                password_hash=bcrypt.hashpw(b"SeedPassword1!", bcrypt.gensalt()).decode("utf-8"),
                tenant_key=tk,
                role="developer",
                org_id=org.id,
                is_active=True,
                token_revocation_epoch=0,
            )
        )
        await session.commit()

    return user_id, tk


def _generate_pkce_pair() -> tuple[str, str]:
    code_verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    code_challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return code_verifier, code_challenge


def _install_builtin_resolver():
    from giljo_mcp.services import oauth_service as svc

    prior = svc.get_client_resolver()
    svc.set_client_resolver(svc._builtin_single_client_resolver)
    return lambda: svc.set_client_resolver(prior)


def _install_confidential_resolver(client_id: str, secret_hash: str):
    from giljo_mcp.services import oauth_service as svc

    prior = svc.get_client_resolver()

    def _resolver(cid: str, tenant_key: str):
        assert tenant_key
        if cid != client_id:
            return None
        return svc.ResolvedClient(
            client_id=cid,
            client_name="SEC9227f Test Client",
            redirect_uris=["http://localhost:3000/callback"],
            client_secret_hash=secret_hash,
        )

    svc.set_client_resolver(_resolver)
    return lambda: svc.set_client_resolver(prior)


@pytest.mark.asyncio
async def test_token_grant_raw_backend_value_holds_no_readable_token_material(db_manager, monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "test_secret_key")
    monkeypatch.setattr(_idem, "OAUTH_TOKEN_IDEMPOTENCY_WINDOW_SECONDS", 30)

    from giljo_mcp.models.oauth import OAuthAuthorizationCode

    user_id, tk = await _seed_user(db_manager)
    code_verifier, code_challenge = _generate_pkce_pair()
    code_value = secrets.token_urlsafe(64)
    redirect_uri = "http://localhost:3000/callback"

    async with db_manager.get_session_async(tenant_key=tk) as session:
        session.add(
            OAuthAuthorizationCode(
                code=code_value,
                client_id=BUILTIN_CLIENT_ID,
                user_id=user_id,
                tenant_key=tk,
                redirect_uri=redirect_uri,
                code_challenge=code_challenge,
                code_challenge_method="S256",
                scope="mcp:read mcp:write",
                resource=None,
                expires_at=datetime.now(UTC) + timedelta(minutes=10),
                used=False,
            )
        )
        await session.commit()

    restore = _install_builtin_resolver()
    try:
        async with db_manager.get_session_async(tenant_key=tk) as session:
            service = OAuthService(db_session=session)
            response = await service.exchange_code_for_token(
                code=code_value,
                client_id=BUILTIN_CLIENT_ID,
                code_verifier=code_verifier,
                redirect_uri=redirect_uri,
            )

        assert "access_token" in response and "refresh_token" in response

        raw = await get_cache_backend(OAUTH_IDEMPOTENCY_BACKEND_NAME).get(tk, code_value)
        assert raw is not None, "the grant must have cached an idempotency entry"
        _assert_no_readable_token_material(raw, response)

        cached = await _idem.cache_get(tk, code_value)
        assert cached is not None
        assert cached.response_body == response
    finally:
        restore()


@pytest.mark.asyncio
async def test_refresh_grant_raw_backend_value_holds_no_readable_token_material(db_manager, monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "test_secret_key")
    monkeypatch.setattr(_refresh_svc, "OAUTH_REFRESH_IDEMPOTENCY_WINDOW_SECONDS", 30)

    user_id, tk = await _seed_user(db_manager)
    client_id = str(uuid4())
    client_secret = secrets.token_urlsafe(48)
    secret_hash = bcrypt.hashpw(client_secret.encode("utf-8"), bcrypt.gensalt()).decode("ascii")
    restore = _install_confidential_resolver(client_id, secret_hash)

    try:
        async with db_manager.get_session_async(tenant_key=tk) as session:
            raw_presented = await issue_refresh_token(
                session,
                family_id=new_family_id(),
                client_id=client_id,
                tenant_key=tk,
                user_id=user_id,
                scope="mcp:read mcp:write",
                aud="",
                lifetime_seconds=3600,
            )
            await session.commit()

        async with db_manager.get_session_async(tenant_key=tk) as session:
            service = OAuthService(db_session=session)
            response = await service.refresh_token_grant(
                refresh_token=raw_presented,
                client_id=client_id,
                client_secret=client_secret,
            )

        assert "access_token" in response and "refresh_token" in response
        token_hash = hash_refresh_token(raw_presented)

        raw = await get_cache_backend(OAUTH_REFRESH_BACKEND_NAME).get(tk, token_hash)
        assert raw is not None, "the grant must have cached an idempotency entry"
        _assert_no_readable_token_material(raw, response)

        cached = await _refresh_svc._refresh_idempotency_cache_get(tk, token_hash)
        assert cached is not None
        assert cached.response_body == response
    finally:
        restore()


def _sample_entries() -> tuple[_idem.IdempotencyEntry, _refresh_svc._RefreshIdempotencyEntry]:
    body = {"access_token": "tok-access-xyz", "refresh_token": "tok-refresh-xyz"}
    return (
        _idem.IdempotencyEntry(response_body=dict(body), body_signature="sig-1"),
        _refresh_svc._RefreshIdempotencyEntry(response_body=dict(body), body_signature="sig-1"),
    )


class TestFailSecureDegradation:

    @pytest.mark.asyncio
    async def test_tampered_entry_is_a_miss_on_both_paths(self, monkeypatch, caplog):
        monkeypatch.setenv("JWT_SECRET", "test_secret_key")
        token_entry, refresh_entry = _sample_entries()

        await _idem.cache_put("tk_t", "code-1", token_entry)
        await _refresh_svc._refresh_idempotency_cache_put("tk_t", "hash-1", refresh_entry)

        for name, key in ((OAUTH_IDEMPOTENCY_BACKEND_NAME, "code-1"), (OAUTH_REFRESH_BACKEND_NAME, "hash-1")):
            backend = get_cache_backend(name)
            raw = await backend.get("tk_t", key)
            assert raw is not None and raw.startswith("v1:")
            body = bytearray(base64.b64decode(raw[3:]))
            body[-1] ^= 0x01
            tampered = "v1:" + base64.b64encode(bytes(body)).decode("ascii")
            await backend.set("tk_t", key, tampered, ttl_seconds=30)

        import logging as _logging

        with caplog.at_level(_logging.WARNING, logger="giljo_mcp.services._idem_crypto"):
            assert await _idem.cache_get("tk_t", "code-1") is None
            assert await _refresh_svc._refresh_idempotency_cache_get("tk_t", "hash-1") is None
        assert sum("oauth_idem_cache_decrypt_failed" in r.message for r in caplog.records) == 2

    @pytest.mark.asyncio
    async def test_wrong_key_is_a_miss_not_an_exception(self, monkeypatch):
        monkeypatch.setenv("JWT_SECRET", "secret-key-A")
        token_entry, refresh_entry = _sample_entries()
        await _idem.cache_put("tk_w", "code-1", token_entry)
        await _refresh_svc._refresh_idempotency_cache_put("tk_w", "hash-1", refresh_entry)

        _idem_crypto.reset_key_cache_for_tests()
        monkeypatch.setenv("JWT_SECRET", "secret-key-B")

        assert await _idem.cache_get("tk_w", "code-1") is None
        assert await _refresh_svc._refresh_idempotency_cache_get("tk_w", "hash-1") is None

    @pytest.mark.asyncio
    async def test_unprefixed_and_unknown_prefix_entries_are_misses(self, monkeypatch):
        monkeypatch.setenv("JWT_SECRET", "test_secret_key")
        legacy_plaintext = '{"response_body": {"access_token": "x"}, "body_signature": "s"}'
        cases = [legacy_plaintext, "v2:AAAA", "v1:!!!not-base64!!!", "v1:", "v1:QUJD"]
        backend_t = get_cache_backend(OAUTH_IDEMPOTENCY_BACKEND_NAME)
        backend_r = get_cache_backend(OAUTH_REFRESH_BACKEND_NAME)
        for i, value in enumerate(cases):
            await backend_t.set("tk_p", f"code-{i}", value, ttl_seconds=30)
            await backend_r.set("tk_p", f"hash-{i}", value, ttl_seconds=30)
            assert await _idem.cache_get("tk_p", f"code-{i}") is None
            assert await _refresh_svc._refresh_idempotency_cache_get("tk_p", f"hash-{i}") is None


class TestCryptoFormat:
    def test_version_prefix_and_fresh_nonce_per_entry(self, monkeypatch):
        monkeypatch.setenv("JWT_SECRET", "test_secret_key")
        one = _idem_crypto.encrypt_payload("same plaintext")
        two = _idem_crypto.encrypt_payload("same plaintext")
        assert one.startswith("v1:") and two.startswith("v1:")
        assert one != two
        assert _idem_crypto.decrypt_payload(one) == "same plaintext"
        assert _idem_crypto.decrypt_payload(two) == "same plaintext"

    def test_key_is_not_derived_at_import_time(self, monkeypatch):
        monkeypatch.delenv("JWT_SECRET", raising=False)
        monkeypatch.delenv("GILJO_MCP_SECRET_KEY", raising=False)
        monkeypatch.delenv("SECRET_KEY", raising=False)
        _idem_crypto.reset_key_cache_for_tests()
        with pytest.raises(RuntimeError):
            _idem_crypto.encrypt_payload("x")
        assert _idem_crypto.decrypt_payload("v1:QUJD") is None
