# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import bcrypt
import pytest
from sqlalchemy import select

from giljo_mcp.api_key_utils import generate_api_key, get_key_prefix, hash_api_key
from giljo_mcp.auth.principal import validate_principal
from giljo_mcp.database import tenant_session_context
from giljo_mcp.models.auth import APIKey, User
from giljo_mcp.models.organizations import Organization
from giljo_mcp.services.user_auth_service import reset_password_via_pin
from giljo_mcp.tenant import TenantManager


OLD_PASSWORD = "OldPassword1!"
NEW_PASSWORD = "NewPassword2@"


async def seed_active_api_key(db_session, *, tenant_key: str, user_id: str) -> tuple[str, str]:
    raw_key = generate_api_key()
    key_id = str(uuid4())
    with tenant_session_context(db_session, tenant_key):
        db_session.add(
            APIKey(
                id=key_id,
                tenant_key=tenant_key,
                user_id=user_id,
                name="reset pin key",
                key_hash=hash_api_key(raw_key),
                key_prefix=get_key_prefix(raw_key, length=12),
                permissions=["*"],
                is_active=True,
                expires_at=datetime.now(UTC) + timedelta(days=90),
            )
        )
        await db_session.commit()
    return key_id, raw_key


async def assert_api_key_still_works(db_session, *, tenant_key: str, user_id: str, key_id: str, raw_key: str):
    with tenant_session_context(db_session, tenant_key):
        key = (await db_session.execute(select(APIKey).where(APIKey.id == key_id))).scalar_one()
        await db_session.refresh(key)
    assert key.is_active is True
    assert key.revoked_at is None

    principal = await validate_principal(db_session, api_key=raw_key)
    assert principal.user_id == user_id
    assert principal.auth_method == "api_key"


async def _seed_user(db_session) -> tuple[User, str]:
    tk = TenantManager.generate_tenant_key()
    unique = uuid4().hex[:8]
    with tenant_session_context(db_session, tk):
        org = Organization(name=f"Reset Keys Org {unique}", slug=f"reset-keys-org-{unique}", tenant_key=tk)
        db_session.add(org)
        await db_session.flush()
        user = User(
            id=str(uuid4()),
            username=f"reset_keys_{unique}",
            email=f"reset_keys_{unique}@example.com",
            password_hash=bcrypt.hashpw(OLD_PASSWORD.encode("utf-8"), bcrypt.gensalt()).decode("utf-8"),
            tenant_key=tk,
            role="developer",
            org_id=org.id,
            is_active=True,
            token_revocation_epoch=0,
        )
        db_session.add(user)
        await db_session.commit()
    return user, tk


@pytest.mark.asyncio
async def test_pin_reset_does_not_revoke_api_keys(db_session, monkeypatch):
    from api.app_state import state

    monkeypatch.setattr(state, "websocket_manager", None)
    user, tk = await _seed_user(db_session)
    key_id, raw_key = await seed_active_api_key(db_session, tenant_key=tk, user_id=user.id)

    with tenant_session_context(db_session, tk):
        await reset_password_via_pin(db_session, user, NEW_PASSWORD)

    await db_session.refresh(user)
    assert user.token_revocation_epoch == 1
    await assert_api_key_still_works(db_session, tenant_key=tk, user_id=user.id, key_id=key_id, raw_key=raw_key)
