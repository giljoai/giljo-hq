# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-6049c H2 regression — REST ``POST /api/v1/tasks`` forces the TSK tag.

The dashboard "New Task" flow hits this REST endpoint (not the MCP path). When
tasks became TSK-only, the MCP ``create_task_for_mcp`` was rewritten to force
TSK + always allocate the global serial, but the REST endpoint was initially
missed — it still resolved an inbound ``task_type`` and only allocated a serial
when a type was present, so a dashboard-created task came out UNTYPED and
serial-less, contradicting the TSK-only dialog (which shows a fixed "TSK" type
and an auto serial).

These tests pin the REST boundary: a created task is always TSK with a
``TSK-nnnn`` alias, whether the client omits ``task_type`` (the real FE payload)
or passes a bogus/legacy value (which must be ignored, not error).
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


async def _seed_user_with_product(db_manager) -> dict:
    """Create org + user + ACTIVE product in a fresh tenant; return auth + ids."""
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


@pytest.mark.asyncio
async def test_rest_create_task_without_type_forces_tsk_and_serial(
    api_client: AsyncClient, seeded_product: dict
) -> None:
    """The real FE payload omits task_type -> task must come out TSK with a serial."""
    resp = await api_client.post(
        "/api/v1/tasks/",
        headers=seeded_product["headers"],
        json={
            "title": "dashboard task",
            "description": "created via the New Task button",
            "product_id": seeded_product["product_id"],
        },
    )
    assert resp.status_code in (200, 201), resp.text
    body = resp.json()
    assert body["task_type"] == "TSK", "dashboard-created task must be the reserved TSK tag"
    assert body["series_number"] is not None, "TSK task must get a global serial"
    assert (body["taxonomy_alias"] or "").startswith("TSK-"), body.get("taxonomy_alias")


@pytest.mark.asyncio
async def test_rest_create_task_ignores_inbound_type(api_client: AsyncClient, seeded_product: dict) -> None:
    """A legacy/bogus task_type is accepted-but-ignored (no error) -> still TSK."""
    resp = await api_client.post(
        "/api/v1/tasks/",
        headers=seeded_product["headers"],
        json={
            "title": "legacy-typed task",
            "description": "task_type must be ignored",
            "product_id": seeded_product["product_id"],
            "task_type": "BE",
        },
    )
    assert resp.status_code in (200, 201), resp.text
    body = resp.json()
    assert body["task_type"] == "TSK"
    assert (body["taxonomy_alias"] or "").startswith("TSK-")


@pytest.mark.asyncio
async def test_rest_create_task_gated_at_serial_cap(api_client: AsyncClient, seeded_product: dict, db_manager) -> None:
    """BE-6079: the REST create auto-assigns the global serial, so it must be gated
    by the centralized >9999 cap. Seed the product at the 9999 watermark, then a
    create must fail (400 'serial space exhausted') instead of minting 10000."""
    import uuid as _uuid

    from giljo_mcp.models import Project
    from giljo_mcp.repositories.project_repository import MAX_SERIES_NUMBER

    async with db_manager.get_session_async() as session:
        session.add(
            Project(
                id=str(_uuid.uuid4()),
                name="Watermark-9999",
                description="watermark seed",
                mission="",
                tenant_key=seeded_product["tenant_key"],
                product_id=seeded_product["product_id"],
                status="inactive",
                series_number=MAX_SERIES_NUMBER,
            )
        )
        await session.commit()

    resp = await api_client.post(
        "/api/v1/tasks/",
        headers=seeded_product["headers"],
        json={
            "title": "task at the cap",
            "description": "must be rejected, serial space exhausted",
            "product_id": seeded_product["product_id"],
        },
    )
    assert resp.status_code == 400, resp.text
    assert "exhausted" in resp.text.lower()
