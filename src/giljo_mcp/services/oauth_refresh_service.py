# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""OAuth 2.1 refresh-token grant — rotation + family reuse detection (API-0021e Phase 2).

Split out of ``oauth_service`` to keep that file under the 800-line guardrail
while still expressing the OAuth flow as a coherent ``OAuthService`` API.
The helpers here operate on the same ``AsyncSession`` the OAuthService caller
holds; they don't open new connections. The owning service (``OAuthService``)
delegates to these for the refresh-token-specific surface.

Security contract (RFC 6749 §6 + §10.4 + OAuth 2.1 Security BCP):
  - The raw refresh token is NEVER persisted; only the sha256 hex digest.
  - ``family_id`` groups every token derived from the same initial
    authorization-code grant. Reusing a revoked or already-rotated token
    revokes the entire family + logs a security event.
  - Tenant_key on the row is the SERVER-AUTHORITATIVE source. A request body
    NEVER produces the tenant — the token's row does.
  - Public PKCE clients ARE supported here (BE-6161). They hold no secret, so
    possession of the one-time-use rotating refresh token is the proof-of-
    possession (RFC 8252 / OAuth 2.1 §4.3.1); rotation + family reuse detection
    is what bounds the risk, exactly as for confidential clients. Confidential
    clients additionally bcrypt-verify their secret.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import os
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import and_, case, func, select, update

from giljo_mcp.auth.jwt_manager import JWTManager
from giljo_mcp.database import tenant_isolation_bypass, tenant_session_context
from giljo_mcp.models.auth import User
from giljo_mcp.models.oauth import OAuthRefreshToken
from giljo_mcp.services._idem_crypto import decrypt_payload, encrypt_payload
from giljo_mcp.services.cache_backends import OAUTH_REFRESH_BACKEND_NAME, get_cache_backend


if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from giljo_mcp.services.oauth_service import OAuthService


logger = logging.getLogger(__name__)

# API-0021l: 5-second idempotency window for /refresh retries. Same shape as
# the /token primitive in oauth_token_idempotency. The cache hit suppresses
# the existing reuse-detection alarm INSIDE the window — that's the whole
# point: concurrent retries from the same client are not malicious replays.
#
# State is held in the `oauth_refresh` `CacheBackend` (INF-5074). CE: dict.
# SaaS: Redis. The swap is transparent to this module.
OAUTH_REFRESH_IDEMPOTENCY_WINDOW_SECONDS = int(os.environ.get("OAUTH_REFRESH_IDEMPOTENCY_WINDOW_SECONDS", "5"))
_REFRESH_IDEMPOTENCY_FIELD_SEP = b"\x1f"

# SEC-9227e (M5): bounded under-lock re-check of the idempotency cache before
# reuse detection revokes a family. Covers the winner's commit->cache-put gap
# (see _converged_pair_under_lock). 5 x 50ms = ~250ms worst case, and ONLY on
# the losing side of a truly concurrent same-token refresh.
_CONVERGE_RECHECK_ATTEMPTS = 5
_CONVERGE_RECHECK_SLEEP_SECONDS = 0.05


@dataclass(frozen=True)
class _RefreshIdempotencyEntry:
    response_body: dict
    body_signature: str


def _serialize_refresh_entry(entry: _RefreshIdempotencyEntry) -> str:
    # SEC-9227f (M2a): the JSON contains the raw access+refresh token pair —
    # encrypt it so no readable token material reaches any cache backend
    # (SaaS Redis persistence/MONITOR would otherwise expose live pairs).
    return encrypt_payload(
        json.dumps(
            {
                "response_body": entry.response_body,
                "body_signature": entry.body_signature,
            }
        )
    )


def _deserialize_refresh_entry(raw: str) -> _RefreshIdempotencyEntry | None:
    # SEC-9227f: an undecryptable entry (tampered, rotated key, stale format)
    # is a cache MISS, never an exception — see _idem_crypto.decrypt_payload.
    plaintext = decrypt_payload(raw)
    if plaintext is None:
        return None
    payload = json.loads(plaintext)
    return _RefreshIdempotencyEntry(
        response_body=dict(payload["response_body"]),
        body_signature=str(payload["body_signature"]),
    )


