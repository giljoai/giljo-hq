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

from giljo_mcp.models.oauth import OAuthRefreshToken
from giljo_mcp.services.oauth_refresh_service import issue_refresh_token, new_family_id
from giljo_mcp.services.oauth_revocation_service import clear_revocation_cache
from giljo_mcp.services.oauth_service import OAuthService
from giljo_mcp.services.session_eviction import evict_user_tokens


async def _seed_user(db_manager) -> tuple[str, str, str]:
    from giljo_mcp.models.auth import User
    from giljo_mcp.models.organizations import Organization
    from giljo_mcp.tenant import TenantManager

    tk = TenantManager.generate_tenant_key()
    unique = uuid4().hex[:8]
    user_id = str(uuid4())
    username = f"sec9217b_user_{unique}"

    async with db_manager.get_session_async(tenant_key=tk) as session:
        org = Organization(name=f"SEC9217b Org {unique}", slug=f"sec9217b-org-{unique}", tenant_key=tk, is_active=True)
        session.add(org)
        await session.flush()
        session.add(
            User(
                id=user_id,
                username=username,
                email=f"sec9217b_{unique}@example.com",
                password_hash=bcrypt.hashpw(b"SeedPassword1!", bcrypt.gensalt()).decode("utf-8"),
                tenant_key=tk,
                role="developer",
                org_id=org.id,
                is_active=True,
                token_revocation_epoch=0,
            )
        )
        await session.commit()

    return user_id, username, tk


def _install_confidential_resolver(client_id: str, secret_hash: str):
    from giljo_mcp.services import oauth_service as svc

    prior = svc.get_client_resolver()

    def _resolver(cid: str, tenant_key: str):
        assert tenant_key
        if cid != client_id:
            return None
        return svc.ResolvedClient(
            client_id=cid,
            client_name="SEC9217b Test Client",
            redirect_uris=["http://localhost:3000/callback"],
            client_secret_hash=secret_hash,
        )

    svc.set_client_resolver(_resolver)
    return lambda: svc.set_client_resolver(prior)


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


async def _live_refresh_rows(db_manager, *, tenant_key: str, user_id: str) -> int:
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
async def test_refresh_grant_loses_to_concurrent_invalidation(api_client, db_manager, monkeypatch):
    from giljo_mcp.services import oauth_refresh_service as _refresh_svc

    monkeypatch.setenv("JWT_SECRET", "test_secret_key")
    monkeypatch.setattr(_refresh_svc, "OAUTH_REFRESH_IDEMPOTENCY_WINDOW_SECONDS", 0)
    clear_revocation_cache()

    user_id, _username, tk = await _seed_user(db_manager)

    client_id = str(uuid4())
    client_secret = secrets.token_urlsafe(48)
    secret_hash = bcrypt.hashpw(client_secret.encode("utf-8"), bcrypt.gensalt()).decode("ascii")
    restore = _install_confidential_resolver(client_id, secret_hash)

    from giljo_mcp.models.auth import User

    orig_verify = OAuthService._verify_client_authentication
    injected = {"done": False}

    async def _verify_then_invalidate(*, client_id: str, tenant_key: str, client_secret: str | None):
        if not injected["done"]:
            injected["done"] = True
            async with db_manager.get_session_async(tenant_key=tk) as inval:
                user = (await inval.execute(select(User).where(User.id == user_id, User.tenant_key == tk))).scalar_one()
                await evict_user_tokens(inval, user)
                await inval.commit()
        return await orig_verify(client_id=client_id, tenant_key=tenant_key, client_secret=client_secret)

    monkeypatch.setattr(OAuthService, "_verify_client_authentication", staticmethod(_verify_then_invalidate))

    try:
        raw = await _seed_refresh_token(db_manager, client_id=client_id, tenant_key=tk, user_id=user_id)
        resp = await _refresh_call(api_client, refresh_token=raw, client_id=client_id, client_secret=client_secret)

        assert injected["done"], "the invalidation seam must have fired mid-grant"
        assert resp.status_code == 401, resp.text
        assert "invalid_grant" in _oauth_err_text(resp.json()).lower()
        assert "access_token" not in resp.json()

        assert await _live_refresh_rows(db_manager, tenant_key=tk, user_id=user_id) == 0
    finally:
        restore()
        clear_revocation_cache()


@pytest.mark.asyncio
async def test_idempotency_window_retry_still_returns_same_pair(api_client, db_manager, monkeypatch):
    from giljo_mcp.services import oauth_refresh_service as _refresh_svc

    monkeypatch.setenv("JWT_SECRET", "test_secret_key")
    monkeypatch.setattr(_refresh_svc, "OAUTH_REFRESH_IDEMPOTENCY_WINDOW_SECONDS", 30)
    clear_revocation_cache()

    user_id, _username, tk = await _seed_user(db_manager)

    client_id = str(uuid4())
    client_secret = secrets.token_urlsafe(48)
    secret_hash = bcrypt.hashpw(client_secret.encode("utf-8"), bcrypt.gensalt()).decode("ascii")
    restore = _install_confidential_resolver(client_id, secret_hash)
    try:
        raw = await _seed_refresh_token(db_manager, client_id=client_id, tenant_key=tk, user_id=user_id)

        first = await _refresh_call(api_client, refresh_token=raw, client_id=client_id, client_secret=client_secret)
        assert first.status_code == 200, first.text

        again = await _refresh_call(api_client, refresh_token=raw, client_id=client_id, client_secret=client_secret)
        assert again.status_code == 200, again.text
        assert again.json()["refresh_token"] == first.json()["refresh_token"]
        assert again.json()["access_token"] == first.json()["access_token"]
    finally:
        restore()
        clear_revocation_cache()
