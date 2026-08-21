# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""Endpoint-layer regression test for BE-6025.

Bug: ``POST /api/auth/refresh`` returned HTTP 500 under the fail-closed tenant
guard (``GILJO_TENANT_GUARD_MODE=enforce``). The endpoint looked up the User row
with hand-written tenant predicates (``User.tenant_key == tenant_key``) but never
set tenant *context* on the session. The ``do_orm_execute`` guard
(``_enforce_tenant_scope`` in ``giljo_mcp/database.py``) requires context, not
explicit predicates, so it raised ``TenantIsolationError`` and the unhandled
exception became a 500. Effect on prod/test-install under enforce: every silent
session-extension refresh failed, bouncing real logged-in customers to /login.

Fix: ``refresh_token`` sets tenant context from the signed JWT's ``tenant_key``
via ``tenant_session_context(db, tenant_key)`` before the User lookup, and drops
the now-redundant explicit ``User.tenant_key`` predicate (the guard injects it
from context). The tenant_key is sourced only from the verified JWT.

This test exercises the FAILING layer -- the real HTTP refresh endpoint through
FastAPI DI via the ASGI client, under enforce guard mode -- per the CLAUDE.md
failing-layer rule (BE-5042 lesson).

Parallel-safe: every test seeds its own unique tenant + org + user; guard mode is
set via ``monkeypatch.setenv``; no module-level mutable state; no ordering
dependency.

Project: BE-6025.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import bcrypt
import jwt
import pytest
import pytest_asyncio

from giljo_mcp.auth.jwt_manager import JWTManager
from giljo_mcp.models import User
from giljo_mcp.models.organizations import Organization
from giljo_mcp.services.oauth_revocation_service import clear_revocation_cache
from giljo_mcp.tenant import TenantManager


_REFRESH_URL = "/api/auth/refresh"


async def _seed_user(db_manager) -> dict:
    """Create a fresh active user (+ org) in a unique tenant. Returns ids + valid token."""
    suffix = uuid.uuid4().hex[:8]
    tenant_key = TenantManager.generate_tenant_key()
    password_hash = bcrypt.hashpw(b"test_password", bcrypt.gensalt()).decode("utf-8")

    async with db_manager.get_session_async() as session:
        org = Organization(
            name=f"BE6025 Org {suffix}",
            slug=f"be6025-org-{suffix}",
            tenant_key=tenant_key,
            is_active=True,
        )
        session.add(org)
        await session.flush()

        user = User(
            username=f"be6025_user_{suffix}",
            email=f"be6025_{suffix}@example.com",
            password_hash=password_hash,
            tenant_key=tenant_key,
            role="developer",
            org_id=org.id,
        )
        session.add(user)
        await session.commit()
        user_id = user.id

    token = JWTManager.create_access_token(
        user_id=user_id,
        username=f"be6025_user_{suffix}",
        role="developer",
        tenant_key=tenant_key,
    )
    return {"tenant_key": tenant_key, "user_id": user_id, "username": f"be6025_user_{suffix}", "token": token}


def _expired_token(user_id: str, username: str, tenant_key: str, hours_ago: int) -> str:
    """Encode an otherwise-valid access token whose exp is ``hours_ago`` in the past."""
    secret_key = JWTManager._get_secret_key()
    now = datetime.now(UTC)
    payload = {
        "sub": str(user_id),
        "username": username,
        "role": "developer",
        "tenant_key": tenant_key,
        "exp": now - timedelta(hours=hours_ago),
        "iat": now - timedelta(hours=hours_ago + JWTManager.ACCESS_TOKEN_EXPIRE_HOURS),
        "type": "access",
        "jti": uuid.uuid4().hex,
    }
    return jwt.encode(payload, secret_key, algorithm=JWTManager.ALGORITHM)


@pytest_asyncio.fixture(scope="function")
async def seeded_user(db_manager) -> dict:
    return await _seed_user(db_manager)


@pytest.mark.asyncio
async def test_refresh_valid_token_returns_200_under_enforce(api_client, seeded_user, monkeypatch) -> None:
    """Regression: a valid token refreshes (200 + renewed cookie) under enforce mode.

    Before BE-6025 the User lookup ran without tenant context and the fail-closed
    guard raised TenantIsolationError -> 500. After the fix the lookup is
    context-scoped and the refresh succeeds with a new access_token cookie.
    """
    monkeypatch.setenv("GILJO_TENANT_GUARD_MODE", "enforce")

    api_client.cookies.set("access_token", seeded_user["token"])
    resp = await api_client.post(_REFRESH_URL)

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["message"] == "Token refreshed"
    assert body["username"] == seeded_user["username"]

    set_cookie = resp.headers.get("set-cookie", "")
    assert "access_token=" in set_cookie


