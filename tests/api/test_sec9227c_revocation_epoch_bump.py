# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""SEC-9227c (H3) — revoking a refresh family bumps token_revocation_epoch so the
derived access JWTs die too.

H3 (verified): `_revoke_refresh_token_family` (RFC 7009 /revoke), the /refresh
reuse-detection branch, and the /token code-reuse path all flipped `revoked=true`
on refresh rows but NEVER bumped `users.token_revocation_epoch`. So a user who
revoked a stolen refresh token left the holder's ALREADY-minted access JWTs valid
until exp — up to 24h (access-token lifetime is unchanged here; M1 is deferred),
which is exactly why the epoch bump is the real fix and M1 only narrows the
window. The enforcement half already existed (`principal.py` rejects any JWT whose
`rev` claim is below the user's live epoch, on the single `_validate_jwt` pipeline
that both cookie AND /mcp Bearer auth flow through) — it was simply never invoked
from the revocation paths.

Fix: `lock_user_for_update` (user-first FOR UPDATE) + `bump_epoch_if_revoked`
(increment ONLY when a revoke revoked live rows), called from all three
revocation sites. The gate keeps RFC 7009 idempotent and stops a reuse of an
already-dead family (e.g. after a password-reset eviction) from re-bumping and
killing the user's fresh re-login tokens.