async def _refresh_idempotency_cache_get(tenant_key: str, token_hash: str) -> _RefreshIdempotencyEntry | None:
    backend = get_cache_backend(OAUTH_REFRESH_BACKEND_NAME)
    raw = await backend.get(tenant_key, token_hash)
    if raw is None:
        return None
    return _deserialize_refresh_entry(raw)


async def _refresh_idempotency_cache_put(tenant_key: str, token_hash: str, entry: _RefreshIdempotencyEntry) -> None:
    backend = get_cache_backend(OAUTH_REFRESH_BACKEND_NAME)
    await backend.set(
        tenant_key,
        token_hash,
        _serialize_refresh_entry(entry),
        ttl_seconds=OAUTH_REFRESH_IDEMPOTENCY_WINDOW_SECONDS,
    )


def _compute_refresh_body_signature(
    *,
    client_id: str,
    client_secret_hash: str | None,
    refresh_token_hash: str,
) -> str:
    """Canonical body-signature for the /refresh idempotency check.

    Uses the stored ``client_secret_hash`` rather than the plaintext secret
    so the signature stays deterministic across retries even though the
    same caller might present its plaintext secret with cosmetic
    whitespace differences (it doesn't, but the hash is the canonical
    server-side identity anyway).

    BE-6161: public PKCE clients have no ``client_secret_hash`` (``None``);
    the empty-string substitution keeps the digest well-defined. The
    ``refresh_token_hash`` already uniquely identifies the in-window retry,
    so the secret-hash component is corroborating, not load-bearing, here.
    """
    h = hashlib.sha256()
    h.update(client_id.encode("utf-8"))
    h.update(_REFRESH_IDEMPOTENCY_FIELD_SEP)
    h.update((client_secret_hash or "").encode("utf-8"))
    h.update(_REFRESH_IDEMPOTENCY_FIELD_SEP)
    h.update(refresh_token_hash.encode("utf-8"))
    return h.hexdigest()


async def _converged_pair_under_lock(
    *,
    tenant_key: str,
    token_hash: str,
    body_signature: str,
) -> _RefreshIdempotencyEntry | None:
    """SEC-9227e (M5): under-lock cache re-check that lets truly concurrent
    refreshes CONVERGE instead of self-revoking the family.

    The incident shape (the reason the idempotency window exists at all — see
    the live-evidence note in ``oauth_token_idempotency.py``): two simultaneous
    /refresh calls with the SAME token from the same honest client (multi-egress
    connector retry). Both miss the pre-lock cache read (neither has written
    yet), then serialize on the user FOR UPDATE lock. The winner rotates,
    commits, and cache-puts; the loser then sees ``row.revoked=True`` under the
    lock and — without this re-check — would trip reuse detection and revoke the
    ENTIRE family, killing the pair the winner just returned. That is the
    protection mechanism destroying the session it protects.

    WHY THE RETRY LOOP EXISTS (do not "simplify" it away): M2b deliberately
    moved the winner's cache-put to AFTER its commit (a cache entry must never
    outlive a rolled-back transaction). The winner's FOR UPDATE lock releases AT
    commit, so the loser can proceed inside the winner's commit->cache-put gap
    and miss a cache entry that is microseconds from existing. The bounded wait
    (up to ~250ms, losing request only) rides out exactly that gap. Removing it
    silently reopens the family self-revocation under true concurrency.

    A HIT is convergence, not an attack: producing the matching
    ``body_signature`` requires the client's own credentials/token — the same
    proof the winner presented. A replay outside the window, or from a different
    identity, has no matching entry (MISS / signature mismatch) and returns
    None, letting the caller's reuse detection fire unchanged.
    """
    for attempt in range(_CONVERGE_RECHECK_ATTEMPTS):
        cached = await _refresh_idempotency_cache_get(tenant_key, token_hash)
        if cached is not None:
            if hmac.compare_digest(cached.body_signature, body_signature):
                return cached
            # An entry exists but was written by a DIFFERENT identity: that can
            # never become a matching entry by waiting — fail to reuse detection
            # immediately (museum rule: mismatch is attack telemetry).
            return None
        if attempt < _CONVERGE_RECHECK_ATTEMPTS - 1:
            await asyncio.sleep(_CONVERGE_RECHECK_SLEEP_SECONDS)
    return None


