# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""SEC-9227e (M2b) — idempotency cache writes must happen only after commit.

Defect (atomicity/ordering): on BOTH grant paths the idempotency cache write
happens inside the request transaction, before the caller's commit:

- /refresh: ``_refresh_grant_after_lookup`` runs ``db.flush()`` for the
  rotation, then ``_refresh_idempotency_cache_put``, then returns; the commit
  belongs to the router's ``get_db_session`` dependency and only happens after
  the response is produced.
- /token: ``exchange_code_for_token`` runs ``_idem.cache_put`` after the
  refresh-row flush inside the service, before the endpoint-level commit.

If the transaction is rolled back after the cache write (a later exception in
the request pipeline, a dropped connection), the cache retains a token pair
whose refresh row never persisted. An honest in-window retry then receives
that phantom pair from the cache, and the client's next /refresh finds no row
— a hard logout for a healthy client.

Both tests simulate the rollback-after-successful-return deterministically:
the grant is driven at the service layer inside a real
``db_manager.get_session_async()`` context, and a sentinel exception raised
after the service returns makes the session context manager roll the
transaction back — exactly what a post-return failure in the request pipeline
does to the router's session. The assertion is an ordering-agnostic
CONSISTENCY invariant, so it keeps passing under either accepted fix shape
(explicit in-service commit before the cache-put, or cache-put lifted to the
endpoint after the dependency's commit):

    a cached response's refresh token must correspond to a live DB row.

Pre-fix both tests failed (cache entry present, row rolled back) and were
marked ``xfail(strict=True)``; the M2b fix (explicit in-service commit before
the cache-put on both paths) removed the markers and both now pass.

Museum rule: nothing here weakens the idempotency window or its in-window
reuse-suppression — the fix changes only WHEN the cache write happens.

Parallel-safe: unique tenant/user/client per test, per-test cache-backend
registry reset (precedent: ``tests/services/test_oauth_token_idempotency.py``),
no module-level mutable state, committed seed rows keyed by a unique
tenant_key.
"""

from __future__ import annotations

import base64
import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import bcrypt
import pytest
from sqlalchemy import select

from giljo_mcp.models.oauth import OAuthRefreshToken
from giljo_mcp.services import cache_backends
from giljo_mcp.services import oauth_refresh_service as _refresh_svc
from giljo_mcp.services import oauth_token_idempotency as _idem
from giljo_mcp.services.oauth_refresh_service import (
    hash_refresh_token,
    issue_refresh_token,
    new_family_id,
)
from giljo_mcp.services.oauth_service import BUILTIN_CLIENT_ID, OAuthService


class _PostReturnFailureError(Exception):
    """Sentinel: a failure AFTER the service returned but BEFORE the commit."""


@pytest.fixture(autouse=True)
def _isolated_cache_registry():
    """Fresh cache-backend registry per test so no entry leaks across tests."""
    cache_backends.reset_registry_for_tests()
    yield
    cache_backends.reset_registry_for_tests()


async def _seed_user(db_manager) -> tuple[str, str]:
    """Create org+user, committed; return (user_id, tenant_key)."""
    from giljo_mcp.models.auth import User
    from giljo_mcp.models.organizations import Organization
    from giljo_mcp.tenant import TenantManager

    tk = TenantManager.generate_tenant_key()
    unique = uuid4().hex[:8]
    user_id = str(uuid4())

    async with db_manager.get_session_async(tenant_key=tk) as session:
        org = Organization(
            name=f"SEC9227e-M2b Org {unique}",
            slug=f"sec9227e-m2b-org-{unique}",
            tenant_key=tk,
            is_active=True,
        )
        session.add(org)
        await session.flush()
        session.add(
            User(
                id=user_id,
                username=f"sec9227e_m2b_user_{unique}",
                email=f"sec9227e_m2b_{unique}@example.com",
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


def _install_confidential_resolver(client_id: str, secret_hash: str):
    """Stub resolver recognizing one confidential client (test_sec9217b pattern)."""
    from giljo_mcp.services import oauth_service as svc

    prior = svc.get_client_resolver()

    def _resolver(cid: str, tenant_key: str):
        assert tenant_key
        if cid != client_id:
            return None
        return svc.ResolvedClient(
            client_id=cid,
            client_name="SEC9227e-M2b Test Client",
            redirect_uris=["http://localhost:3000/callback"],
            client_secret_hash=secret_hash,
        )

    svc.set_client_resolver(_resolver)
    return lambda: svc.set_client_resolver(prior)


async def _refresh_row_exists(db_manager, *, tenant_key: str, raw_token: str) -> bool:
    async with db_manager.get_session_async(tenant_key=tenant_key) as session:
        row = (
            await session.execute(
                select(OAuthRefreshToken).where(
                    OAuthRefreshToken.token_hash == hash_refresh_token(raw_token),
                    OAuthRefreshToken.tenant_key == tenant_key,
                )
            )
        ).scalar_one_or_none()
        return row is not None


@pytest.mark.asyncio
async def test_refresh_cache_entry_never_outlives_a_rolled_back_transaction(db_manager, monkeypatch):
    """/refresh: after a post-return rollback, any cached pair must map to a live row."""
    monkeypatch.setenv("JWT_SECRET", "test_secret_key")
    monkeypatch.setattr(_refresh_svc, "OAUTH_REFRESH_IDEMPOTENCY_WINDOW_SECONDS", 30)

    user_id, tk = await _seed_user(db_manager)
    client_id = str(uuid4())
    client_secret = secrets.token_urlsafe(48)
    secret_hash = bcrypt.hashpw(client_secret.encode("utf-8"), bcrypt.gensalt()).decode("ascii")
    restore = _install_confidential_resolver(client_id, secret_hash)

    try:
        # Committed presented row (separate session): the grant's lookup finds it,
        # and the later rollback removes only the grant's own writes.
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

        # Drive the grant on a real session, then fail BEFORE the context
        # manager's commit — the rollback-after-cache-put shape.
        response_holder: dict = {}

        async def _grant_then_fail_pre_commit() -> None:
            async with db_manager.get_session_async(tenant_key=tk) as session:
                service = OAuthService(db_session=session)
                response_holder["body"] = await service.refresh_token_grant(
                    refresh_token=raw_presented,
                    client_id=client_id,
                    client_secret=client_secret,
                )
                raise _PostReturnFailureError

        with pytest.raises(_PostReturnFailureError):
            await _grant_then_fail_pre_commit()

        assert "body" in response_holder, "the grant itself must have succeeded before the failure"

        # Consistency invariant (holds under either accepted fix shape): if the
        # cache holds a response for the presented token, the rotated refresh
        # token inside it must exist as a DB row. Pre-fix the entry is present
        # but the row was rolled back.
        cached = await _refresh_svc._refresh_idempotency_cache_get(tk, hash_refresh_token(raw_presented))
        if cached is not None:
            cached_refresh = cached.response_body["refresh_token"]
            assert await _refresh_row_exists(db_manager, tenant_key=tk, raw_token=cached_refresh), (
                "idempotency cache serves a refresh token that has NO persisted row: "
                "an in-window retry would receive a pair the DB does not know"
            )
    finally:
        restore()


def _generate_pkce_pair() -> tuple[str, str]:
    code_verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    code_challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return code_verifier, code_challenge


@pytest.mark.asyncio
async def test_token_cache_entry_never_outlives_a_rolled_back_transaction(db_manager, monkeypatch):
    """/token: after a post-return rollback, any cached pair must map to a live row."""
    monkeypatch.setenv("JWT_SECRET", "test_secret_key")
    monkeypatch.setattr(_idem, "OAUTH_TOKEN_IDEMPOTENCY_WINDOW_SECONDS", 30)

    from giljo_mcp.models.oauth import OAuthAuthorizationCode

    user_id, tk = await _seed_user(db_manager)
    code_verifier, code_challenge = _generate_pkce_pair()
    code_value = secrets.token_urlsafe(64)
    redirect_uri = "http://localhost:3000/callback"

    # Committed auth code for the built-in public PKCE client (no resolver stub
    # needed; public clients also receive a refresh token — BE-6161).
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

    response_holder: dict = {}

    async def _exchange_then_fail_pre_commit() -> None:
        async with db_manager.get_session_async(tenant_key=tk) as session:
            service = OAuthService(db_session=session)
            response_holder["body"] = await service.exchange_code_for_token(
                code=code_value,
                client_id=BUILTIN_CLIENT_ID,
                code_verifier=code_verifier,
                redirect_uri=redirect_uri,
            )
            raise _PostReturnFailureError

    with pytest.raises(_PostReturnFailureError):
        await _exchange_then_fail_pre_commit()

    assert "body" in response_holder, "the exchange itself must have succeeded before the failure"
    assert "refresh_token" in response_holder["body"]

    # Same consistency invariant as the /refresh twin.
    cached = await _idem.cache_get(tk, code_value)
    if cached is not None:
        cached_refresh = cached.response_body["refresh_token"]
        assert await _refresh_row_exists(db_manager, tenant_key=tk, raw_token=cached_refresh), (
            "/token idempotency cache serves a refresh token that has NO persisted row: "
            "an in-window retry would receive a pair the DB does not know"
        )
