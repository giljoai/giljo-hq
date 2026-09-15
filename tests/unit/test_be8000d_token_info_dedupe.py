# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.database import tenant_session_context
from giljo_mcp.download_tokens import TokenManager
from giljo_mcp.tenant import TenantManager


pytestmark = pytest.mark.asyncio


async def test_get_token_info_and_by_token_agree_on_the_same_row(db_session: AsyncSession) -> None:
    tenant_key = TenantManager.generate_tenant_key()
    manager = TokenManager(db_session)

    token = await manager.generate_token(tenant_key, "slash_commands", filename="slash_commands.zip")

    by_tenant = await manager.get_token_info(token, tenant_key)
    by_token_only = await manager.get_token_info_by_token(token)

    assert by_tenant is not None
    assert by_token_only is not None
    assert by_tenant == by_token_only
    assert by_tenant["token"] == token
    assert by_tenant["tenant_key"] == tenant_key
    assert by_tenant["download_type"] == "slash_commands"
    assert by_tenant["filename"] == "slash_commands.zip"
    assert by_tenant["is_expired"] is False
    assert by_tenant["last_downloaded_at"] is None


async def test_get_token_info_returns_none_on_miss(db_session: AsyncSession) -> None:
    tenant_key = TenantManager.generate_tenant_key()
    manager = TokenManager(db_session)

    with tenant_session_context(db_session, tenant_key):
        assert await manager.get_token_info("ghost-token", tenant_key) is None
    assert await manager.get_token_info_by_token("ghost-token") is None