def hash_refresh_token(raw_token: str) -> str:
    """Return the sha256 hex digest of ``raw_token`` for DB lookup.

    Refresh tokens are 64-byte url-safe random strings; the raw value is
    returned to the client ONCE in the response and never persisted.
    Lookups go ``hash(presented) -> WHERE token_hash =``. sha256 is
    sufficient here because the input already has 64 bytes of entropy —
    bcrypt would add no real-world security and a lot of latency on every
    refresh call.
    """
    # SEC-9227 (L1): utf-8 is a superset of ascii, so the digest is byte-identical
    # for every existing (ascii) token — no migration — while a future non-ascii
    # token hashes cleanly instead of raising UnicodeEncodeError (a 500).
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def hash_authorization_code(code: str) -> str:
    """Return the sha256 hex digest of an authorization ``code`` (SEC-9227b, M4).

    Stored as ``oauth_refresh_tokens.origin_code_hash`` at /token issuance and
    recomputed on the code-reuse path to find every family born of a replayed
    code. The raw code is NEVER persisted — only this digest. utf-8 (not ascii)
    for the same reason as :func:`hash_refresh_token`.
    """
    return hashlib.sha256(code.encode("utf-8")).hexdigest()


def new_family_id() -> str:
    """Mint a fresh ``family_id`` (UUIDv4) for a brand-new refresh-token chain."""
    return str(uuid4())


async def issue_refresh_token(
    session: AsyncSession,
    *,
    family_id: str,
    client_id: str,
    tenant_key: str,
    user_id: str,
    scope: str | None,
    aud: str,
    lifetime_seconds: int,
    origin_code_hash: str | None = None,
) -> str:
    """Mint + persist a refresh-token row, return the raw token string.

    The raw value is what's handed back to the client; the DB stores only
    its sha256 hex hash. ``family_id`` groups every token derived from the
    same initial authorization-code grant; reusing a revoked token revokes
    the entire family (RFC 6749 §10.4 + OAuth 2.1 Security BCP).

    ``origin_code_hash`` (SEC-9227b, M4): the sha256 hex of the authorization
    code that minted this family. Passed only at initial /token issuance;
    rotation and other callers leave it None (the family is revoked by
    family_id, so rotated rows need no linkage of their own).
    """
    raw_token = secrets.token_urlsafe(64)
    token_hash = hash_refresh_token(raw_token)
    expires_at = datetime.now(UTC) + timedelta(seconds=lifetime_seconds)

    row = OAuthRefreshToken(
        token_hash=token_hash,
        family_id=family_id,
        client_id=client_id,
        tenant_key=tenant_key,
        user_id=user_id,
        scope=scope,
        aud=aud,
        expires_at=expires_at,
        revoked=False,
        origin_code_hash=origin_code_hash,
    )
    session.add(row)
    await session.flush()
    return raw_token


async def revoke_family(
    session: AsyncSession,
    *,
    family_id: str,
    tenant_key: str,
) -> int:
    """Mark every token in the family as revoked (idempotent).

    Tenant filter is mandatory (CLAUDE.md tenant-isolation rule); a
    family_id collision across tenants is astronomically unlikely with
    UUIDv4 but the WHERE clause is part of the contract.
    Returns the number of rows updated for observability/logging.
    """
    result = await session.execute(
        update(OAuthRefreshToken)
        .where(
            OAuthRefreshToken.family_id == family_id,
            OAuthRefreshToken.tenant_key == tenant_key,
            OAuthRefreshToken.revoked.is_(False),
        )
        .values(revoked=True)
    )
    await session.flush()
    return int(result.rowcount or 0)


