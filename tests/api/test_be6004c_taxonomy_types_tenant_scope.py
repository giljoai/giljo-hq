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
from giljo_mcp.models import TaxonomyType, User
from giljo_mcp.models.organizations import Organization
from giljo_mcp.tenant import TenantManager


_TEST_CSRF_TOKEN = secrets.token_urlsafe(32)


async def _seed_tenant_with_taxonomy(db_manager) -> dict:
    async with db_manager.get_session_async() as session:
        suffix = uuid.uuid4().hex[:8]
        tenant_key = TenantManager.generate_tenant_key()

        org = Organization(
            name=f"Org {suffix}",
            slug=f"org-{suffix}",
            tenant_key=tenant_key,
            is_active=True,
        )
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

        abbr_a = f"X{suffix[:2].upper()}"
        abbr_b = f"Y{suffix[:2].upper()}"
        type_a = TaxonomyType(
            tenant_key=tenant_key,
            abbreviation=abbr_a,
            label=f"Type A {suffix}",
            color="#112233",
            sort_order=100,
        )
        type_b = TaxonomyType(
            tenant_key=tenant_key,
            abbreviation=abbr_b,
            label=f"Type B {suffix}",
            color="#445566",
            sort_order=101,
        )
        session.add(type_a)
        session.add(type_b)
        await session.commit()

        token = JWTManager.create_access_token(
            user_id=user.id,
            username=user.username,
            role="developer",
            tenant_key=tenant_key,
        )
        headers = {
            "Cookie": f"access_token={token}; csrf_token={_TEST_CSRF_TOKEN}",
            "X-CSRF-Token": _TEST_CSRF_TOKEN,
        }
        return {
            "tenant_key": tenant_key,
            "user_id": user.id,
            "headers": headers,
            "abbreviations": {abbr_a, abbr_b},
            "type_ids": {type_a.id, type_b.id},
        }


@pytest_asyncio.fixture(scope="function")
async def seeded_taxonomy(db_manager) -> dict:
    return await _seed_tenant_with_taxonomy(db_manager)


@pytest.mark.asyncio
async def test_list_taxonomy_types_returns_200_for_authenticated_tenant(
    api_client: AsyncClient, seeded_taxonomy: dict
) -> None:
    resp = await api_client.get("/api/v1/taxonomy-types/", headers=seeded_taxonomy["headers"])
    assert resp.status_code == 200, resp.text

    body = resp.json()
    assert isinstance(body, list)

    returned_tenants = {row["tenant_key"] for row in body}
    assert returned_tenants == {seeded_taxonomy["tenant_key"]}, returned_tenants

    returned_abbrs = {row["abbreviation"] for row in body}
    assert seeded_taxonomy["abbreviations"].issubset(returned_abbrs), returned_abbrs


@pytest.mark.asyncio
async def test_list_taxonomy_types_does_not_leak_other_tenants(api_client: AsyncClient, db_manager) -> None:
    tenant_a = await _seed_tenant_with_taxonomy(db_manager)
    tenant_b = await _seed_tenant_with_taxonomy(db_manager)

    resp = await api_client.get("/api/v1/taxonomy-types/", headers=tenant_a["headers"])
    assert resp.status_code == 200, resp.text

    body = resp.json()
    returned_tenants = {row["tenant_key"] for row in body}
    assert returned_tenants == {tenant_a["tenant_key"]}, returned_tenants

    returned_ids = {row["id"] for row in body}
    assert returned_ids.isdisjoint(tenant_b["type_ids"]), returned_ids & tenant_b["type_ids"]
