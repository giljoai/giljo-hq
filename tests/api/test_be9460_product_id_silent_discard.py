# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import secrets
import uuid

import bcrypt
import pytest
import pytest_asyncio
from httpx import AsyncClient

from giljo_mcp.auth.jwt_manager import JWTManager
from giljo_mcp.models import Product, Task, User
from giljo_mcp.models.organizations import Organization
from giljo_mcp.tenant import TenantManager


_TEST_CSRF_TOKEN = secrets.token_urlsafe(32)


async def _seed_user_with_two_products(db_manager) -> dict:
    async with db_manager.get_session_async() as session:
        suffix = uuid.uuid4().hex[:8]
        tenant_key = TenantManager.generate_tenant_key()

        org = Organization(name=f"Org {suffix}", slug=f"org-{suffix}", tenant_key=tenant_key, is_active=True)
        session.add(org)
        await session.flush()

        password_hash = bcrypt.hashpw(b"test_password", bcrypt.gensalt()).decode("utf-8")
        user = User(
            username=f"user_{suffix}",
            email=f"user_{suffix}@example.com",
            password_hash=password_hash,
            tenant_key=tenant_key,
            role="developer",
            org_id=org.id,
        )
        session.add(user)
        await session.flush()

        product_a = Product(
            id=str(uuid.uuid4()),
            name=f"Product A {suffix}",
            description="Test product A",
            tenant_key=tenant_key,
            is_active=True,
        )
        product_b = Product(
            id=str(uuid.uuid4()),
            name=f"Product B {suffix}",
            description="Test product B",
            tenant_key=tenant_key,
            is_active=False,
        )
        session.add(product_a)
        session.add(product_b)
        await session.commit()

        token = JWTManager.create_access_token(
            user_id=user.id,
            username=user.username,
            role="developer",
            tenant_key=tenant_key,
        )
        return {
            "tenant_key": tenant_key,
            "user_id": user.id,
            "product_a_id": product_a.id,
            "product_b_id": product_b.id,
            "headers": {
                "Cookie": f"access_token={token}; csrf_token={_TEST_CSRF_TOKEN}",
                "X-CSRF-Token": _TEST_CSRF_TOKEN,
            },
        }


@pytest_asyncio.fixture(scope="function")
async def seeded_two_products(db_manager):
    return await _seed_user_with_two_products(db_manager)


async def _read_back(db_manager, task_id: str, tenant_key: str) -> Task | None:
    async with db_manager.get_session_async(tenant_key=tenant_key) as session:
        return await session.get(Task, task_id)


async def _create_task(api_client: AsyncClient, seeded: dict) -> dict:
    resp = await api_client.post(
        "/api/v1/tasks/",
        headers=seeded["headers"],
        json={"title": "bound to product A", "product_id": seeded["product_a_id"]},
    )
    assert resp.status_code in (200, 201), resp.text
    return resp.json()


@pytest.mark.asyncio
async def test_changed_product_id_is_rejected_not_silently_dropped(
    api_client: AsyncClient, db_manager, seeded_two_products: dict
) -> None:
    created = await _create_task(api_client, seeded_two_products)
    task_id = created["id"]
    assert created["product_id"] == seeded_two_products["product_a_id"], created

    resp = await api_client.put(
        f"/api/v1/tasks/{task_id}/",
        headers=seeded_two_products["headers"],
        json={"product_id": seeded_two_products["product_b_id"]},
    )
    assert 400 <= resp.status_code < 500, (
        f"BE-9460: a changed product_id must be visibly rejected, not silently "
        f"accepted with 200 -- got {resp.status_code}: {resp.text}"
    )

    row = await _read_back(db_manager, task_id, seeded_two_products["tenant_key"])
    assert row is not None
    assert str(row.product_id) == str(seeded_two_products["product_a_id"]), (
        "a rejected product_id change must not partially apply"
    )


@pytest.mark.asyncio
async def test_unchanged_echoed_product_id_is_tolerated(
    api_client: AsyncClient, db_manager, seeded_two_products: dict
) -> None:
    created = await _create_task(api_client, seeded_two_products)
    task_id = created["id"]

    resp = await api_client.put(
        f"/api/v1/tasks/{task_id}/",
        headers=seeded_two_products["headers"],
        json={
            "title": "EDITED title",
            "product_id": seeded_two_products["product_a_id"],
        },
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["product_id"] == seeded_two_products["product_a_id"], resp.json()

    row = await _read_back(db_manager, task_id, seeded_two_products["tenant_key"])
    assert row is not None
    assert row.title == "EDITED title", "the echoed product_id must not discard the user's other edits"
    assert str(row.product_id) == str(seeded_two_products["product_a_id"])
