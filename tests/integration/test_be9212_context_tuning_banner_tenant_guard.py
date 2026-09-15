# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import delete

from api.startup import context_tuning_banner as ctb
from giljo_mcp.database import TenantIsolationError  # noqa: F401  (documents the pre-fix failure)
from giljo_mcp.models import User
from giljo_mcp.models.organizations import Organization
from giljo_mcp.tenant import TenantManager


@pytest.mark.asyncio
async def test_resolve_active_user_id_finds_tenant_user_under_enforce(db_manager, monkeypatch):
    monkeypatch.setenv("GILJO_TENANT_GUARD_MODE", "enforce")
    tenant_key = TenantManager.generate_tenant_key()
    suffix = uuid4().hex[:8]
    org_id = str(uuid4())
    user_id = str(uuid4())

    async with db_manager.get_session_async(tenant_key=tenant_key) as session:
        session.add(
            Organization(
                id=org_id,
                name=f"BE9212 Org {suffix}",
                slug=f"be9212-org-{suffix}",
                tenant_key=tenant_key,
                is_active=True,
            )
        )
        await session.flush()
        session.add(
            User(
                id=user_id,
                username=f"be9212_{suffix}",
                tenant_key=tenant_key,
                role="developer",
                org_id=org_id,
                is_active=True,
            )
        )
        await session.commit()

    try:
        TenantManager.clear_current_tenant()
        resolved = await ctb._resolve_active_user_id(db_manager, tenant_key)
        assert resolved == user_id
    finally:
        async with db_manager.get_session_async(tenant_key=tenant_key) as session:
            await session.execute(delete(User).where(User.tenant_key == tenant_key))
            await session.execute(delete(Organization).where(Organization.tenant_key == tenant_key))
            await session.commit()


@pytest.mark.asyncio
async def test_resolve_active_user_id_empty_tenant_returns_none_under_enforce(db_manager, monkeypatch):
    monkeypatch.setenv("GILJO_TENANT_GUARD_MODE", "enforce")
    TenantManager.clear_current_tenant()
    empty_tenant = TenantManager.generate_tenant_key()

    resolved = await ctb._resolve_active_user_id(db_manager, empty_tenant)

    assert resolved is None