@pytest.mark.asyncio
async def test_refresh_missing_token_returns_401_under_enforce(api_client, monkeypatch) -> None:
    """No cookie -> 401 (not a 500), even under enforce mode."""
    monkeypatch.setenv("GILJO_TENANT_GUARD_MODE", "enforce")

    api_client.cookies.clear()
    resp = await api_client.post(_REFRESH_URL)

    assert resp.status_code == 401, resp.text


@pytest.mark.asyncio
async def test_refresh_expired_beyond_grace_returns_401_under_enforce(api_client, seeded_user, monkeypatch) -> None:
    """Token expired beyond the 1h grace window -> 401 (rejected before any DB query)."""
    monkeypatch.setenv("GILJO_TENANT_GUARD_MODE", "enforce")

    stale = _expired_token(
        seeded_user["user_id"],
        seeded_user["username"],
        seeded_user["tenant_key"],
        hours_ago=JWTManager.REFRESH_GRACE_PERIOD_HOURS + 2,
    )
    api_client.cookies.set("access_token", stale)
    resp = await api_client.post(_REFRESH_URL)

    assert resp.status_code == 401, resp.text


@pytest.mark.asyncio
async def test_refresh_rejects_revoked_token(api_client, seeded_user, monkeypatch) -> None:
    """SEC-3001a Wave 2 (item 2): a revoked (logged-out) token cannot be
    silently refreshed into a brand-new access token.

    Class of bug: logout writes an ``OAuthRevokedToken`` row for the token's
    ``jti``, but ``/api/auth/refresh`` never consulted the revocation ledger --
    so a logged-out-but-not-yet-expired cookie could be exchanged for a fresh
    24h token, defeating logout. The fix adds an ``is_access_token_jti_revoked``
    check on the refresh seam.

    Two-sided, modeled on the real flow (login-token -> logout -> replay): the
    SAME token refreshes (200) BEFORE logout, then is rejected (401) AFTER
    logout revokes its jti -- proving the revocation check is what flips the
    outcome. Exercised at the failing layer (the real HTTP refresh endpoint)
    under enforce guard mode; revocation is driven through the logout endpoint
    so it shares the app's DB context.
    """
    monkeypatch.setenv("GILJO_TENANT_GUARD_MODE", "enforce")
    clear_revocation_cache()
    token = seeded_user["token"]

    # Each phase clears the cookie jar first: a successful refresh rotates the
    # access_token cookie, so we re-pin ONLY the original token every time to be
    # certain logout revokes -- and refresh replays -- that exact jti.

    # Happy half: a pristine, non-revoked token refreshes successfully.
    api_client.cookies.clear()
    api_client.cookies.set("access_token", token)
    ok = await api_client.post(_REFRESH_URL)
    assert ok.status_code == 200, ok.text

    # Revoke it the real way: logout writes the OAuthRevokedToken row for the jti.
    api_client.cookies.clear()
    api_client.cookies.set("access_token", token)
    out = await api_client.post("/api/auth/logout")
    assert out.status_code == 200, out.text

    # Kill half: the now-revoked token is refused at /refresh (no new cookie).
    api_client.cookies.clear()
    api_client.cookies.set("access_token", token)
    blocked = await api_client.post(_REFRESH_URL)
    assert blocked.status_code == 401, blocked.text
    # The error envelope surfaces the HTTPException detail under "message".
    assert "revoked" in blocked.text.lower(), blocked.text
    assert "set-cookie" not in {k.lower() for k in blocked.headers}, "revoked refresh must not mint a new cookie"


@pytest.mark.asyncio
async def test_me_org_loading_returns_200_under_enforce(api_client, seeded_user, monkeypatch) -> None:
    """Sibling-path audit: GET /api/auth/me loads the user's Organization + OrgMembership
    (both tenant-scoped models) after resolving the user. The resolver sets tenant context
    on the shared session, so the org-loading queries are covered -- 200 under enforce.

    This guards the audited sibling so a future refactor that drops the resolver's context
    side effect would be caught here.
    """
    monkeypatch.setenv("GILJO_TENANT_GUARD_MODE", "enforce")

    api_client.cookies.set("access_token", seeded_user["token"])
    resp = await api_client.get("/api/auth/me")

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["username"] == seeded_user["username"]
    assert body["org_name"] is not None