async def revoke_all_for_user(
    session: AsyncSession,
    *,
    user_id: str,
    tenant_key: str,
) -> int:
    """Revoke EVERY outstanding refresh token the user holds, across all families.

    SEC-9047: called from the password change/reset paths so a credential
    change cuts off refresh-token minting everywhere, not just for one
    family. Idempotent; tenant filter is mandatory (CLAUDE.md tenant-isolation
    rule). Returns the number of rows updated for observability/logging.
    """
    result = await session.execute(
        update(OAuthRefreshToken)
        .where(
            OAuthRefreshToken.user_id == user_id,
            OAuthRefreshToken.tenant_key == tenant_key,
            OAuthRefreshToken.revoked.is_(False),
        )
        .values(revoked=True)
    )
    await session.flush()
    return int(result.rowcount or 0)


async def get_oauth_credential_status(session: AsyncSession, tenant_key: str) -> tuple[bool, bool]:
    """Return ``(has_valid_oauth, has_expired_oauth)`` for tenant_key (FE-9274 connect-status).

    ``has_valid_oauth``: >=1 non-revoked, non-expired row.
    ``has_expired_oauth``: >=1 row exists at all, but none are currently
    valid (all revoked and/or past ``expires_at``) -- distinct from "never
    connected" (no rows), which reports both False.

    One COUNT query, read-only, no locking.
    """
    now = datetime.now(UTC)
    is_valid = and_(OAuthRefreshToken.revoked.is_(False), OAuthRefreshToken.expires_at > now)
    stmt = select(
        func.count(OAuthRefreshToken.id),
        func.count(case((is_valid, 1))),
    ).where(OAuthRefreshToken.tenant_key == tenant_key)
    result = await session.execute(stmt)
    total, valid = result.one()
    has_valid_oauth = valid > 0
    has_expired_oauth = total > 0 and not has_valid_oauth
    return has_valid_oauth, has_expired_oauth


async def lock_user_for_update(session: AsyncSession, *, user_id: str, tenant_key: str) -> User | None:
    """SEC-9227c (H3): take the user-first ``SELECT ... FOR UPDATE`` on the owning User.

    Every family-revocation site locks the User BEFORE revoking the refresh
    family so it serializes against a concurrent /refresh grant in the SAME order
    (SEC-9217b lock-order contract, same as ``session_eviction`` and
    ``_refresh_grant_after_lookup``). The caller then passes the returned row to
    :func:`bump_epoch_if_revoked`. Returns the locked User, or None if absent.
    """
    return (
        await session.execute(select(User).where(User.id == user_id, User.tenant_key == tenant_key).with_for_update())
    ).scalar_one_or_none()


def bump_epoch_if_revoked(user: User | None, revoked_rows: int) -> bool:
    """SEC-9227c (H3): increment ``token_revocation_epoch`` iff a revoke revoked LIVE rows.

    Bumping the epoch makes ``principal.py`` reject every access JWT already
    derived from the just-revoked family (its ``rev`` claim is now below the
    user's epoch) — the enforcement half of RFC 7009 revocation that flipping
    ``revoked`` alone does NOT provide. ONE shared, GATED bump so every
    revocation path (RFC 7009 /revoke, /refresh reuse, /token code-reuse) invokes
    it identically (avoiding the "fix in only N of the copies" drift
    ``principal.py`` warns about).

    GATE (``revoked_rows > 0``): re-revoking an ALREADY-dead family (e.g. a client
    presenting its old token after a password-reset eviction already revoked the
    family + bumped the epoch) must NOT keep bumping — that would spuriously
    invalidate the user's fresh re-login tokens (regression pinned by
    tests/saas/test_sec9047_reset_eviction). The epoch is bumped exactly once,
    when live tokens actually transition to revoked. Requires the User already
    locked FOR UPDATE (see :func:`lock_user_for_update`); the caller commits.
    """
    if revoked_rows > 0 and user is not None:
        user.token_revocation_epoch = (user.token_revocation_epoch or 0) + 1
        return True
    return False


