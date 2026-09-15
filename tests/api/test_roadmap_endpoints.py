# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import secrets
import uuid

import bcrypt
import pytest
from httpx import AsyncClient

from giljo_mcp.auth.jwt_manager import JWTManager
from giljo_mcp.models import Product, Project, User
from giljo_mcp.models.organizations import Organization
from giljo_mcp.services.roadmap_service import RoadmapService
from giljo_mcp.tenant import TenantManager


_TEST_CSRF_TOKEN = secrets.token_urlsafe(32)


async def _seed(db_manager, *, active: bool = True) -> dict:
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
            description="roadmap api test product",
            tenant_key=tenant_key,
            is_active=active,
        )
        session.add(product)
        await session.flush()

        project = Project(
            id=str(uuid.uuid4()),
            tenant_key=tenant_key,
            product_id=product.id,
            name=f"Project {suffix}",
            description="desc",
            mission="mission",
        )
        session.add(project)
        await session.commit()

        token = JWTManager.create_access_token(
            user_id=user.id, username=user.username, role="developer", tenant_key=tenant_key
        )
        headers = {
            "Cookie": f"access_token={token}; csrf_token={_TEST_CSRF_TOKEN}",
            "X-CSRF-Token": _TEST_CSRF_TOKEN,
        }
        return {
            "tenant_key": tenant_key,
            "product_id": product.id,
            "project_id": project.id,
            "headers": headers,
        }


async def _upsert_one_project_item(db_manager, tenant_key: str, project_id: str, sort_order: int = 0) -> None:
    svc = RoadmapService(db_manager=db_manager, tenant_manager=TenantManager())
    await svc.upsert_metadata(
        items=[{"item_type": "project", "project_id": project_id, "sort_order": sort_order, "risk": "low"}],
        summary="api test roadmap",
        tenant_key=tenant_key,
    )


@pytest.mark.asyncio
async def test_get_roadmap_returns_items(api_client: AsyncClient, db_manager) -> None:
    seed = await _seed(db_manager)
    await _upsert_one_project_item(db_manager, seed["tenant_key"], seed["project_id"])

    resp = await api_client.get("/api/v1/roadmap", headers=seed["headers"])
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["product_id"] == seed["product_id"]
    assert body["roadmap"]["summary"] == "api test roadmap"
    assert len(body["items"]) == 1
    row = body["items"][0]
    assert row["project_id"] == seed["project_id"]
    assert row["item_type"] == "project"
    assert row["risk"] == "low"
    assert row.get("title")
    assert "taxonomy_alias" in row
    assert "status" in row
    assert "id" in row


@pytest.mark.asyncio
async def test_get_roadmap_no_active_product_404(api_client: AsyncClient, db_manager) -> None:
    seed = await _seed(db_manager, active=False)
    resp = await api_client.get("/api/v1/roadmap", headers=seed["headers"])
    assert resp.status_code == 404, resp.text


@pytest.mark.asyncio
async def test_reorder_updates_sort_order(api_client: AsyncClient, db_manager) -> None:
    seed = await _seed(db_manager)
    await _upsert_one_project_item(db_manager, seed["tenant_key"], seed["project_id"], sort_order=0)

    get1 = await api_client.get("/api/v1/roadmap", headers=seed["headers"])
    item_id = get1.json()["items"][0]["id"]

    resp = await api_client.patch(
        "/api/v1/roadmap/reorder",
        headers=seed["headers"],
        json={"items": [{"id": item_id, "sort_order": 5}]},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["items_reordered"] == 1

    get2 = await api_client.get("/api/v1/roadmap", headers=seed["headers"])
    assert get2.json()["items"][0]["sort_order"] == 5


@pytest.mark.asyncio
async def test_reorder_negative_sort_order_422(api_client: AsyncClient, db_manager) -> None:
    seed = await _seed(db_manager)
    resp = await api_client.patch(
        "/api/v1/roadmap/reorder",
        headers=seed["headers"],
        json={"items": [{"id": "anything", "sort_order": -1}]},
    )
    assert resp.status_code == 422, resp.text


@pytest.mark.asyncio
async def test_get_roadmap_is_tenant_isolated(api_client: AsyncClient, db_manager) -> None:
    a = await _seed(db_manager)
    b = await _seed(db_manager)
    await _upsert_one_project_item(db_manager, a["tenant_key"], a["project_id"])

    resp = await api_client.get("/api/v1/roadmap", headers=b["headers"])
    assert resp.status_code == 200, resp.text
    body = resp.json()
    project_ids = {row["project_id"] for row in body["items"]}
    assert a["project_id"] not in project_ids


@pytest.mark.asyncio
async def test_reorder_cross_tenant_item_is_noop(api_client: AsyncClient, db_manager) -> None:
    a = await _seed(db_manager)
    b = await _seed(db_manager)
    await _upsert_one_project_item(db_manager, a["tenant_key"], a["project_id"], sort_order=0)
    await _upsert_one_project_item(db_manager, b["tenant_key"], b["project_id"], sort_order=0)

    a_item_id = (await api_client.get("/api/v1/roadmap", headers=a["headers"])).json()["items"][0]["id"]

    resp = await api_client.patch(
        "/api/v1/roadmap/reorder",
        headers=b["headers"],
        json={"items": [{"id": a_item_id, "sort_order": 99}]},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["items_reordered"] == 0

    a_after = (await api_client.get("/api/v1/roadmap", headers=a["headers"])).json()["items"][0]
    assert a_after["sort_order"] == 0


@pytest.mark.asyncio
async def test_delete_roadmap_item_removes_own(api_client: AsyncClient, db_manager) -> None:
    seed = await _seed(db_manager)
    await _upsert_one_project_item(db_manager, seed["tenant_key"], seed["project_id"])
    item_id = (await api_client.get("/api/v1/roadmap", headers=seed["headers"])).json()["items"][0]["id"]

    resp = await api_client.delete(f"/api/v1/roadmap/items/{item_id}", headers=seed["headers"])
    assert resp.status_code == 200, resp.text
    assert resp.json()["removed"] == 1

    after = await api_client.get("/api/v1/roadmap", headers=seed["headers"])
    assert after.json()["items"] == []


@pytest.mark.asyncio
async def test_delete_roadmap_item_cross_tenant_is_noop(api_client: AsyncClient, db_manager) -> None:
    a = await _seed(db_manager)
    b = await _seed(db_manager)
    await _upsert_one_project_item(db_manager, a["tenant_key"], a["project_id"])
    await _upsert_one_project_item(db_manager, b["tenant_key"], b["project_id"])

    a_item_id = (await api_client.get("/api/v1/roadmap", headers=a["headers"])).json()["items"][0]["id"]

    resp = await api_client.delete(f"/api/v1/roadmap/items/{a_item_id}", headers=b["headers"])
    assert resp.status_code == 200, resp.text
    assert resp.json()["removed"] == 0

    a_items = (await api_client.get("/api/v1/roadmap", headers=a["headers"])).json()["items"]
    assert len(a_items) == 1
