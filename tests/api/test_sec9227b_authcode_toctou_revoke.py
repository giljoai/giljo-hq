# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import base64
import hashlib
import secrets
import time as _time
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select, update

from giljo_mcp.models.auth import User
from giljo_mcp.models.oauth import OAuthAuthorizationCode, OAuthRefreshToken
from giljo_mcp.models.organizations import Organization
from giljo_mcp.services import oauth_token_idempotency as _idem_svc
from giljo_mcp.services.oauth_refresh_service import (
    hash_authorization_code,
    issue_refresh_token,
    new_family_id,
    revoke_families_for_code,
)
from giljo_mcp.services.oauth_service import BUILTIN_CLIENT_ID, OAuthService
from giljo_mcp.tenant import TenantManager


_REDIRECT = "http://localhost:3000/callback"


def _generate_pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


async def _seed_user(db_manager) -> tuple[str, str]:
    tk = TenantManager.generate_tenant_key()
    unique = uuid4().hex[:8]
    user_id = str(uuid4())
    async with db_manager.get_session_async(tenant_key=tk) as session:
        org = Organization(name=f"SEC9227b Org {unique}", slug=f"sec9227b-org-{unique}", tenant_key=tk, is_active=True)
        session.add(org)
        await session.flush()
        session.add(
            User(
                id=user_id,
                username=f"sec9227b_user_{unique}",
                email=f"sec9227b_{unique}@example.com",
                role="developer",
                tenant_key=tk,
                org_id=org.id,
                is_active=True,
                token_revocation_epoch=0,
            )
        )
        await session.commit()
    return user_id, tk


async def _seed_code(db_manager, *, user_id: str, tenant_key: str, challenge: str) -> str:
    code_value = secrets.token_urlsafe(64)
    async with db_manager.get_session_async(tenant_key=tenant_key) as session:
        session.add(
            OAuthAuthorizationCode(
                code=code_value,
                client_id=BUILTIN_CLIENT_ID,
                user_id=user_id,
                tenant_key=tenant_key,
                redirect_uri=_REDIRECT,
                code_challenge=challenge,
                code_challenge_method="S256",
                scope="mcp:read mcp:write",
                expires_at=datetime.now(UTC) + timedelta(minutes=10),
                used=False,
            )
        )
        await session.commit()
    return code_value


async def _live_families(db_manager, *, tenant_key: str, user_id: str) -> int:
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


async def _refresh_row_for_code(db_manager, *, tenant_key: str, code: str) -> OAuthRefreshToken | None:
    async with db_manager.get_session_async(tenant_key=tenant_key) as session:
        return (
            (
                await session.execute(
                    select(OAuthRefreshToken).where(
                        OAuthRefreshToken.origin_code_hash == hash_authorization_code(code),
                        OAuthRefreshToken.tenant_key == tenant_key,
                    )
                )
            )
            .scalars()
            .first()
        )


async def _token_call(api_client, *, code: str, verifier: str):
    return await api_client.post(
        "/api/oauth/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "client_id": BUILTIN_CLIENT_ID,
            "code_verifier": verifier,
            "redirect_uri": _REDIRECT,
        },
    )


@pytest.mark.asyncio
async def test_h1_concurrent_loser_fails_closed_and_keeps_winner_family(db_manager, monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "test_secret_key")
    user_id, tk = await _seed_user(db_manager)
    verifier, challenge = _generate_pkce_pair()
    code = await _seed_code(db_manager, user_id=user_id, tenant_key=tk, challenge=challenge)

    orig_verify = OAuthService._verify_client_authentication
    fired = {"done": False}

    async def _verify_then_win(*, client_id: str, tenant_key: str, client_secret: str | None):
        if not fired["done"]:
            fired["done"] = True
            async with db_manager.get_session_async(tenant_key=tk) as win:
                await win.execute(
                    update(OAuthAuthorizationCode)
                    .where(
                        OAuthAuthorizationCode.code == code,
                        OAuthAuthorizationCode.tenant_key == tk,
                        OAuthAuthorizationCode.used == False,  # noqa: E712
                    )
                    .values(used=True)
                )
                await issue_refresh_token(
                    win,
                    family_id=new_family_id(),
                    client_id=BUILTIN_CLIENT_ID,
                    tenant_key=tk,
                    user_id=user_id,
                    scope="mcp:read mcp:write",
                    aud="",
                    lifetime_seconds=3600,
                    origin_code_hash=hash_authorization_code(code),
                )
                await win.commit()
        return await orig_verify(client_id=client_id, tenant_key=tenant_key, client_secret=client_secret)

    monkeypatch.setattr(OAuthService, "_verify_client_authentication", staticmethod(_verify_then_win))

    async with db_manager.get_session_async(tenant_key=tk) as loser:
        svc = OAuthService(db_session=loser)
        with pytest.raises(ValueError, match="already been used"):
            await svc.exchange_code_for_token(
                code=code,
                client_id=BUILTIN_CLIENT_ID,
                code_verifier=verifier,
                redirect_uri=_REDIRECT,
            )

    assert fired["done"], "the concurrent-winner seam must have fired mid-exchange"
    assert await _live_families(db_manager, tenant_key=tk, user_id=user_id) == 1