async def revoke_families_for_code(
    session: AsyncSession,
    *,
    code: str,
    tenant_key: str,
) -> int:
    """SEC-9227b (M4): on authorization-code REUSE, revoke every refresh family
    minted from that code (RFC 9700 §4.5.3 / RFC 6749 §4.1.2).

    Finds the distinct families whose ``origin_code_hash`` matches this code
    within ``tenant_key`` and revokes each. Runs the lookup tenant-SCOPED and
    COMMITS before returning so the caller can raise immediately afterward: the
    router maps the raised ValueError to an HTTPException, whose GeneratorExit
    would otherwise roll the session back and lose the revocation (the same
    durability contract the /refresh reuse path relies on). Logs a security
    warning for attack telemetry. Returns the number of families revoked.
    """
    code_hash = hash_authorization_code(code)
    with tenant_session_context(session, tenant_key):
        rows = (
            await session.execute(
                select(OAuthRefreshToken.family_id, OAuthRefreshToken.user_id)
                .where(
                    OAuthRefreshToken.origin_code_hash == code_hash,
                    OAuthRefreshToken.tenant_key == tenant_key,
                )
                .distinct()
            )
        ).all()
        family_ids = [r.family_id for r in rows]
        # SEC-9227c (H3): lock the owning user(s) user-first (a code is issued to
        # ONE user, so normally one), revoke the families, then bump the epoch iff
        # a family actually had live rows — so their already-derived access JWTs
        # die too, without re-bumping on a repeat reuse of an already-dead code.
        locked_users = [
            await lock_user_for_update(session, user_id=uid, tenant_key=tenant_key)
            for uid in {r.user_id for r in rows if r.user_id}
        ]
        total_revoked = 0
        for family_id in family_ids:
            total_revoked += await revoke_family(session, family_id=family_id, tenant_key=tenant_key)
        for user in locked_users:
            bump_epoch_if_revoked(user, total_revoked)
        await session.commit()

    logger.warning(
        "oauth_auth_code_reuse_detected tenant=%s families_revoked=%d",
        tenant_key[:12] if tenant_key else "",
        len(family_ids),
    )
    return len(family_ids)


