# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from datetime import UTC, datetime
from unittest.mock import patch
from uuid import uuid4

import bcrypt
import pytest
from fastapi import HTTPException

from giljo_mcp.auth.dependencies import require_ce_mode
from giljo_mcp.models.auth import User




@pytest.mark.asyncio
async def test_list_users_with_explicit_tenant_key_filters_correctly(
    user_service, db_session, test_user, test_tenant_key
):
    other_tenant = f"tenant_b_{uuid4().hex[:8]}"
    other_user = User(
        id=str(uuid4()),
        username=f"tenantb_{uuid4().hex[:6]}",
        email=f"tenantb_{uuid4().hex[:6]}@example.com",
        password_hash=bcrypt.hashpw(b"Pass", bcrypt.gensalt()).decode("utf-8"),
        tenant_key=other_tenant,
        role="developer",
        is_active=True,
        created_at=datetime.now(UTC),
    )
    db_session.add(other_user)
    await db_session.commit()

    users_a = await user_service.list_users(tenant_key=test_tenant_key)
    usernames_a = [u.username for u in users_a]
    assert test_user.username in usernames_a
    assert other_user.username not in usernames_a

    users_b = await user_service.list_users(tenant_key=other_tenant)
    usernames_b = [u.username for u in users_b]
    assert other_user.username in usernames_b
    assert test_user.username not in usernames_b


@pytest.mark.asyncio
async def test_list_users_tenant_key_overrides_service_tenant(user_service, db_session, test_tenant_key):
    foreign_tenant = f"tenant_foreign_{uuid4().hex[:8]}"
    foreign_user = User(
        id=str(uuid4()),
        username=f"foreign_{uuid4().hex[:6]}",
        email=f"foreign_{uuid4().hex[:6]}@example.com",
        password_hash=bcrypt.hashpw(b"Pass", bcrypt.gensalt()).decode("utf-8"),
        tenant_key=foreign_tenant,
        role="developer",
        is_active=True,
        created_at=datetime.now(UTC),
    )
    db_session.add(foreign_user)
    await db_session.commit()

    users = await user_service.list_users(tenant_key=foreign_tenant)
    usernames = [u.username for u in users]
    assert foreign_user.username in usernames




@pytest.mark.asyncio
async def test_require_ce_mode_allows_ce():
    with patch("api.app_state.GILJO_MODE", "ce"):
        result = await require_ce_mode()
    assert result is None


@pytest.mark.asyncio
async def test_require_ce_mode_blocks_saas():
    with patch("api.app_state.GILJO_MODE", "saas"), pytest.raises(HTTPException) as exc_info:
        await require_ce_mode()
    assert exc_info.value.status_code == 404
