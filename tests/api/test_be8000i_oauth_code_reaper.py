# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import asyncio
import types
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select

from api.startup import oauth_code_reaper
from giljo_mcp.database import TENANT_CONTEXT_SOURCE_KEY, tenant_isolation_bypass
from giljo_mcp.models.auth import User
from giljo_mcp.models.oauth import OAuthAuthorizationCode


class _BareSessionManager:

    def __init__(self, session):
        self._session = session

    @asynccontextmanager
    async def get_session_async(self):
        self._session.info.pop("tenant_key", None)
        self._session.info.pop(TENANT_CONTEXT_SOURCE_KEY, None)
        yield self._session


async def _seed_user_and_code(session, *, tenant_key: str, expires_at: datetime, used: bool) -> str:
    user_id = str(uuid4())
    code = f"code_{uuid4().hex}"
    with tenant_isolation_bypass(session, reason="test setup: seed oauth code", models=(User, OAuthAuthorizationCode)):
        session.add(
            User(
                id=user_id,
                username=f"oauth_reaper_{uuid4().hex[:8]}",
                email=f"oauth_reaper_{uuid4().hex[:8]}@example.com",
                role="developer",
                tenant_key=tenant_key,
                is_active=True,
                is_system_user=False,
                must_change_password=False,
                must_set_pin=False,
                failed_pin_attempts=0,
            )
        )
        session.add(
            OAuthAuthorizationCode(
                id=str(uuid4()),
                code=code,
                client_id="giljo-mcp-default",
                user_id=user_id,
                tenant_key=tenant_key,
                redirect_uri="http://localhost:3000/callback",
                code_challenge="challenge",
                code_challenge_method="S256",
                expires_at=expires_at,
                used=used,
            )
        )
        await session.flush()
    await session.commit()
    return code


def _single_iteration_sleep():
    calls = {"n": 0}

    async def _fake_sleep(_seconds):
        calls["n"] += 1
        if calls["n"] > 1:
            raise asyncio.CancelledError

    return _fake_sleep


@pytest.mark.asyncio
class TestOAuthCodeReaperTask:
    async def test_registered_task_deletes_expired_and_used_codes(self, monkeypatch, db_session):
        now = datetime.now(UTC)
        tenant = f"t_{uuid4().hex[:8]}"

        expired_code = await _seed_user_and_code(
            db_session, tenant_key=tenant, expires_at=now - timedelta(minutes=5), used=False
        )
        used_code = await _seed_user_and_code(
            db_session, tenant_key=tenant, expires_at=now + timedelta(minutes=10), used=True
        )
        valid_code = await _seed_user_and_code(
            db_session, tenant_key=tenant, expires_at=now + timedelta(minutes=10), used=False
        )

        monkeypatch.setattr(oauth_code_reaper.asyncio, "sleep", _single_iteration_sleep())
        state = types.SimpleNamespace(db_manager=_BareSessionManager(db_session))

        with pytest.raises(asyncio.CancelledError):
            await oauth_code_reaper.cleanup_expired_oauth_codes_task(state)

        with tenant_isolation_bypass(
            db_session, reason="test assert: read remaining oauth codes", models=(OAuthAuthorizationCode,)
        ):
            remaining = (
                (
                    await db_session.execute(
                        select(OAuthAuthorizationCode.code).where(OAuthAuthorizationCode.tenant_key == tenant)
                    )
                )
                .scalars()
                .all()
            )

        assert expired_code not in remaining
        assert used_code not in remaining
        assert valid_code in remaining

    async def test_registered_task_is_a_noop_without_a_db_manager(self, monkeypatch):
        monkeypatch.setattr(oauth_code_reaper.asyncio, "sleep", _single_iteration_sleep())
        state = types.SimpleNamespace(db_manager=None)

        with pytest.raises(asyncio.CancelledError):
            await oauth_code_reaper.cleanup_expired_oauth_codes_task(state)
