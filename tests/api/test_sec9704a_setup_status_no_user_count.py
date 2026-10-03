# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import uuid

import pytest

from giljo_mcp.models import User
from giljo_mcp.tenant import TenantManager


pytestmark = pytest.mark.asyncio


async def _seed_users(db_manager, count: int) -> None:
    async with db_manager.get_session_async() as session:
        for _ in range(count):
            suffix = uuid.uuid4().hex[:8]
            session.add(
                User(
                    username=f"count_probe_{suffix}",
                    email=f"count_probe_{suffix}@example.com",
                    password_hash="x",
                    tenant_key=TenantManager.generate_tenant_key(),
                    role="developer",
                )
            )
        await session.commit()


async def test_saas_status_reports_at_most_one_user(api_client, db_manager, monkeypatch):
    await _seed_users(db_manager, 2)
    monkeypatch.setattr("api.endpoints.setup_security.GILJO_MODE", "saas")

    data = (await api_client.get("/api/setup/status")).json()

    assert data["total_users_count"] == 1


async def test_ce_status_still_reports_the_count(api_client, db_manager, monkeypatch):
    await _seed_users(db_manager, 2)
    monkeypatch.setattr("api.endpoints.setup_security.GILJO_MODE", "ce")

    data = (await api_client.get("/api/setup/status")).json()

    assert data["total_users_count"] >= 2
