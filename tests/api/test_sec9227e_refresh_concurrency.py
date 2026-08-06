# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""SEC-9227e (M5) — truly concurrent refreshes of the same token must converge.

Defect (ordering): ``_refresh_grant_after_lookup`` checks the idempotency cache
BEFORE taking the user-row ``FOR UPDATE`` lock. Two truly simultaneous
refreshes of the same token — the multi-egress-IP connector retry shape the
window was built for (see the live-evidence note in
``oauth_token_idempotency.py``) — BOTH miss the cache (neither has written
yet), then serialize on the lock: the first rotates and revokes the presented
row; the second re-reads ``row.revoked`` fresh under the lock (the SEC-9217b
re-read), sees True, and trips reuse detection — revoking the ENTIRE family,
including the pair the first request just returned to its client. The
convergence mechanism only works when the two requests are separated by more
than the cache-write latency.

Museum rule: the idempotency window and its in-window reuse-suppression are
deliberate (real production incident) and are NOT weakened by these tests or
the fix they specify. Only the truly-simultaneous case is tightened: honest
concurrent retries converge on ONE rotated pair, while a genuine replay
(revoked row + no matching cached response) still revokes the family.

Test design:

- ``test_truly_concurrent_refresh_converges_on_one_pair`` — the incident
  shape. Two ``/refresh`` calls for the SAME token run concurrently via
  ``asyncio.gather``; each request receives its OWN ``AsyncSession`` from the
  ``get_db_session`` dependency override, so the two grants hold two separate
  DB transactions (a single shared session would serialize them client-side
  and prove nothing). A rendezvous barrier at the cache-get seam guarantees
  BOTH requests complete their pre-lock cache read before either proceeds —
  the sub-millisecond interleaving the incident produces, made deterministic.
  Pre-fix this was ``xfail(strict=True)``: the family self-revoked (one 200
  whose pair is already dead + one 401). The M5 fix (under-lock cache re-check
  with bounded retry) removed the marker; both requests must return the same
  rotated pair.

  Deterministic fallback (if this ever flakes in CI): drop the gather and
  replicate the loser's view directly — pre-set ``row.revoked=True`` on a
  committed row, populate the cache with the winner's entry under the same
  signature, monkeypatch the FIRST ``_refresh_idempotency_cache_get`` call to
  miss (the early read that lost the interleaving), and assert convergence.

- ``test_replay_of_revoked_token_with_empty_cache_revokes_family`` — the
  genuine-replay path must KEEP revoking the family (the museum-rule
  behavior). Guards the fix against overshoot.

- ``test_cached_entry_with_mismatched_signature_still_revokes_family`` — a
  cached response only converges for the SAME client identity; a signature
  mismatch must fall through to reuse detection, before and after the fix.

