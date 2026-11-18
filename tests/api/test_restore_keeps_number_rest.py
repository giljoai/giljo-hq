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
from giljo_mcp.models import Product, User
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
            user_id=user.id, username=user.username, role="developer", tenant_key=tenant_key
        )
        headers = {
            "Cookie": f"access_token={token}; csrf_token={_TEST_CSRF_TOKEN}",
            "X-CSRF-Token": _TEST_CSRF_TOKEN,
        }
        return {"tenant_key": tenant_key, "product_id": product.id, "headers": headers}


@pytest_asyncio.fixture(scope="function")
async def seeded_product(db_manager):
    return await _seed_user_with_product(db_manager)


async def _create_task(client: AsyncClient, seeded: dict, title: str) -> dict:
    resp = await client.post(
        "/api/v1/tasks/",
        headers=seeded["headers"],
        json={"title": title, "description": "restore keeps number", "product_id": seeded["product_id"]},
    )
    assert resp.status_code in (200, 201), resp.text
    return resp.json()


async def _create_project(client: AsyncClient, seeded: dict, name: str) -> dict:
    resp = await client.post(
        "/api/v1/projects/",
        headers=seeded["headers"],
        json={"name": name, "description": "restore keeps number", "product_id": seeded["product_id"]},
    )
    assert resp.status_code in (200, 201), resp.text
    return resp.json()


@pytest.mark.asyncio
async def test_a_restored_task_comes_back_with_its_old_number(api_client: AsyncClient, seeded_product: dict) -> None:
    first = await _create_task(api_client, seeded_product, "first")
    second = await _create_task(api_client, seeded_product, "second")
    assert (first["series_number"], second["series_number"]) == (1, 2)

    resp = await api_client.delete(f"/api/v1/tasks/{first['id']}", headers=seeded_product["headers"])
    assert resp.status_code == 204, resp.text
    third = await _create_task(api_client, seeded_product, "third")
    assert third["series_number"] == 3, "the trashed number must not be handed to a new task"

    resp = await api_client.post(f"/api/v1/tasks/{first['id']}/restore", headers=seeded_product["headers"])
    assert resp.status_code == 200, resp.text
    assert resp.json()["series_number"] == 1
    assert resp.json()["taxonomy_alias"] == first["taxonomy_alias"]
    read_back = await api_client.get(f"/api/v1/tasks/{first['id']}/", headers=seeded_product["headers"])
    assert read_back.status_code == 200, read_back.text
    assert read_back.json()["series_number"] == 1


@pytest.mark.asyncio
async def test_a_restored_project_comes_back_with_its_old_number(api_client: AsyncClient, seeded_product: dict) -> None:
    first = await _create_project(api_client, seeded_product, "first")
    second = await _create_project(api_client, seeded_product, "second")
    assert (first["series_number"], second["series_number"]) == (1, 2)

    resp = await api_client.delete(f"/api/v1/projects/{first['id']}", headers=seeded_product["headers"])
    assert resp.status_code == 200, resp.text
    third = await _create_project(api_client, seeded_product, "third")
    assert third["series_number"] == 3, "the trashed number must not be handed to a new project"

    resp = await api_client.post(f"/api/v1/projects/{first['id']}/restore", headers=seeded_product["headers"])
    assert resp.status_code == 200, resp.text
    read_back = await api_client.get(f"/api/v1/projects/{first['id']}", headers=seeded_product["headers"])
    assert read_back.status_code == 200, read_back.text
    assert read_back.json()["series_number"] == 1
    listing = await api_client.get("/api/v1/projects/", headers=seeded_product["headers"])
    assert {row["id"]: row["series_number"] for row in listing.json()}[first["id"]] == 1
