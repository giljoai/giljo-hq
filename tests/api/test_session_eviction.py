# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import logging
from uuid import uuid4

import bcrypt
import pytest

from giljo_mcp.services.session_eviction import close_live_user_sockets, evict_user_tokens


logger = logging.getLogger(__name__)


async def _seed_user_and_refresh(db_manager) -> tuple[str, str, str]:
    from giljo_mcp.models.auth import User
    from giljo_mcp.models.organizations import Organization
    from giljo_mcp.services.oauth_refresh_service import issue_refresh_token, new_family_id
    from giljo_mcp.tenant import TenantManager

    tk = TenantManager.generate_tenant_key()
    unique = uuid4().hex[:8]
    user_id = str(uuid4())

    async with db_manager.get_session_async(tenant_key=tk) as session:
        org = Organization(name=f"SE Org {unique}", slug=f"se-org-{unique}", tenant_key=tk, is_active=True)
        session.add(org)
        await session.flush()
        session.add(
            User(
                id=user_id,
                username=f"se_user_{unique}",
                email=f"se_{unique}@example.com",
                password_hash=bcrypt.hashpw(b"Password1!", bcrypt.gensalt()).decode("utf-8"),
                tenant_key=tk,
                role="developer",
                org_id=org.id,
                is_active=True,
                token_revocation_epoch=0,
            )
        )
        raw = await issue_refresh_token(
            session,
            family_id=new_family_id(),
            client_id=str(uuid4()),
            tenant_key=tk,
            user_id=user_id,
            scope="mcp:read",
            aud="",
            lifetime_seconds=3600,
        )
        await session.commit()

    return user_id, tk, raw


@pytest.mark.asyncio
async def test_evict_user_tokens_bumps_epoch_and_revokes_refresh(db_manager):
    from giljo_mcp.models.auth import User
    from giljo_mcp.models.oauth import OAuthRefreshToken

    user_id, tk, _raw = await _seed_user_and_refresh(db_manager)

    async with db_manager.get_session_async(tenant_key=tk) as session:
        user = await session.get(User, user_id)
        revoked = await evict_user_tokens(session, user)
        await session.commit()

    assert revoked == 1

    async with db_manager.get_session_async(tenant_key=tk) as session:
        user = await session.get(User, user_id)
        assert int(user.token_revocation_epoch or 0) == 1
        rows = (
            (await session.execute(OAuthRefreshToken.__table__.select().where(OAuthRefreshToken.user_id == user_id)))
            .mappings()
            .all()
        )
        assert rows and all(r["revoked"] for r in rows)


class _SpyWs:
    def __init__(self, *, raises: bool = False) -> None:
        self.calls: list[str] = []
        self.raises = raises

    async def disconnect_tenant(self, tenant_key: str, *, reason: str = "", **_) -> int:
        self.calls.append(tenant_key)
        if self.raises:
            raise RuntimeError("simulated close failure")
        return 3


@pytest.mark.asyncio
async def test_close_live_user_sockets_invokes_disconnect(monkeypatch):
    from api import app_state

    spy = _SpyWs()
    monkeypatch.setattr(app_state.state, "websocket_manager", spy, raising=False)

    await close_live_user_sockets("tenant_X", logger)

    assert spy.calls == ["tenant_X"]


@pytest.mark.asyncio
async def test_close_live_user_sockets_noop_when_no_manager(monkeypatch):
    from api import app_state

    monkeypatch.setattr(app_state.state, "websocket_manager", None, raising=False)

    await close_live_user_sockets("tenant_X", logger)


@pytest.mark.asyncio
async def test_close_live_user_sockets_swallows_errors(monkeypatch):
    from api import app_state

    spy = _SpyWs(raises=True)
    monkeypatch.setattr(app_state.state, "websocket_manager", spy, raising=False)

    await close_live_user_sockets("tenant_X", logger)
    assert spy.calls == ["tenant_X"]
