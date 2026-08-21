# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""TSK-9265 REST regression: ``PUT /api/v1/products/{id}`` must be honest about
``product_memory``.

Bug: ``ProductUpdate`` advertised ``product_memory`` and crud.py forwarded it
verbatim, but ``ProductService.update_product()``'s field allowlist (a
deliberate security gate) silently dropped it — the caller got 200 + the stale
value, every browser got a stale ``product:memory:updated`` broadcast, and
nothing was persisted. Product memory has its own owning write path
(ProductMemoryService via the 360 memory tools); this endpoint must reject the
field with a clear 422 instead of lying with a 200.

Tests live at the REST layer (api_client) because the failing layer is the
schema + endpoint wiring (same failing-layer rule as BE-5056).
"""

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
_ORIGINAL_MEMORY = {"learnings": ["seeded learning"], "marker": "original"}


async def _seed_user_with_product(db_manager) -> dict:
    """Create org + user + product (with populated product_memory) in a fresh tenant."""
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
            description="TSK-9265 fixture",
            tenant_key=tenant_key,
            is_active=True,
            product_memory=dict(_ORIGINAL_MEMORY),
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


async def _fetch_product_memory(db_manager, product_id: str, tenant_key: str) -> dict | None:
    async with db_manager.get_session_async(tenant_key=tenant_key) as session:
        row = await session.get(Product, product_id)
        return row.product_memory if row else None


@pytest.mark.asyncio
async def test_put_product_memory_is_rejected_not_silently_dropped(
    api_client: AsyncClient, db_manager, seeded: dict
) -> None:
    """product_memory in the PUT body -> 422 naming the field, nothing persisted.

    Fail-first on the buggy code: the endpoint returned 200 with the stale value
    (silent drop) and fired a stale broadcast.
    """
    resp = await api_client.put(
        f"/api/v1/products/{seeded['product_id']}",
        headers=seeded["headers"],
        json={"product_memory": {"injected": "should never land"}},
    )

    assert resp.status_code == 422, f"expected honest 422, got {resp.status_code}: {resp.text}"
    assert "product_memory" in resp.text

    memory = await _fetch_product_memory(db_manager, seeded["product_id"], seeded["tenant_key"])
    assert memory == _ORIGINAL_MEMORY, "DB memory must be untouched by the rejected request"


@pytest.mark.asyncio
async def test_put_without_product_memory_still_updates(api_client: AsyncClient, db_manager, seeded: dict) -> None:
    """Mainline guard: normal field updates keep working after the rejection gate."""
    resp = await api_client.put(
        f"/api/v1/products/{seeded['product_id']}",
        headers=seeded["headers"],
        json={"description": "updated by TSK-9265 mainline guard"},
    )

    assert resp.status_code == 200, resp.text
    assert resp.json()["description"] == "updated by TSK-9265 mainline guard"

    memory = await _fetch_product_memory(db_manager, seeded["product_id"], seeded["tenant_key"])
    assert memory == _ORIGINAL_MEMORY, "memory untouched by an unrelated field update"