Failing layer for the mandatory test: the /mcp Bearer enforcement boundary
(`validate_principal` with an MCP audience) — a previously-valid access JWT is
rejected after the refresh token is revoked. Parallel-safe: unique tenant/user per
test, committed seed rows, monkeypatch-only, no shared mutable state.
"""

from __future__ import annotations

import secrets
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select

from giljo_mcp.auth.jwt_manager import JWTManager
from giljo_mcp.auth.principal import AuthErrorReason, PrincipalValidationError, validate_principal
from giljo_mcp.models.auth import User
from giljo_mcp.models.oauth import OAuthRefreshToken
from giljo_mcp.models.organizations import Organization
from giljo_mcp.services import oauth_refresh_service as _refresh
from giljo_mcp.services.oauth_refresh_service import (
    bump_epoch_if_revoked,
    hash_authorization_code,
    hash_refresh_token,
    lock_user_for_update,
    new_family_id,
    revoke_families_for_code,
)
from giljo_mcp.services.oauth_revocation_service import revoke_token
from giljo_mcp.services.oauth_service import BUILTIN_CLIENT_ID, OAuthService
from giljo_mcp.tenant import TenantManager


_MCP_AUD = "https://mcp.giljo.test/resource"


async def _seed_user(db_manager) -> tuple[str, str, str]:
    """Create org+user (epoch 0), committed; return (user_id, username, tenant_key)."""
    tk = TenantManager.generate_tenant_key()
    unique = uuid4().hex[:8]
    user_id = str(uuid4())
    username = f"sec9227c_user_{unique}"
    async with db_manager.get_session_async(tenant_key=tk) as session:
        org = Organization(name=f"SEC9227c Org {unique}", slug=f"sec9227c-org-{unique}", tenant_key=tk, is_active=True)
        session.add(org)
        await session.flush()
        session.add(
            User(
                id=user_id,
                username=username,
                email=f"sec9227c_{unique}@example.com",
                role="developer",
                tenant_key=tk,
                org_id=org.id,
                is_active=True,
                token_revocation_epoch=0,
            )
        )
        await session.commit()
    return user_id, username, tk


async def _insert_refresh_row(
    db_manager, *, tenant_key: str, user_id: str, revoked: bool = False, origin_code_hash: str | None = None
) -> str:
    """Insert one refresh-token row committed (built-in public client); return the raw token."""
    raw = secrets.token_urlsafe(64)
    async with db_manager.get_session_async(tenant_key=tenant_key) as session:
        session.add(
            OAuthRefreshToken(
                token_hash=hash_refresh_token(raw),
                family_id=new_family_id(),
                client_id=BUILTIN_CLIENT_ID,
                tenant_key=tenant_key,
                user_id=user_id,
                scope="mcp:read mcp:write",
                aud=_MCP_AUD,
                expires_at=datetime.now(UTC) + timedelta(days=30),
                revoked=revoked,
                origin_code_hash=origin_code_hash,
            )
        )
        await session.commit()
    return raw


def _mint_access_jwt(*, user_id: str, username: str, tenant_key: str, epoch: int) -> str:
    return JWTManager.create_access_token(
        user_id=UUID(user_id),
        username=username,
        role="developer",
        tenant_key=tenant_key,
        audience=_MCP_AUD,
        scope="mcp:read mcp:write",
        revocation_epoch=epoch,
    )


async def _current_epoch(db_manager, *, tenant_key: str, user_id: str) -> int:
    async with db_manager.get_session_async(tenant_key=tenant_key) as session:
        user = (
            await session.execute(select(User).where(User.id == user_id, User.tenant_key == tenant_key))
        ).scalar_one()
        return int(user.token_revocation_epoch or 0)


# --------------------------------------------------------------------------- #
# Site 1 — RFC 7009 /revoke: the mandatory /mcp Bearer boundary test           #
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_revoke_refresh_token_rejects_prior_access_jwt_at_mcp_boundary(db_manager, monkeypatch):
    """Revoking a refresh token bumps the epoch, so a previously-valid access JWT
    for that user is now rejected at the /mcp Bearer enforcement boundary
    (validate_principal with the MCP audience). This FAILS before the epoch bump
    (the access JWT stays valid) and PASSES after."""
    monkeypatch.setenv("JWT_SECRET", "test_secret_key")
    user_id, username, tk = await _seed_user(db_manager)
    raw_refresh = await _insert_refresh_row(db_manager, tenant_key=tk, user_id=user_id)

    access_jwt = _mint_access_jwt(user_id=user_id, username=username, tenant_key=tk, epoch=0)

    # Pre-revoke: the Bearer JWT is accepted at the /mcp boundary.
    async with db_manager.get_session_async(tenant_key=tk) as s1:
        principal = await validate_principal(s1, jwt_token=access_jwt, expected_audience=_MCP_AUD)
        assert principal.user_id == user_id

    # RFC 7009 revoke of the refresh token (bumps the user's epoch via site 1).
    async with db_manager.get_session_async(tenant_key=tk) as s2:
        await revoke_token(s2, token=raw_refresh, token_type_hint="refresh_token")
        await s2.commit()
    assert await _current_epoch(db_manager, tenant_key=tk, user_id=user_id) == 1

    # Post-revoke: the SAME Bearer JWT is now rejected as revoked at /mcp.
    async with db_manager.get_session_async(tenant_key=tk) as s3:
        with pytest.raises(PrincipalValidationError) as exc:
            await validate_principal(s3, jwt_token=access_jwt, expected_audience=_MCP_AUD)
        assert exc.value.reason == AuthErrorReason.REVOKED


# --------------------------------------------------------------------------- #
# Site 3 — /token code-reuse (revoke_families_for_code) bumps the epoch         #
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_code_reuse_revocation_bumps_epoch(db_manager, monkeypatch):
    """The code-reuse family revocation added in step b must ALSO bump the epoch
    (site 3) — else the derived access tokens survive the reuse-revoke (the exact
    H3 defect on that path)."""
    monkeypatch.setenv("JWT_SECRET", "test_secret_key")
    user_id, _username, tk = await _seed_user(db_manager)
    code = secrets.token_urlsafe(64)
    await _insert_refresh_row(
        db_manager, tenant_key=tk, user_id=user_id, origin_code_hash=hash_authorization_code(code)
    )

    async with db_manager.get_session_async(tenant_key=tk) as session:
        revoked = await revoke_families_for_code(session, code=code, tenant_key=tk)
    assert revoked == 1
    assert await _current_epoch(db_manager, tenant_key=tk, user_id=user_id) == 1


# --------------------------------------------------------------------------- #
# Site 2 — /refresh reuse-detection bumps the epoch                            #
# --------------------------------------------------------------------------- #
async def _seed_family(db_manager, *, tenant_key: str, user_id: str, rows: list[bool]) -> list[str]:
    """Insert one family (shared family_id) with a revoked/live flag per row; return raw tokens."""
    family_id = new_family_id()
    raws: list[str] = []
    async with db_manager.get_session_async(tenant_key=tenant_key) as session:
        for revoked in rows:
            raw = secrets.token_urlsafe(64)
            raws.append(raw)
            session.add(
                OAuthRefreshToken(
                    token_hash=hash_refresh_token(raw),
                    family_id=family_id,
                    client_id=BUILTIN_CLIENT_ID,
                    tenant_key=tenant_key,
                    user_id=user_id,
                    scope="mcp:read mcp:write",
                    aud=_MCP_AUD,
                    expires_at=datetime.now(UTC) + timedelta(days=30),
                    revoked=revoked,
                )
            )
        await session.commit()
    return raws


@pytest.mark.asyncio
async def test_refresh_reuse_detection_bumps_epoch(db_manager, monkeypatch):
    """Presenting an already-revoked refresh token whose family still has a LIVE
    sibling trips reuse detection, which revokes the sibling AND bumps the epoch
    (site 2), killing the derived access tokens before the invalid_grant is raised."""
    monkeypatch.setenv("JWT_SECRET", "test_secret_key")
    monkeypatch.setattr(_refresh, "OAUTH_REFRESH_IDEMPOTENCY_WINDOW_SECONDS", 0)

    user_id, _username, tk = await _seed_user(db_manager)
    # [revoked presented token, live sibling] — the reuse revokes the live sibling.
    raw_revoked, _raw_live = await _seed_family(db_manager, tenant_key=tk, user_id=user_id, rows=[True, False])

    async with db_manager.get_session_async(tenant_key=tk) as session:
        service = OAuthService(db_session=session)
        with pytest.raises(ValueError, match="reuse detected"):
            await _refresh.refresh_token_grant(
                service,
                refresh_token=raw_revoked,
                client_id=BUILTIN_CLIENT_ID,
                client_secret=None,
                access_token_lifetime_seconds=3600,
                refresh_token_lifetime_seconds=30 * 86400,
            )
    assert await _current_epoch(db_manager, tenant_key=tk, user_id=user_id) == 1


@pytest.mark.asyncio
async def test_reuse_of_already_dead_family_does_not_rebump_epoch(db_manager, monkeypatch):
    """Gating (SEC-9047 regression): presenting a token whose family is ALREADY
    fully revoked (e.g. a client's old token after a password-reset eviction) must
    NOT bump the epoch again — otherwise the user's fresh re-login tokens (minted at
    the post-eviction epoch) would be spuriously invalidated."""
    monkeypatch.setenv("JWT_SECRET", "test_secret_key")
    monkeypatch.setattr(_refresh, "OAUTH_REFRESH_IDEMPOTENCY_WINDOW_SECONDS", 0)

    user_id, _username, tk = await _seed_user(db_manager)
    # Whole family already dead; a prior eviction already left the epoch at 1.
    (raw_dead,) = await _seed_family(db_manager, tenant_key=tk, user_id=user_id, rows=[True])
    async with db_manager.get_session_async(tenant_key=tk) as session:
        user = (await session.execute(select(User).where(User.id == user_id, User.tenant_key == tk))).scalar_one()
        user.token_revocation_epoch = 1
        await session.commit()

    async with db_manager.get_session_async(tenant_key=tk) as session:
        service = OAuthService(db_session=session)
        with pytest.raises(ValueError, match="reuse detected"):
            await _refresh.refresh_token_grant(
                service,
                refresh_token=raw_dead,
                client_id=BUILTIN_CLIENT_ID,
                client_secret=None,
                access_token_lifetime_seconds=3600,
                refresh_token_lifetime_seconds=30 * 86400,
            )
    # Epoch stays 1 — the gate held (no re-bump on an already-dead family).
    assert await _current_epoch(db_manager, tenant_key=tk, user_id=user_id) == 1


# --------------------------------------------------------------------------- #
# The shared helpers                                                           #
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_lock_and_gated_bump_helpers(db_manager):
    """lock_user_for_update returns the user (None if absent); bump_epoch_if_revoked
    increments ONLY when revoked_rows > 0, exactly once."""
    user_id, _username, tk = await _seed_user(db_manager)

    async with db_manager.get_session_async(tenant_key=tk) as session:
        user = await lock_user_for_update(session, user_id=user_id, tenant_key=tk)
        assert user is not None
        # No live rows revoked -> no bump; live rows revoked -> exactly one bump.
        assert bump_epoch_if_revoked(user, 0) is False
        assert bump_epoch_if_revoked(user, 2) is True
        await session.commit()
    assert await _current_epoch(db_manager, tenant_key=tk, user_id=user_id) == 1

    async with db_manager.get_session_async(tenant_key=tk) as session:
        assert await lock_user_for_update(session, user_id=str(uuid4()), tenant_key=tk) is None