@pytest.mark.asyncio
async def test_m4_sequential_reuse_revokes_family(api_client, db_manager, monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "test_secret_key")
    monkeypatch.setattr(_idem_svc, "OAUTH_TOKEN_IDEMPOTENCY_WINDOW_SECONDS", 0)

    user_id, tk = await _seed_user(db_manager)
    verifier, challenge = _generate_pkce_pair()
    code = await _seed_code(db_manager, user_id=user_id, tenant_key=tk, challenge=challenge)

    first = await _token_call(api_client, code=code, verifier=verifier)
    assert first.status_code == 200, first.text
    assert await _live_families(db_manager, tenant_key=tk, user_id=user_id) == 1

    _time.sleep(0.05)

    replay = await _token_call(api_client, code=code, verifier=verifier)
    assert replay.status_code == 400, replay.text
    assert replay.json().get("error") == "invalid_request", replay.text
    assert await _live_families(db_manager, tenant_key=tk, user_id=user_id) == 0


@pytest.mark.asyncio
async def test_m4_same_verifier_retry_in_window_is_idempotent_no_revoke(api_client, db_manager, monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "test_secret_key")
    monkeypatch.setattr(_idem_svc, "OAUTH_TOKEN_IDEMPOTENCY_WINDOW_SECONDS", 30)

    user_id, tk = await _seed_user(db_manager)
    verifier, challenge = _generate_pkce_pair()
    code = await _seed_code(db_manager, user_id=user_id, tenant_key=tk, challenge=challenge)

    first = await _token_call(api_client, code=code, verifier=verifier)
    assert first.status_code == 200, first.text
    again = await _token_call(api_client, code=code, verifier=verifier)
    assert again.status_code == 200, again.text
    assert again.json()["refresh_token"] == first.json()["refresh_token"]
    assert again.json()["access_token"] == first.json()["access_token"]
    assert await _live_families(db_manager, tenant_key=tk, user_id=user_id) == 1


@pytest.mark.asyncio
async def test_m4_varied_verifier_replay_misses_cache_and_revokes(api_client, db_manager, monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "test_secret_key")
    monkeypatch.setattr(_idem_svc, "OAUTH_TOKEN_IDEMPOTENCY_WINDOW_SECONDS", 30)

    user_id, tk = await _seed_user(db_manager)
    verifier, challenge = _generate_pkce_pair()
    code = await _seed_code(db_manager, user_id=user_id, tenant_key=tk, challenge=challenge)

    first = await _token_call(api_client, code=code, verifier=verifier)
    assert first.status_code == 200, first.text
    assert await _live_families(db_manager, tenant_key=tk, user_id=user_id) == 1

    replay = await _token_call(api_client, code=code, verifier=secrets.token_urlsafe(64))
    assert replay.status_code == 400, replay.text
    assert await _live_families(db_manager, tenant_key=tk, user_id=user_id) == 0


@pytest.mark.asyncio
async def test_origin_code_hash_recorded_on_issuance(api_client, db_manager, monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "test_secret_key")
    user_id, tk = await _seed_user(db_manager)
    verifier, challenge = _generate_pkce_pair()
    code = await _seed_code(db_manager, user_id=user_id, tenant_key=tk, challenge=challenge)

    resp = await _token_call(api_client, code=code, verifier=verifier)
    assert resp.status_code == 200, resp.text
    assert resp.json().get("refresh_token")

    row = await _refresh_row_for_code(db_manager, tenant_key=tk, code=code)
    assert row is not None, "issued refresh row must be linked to its origin code"
    assert row.origin_code_hash == hash_authorization_code(code)
    assert row.user_id == user_id


@pytest.mark.asyncio
async def test_revoke_families_for_code_revokes_all_matching_and_commits(db_manager, monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "test_secret_key")
    user_id, tk = await _seed_user(db_manager)
    code = secrets.token_urlsafe(64)
    other_code = secrets.token_urlsafe(64)

    async with db_manager.get_session_async(tenant_key=tk) as session:
        for _ in range(2):
            await issue_refresh_token(
                session,
                family_id=new_family_id(),
                client_id=BUILTIN_CLIENT_ID,
                tenant_key=tk,
                user_id=user_id,
                scope="mcp:read mcp:write",
                aud="",
                lifetime_seconds=3600,
                origin_code_hash=hash_authorization_code(code),
            )
        await issue_refresh_token(
            session,
            family_id=new_family_id(),
            client_id=BUILTIN_CLIENT_ID,
            tenant_key=tk,
            user_id=user_id,
            scope="mcp:read mcp:write",
            aud="",
            lifetime_seconds=3600,
            origin_code_hash=hash_authorization_code(other_code),
        )
        await session.commit()

    async with db_manager.get_session_async(tenant_key=tk) as session:
        revoked = await revoke_families_for_code(session, code=code, tenant_key=tk)
    assert revoked == 2, "both families minted from the reused code must be revoked"

    assert await _live_families(db_manager, tenant_key=tk, user_id=user_id) == 1
    survivor = await _refresh_row_for_code(db_manager, tenant_key=tk, code=other_code)
    assert survivor is not None and survivor.revoked is False
