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
_INSTRUCTIONS = "Focus on the billing domain; ignore marketing sections."


async def _seed_user_with_product(db_manager) -> dict:
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

        product = Product(
            id=str(uuid.uuid4()),
            name=f"Product {suffix}",
            description="INF-9321 readback fixture",
            tenant_key=tenant_key,
            is_active=True,
        )
        session.add(product)
        await session.commit()
        await session.refresh(product)

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
        return {"tenant_key": tenant_key, "product_id": product.id, "headers": headers}


@pytest_asyncio.fixture(scope="function")
async def seeded(db_manager):
    return await _seed_user_with_product(db_manager)


@pytest.mark.asyncio
async def test_extraction_instructions_round_trip(api_client: AsyncClient, seeded: dict) -> None:
    put_resp = await api_client.put(
        f"/api/v1/products/{seeded['product_id']}",
        headers=seeded["headers"],
        json={"extraction_custom_instructions": _INSTRUCTIONS},
    )
    assert put_resp.status_code == 200, put_resp.text
    assert put_resp.json().get("extraction_custom_instructions") == _INSTRUCTIONS, (
        "PUT response must echo the persisted value, not omit the field"
    )

    get_resp = await api_client.get(
        f"/api/v1/products/{seeded['product_id']}",
        headers=seeded["headers"],
    )
    assert get_resp.status_code == 200, get_resp.text
    assert get_resp.json().get("extraction_custom_instructions") == _INSTRUCTIONS, (
        "GET must carry the persisted value — a missing key here is what visually "
        "cleared the user's typed instructions on analysis completion"
    )


@pytest.mark.asyncio
async def test_unset_instructions_echo_as_null_not_missing(api_client: AsyncClient, seeded: dict) -> None:
    get_resp = await api_client.get(
        f"/api/v1/products/{seeded['product_id']}",
        headers=seeded["headers"],
    )
    assert get_resp.status_code == 200, get_resp.text
    body = get_resp.json()
    assert "extraction_custom_instructions" in body, "key must exist even when unset"
    assert body["extraction_custom_instructions"] is None
