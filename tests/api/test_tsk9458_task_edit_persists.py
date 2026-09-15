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


async def _seed_user_with_product(db_manager) -> dict:
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

        product = Product(
            id=str(uuid.uuid4()),
            name=f"Product {suffix}",
            description="Test product",
            tenant_key=tenant_key,
            is_active=True,
        )
        session.add(product)
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
            "product_id": product.id,
            "headers": {
                "Cookie": f"access_token={token}; csrf_token={_TEST_CSRF_TOKEN}",
                "X-CSRF-Token": _TEST_CSRF_TOKEN,
            },
        }


@pytest_asyncio.fixture(scope="function")
async def seeded_product(db_manager):
    return await _seed_user_with_product(db_manager)


async def _create_task(api_client: AsyncClient, seeded: dict) -> dict:
    resp = await api_client.post(
        "/api/v1/tasks/",
        headers=seeded["headers"],
        json={
            "title": "original title",
            "description": "original description",
            "product_id": seeded["product_id"],
        },
    )
    assert resp.status_code in (200, 201), resp.text
    return resp.json()


async def _read_back(db_manager, task_id: str, tenant_key: str) -> Task | None:
    async with db_manager.get_session_async(tenant_key=tenant_key) as session:
        return await session.get(Task, task_id)


@pytest.mark.asyncio
async def test_round_tripped_task_type_does_not_discard_the_edit(
    api_client: AsyncClient, db_manager, seeded_product: dict
) -> None:
    created = await _create_task(api_client, seeded_product)
    task_id = created["id"]

    assert created["task_type"] == "TSK", created

    fetched = await api_client.get(f"/api/v1/tasks/{task_id}/", headers=seeded_product["headers"])
    assert fetched.status_code == 200, fetched.text
    body = fetched.json()
    assert body["task_type"] == "TSK", body

    payload = {
        "title": "EDITED title",
        "description": "EDITED description",
        "status": body["status"],
        "priority": body["priority"],
        "task_type": body["task_type"],
    }
    resp = await api_client.put(
        f"/api/v1/tasks/{task_id}/",
        headers=seeded_product["headers"],
        json=payload,
    )
    assert resp.status_code == 200, resp.text

    row = await _read_back(db_manager, task_id, seeded_product["tenant_key"])
    assert row is not None
    assert row.title == "EDITED title", "the user's edited title was discarded"
    assert row.description == "EDITED description", "the user's edited description was discarded"


@pytest.mark.asyncio
async def test_edit_without_task_type_still_persists(api_client: AsyncClient, db_manager, seeded_product: dict) -> None:
    created = await _create_task(api_client, seeded_product)
    task_id = created["id"]

    resp = await api_client.put(
        f"/api/v1/tasks/{task_id}/",
        headers=seeded_product["headers"],
        json={"title": "no-type title", "description": "no-type description"},
    )
    assert resp.status_code == 200, resp.text

    row = await _read_back(db_manager, task_id, seeded_product["tenant_key"])
    assert row is not None
    assert row.title == "no-type title"
    assert row.description == "no-type description"


@pytest.mark.asyncio
async def test_reserved_tag_stays_bound_after_an_edit(
    api_client: AsyncClient, db_manager, seeded_product: dict
) -> None:
    created = await _create_task(api_client, seeded_product)
    task_id = created["id"]
    original_type_id = created["task_type_id"]
    assert original_type_id is not None, created

    resp = await api_client.put(
        f"/api/v1/tasks/{task_id}/",
        headers=seeded_product["headers"],
        json={"title": "still TSK", "task_type": "TSK"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["task_type"] == "TSK", resp.text

    row = await _read_back(db_manager, task_id, seeded_product["tenant_key"])
    assert row is not None
    assert str(row.task_type_id) == str(original_type_id), "the reserved tag was rebound by an edit"


@pytest.mark.asyncio
async def test_a_genuinely_unknown_task_type_is_still_rejected(
    api_client: AsyncClient, db_manager, seeded_product: dict
) -> None:
    created = await _create_task(api_client, seeded_product)
    task_id = created["id"]

    resp = await api_client.put(
        f"/api/v1/tasks/{task_id}/",
        headers=seeded_product["headers"],
        json={"title": "bogus type", "task_type": "ZZZZ"},
    )
    assert 400 <= resp.status_code < 500, resp.text

    row = await _read_back(db_manager, task_id, seeded_product["tenant_key"])
    assert row is not None
    assert row.title == "original title", "a rejected update must not partially apply"