Parallel-safe: unique tenant/user/client per test, per-test cache-backend
registry reset (precedent: ``tests/services/test_oauth_token_idempotency.py``),
monkeypatch-only patching, no module-level mutable state.
"""

from __future__ import annotations

import asyncio
import secrets
from uuid import uuid4

import bcrypt
import pytest
from sqlalchemy import select, update

from giljo_mcp.models.oauth import OAuthRefreshToken
from giljo_mcp.services import cache_backends
from giljo_mcp.services import oauth_refresh_service as _refresh_svc
from giljo_mcp.services.oauth_refresh_service import (
    hash_refresh_token,
    issue_refresh_token,
    new_family_id,
)


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
            name=f"SEC9227e Org {unique}",
            slug=f"sec9227e-org-{unique}",
            tenant_key=tk,
            is_active=True,
        )
        session.add(org)
        await session.flush()
        session.add(
            User(
                id=user_id,
                username=f"sec9227e_user_{unique}",
                email=f"sec9227e_{unique}@example.com",
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
            client_name="SEC9227e Test Client",
            redirect_uris=["http://localhost:3000/callback"],
            client_secret_hash=secret_hash,
        )

    svc.set_client_resolver(_resolver)
    return lambda: svc.set_client_resolver(prior)


async def _seed_refresh_token(
    db_manager,
    *,
    client_id: str,
    tenant_key: str,
    user_id: str,
    family_id: str | None = None,
) -> tuple[str, str]:
    """Mint + commit one refresh row; return (raw_token, family_id)."""
    fam = family_id or new_family_id()
    async with db_manager.get_session_async(tenant_key=tenant_key) as session:
        raw = await issue_refresh_token(
            session,
            family_id=fam,
            client_id=client_id,
            tenant_key=tenant_key,
            user_id=user_id,
            scope="mcp:read mcp:write",
            aud="",
            lifetime_seconds=3600,
        )
        await session.commit()
    return raw, fam


async def _refresh_call(api_client, *, refresh_token: str, client_id: str, client_secret: str):
    return await api_client.post(
        "/api/oauth/refresh",
        data={
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": client_id,
            "client_secret": client_secret,
        },
    )


def _oauth_err_text(body: dict) -> str:
    return " ".join(str(body.get(k, "")) for k in ("error", "error_description", "detail", "message"))


async def _family_rows(db_manager, *, tenant_key: str, family_id: str) -> list[OAuthRefreshToken]:
    async with db_manager.get_session_async(tenant_key=tenant_key) as session:
        return list(
            (
                await session.execute(
                    select(OAuthRefreshToken).where(
                        OAuthRefreshToken.family_id == family_id,
                        OAuthRefreshToken.tenant_key == tenant_key,
                    )
                )
            )
            .scalars()
            .all()
        )


async def _mark_revoked(db_manager, *, tenant_key: str, token_hash: str) -> None:
    async with db_manager.get_session_async(tenant_key=tenant_key) as session:
        await session.execute(
            update(OAuthRefreshToken)
            .where(
                OAuthRefreshToken.token_hash == token_hash,
                OAuthRefreshToken.tenant_key == tenant_key,
            )
            .values(revoked=True)
        )
        await session.commit()


@pytest.mark.asyncio
async def test_truly_concurrent_refresh_converges_on_one_pair(api_client, db_manager, monkeypatch):
    """Two concurrent grants for the SAME token, two SEPARATE DB sessions.

    Desired contract (post-M5): the lock winner rotates; the lock loser finds
    the winner's cached response under the lock and returns the SAME pair.
    Both calls 200, identical bodies, exactly one live row in the family.

    Pre-fix behavior (the defect this test was written to reproduce): one 200
    + one 401 invalid_grant, and ZERO live rows — the losing request revoked
    the whole family, killing the pair the winning request returned.
    """
    monkeypatch.setenv("JWT_SECRET", "test_secret_key")
    # Real positive window: the in-window convergence contract is the subject.
    monkeypatch.setattr(_refresh_svc, "OAUTH_REFRESH_IDEMPOTENCY_WINDOW_SECONDS", 30)

    user_id, tk = await _seed_user(db_manager)
    client_id = str(uuid4())
    client_secret = secrets.token_urlsafe(48)
    secret_hash = bcrypt.hashpw(client_secret.encode("utf-8"), bcrypt.gensalt()).decode("ascii")
    restore = _install_confidential_resolver(client_id, secret_hash)

    # Rendezvous at the cache-get seam: BOTH requests must complete their
    # pre-lock cache read before either proceeds. This pins the exact
    # interleaving of the incident (neither request has written the cache when
    # the other reads it) without relying on wall-clock timing. Only the first
    # two calls are gated so a post-fix under-lock re-check passes through.
    real_cache_get = _refresh_svc._refresh_idempotency_cache_get
    barrier = asyncio.Barrier(2)
    gate = {"remaining": 2}

    async def _cache_get_with_rendezvous(tenant_key: str, token_hash: str):
        result = await real_cache_get(tenant_key, token_hash)
        if gate["remaining"] > 0:
            gate["remaining"] -= 1
            await asyncio.wait_for(barrier.wait(), timeout=30)
        return result

    monkeypatch.setattr(_refresh_svc, "_refresh_idempotency_cache_get", _cache_get_with_rendezvous)

    try:
        raw, fam = await _seed_refresh_token(db_manager, client_id=client_id, tenant_key=tk, user_id=user_id)

        resp_a, resp_b = await asyncio.wait_for(
            asyncio.gather(
                _refresh_call(api_client, refresh_token=raw, client_id=client_id, client_secret=client_secret),
                _refresh_call(api_client, refresh_token=raw, client_id=client_id, client_secret=client_secret),
            ),
            timeout=120,
        )

        # The reproduction is only meaningful if both requests actually
        # rendezvoused at the pre-lock cache read.
        assert gate["remaining"] == 0, "both requests must have completed the pre-lock cache read"

        statuses = sorted([resp_a.status_code, resp_b.status_code])
        rows = await _family_rows(db_manager, tenant_key=tk, family_id=fam)
        live = [r for r in rows if not r.revoked]

        # Desired contract (post-M5). Pre-fix this fails with
        # statuses == [200, 401] and live == [] — the family self-revocation.
        assert statuses == [200, 200], (
            f"concurrent refreshes must both succeed; got statuses={statuses} "
            f"(loser body: {_oauth_err_text((resp_a if resp_a.status_code != 200 else resp_b).json())!r}), "
            f"live family rows={len(live)}"
        )
        assert resp_a.json()["refresh_token"] == resp_b.json()["refresh_token"], (
            "both requests must converge on the SAME rotated refresh token"
        )
        assert resp_a.json()["access_token"] == resp_b.json()["access_token"], (
            "both requests must converge on the SAME access token"
        )
        assert len(live) == 1, f"exactly the rotated row must remain live, got {len(live)}"
    finally:
        restore()


@pytest.mark.asyncio
async def test_replay_of_revoked_token_with_empty_cache_revokes_family(api_client, db_manager, monkeypatch):
    """Genuine replay (revoked row, NO cached response) must still revoke the family.

    This is the museum-rule behavior the M5 fix must preserve: outside the
    window — or inside it with no matching cached response — presenting a
    consumed token is reuse, and reuse durably revokes every sibling. A
    same-family live sibling proves the revocation is family-wide.
    """
    monkeypatch.setenv("JWT_SECRET", "test_secret_key")
    monkeypatch.setattr(_refresh_svc, "OAUTH_REFRESH_IDEMPOTENCY_WINDOW_SECONDS", 30)

    user_id, tk = await _seed_user(db_manager)
    client_id = str(uuid4())
    client_secret = secrets.token_urlsafe(48)
    secret_hash = bcrypt.hashpw(client_secret.encode("utf-8"), bcrypt.gensalt()).decode("ascii")
    restore = _install_confidential_resolver(client_id, secret_hash)

    try:
        raw_consumed, fam = await _seed_refresh_token(db_manager, client_id=client_id, tenant_key=tk, user_id=user_id)
        _raw_sibling, _ = await _seed_refresh_token(
            db_manager, client_id=client_id, tenant_key=tk, user_id=user_id, family_id=fam
        )
        await _mark_revoked(db_manager, tenant_key=tk, token_hash=hash_refresh_token(raw_consumed))

        # Cache is empty (registry reset per test): the replay has no cached
        # response to converge on, so reuse detection must fire.
        resp = await _refresh_call(
            api_client, refresh_token=raw_consumed, client_id=client_id, client_secret=client_secret
        )

        assert resp.status_code == 401, resp.text
        assert "invalid_grant" in _oauth_err_text(resp.json()).lower(), resp.json()

        rows = await _family_rows(db_manager, tenant_key=tk, family_id=fam)
        assert rows, "seeded family rows must exist"
        assert all(r.revoked for r in rows), "reuse must revoke EVERY row in the family, including the live sibling"
    finally:
        restore()


@pytest.mark.asyncio
async def test_cached_entry_with_mismatched_signature_still_revokes_family(api_client, db_manager, monkeypatch):
    """A cached response converges only for the SAME client identity.

    A cache entry whose body signature does not match the caller must fall
    through to reuse detection — before and after the M5 fix. This pins the
    boundary between an honest in-window retry (same signature) and a replay
    presented under a different identity.
    """
    monkeypatch.setenv("JWT_SECRET", "test_secret_key")
    monkeypatch.setattr(_refresh_svc, "OAUTH_REFRESH_IDEMPOTENCY_WINDOW_SECONDS", 30)

    user_id, tk = await _seed_user(db_manager)
    client_id = str(uuid4())
    client_secret = secrets.token_urlsafe(48)
    secret_hash = bcrypt.hashpw(client_secret.encode("utf-8"), bcrypt.gensalt()).decode("ascii")
    restore = _install_confidential_resolver(client_id, secret_hash)

    try:
        raw_consumed, fam = await _seed_refresh_token(db_manager, client_id=client_id, tenant_key=tk, user_id=user_id)
        _raw_sibling, _ = await _seed_refresh_token(
            db_manager, client_id=client_id, tenant_key=tk, user_id=user_id, family_id=fam
        )
        await _mark_revoked(db_manager, tenant_key=tk, token_hash=hash_refresh_token(raw_consumed))

        # A cache entry exists for this token hash, but under a signature no
        # real caller can produce — the convergence path must NOT accept it.
        await _refresh_svc._refresh_idempotency_cache_put(
            tk,
            hash_refresh_token(raw_consumed),
            _refresh_svc._RefreshIdempotencyEntry(
                response_body={
                    "access_token": "cached-access",
                    "token_type": "bearer",
                    "expires_in": 60,
                    "refresh_token": "cached-refresh",
                    "refresh_expires_in": 60,
                },
                body_signature="0" * 64,
            ),
        )

        resp = await _refresh_call(
            api_client, refresh_token=raw_consumed, client_id=client_id, client_secret=client_secret
        )

        assert resp.status_code == 401, resp.text
        assert "invalid_grant" in _oauth_err_text(resp.json()).lower(), resp.json()
        assert "cached-access" not in resp.text, "a mismatched-signature cache entry must never be served"

        rows = await _family_rows(db_manager, tenant_key=tk, family_id=fam)
        assert all(r.revoked for r in rows), "signature-mismatch replay must revoke the family"
    finally:
        restore()