async def refresh_token_grant(
    service: OAuthService,
    *,
    refresh_token: str,
    client_id: str,
    client_secret: str | None,
    access_token_lifetime_seconds: int,
    refresh_token_lifetime_seconds: int,
) -> dict:
    """Exchange a refresh token for a new access+refresh pair.

    Steps (see module docstring for the security contract):
      1. Hash the presented token → unique global lookup. Either the row
         exists or it doesn't.
      2. Cross-tenant + cross-client guard: ``row.client_id`` MUST match
         the body-supplied ``client_id``. The row's ``tenant_key`` is the
         server-authoritative tenant for everything that follows.
      3. Verify client through the active ``ClientResolver`` under the
         row's tenant_key. Confidential clients bcrypt-verify their
         client_secret; public PKCE clients (BE-6161) present no secret and
         are authenticated by possession of the rotating refresh token.
      4. Reuse detection: a revoked row triggers ``revoke_family()`` and an
         EXPLICIT commit BEFORE raising; otherwise the router's
         HTTPException would surface as GeneratorExit through the session
         context manager and roll back the revocation.
      5. Otherwise: revoke prior row, mint a fresh access+refresh pair in
         the same ``family_id``.

    Args:
        service: ``OAuthService`` instance — used for its DB session
            handle and its ``_verify_client_authentication`` static.
        refresh_token: Plaintext refresh token from the client body.
        client_id: Client identifier from the request body. Used to
            corroborate (not produce) the row's tenant_key.
        client_secret: Confidential client's plaintext secret.
        access_token_lifetime_seconds: Lifetime to bake into the new JWT
            (``exp`` claim). Mirrors what /token issues.
        refresh_token_lifetime_seconds: Lifetime to bake into the new
            refresh row (``expires_at``). Mirrors what /token issues.

    Returns:
        Dict with ``access_token``, ``token_type``, ``expires_in``,
        ``refresh_token``, ``refresh_expires_in``.

    Raises:
        ValueError: With one of these prefixes (router maps to status):
            - ``invalid_client``  (401, RFC 6749 §5.2)
            - ``invalid_grant``   (401, RFC 6749 §5.2)
            - ``invalid_request`` (400)
    """
    if not refresh_token:
        raise ValueError("invalid_request: refresh_token is required")

    db = service._db
    token_hash = hash_refresh_token(refresh_token)
    # API-0022 (folds API-0024): defense-in-depth. Bind the lookup itself to
    # the body-supplied client_id so a stolen token_hash presented under a
    # different client never even resolves a row. ``oauth_clients.client_id``
    # is a UUIDv4 primary key (globally unique), so this is equivalent to
    # binding to tenant_key without a second round-trip. The existing
    # explicit client_id guard below stays as the second layer.
    # BE6004C-5: public, pre-auth /refresh call -- no tenant context exists;
    # the refresh row carries the server-authoritative tenant_key. Scope the
    # resolve-from-row lookup with an audited bypass; everything AFTER the row
    # is resolved runs tenant-scoped under _refresh_grant_after_lookup().
    with tenant_isolation_bypass(
        db,
        reason="oauth /refresh: resolve refresh token before tenant is known",
        models=(OAuthRefreshToken,),
    ):
        row_result = await db.execute(
            select(OAuthRefreshToken).where(
                OAuthRefreshToken.token_hash == token_hash,
                OAuthRefreshToken.client_id == client_id,
            )
        )
        row = row_result.scalar_one_or_none()

    if row is None:
        # Unknown token. Don't leak whether it's the wrong client/tenant
        # vs. a never-issued value — invalid_grant for both.
        raise ValueError("invalid_grant: refresh_token not found")

    if row.client_id != client_id:
        raise ValueError("invalid_grant: refresh_token does not belong to this client")

    # The row's tenant_key is now authoritative; the remainder (client verify,
    # reuse-detection family revoke, User read, rotation INSERT) runs scoped.
    with tenant_session_context(db, row.tenant_key):
        return await _refresh_grant_after_lookup(
            service=service,
            db=db,
            row=row,
            token_hash=token_hash,
            client_id=client_id,
            client_secret=client_secret,
            access_token_lifetime_seconds=access_token_lifetime_seconds,
            refresh_token_lifetime_seconds=refresh_token_lifetime_seconds,
        )


