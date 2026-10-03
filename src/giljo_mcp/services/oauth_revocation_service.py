# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import hashlib
import logging
import time
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from fastapi import HTTPException
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from giljo_mcp.auth.jwt_manager import JWTAudienceMismatchError, JWTManager
from giljo_mcp.database import tenant_isolation_bypass, tenant_session_context
from giljo_mcp.models.oauth import OAuthRefreshToken, OAuthRevokedToken


if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


logger = logging.getLogger(__name__)


TOKEN_TYPE_ACCESS = "access_token"
TOKEN_TYPE_REFRESH = "refresh_token"

TOKEN_TYPE_ACCESS_ROTATED = "access_token_rotated"
ROTATION_GRACE_SECONDS = 30

REVOCATION_CACHE_TTL_POSITIVE = 60.0
REVOCATION_CACHE_TTL_NEGATIVE = 5.0
_REVOCATION_CACHE_MAX_ENTRIES = 4096

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
        try:
            oldest_key = next(iter(_revocation_cache))
            _revocation_cache.pop(oldest_key, None)
        except StopIteration:
            pass
    ttl = REVOCATION_CACHE_TTL_POSITIVE if is_revoked else REVOCATION_CACHE_TTL_NEGATIVE
    _revocation_cache[(tenant_key, jti)] = (is_revoked, time.monotonic() + ttl)


def clear_revocation_cache() -> None:
    _revocation_cache.clear()


def _row_is_effective_revocation(row) -> bool:
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
    cached = _cache_get(tenant_key, jti)
    if cached is not None:
        return cached

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
    try:
        payload = JWTManager.verify_token(token)
    except JWTAudienceMismatchError:
        return False
    except HTTPException as exc:
        if exc.status_code >= 500:
            raise
        return False

    return await _persist_access_jti_revocation(db_session, payload)


async def _persist_access_jti_revocation(db_session: AsyncSession, payload: dict) -> bool:
    jti = payload.get("jti")
    tenant_key = payload.get("tenant_key")
    if not jti or not tenant_key:
        return False

    with tenant_isolation_bypass(
        db_session,
        reason="oauth revoke: global jti uniqueness probe precedes tenant scoping",
        models=(OAuthRevokedToken,),
    ):
        existing = await db_session.execute(select(OAuthRevokedToken.token_type).where(OAuthRevokedToken.jti == jti))
    existing_type = existing.scalar_one_or_none()
    if existing_type is not None:
        if existing_type == TOKEN_TYPE_ACCESS_ROTATED:
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
    token_hash = _sha256_hex(token)
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
    if not token:
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

    logger.debug("Revoke request for unknown/foreign token (idempotent 200)")
