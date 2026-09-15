# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import secrets
from uuid import uuid4

import bcrypt
import pytest
from sqlalchemy import select

from giljo_mcp.auth.jwt_manager import JWTManager
from giljo_mcp.models.oauth import OAuthRefreshToken
from giljo_mcp.services.oauth_refresh_service import issue_refresh_token, new_family_id
from giljo_mcp.services.oauth_revocation_service import clear_revocation_cache
from giljo_mcp.services.user_auth_service import UserAuthService


PASSWORD = "ForceLogout1!"

_CSRF = secrets.token_urlsafe(32)

AUTH_PROBE = "/api/v1/users/me/field-priority"


async def _seed_user(db_manager) -> tuple[str, str, str]:
    from giljo_mcp.models.auth import User
    from giljo_mcp.models.organizations import Organization
    from giljo_mcp.tenant import TenantManager

    tk = TenantManager.generate_tenant_key()
    unique = uuid4().hex[:8]
    user_id = str(uuid4())
    username = f"sec9217a_user_{unique}"

    async with db_manager.get_session_async(tenant_key=tk) as session:
        org = Organization(
            name=f"SEC9217a Org {unique}",
            slug=f"sec9217a-org-{unique}",
            tenant_key=tk,
            is_active=True,
        )
        session.add(org)
        await session.flush()
        session.add(
            User(
                id=user_id,
                username=username,
                email=f"sec9217a_{unique}@example.com",
                password_hash=bcrypt.hashpw(PASSWORD.encode("utf-8"), bcrypt.gensalt()).decode("utf-8"),
                tenant_key=tk,
                role="developer",
                org_id=org.id,
                is_active=True,
                token_revocation_epoch=0,
            )
        )
        await session.commit()

    return user_id, username, tk


def _cookie_headers(token: str) -> dict:
    return {
        "Cookie": f"access_token={token}; csrf_token={_CSRF}",
        "X-CSRF-Token": _CSRF,
    }


def _mint(user_id: str, username: str, tenant_key: str, *, revocation_epoch: int) -> str:
    return JWTManager.create_access_token(
        user_id=user_id,
        username=username,
        role="developer",
        tenant_key=tenant_key,
        revocation_epoch=revocation_epoch,
    )


def _install_confidential_resolver(client_id: str, secret_hash: str):
    from giljo_mcp.services import oauth_service as svc

    prior = svc.get_client_resolver()

    def _resolver(cid: str, tenant_key: str):
        assert tenant_key
        if cid != client_id:
            return None
        return svc.ResolvedClient(
            client_id=cid,
            client_name="SEC9217a Test Client",
            redirect_uris=["http://localhost:3000/callback"],
            client_secret_hash=secret_hash,
        )

    svc.set_client_resolver(_resolver)

    def _restore() -> None:
        svc.set_client_resolver(prior)

    return _restore


async def _seed_refresh_token(db_manager, *, client_id: str, tenant_key: str, user_id: str) -> str:
    async with db_manager.get_session_async(tenant_key=tenant_key) as session:
        raw = await issue_refresh_token(
            session,
            family_id=new_family_id(),
            client_id=client_id,
            tenant_key=tenant_key,
            user_id=user_id,
            scope="mcp:read mcp:write",
            aud="",
            lifetime_seconds=3600,
        )
        await session.commit()
    return raw


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


async def _unrevoked_refresh_count(db_manager, *, tenant_key: str, user_id: str) -> int:
    async with db_manager.get_session_async(tenant_key=tenant_key) as session:
        rows = (
            (
                await session.execute(
                    select(OAuthRefreshToken).where(
                        OAuthRefreshToken.user_id == user_id,
                        OAuthRefreshToken.tenant_key == tenant_key,
                        OAuthRefreshToken.revoked.is_(False),
                    )
                )
            )
            .scalars()
            .all()
        )
    return len(rows)


@pytest.mark.asyncio
async def test_force_logout_revokes_refresh_families_and_kills_access(api_client, db_manager, monkeypatch):
    from giljo_mcp.services import oauth_refresh_service as _refresh_svc

    monkeypatch.setenv("JWT_SECRET", "test_secret_key")
    monkeypatch.setattr(_refresh_svc, "OAUTH_REFRESH_IDEMPOTENCY_WINDOW_SECONDS", 0)
    clear_revocation_cache()

    user_id, username, tk = await _seed_user(db_manager)

    stale_access = _mint(user_id, username, tk, revocation_epoch=0)
    probe = await api_client.get(AUTH_PROBE, headers=_cookie_headers(stale_access))
    assert probe.status_code == 200, probe.text

    client_id = str(uuid4())
    client_secret = secrets.token_urlsafe(48)
    secret_hash = bcrypt.hashpw(client_secret.encode("utf-8"), bcrypt.gensalt()).decode("ascii")
    restore = _install_confidential_resolver(client_id, secret_hash)
    try:
        raw1 = await _seed_refresh_token(db_manager, client_id=client_id, tenant_key=tk, user_id=user_id)
        before = await _refresh_call(api_client, refresh_token=raw1, client_id=client_id, client_secret=client_secret)
        assert before.status_code == 200, before.text
        rotated = before.json()["refresh_token"]
        assert await _unrevoked_refresh_count(db_manager, tenant_key=tk, user_id=user_id) >= 1

        auth_service = UserAuthService(db_manager=db_manager, tenant_key=tk)
        updated = await auth_service.force_logout(user_id)
        assert updated.token_revocation_epoch == 1

        assert await _unrevoked_refresh_count(db_manager, tenant_key=tk, user_id=user_id) == 0

        clear_revocation_cache()
        after = await _refresh_call(api_client, refresh_token=rotated, client_id=client_id, client_secret=client_secret)
        assert after.status_code == 401, after.text
        assert "invalid_grant" in _oauth_err_text(after.json()).lower()

        stale = await api_client.get(AUTH_PROBE, headers=_cookie_headers(stale_access))
        assert stale.status_code == 401, stale.text

        fresh = _mint(user_id, username, tk, revocation_epoch=1)
        relogin = await api_client.get(AUTH_PROBE, headers=_cookie_headers(fresh))
        assert relogin.status_code == 200, relogin.text
    finally:
        restore()
        clear_revocation_cache()
