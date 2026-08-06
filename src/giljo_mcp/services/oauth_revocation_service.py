# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""RFC 7009 OAuth Token Revocation (API-0022).

Split out of ``oauth_service`` to keep that file under the 800-line
guardrail. The revocation surface has two seams:

1. Write side -- :func:`revoke_token` is called from the /oauth/revoke
   endpoint. It accepts the presented token (access or refresh), extracts
   the lookup key (``jti`` for access JWTs, sha256 hex for refresh tokens),
   and persists a row in ``oauth_revoked_tokens``. For refresh tokens it
   additionally flips ``revoked=true`` on the entire family in
   ``oauth_refresh_tokens`` (RFC 6749 §10.4).

2. Read side -- :func:`is_access_token_jti_revoked` is called from
   :class:`MCPAuthMiddleware` on every Bearer JWT. A short-lived in-process
   TTL cache (default 60s) sits in front of the DB lookup to keep the
   hot path cheap. Cache misses fall through to the DB and populate the
   cache. Tenant isolation: the cache key is ``(tenant_key, jti)`` so a
   revoked jti in tenant A cannot poison tenant B.

The endpoint is idempotent per RFC 7009 §2.2 -- garbage in, 200 OK out.
This module surfaces ValueError only for genuine internal contract
violations (e.g. missing tenant_key on a verified JWT, which would be a
JWTManager bug). Endpoint-layer callers should treat ValueError as a 500.
"""

from __future__ import annotations

import hashlib
import logging
import time
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from giljo_mcp.auth.jwt_manager import JWTManager
from giljo_mcp.database import tenant_isolation_bypass, tenant_session_context
from giljo_mcp.models.oauth import OAuthRefreshToken, OAuthRevokedToken


if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


logger = logging.getLogger(__name__)


TOKEN_TYPE_ACCESS = "access_token"
TOKEN_TYPE_REFRESH = "refresh_token"

# TSK-9005: dashboard access-token jti rotation on refresh. A rotation writes a
# revocation-ledger row of THIS distinct type for the PRIOR jti, so the stolen
# cookie cannot be silently refreshed into a fresh 24h token indefinitely past
# revocation. Unlike logout / force-logout (immediate), a rotation row is
# honored for a short overlap window -- ROTATION_GRACE_SECONDS -- during which
# the prior jti is STILL valid, so an in-flight request or a concurrent second
# /refresh racing the rotation is never spuriously 401'd. After the window the
# prior jti is dead. The window comfortably covers in-flight request latency +
# a concurrent-refresh round trip + minor DB/app clock skew; the stolen-cookie
# exposure after the legit user's next refresh shrinks from "indefinite" to
# ~this window (+ the <=5s negative-cache lag).
TOKEN_TYPE_ACCESS_ROTATED = "access_token_rotated"
ROTATION_GRACE_SECONDS = 30

# Hot-path cache: positive entries (jti IS revoked) live REVOCATION_CACHE_TTL
# seconds before the next DB confirmation. Negative entries (jti NOT
# revoked) live a much shorter window so a freshly-revoked token surfaces
# at the resource server quickly. The mission cites <60s; we keep
# positives at 60s and negatives at 5s.
REVOCATION_CACHE_TTL_POSITIVE = 60.0
REVOCATION_CACHE_TTL_NEGATIVE = 5.0
_REVOCATION_CACHE_MAX_ENTRIES = 4096

# Cache: (tenant_key, jti) -> (is_revoked: bool, expires_at_monotonic: float)
_revocation_cache: dict[tuple[str, str], tuple[bool, float]] = {}


def _cache_get(tenant_key: str, jti: str) -> bool | None:
    entry = _revocation_cache.get((tenant_key, jti))
    if entry is None:
        return None
    is_revoked, expires_at = entry
    if time.monotonic() >= expires_at:
        _revocation_cache.pop((tenant_key, jti), None)
        return None
    return is_revoked


def _cache_put(tenant_key: str, jti: str, *, is_revoked: bool) -> None:
    if len(_revocation_cache) >= _REVOCATION_CACHE_MAX_ENTRIES:
        # Cheap FIFO-ish eviction: drop the oldest insertion.
        try:
            oldest_key = next(iter(_revocation_cache))
            _revocation_cache.pop(oldest_key, None)
        except StopIteration:
            pass
    ttl = REVOCATION_CACHE_TTL_POSITIVE if is_revoked else REVOCATION_CACHE_TTL_NEGATIVE
    _revocation_cache[(tenant_key, jti)] = (is_revoked, time.monotonic() + ttl)


def clear_revocation_cache() -> None:
    """Test helper: wipe the in-process revocation cache."""
    _revocation_cache.clear()


def _row_is_effective_revocation(row) -> bool:
    """Decide whether a revocation-ledger row means "this token is dead NOW".

    Immediate revocations (logout / RFC 7009 / refresh-family) are effective the
    instant the row exists. A TSK-9005 rotation row is grace-windowed: it is
    effective only once ``ROTATION_GRACE_SECONDS`` have elapsed since
    ``revoked_at`` -- the overlap that keeps an in-flight request or a concurrent
    refresh racing the rotation from being spuriously 401'd. ``revoked_at`` is
    NOT NULL in the schema; the None guard is defensive only.
    """
    if row is None:
        return False
    token_type, revoked_at = row
    if token_type != TOKEN_TYPE_ACCESS_ROTATED:
        return True
    if revoked_at is None:
        return True
    return datetime.now(UTC) >= revoked_at + timedelta(seconds=ROTATION_GRACE_SECONDS)


async def is_access_token_jti_revoked(
    db_session: AsyncSession,
    *,
    tenant_key: str,
    jti: str,
) -> bool:
    """Return True iff the access-token jti has been revoked in this tenant.

    Hot path: in-process TTL cache in front of a DB lookup. Tenant-scoped
    cache key prevents cross-tenant poisoning. A grace-windowed TSK-9005
    rotation row reads as NOT revoked until its window elapses (see
    :func:`_row_is_effective_revocation`); the short negative-cache TTL bounds
    how long past the window a stale "not revoked" verdict can linger.
    """
    cached = _cache_get(tenant_key, jti)
    if cached is not None:
        return cached

    # BE6004C-5: tenant_key is a required argument, so this hot-path read is
    # self-sufficient -- scope the session to it rather than depending on the
    # caller having pre-stamped tenant context (the MCP middleware sets the
    # ContextVar; the dashboard dependency stamps session.info; a direct
    # caller may do neither). The explicit tenant predicate then matches the
    # scoped context cleanly.
    with tenant_session_context(db_session, tenant_key):
        result = await db_session.execute(
            select(OAuthRevokedToken.token_type, OAuthRevokedToken.revoked_at).where(
                OAuthRevokedToken.jti == jti,
                OAuthRevokedToken.tenant_key == tenant_key,
            )
        )
    is_revoked = _row_is_effective_revocation(result.first())
    _cache_put(tenant_key, jti, is_revoked=is_revoked)
    return is_revoked


def _sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


async def _revoke_access_jwt(
    db_session: AsyncSession,
    *,
    token: str,
) -> bool:
    """Attempt to revoke ``token`` as a signed access JWT. Returns True on success."""
    try:
        # No expected_audience: revocation is identity by signature + jti, not by aud.
        payload = JWTManager.verify_token(token)
    except Exception:  # noqa: BLE001 -- RFC 7009: never leak token validity
        return False

    return await _persist_access_jti_revocation(db_session, payload)


async def _persist_access_jti_revocation(db_session: AsyncSession, payload: dict) -> bool:
    """Insert the ``OAuthRevokedToken`` row for a verified access-JWT payload.

    Shared by the RFC 7009 strict-verify path (:func:`_revoke_access_jwt`) and
    the dashboard logout path (:func:`revoke_dashboard_access_jwt`), so there is
    exactly one write path for access-token revocation. Returns True when a row
    exists or was inserted; False when the payload lacks the jti/tenant_key
    needed to persist (pre-API-0022 tokens).
    """
    jti = payload.get("jti")
    tenant_key = payload.get("tenant_key")
    if not jti or not tenant_key:
        # Pre-API-0022 tokens lacked jti. Best-effort: nothing to revoke server-side;
        # token will roll off when it expires. Returning False keeps the endpoint
        # idempotent at the HTTP layer (still 200 OK) without persisting a row we
        # could never match against.
        return False

    # BE6004C-5: the jti is a globally-unique identifier, so the existence
    # probe is intentionally cross-tenant (any tenant having revoked this jti
    # is a duplicate). Scope it with an audited bypass; the INSERT below runs
    # tenant-scoped under the payload's tenant_key.
    with tenant_isolation_bypass(
        db_session,
        reason="oauth revoke: global jti uniqueness probe precedes tenant scoping",
        models=(OAuthRevokedToken,),
    ):
        existing = await db_session.execute(select(OAuthRevokedToken.token_type).where(OAuthRevokedToken.jti == jti))
    existing_type = existing.scalar_one_or_none()
    if existing_type is not None:
        if existing_type == TOKEN_TYPE_ACCESS_ROTATED:
            # TSK-9005: an explicit logout / RFC 7009 revoke must be IMMEDIATE and
            # must not be softened by a rotation overlap that happens to already
            # cover this jti. Collapse the grace by upgrading the rotation row to
            # an immediate access-token revocation (and prime the cache), so the
            # very next validation refuses the token instead of honoring the
            # remaining rotation window.
            with tenant_session_context(db_session, tenant_key):
                await db_session.execute(
                    update(OAuthRevokedToken)
                    .where(
                        OAuthRevokedToken.jti == jti,
                        OAuthRevokedToken.tenant_key == tenant_key,
                    )
                    .values(token_type=TOKEN_TYPE_ACCESS, revoked_at=datetime.now(UTC))
                )
                await db_session.flush()
            _cache_put(tenant_key, jti, is_revoked=True)
        return True

    with tenant_session_context(db_session, tenant_key):
        db_session.add(
            OAuthRevokedToken(
                jti=jti,
                token_type=TOKEN_TYPE_ACCESS,
                tenant_key=tenant_key,
            )
        )
        await db_session.flush()
    _cache_put(tenant_key, jti, is_revoked=True)
    return True


async def revoke_dashboard_access_jwt(db_session: AsyncSession, *, token: str) -> bool:
    """Revoke a dashboard cookie/Bearer access JWT, accepting expired-in-grace.

    SEC-6001 logout path. Unlike :func:`revoke_token` (RFC 7009, strict
    ``verify_token``), this accepts a token expired within the JWT grace window
    via ``verify_token_allow_expired`` so a session whose access token is on the
    edge of expiry still gets a revocation row written — otherwise a token that
    expired seconds before logout could be replayed during its refresh-grace
    window. Reuses the single :func:`_persist_access_jti_revocation` write path.

    Idempotent: returns True if a row was written or already existed, False if
    the token is unverifiable or lacks jti/tenant_key (nothing to persist).
    """
    payload = JWTManager.verify_token_allow_expired(token)
    if payload is None:
        return False
    return await _persist_access_jti_revocation(db_session, payload)


async def rotate_access_token_jti(
    db_session: AsyncSession,
    *,
    tenant_key: str,
    jti: str,
) -> None:
    """Grace-revoke the PRIOR access-token jti on dashboard refresh (TSK-9005).

    Writes a ``TOKEN_TYPE_ACCESS_ROTATED`` ledger row for ``jti`` so the
    just-superseded cookie cannot be silently refreshed into a fresh 24h token
    indefinitely past revocation (stolen-cookie containment). The row is
    honored for ``ROTATION_GRACE_SECONDS`` (see
    :func:`_row_is_effective_revocation`) so an in-flight request or a
    concurrent second /refresh racing the rotation is NOT spuriously 401'd.

    Race-safe + idempotent: a concurrent rotation of the same jti no-ops via
    ``ON CONFLICT DO NOTHING`` (no IntegrityError to poison the session), and
    the grace is measured from the FIRST rotation's ``revoked_at``. Does NOT
    populate the positive cache -- the row is grace-delayed, so the next read
    computes effectiveness from ``revoked_at`` rather than trusting a premature
    "revoked" verdict. Callers pass a jti that has already cleared the
    revocation gate; a missing jti/tenant_key (pre-API-0022 token) no-ops.
    """
    if not jti or not tenant_key:
        return
    with tenant_session_context(db_session, tenant_key):
        await db_session.execute(
            pg_insert(OAuthRevokedToken)
            .values(
                jti=jti,
                token_type=TOKEN_TYPE_ACCESS_ROTATED,
                tenant_key=tenant_key,
                revoked_at=datetime.now(UTC),
            )
            .on_conflict_do_nothing(index_elements=["jti"])
        )
        await db_session.flush()


async def _revoke_refresh_token_family(
    db_session: AsyncSession,
    *,
    token: str,
) -> bool:
    """Revoke ``token`` as a raw refresh token; flips the whole family.

    Per RFC 6749 §10.4 and OAuth 2.1 Security BCP, revoking any refresh
    token revokes the entire family derived from the same initial grant.
    """
    token_hash = _sha256_hex(token)
    # BE6004C-5: token_hash is globally unique; the row carries the
    # authoritative tenant_key, which is unknown before this lookup. Scope the
    # resolve-from-row read with an audited bypass; the family-revoke UPDATE
    # below runs tenant-scoped under that resolved tenant_key.
    with tenant_isolation_bypass(
        db_session,
        reason="oauth revoke: resolve refresh-token family before tenant is known",
        models=(OAuthRefreshToken,),
    ):
        row = await db_session.execute(
            select(
                OAuthRefreshToken.family_id,
                OAuthRefreshToken.tenant_key,
                OAuthRefreshToken.user_id,
            ).where(OAuthRefreshToken.token_hash == token_hash)
        )
        found = row.first()
    if found is None:
        return False

    family_id, tenant_key, user_id = found.family_id, found.tenant_key, found.user_id
    with tenant_session_context(db_session, tenant_key):
        # SEC-9227c (H3): user-first lock (SEC-9217b lock order), revoke the family,
        # then bump the epoch iff LIVE rows were actually revoked — so the access
        # JWTs derived from this family die too (principal.py `rev` check), the
        # enforcement half a `revoked` flip alone lacks. Gating keeps RFC 7009's
        # idempotency: a repeat /revoke of an already-dead token does not re-bump
        # and spuriously invalidate the user's fresh tokens.
        from giljo_mcp.services.oauth_refresh_service import (
            bump_epoch_if_revoked,
            lock_user_for_update,
            revoke_family,
        )

        user = await lock_user_for_update(db_session, user_id=user_id, tenant_key=tenant_key)
        revoked = await revoke_family(db_session, family_id=family_id, tenant_key=tenant_key)
        bump_epoch_if_revoked(user, revoked)
        await db_session.flush()
    logger.info(
        "Revoked refresh-token family: family_id=%s tenant_key=%s",
        family_id,
        tenant_key,
    )
    return True


async def revoke_token(
    db_session: AsyncSession,
    *,
    token: str,
    token_type_hint: str | None = None,
) -> None:
    """RFC 7009 token revocation entry point.

    Idempotent: ALWAYS returns None. Garbage input, already-revoked tokens,
    foreign tokens, and unknown formats all complete without raising. The
    only outward signal of success is "no exception."

    Behavior:
      - ``token_type_hint == 'refresh_token'`` -- try refresh first, then access.
      - ``token_type_hint == 'access_token'`` (or unset) -- try access first,
        then refresh.
      - Either way, the first match wins; a token can only be one type.
    """
    if not token:
        # Empty body still 200 OK per spec; nothing to do.
        return

    order: tuple[str, ...]
    if token_type_hint == TOKEN_TYPE_REFRESH:
        order = (TOKEN_TYPE_REFRESH, TOKEN_TYPE_ACCESS)
    else:
        order = (TOKEN_TYPE_ACCESS, TOKEN_TYPE_REFRESH)

    for token_type in order:
        if token_type == TOKEN_TYPE_ACCESS:
            if await _revoke_access_jwt(db_session, token=token):
                return
        elif await _revoke_refresh_token_family(db_session, token=token):
            return

    # No match in either type. RFC 7009 §2.2: still 200 OK; do not leak.
    logger.debug("Revoke request for unknown/foreign token (idempotent 200)")
