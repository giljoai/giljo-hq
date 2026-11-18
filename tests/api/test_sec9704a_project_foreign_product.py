# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import secrets
import string
import uuid

import pytest
from sqlalchemy import text

from giljo_mcp.models import Product, TaxonomyType
from giljo_mcp.tenant import TenantManager


pytestmark = pytest.mark.asyncio


async def _seed_foreign_product(db_manager) -> str:
    async with db_manager.get_session_async() as session:
        product = Product(
            id=str(uuid.uuid4()),
            name=f"Foreign product {uuid.uuid4().hex[:6]}",
            description="belongs to another tenant",
            tenant_key=TenantManager.generate_tenant_key(),
        )
        session.add(product)
        await session.commit()
        return product.id


async def test_a_foreign_product_id_is_not_found(api_client, auth_headers, db_manager):
    foreign_product_id = await _seed_foreign_product(db_manager)

    resp = await api_client.post(
        "/api/v1/projects/",
        headers=auth_headers,
        json={"name": "cross-tenant", "description": "fixture", "product_id": foreign_product_id},
    )

    assert resp.status_code == 404, f"expected 404, got {resp.status_code}: {resp.text}"
    async with db_manager.get_session_async() as session:
        count = await session.scalar(
            text("SELECT count(*) FROM projects WHERE product_id = :pid"), {"pid": foreign_product_id}
        )
    assert count == 0


async def test_an_own_product_id_still_creates(api_client, auth_headers):
    product_resp = await api_client.post(
        "/api/v1/products/",
        headers=auth_headers,
        json={"name": f"own product {uuid.uuid4().hex[:6]}", "description": "fixture"},
    )
    assert product_resp.status_code == 200, product_resp.text

    resp = await api_client.post(
        "/api/v1/projects/",
        headers=auth_headers,
        json={"name": "own", "description": "fixture", "product_id": product_resp.json()["id"]},
    )

    assert resp.status_code == 201, f"expected 201, got {resp.status_code}: {resp.text}"


async def _seed_foreign_project_type(db_manager) -> str:
    async with db_manager.get_session_async() as session:
        project_type = TaxonomyType(
            id=str(uuid.uuid4()),
            tenant_key=TenantManager.generate_tenant_key(),
            abbreviation="ZZ",
            label=f"Foreign {uuid.uuid4().hex[:6]}",
        )
        session.add(project_type)
        await session.commit()
        return project_type.id


async def test_a_foreign_project_type_id_is_not_found(api_client, auth_headers, db_manager):
    foreign_type_id = await _seed_foreign_project_type(db_manager)
    product_resp = await api_client.post(
        "/api/v1/products/",
        headers=auth_headers,
        json={"name": f"own product {uuid.uuid4().hex[:6]}", "description": "fixture"},
    )
    assert product_resp.status_code == 200, product_resp.text

    resp = await api_client.post(
        "/api/v1/projects/",
        headers=auth_headers,
        json={
            "name": "cross-tenant type",
            "description": "fixture",
            "product_id": product_resp.json()["id"],
            "project_type_id": foreign_type_id,
        },
    )

    assert resp.status_code == 404, f"expected 404, got {resp.status_code}: {resp.text}"
    async with db_manager.get_session_async() as session:
        count = await session.scalar(
            text("SELECT count(*) FROM projects WHERE project_type_id = :tid"), {"tid": foreign_type_id}
        )
    assert count == 0


async def _own_project(api_client, auth_headers) -> str:
    product_resp = await api_client.post(
        "/api/v1/products/",
        headers=auth_headers,
        json={"name": f"own product {uuid.uuid4().hex[:6]}", "description": "fixture"},
    )
    assert product_resp.status_code == 200, product_resp.text
    resp = await api_client.post(
        "/api/v1/projects/",
        headers=auth_headers,
        json={"name": "own", "description": "fixture", "product_id": product_resp.json()["id"]},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def test_patch_to_a_foreign_project_type_id_is_not_found(api_client, auth_headers, db_manager):
    foreign_type_id = await _seed_foreign_project_type(db_manager)
    project_id = await _own_project(api_client, auth_headers)

    resp = await api_client.patch(
        f"/api/v1/projects/{project_id}", headers=auth_headers, json={"project_type_id": foreign_type_id}
    )

    assert resp.status_code == 404, f"expected 404, got {resp.status_code}: {resp.text}"
    async with db_manager.get_session_async() as session:
        stored = await session.scalar(text("SELECT project_type_id FROM projects WHERE id = :pid"), {"pid": project_id})
    assert stored is None


async def test_patch_to_an_own_project_type_id_still_applies(api_client, auth_headers, db_manager):
    project_id = await _own_project(api_client, auth_headers)
    type_resp = await api_client.post(
        "/api/v1/taxonomy-types/",
        headers=auth_headers,
        json={"abbreviation": "".join(secrets.choice(string.ascii_uppercase) for _ in range(4)), "label": "Own"},
    )
    assert type_resp.status_code in (200, 201), type_resp.text
    own_type_id = type_resp.json()["id"]

    resp = await api_client.patch(
        f"/api/v1/projects/{project_id}", headers=auth_headers, json={"project_type_id": own_type_id}
    )

    assert resp.status_code == 200, resp.text
    assert resp.json()["project_type_id"] == own_type_id