async def _refresh_grant_after_lookup(
    *,
    service: OAuthService,
    db: AsyncSession,
    row: OAuthRefreshToken,
    token_hash: str,
    client_id: str,
    client_secret: str | None,
    access_token_lifetime_seconds: int,
    refresh_token_lifetime_seconds: int,
) -> dict:
    """Post-lookup refresh-grant flow, run under the row's tenant context.

    Split out of :func:`refresh_token_grant` so the resolve-from-row lookup can
    run under a scoped ``tenant_isolation_bypass`` while everything that follows
    (which touches tenant-scoped ``OAuthRefreshToken``/``User`` rows) runs
    tenant-SCOPED via ``tenant_session_context(row.tenant_key)`` (BE6004C-5).
    """
    resolved = await service._verify_client_authentication(
        client_id=client_id,
        tenant_key=row.tenant_key,
        client_secret=client_secret,
    )

    # BE-6161: public PKCE clients are now first-class at /refresh. They hold no
    # secret — possession of the one-time-use rotating refresh token IS the
    # proof-of-possession (RFC 8252 / OAuth 2.1 §4.3.1), and the rotation +
    # family reuse-detection below is what bounds the risk. _verify_client_
    # authentication has already enforced the matching auth shape: a public
    # client (client_secret_hash is None) MUST NOT present a secret, a
    # confidential client MUST present a verifying one. Either way the resolved
    # client is the legitimate holder, so the grant proceeds for both.
    now = datetime.now(UTC)

    # API-0021l: idempotency-window cache check. Concurrent retries of the
    # SAME refresh_token from the SAME confidential client must yield the
    # SAME rotated pair, otherwise the second call would either rotate
    # twice (issuing two access_tokens, leaving one orphaned) or trip the
    # reuse-detection alarm and revoke the entire family. The cache hit
    # path SUPPRESSES the reuse-detection alarm by short-circuiting before
    # the ``row.revoked`` branch — that's intentional: in-window retries
    # are not malicious replays. Mismatched signature falls through to
    # existing reuse-detection unchanged.
    refresh_idem_signature = _compute_refresh_body_signature(
        client_id=client_id,
        client_secret_hash=resolved.client_secret_hash,
        refresh_token_hash=token_hash,
    )
    cached = await _refresh_idempotency_cache_get(row.tenant_key, token_hash)
    if cached is not None and hmac.compare_digest(cached.body_signature, refresh_idem_signature):
        logger.info(
            "oauth_refresh_idempotency_hit family_id=%s tenant=%s",
            row.family_id,
            row.tenant_key[:12] if row.tenant_key else "",
        )
        return dict(cached.response_body)

    # SEC-9217b: serialize this grant against a concurrent session invalidation
    # (force-logout / password change / deactivation via evict_user_tokens). Those
    # paths take a user-first SELECT ... FOR UPDATE on the owning User row; take
    # the SAME lock here, in the SAME order, so the two cannot interleave. The
    # reuse-detection gate below reads `row.revoked`, which was cached at the
    # initial UNLOCKED lookup (a TOCTOU window widened by the bcrypt client-secret
    # verify above) -- re-read it FRESH under the lock so a revoke that committed
    # in that window is seen. If the invalidation instead lands AFTER this grant,
    # it blocks on the lock until this commits, then revokes the freshly minted
    # row and out-epochs the freshly minted access token. Either order is safe.
    user_result = await db.execute(
        select(User).where(User.id == row.user_id, User.tenant_key == row.tenant_key).with_for_update()
    )
    user = user_result.scalar_one_or_none()
    await db.refresh(row, attribute_names=["revoked"])

    if row.revoked:
        # SEC-9227e (M5): before treating this as reuse, re-check the idempotency
        # cache UNDER the lock (bounded retry). A truly concurrent honest retry
        # loses the lock race to its twin and only now sees revoked=True; if the
        # winner's response is cached under OUR signature, this is convergence —
        # return the winner's pair instead of revoking the family the winner
        # just extended. See _converged_pair_under_lock for why the wait exists
        # (the winner's commit->cache-put gap) and why a signature-matched HIT
        # is provably the same client, not an attacker.
        converged = await _converged_pair_under_lock(
            tenant_key=row.tenant_key,
            token_hash=token_hash,
            body_signature=refresh_idem_signature,
        )
        if converged is not None:
            logger.info(
                "oauth_refresh_concurrent_converged family_id=%s tenant=%s",
                row.family_id,
                row.tenant_key[:12] if row.tenant_key else "",
            )
            return dict(converged.response_body)
        # MISS after the bounded retry (or signature mismatch): genuine replay.
        # Everything below is the unchanged museum-rule path — family revocation,
        # epoch bump, durable commit, attack telemetry.
        revoked_count = await revoke_family(db, family_id=row.family_id, tenant_key=row.tenant_key)
        # SEC-9227c (H3): bump the epoch so access JWTs already derived from this
        # reused family are rejected at principal.py — but ONLY if this reuse
        # revoked LIVE rows (a live sibling of the replayed token). The User is
        # already locked FOR UPDATE above (user-first order). Gating avoids
        # re-bumping when the family was already fully revoked (e.g. a
        # password-reset eviction), which would kill the user's fresh tokens.
        bump_epoch_if_revoked(user, revoked_count)
        # Commit BEFORE raising. The router maps ValueError to an
        # HTTPException, which FastAPI surfaces as GeneratorExit through
        # the session context manager — that path rolls back. Without
        # this explicit commit the family revocation (and the epoch bump)
        # would be lost and a sibling token in the family could keep
        # refreshing. RFC 6749 §10.4 reuse detection MUST be durable.
        await db.commit()
        logger.warning(
            "oauth_refresh_token_reuse_detected family_id=%s tenant=%s revoked_rows=%d",
            row.family_id,
            row.tenant_key[:12] if row.tenant_key else "",
            revoked_count,
        )
        raise ValueError("invalid_grant: refresh_token reuse detected; family revoked")

    if row.expires_at < now:
        raise ValueError("invalid_grant: refresh_token has expired")

    # SEC-3001a item 1 (deactivation propagation): the refresh grant must enforce
    # is_active, not merely existence. An offboarded user keeps a live refresh
    # token; without this filter they would rotate it into fresh access+refresh
    # pairs until the row's expiry. Mirrors the dashboard /api/auth/refresh gate
    # (api/endpoints/auth/session.py) and the REST dependency is_active check.
    # (SEC-9217b: evaluated on the User row already locked FOR UPDATE above.)
    if user is None or not user.is_active:
        raise ValueError("invalid_grant: user no longer active")

    # Rotation: revoke the prior token, mint a new pair in the same family.
    row.revoked = True
    await db.flush()

    new_access = JWTManager.create_access_token(
        user_id=UUID(user.id),
        username=user.username,
        role=user.role,
        tenant_key=user.tenant_key,
        audience=row.aud or None,
        scope=row.scope,
        revocation_epoch=user.token_revocation_epoch or 0,
    )
    new_refresh = await issue_refresh_token(
        db,
        family_id=row.family_id,
        client_id=row.client_id,
        tenant_key=row.tenant_key,
        user_id=row.user_id,
        scope=row.scope,
        aud=row.aud,
        lifetime_seconds=refresh_token_lifetime_seconds,
    )

    logger.info(
        "oauth_refresh_token_rotated family_id=%s tenant=%s user_id=%s",
        row.family_id,
        row.tenant_key[:12] if row.tenant_key else "",
        row.user_id,
    )

    response: dict = {
        "access_token": new_access,
        "token_type": "bearer",
        "expires_in": access_token_lifetime_seconds,
        "refresh_token": new_refresh,
        "refresh_expires_in": refresh_token_lifetime_seconds,
    }

    # SEC-9227e (M2b): commit BEFORE the cache-put so the cache can never serve
    # a pair whose refresh row did not persist. Pre-fix, the put ran inside the
    # still-open transaction (the router's get_db_session dependency commits
    # only after the endpoint returns); a rollback after this point — a later
    # pipeline exception, a dropped connection — left the cache holding a
    # phantom pair, and an in-window retry receiving it was hard-logged-out at
    # its next refresh (row unknown to the DB). Mirrors the reuse-detection
    # branch above, which already explicitly commits for exactly this
    # durability reason; the dependency's own later commit becomes a no-op.
    # This also releases the user FOR UPDATE lock, which is what opens the
    # commit->cache-put gap the M5 under-lock retry waits out.
    await db.commit()

    # API-0021l: cache the rotated pair so a concurrent retry inside the
    # window receives the SAME pair instead of triggering a second rotation
    # (which would either orphan an access_token or trip reuse-detection
    # and revoke the family).
    await _refresh_idempotency_cache_put(
        row.tenant_key,
        token_hash,
        _RefreshIdempotencyEntry(
            response_body=dict(response),
            body_signature=refresh_idem_signature,
        ),
    )

    return response
