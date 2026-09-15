# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

from fastapi import HTTPException
from sqlalchemy import func, or_, select

from giljo_mcp.api_key_utils import get_key_prefix, verify_api_key_cached
from giljo_mcp.auth.jwt_manager import JWTAudienceMismatchError, JWTManager
from giljo_mcp.database import tenant_isolation_bypass
from giljo_mcp.models import APIKey, User
from giljo_mcp.services.oauth_revocation_service import is_access_token_jti_revoked


if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


logger = logging.getLogger(__name__)


class AuthErrorReason(StrEnum):

    INVALID_TOKEN = "invalid_token"
    EXPIRED = "expired"
    NO_TENANT = "no_tenant"
    INVALID_AUDIENCE = "invalid_audience"
    REVOKED = "revoked"
    INACTIVE = "inactive"
    INVALID_CREDENTIALS = "invalid_credentials"


JWT_FALLBACK_REASONS = frozenset({AuthErrorReason.INVALID_TOKEN, AuthErrorReason.EXPIRED, AuthErrorReason.NO_TENANT})


class PrincipalValidationError(Exception):

    def __init__(self, reason: AuthErrorReason, detail: str = "") -> None:
        self.reason = reason
        self.detail = detail or reason.value
        super().__init__(self.detail)


@dataclass(frozen=True)
class Principal:

    user_id: str
    tenant_key: str
    auth_method: str
    user: User
    username: str | None = None
    role: str | None = None
    scopes: list[str] | None = None
    api_key_id: str | None = None
    exp: int | None = None
    jti: str | None = None


async def _resolve_api_key(db: AsyncSession, api_key: str) -> tuple[APIKey, User] | None:
    key_prefix = get_key_prefix(api_key)
    stmt = select(APIKey).where(
        APIKey.is_active,
        APIKey.key_prefix == key_prefix,
        or_(APIKey.expires_at > func.now(), APIKey.expires_at.is_(None)),
    )
    with tenant_isolation_bypass(
        db,
        reason="api key prefix lookup resolves tenant before authentication",
        models=(APIKey,),
    ):
        result = await db.execute(stmt)
    candidates = result.scalars().all()

    for key_record in candidates:
        if await verify_api_key_cached(
            api_key,
            key_record.key_hash,
            key_id=key_record.id,
            expires_at=key_record.expires_at,
        ):
            db.info["tenant_key"] = key_record.tenant_key
            user = (
                await db.execute(
                    select(User).where(
                        User.id == key_record.user_id,
                        User.is_active,
                        User.tenant_key == key_record.tenant_key,
                    )
                )
            ).scalar_one_or_none()
            if user is not None:
                return key_record, user
            logger.warning("API key valid but user inactive or tenant mismatch: user_id=%s", key_record.user_id)
            return None

    return None


async def _validate_jwt(
    db: AsyncSession,
    token: str,
    *,
    expected_audience: str | None,
    prefetched_user: User | None,
) -> Principal:
    try:
        payload = JWTManager.verify_token(token, expected_audience=expected_audience)
    except JWTAudienceMismatchError as exc:
        raise PrincipalValidationError(AuthErrorReason.INVALID_AUDIENCE, str(exc)) from exc
    except HTTPException as exc:
        reason = (
            AuthErrorReason.EXPIRED
            if isinstance(exc.detail, str) and "expired" in exc.detail.lower()
            else AuthErrorReason.INVALID_TOKEN
        )
        raise PrincipalValidationError(reason, str(exc.detail)) from exc

    user_id = payload.get("sub")
    tenant_key = payload.get("tenant_key")
    if not user_id or not tenant_key:
        raise PrincipalValidationError(AuthErrorReason.NO_TENANT, "JWT missing sub/tenant_key")

    db.info["tenant_key"] = tenant_key

    jti = payload.get("jti")
    if jti and await is_access_token_jti_revoked(db, tenant_key=tenant_key, jti=jti):
        raise PrincipalValidationError(AuthErrorReason.REVOKED, "Token revoked")

    user = await _reuse_prefetched_user(db, prefetched_user, user_id=user_id, tenant_key=tenant_key)
    if user is None:
        user = (
            await db.execute(
                select(User).where(
                    User.id == user_id,
                    User.tenant_key == tenant_key,
                    User.is_active,
                )
            )
        ).scalar_one_or_none()
    if user is None:
        raise PrincipalValidationError(AuthErrorReason.INACTIVE, "User not found or inactive")

    try:
        token_epoch = int(payload.get("rev", 0) or 0)
    except (TypeError, ValueError):
        token_epoch = 0
    if (user.token_revocation_epoch or 0) > token_epoch:
        raise PrincipalValidationError(AuthErrorReason.REVOKED, "Token revoked (forced logout)")

    raw_scope = payload.get("scope")
    scopes = [s for s in str(raw_scope).split() if s] if raw_scope is not None else None

    return Principal(
        user_id=str(user_id),
        tenant_key=tenant_key,
        auth_method="jwt",
        user=user,
        username=payload.get("username") or user.username,
        role=payload.get("role") or user.role,
        scopes=scopes,
        exp=payload.get("exp"),
        jti=jti,
    )


async def _reuse_prefetched_user(
    db: AsyncSession,
    prefetched_user: User | None,
    *,
    user_id: str,
    tenant_key: str,
) -> User | None:
    if prefetched_user is None:
        return None
    if not getattr(prefetched_user, "is_active", False):
        return None
    if str(getattr(prefetched_user, "id", "")) != str(user_id):
        return None
    if getattr(prefetched_user, "tenant_key", None) != tenant_key:
        return None
    return await db.merge(prefetched_user, load=False)


async def validate_principal(
    db: AsyncSession,
    *,
    jwt_token: str | None = None,
    api_key: str | None = None,
    expected_audience: str | None = None,
    prefetched_user: User | None = None,
) -> Principal:
    if jwt_token:
        return await _validate_jwt(db, jwt_token, expected_audience=expected_audience, prefetched_user=prefetched_user)

    if api_key:
        resolved = await _resolve_api_key(db, api_key)
        if resolved is None:
            raise PrincipalValidationError(AuthErrorReason.INVALID_CREDENTIALS, "Invalid API key")
        key_record, user = resolved
        return Principal(
            user_id=str(user.id),
            tenant_key=user.tenant_key,
            auth_method="api_key",
            user=user,
            username=user.username,
            role=user.role,
            api_key_id=str(key_record.id),
        )

    raise PrincipalValidationError(AuthErrorReason.INVALID_CREDENTIALS, "No credentials supplied")
