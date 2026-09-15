# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


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

OAUTH_REFRESH_IDEMPOTENCY_WINDOW_SECONDS = int(os.environ.get("OAUTH_REFRESH_IDEMPOTENCY_WINDOW_SECONDS", "5"))
_REFRESH_IDEMPOTENCY_FIELD_SEP = b"\x1f"

_CONVERGE_RECHECK_ATTEMPTS = 5
_CONVERGE_RECHECK_SLEEP_SECONDS = 0.05


@dataclass(frozen=True)
class _RefreshIdempotencyEntry:
    response_body: dict
    body_signature: str


def _serialize_refresh_entry(entry: _RefreshIdempotencyEntry) -> str:
    return encrypt_payload(
        json.dumps(
            {
                "response_body": entry.response_body,
                "body_signature": entry.body_signature,
            }
        )
    )


def _deserialize_refresh_entry(raw: str) -> _RefreshIdempotencyEntry | None:
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
    for attempt in range(_CONVERGE_RECHECK_ATTEMPTS):
        cached = await _refresh_idempotency_cache_get(tenant_key, token_hash)
        if cached is not None:
            if hmac.compare_digest(cached.body_signature, body_signature):
                return cached
            return None
        if attempt < _CONVERGE_RECHECK_ATTEMPTS - 1:
            await asyncio.sleep(_CONVERGE_RECHECK_SLEEP_SECONDS)
    return None


def hash_refresh_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def hash_authorization_code(code: str) -> str:
    return hashlib.sha256(code.encode("utf-8")).hexdigest()


def new_family_id() -> str:
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
    return (
        await session.execute(select(User).where(User.id == user_id, User.tenant_key == tenant_key).with_for_update())
    ).scalar_one_or_none()


def bump_epoch_if_revoked(user: User | None, revoked_rows: int) -> bool:
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
    if not refresh_token:
        raise ValueError("invalid_request: refresh_token is required")

    db = service._db
    token_hash = hash_refresh_token(refresh_token)
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
        raise ValueError("invalid_grant: refresh_token not found")

    if row.client_id != client_id:
        raise ValueError("invalid_grant: refresh_token does not belong to this client")

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
    resolved = await service._verify_client_authentication(
        client_id=client_id,
        tenant_key=row.tenant_key,
        client_secret=client_secret,
    )

    now = datetime.now(UTC)

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

    user_result = await db.execute(
        select(User).where(User.id == row.user_id, User.tenant_key == row.tenant_key).with_for_update()
    )
    user = user_result.scalar_one_or_none()
    await db.refresh(row, attribute_names=["revoked"])

    if row.revoked:
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
        revoked_count = await revoke_family(db, family_id=row.family_id, tenant_key=row.tenant_key)
        bump_epoch_if_revoked(user, revoked_count)
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

    if user is None or not user.is_active:
        raise ValueError("invalid_grant: user no longer active")

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

    await db.commit()

    await _refresh_idempotency_cache_put(
        row.tenant_key,
        token_hash,
        _RefreshIdempotencyEntry(
            response_body=dict(response),
            body_signature=refresh_idem_signature,
        ),
    )

    return response
