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


async def _seed_user_with_task(db_manager, *, title: str = "Patch target") -> dict:
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
            description="Test product",
            tenant_key=tenant_key,
            is_active=True,
        )
        session.add(product)
        await session.flush()

        task = Task(
            id=str(uuid.uuid4()),
            title=title,
            description="initial description",
            tenant_key=tenant_key,
            product_id=product.id,
            status="pending",
            priority="medium",
            created_by_user_id=user.id,
        )
        session.add(task)
        await session.commit()
        await session.refresh(task)

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
            "task_id": task.id,
            "headers": headers,
            "initial_description": task.description,
        }


@pytest_asyncio.fixture(scope="function")
async def seeded(db_manager):
    return await _seed_user_with_task(db_manager)


async def _fetch_task_description(db_manager, task_id: str, tenant_key: str) -> str | None:
    async with db_manager.get_session_async(tenant_key=tenant_key) as session:
        row = await session.get(Task, task_id)
        return row.description if row else None


@pytest.mark.asyncio
async def test_patch_completed_with_notes_appends_audit_trail(
    api_client: AsyncClient, db_manager, seeded: dict
) -> None:
    resp = await api_client.patch(
        f"/api/v1/tasks/{seeded['task_id']}",
        headers=seeded["headers"],
        json={"status": "completed", "completion_notes": "shipped to test install"},
    )
    assert resp.status_code == 200, resp.text

    description = await _fetch_task_description(db_manager, seeded["task_id"], seeded["tenant_key"])
    assert description is not None
    assert description.startswith(seeded["initial_description"])
    assert "[completed " in description
    assert "shipped to test install" in description


@pytest.mark.asyncio
async def test_patch_in_progress_with_notes_is_silent_noop(api_client: AsyncClient, db_manager, seeded: dict) -> None:
    resp = await api_client.patch(
        f"/api/v1/tasks/{seeded['task_id']}",
        headers=seeded["headers"],
        json={"status": "in_progress", "completion_notes": "should be ignored"},
    )
    assert resp.status_code == 200, resp.text

    description = await _fetch_task_description(db_manager, seeded["task_id"], seeded["tenant_key"])
    assert description == seeded["initial_description"]
    assert "should be ignored" not in (description or "")


@pytest.mark.asyncio
async def test_patch_cross_tenant_cannot_mutate_other_tenants_task(api_client: AsyncClient, db_manager) -> None:
    tenant_a = await _seed_user_with_task(db_manager, title="Tenant A target")
    tenant_b = await _seed_user_with_task(db_manager, title="Tenant B caller")

    resp = await api_client.patch(
        f"/api/v1/tasks/{tenant_a['task_id']}",
        headers=tenant_b["headers"],
        json={"status": "completed", "completion_notes": "cross-tenant attack"},
    )
    assert resp.status_code in (403, 404), resp.text

    description = await _fetch_task_description(db_manager, tenant_a["task_id"], tenant_a["tenant_key"])
    assert description == tenant_a["initial_description"]
    assert "cross-tenant attack" not in (description or "")
