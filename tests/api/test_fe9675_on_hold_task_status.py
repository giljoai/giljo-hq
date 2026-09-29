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
from httpx import AsyncClient, Response

from giljo_mcp.auth.jwt_manager import JWTManager
from giljo_mcp.domain.task_status import TASK_STATUS_META, TaskStatus
from giljo_mcp.models import Product, Task, User
from giljo_mcp.models.organizations import Organization
from giljo_mcp.repositories.product_memory_repository import ProductMemoryRepository
from giljo_mcp.services.next_action import task_list_next_action
from giljo_mcp.tenant import TenantManager
from giljo_mcp.tools.context_tools.get_tasks import get_tasks


_TEST_CSRF_TOKEN = secrets.token_urlsafe(32)


@pytest_asyncio.fixture(scope="function")
async def seeded(db_manager) -> dict:
    async with db_manager.get_session_async() as session:
        suffix = uuid.uuid4().hex[:8]
        tenant_key = TenantManager.generate_tenant_key()
        org = Organization(name=f"Org {suffix}", slug=f"org-{suffix}", tenant_key=tenant_key, is_active=True)
        session.add(org)
        await session.flush()
        user = User(
            username=f"user_{suffix}",
            email=f"user_{suffix}@example.com",
            password_hash=bcrypt.hashpw(b"test_password", bcrypt.gensalt()).decode("utf-8"),
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
        return {
            "tenant_key": tenant_key,
            "product_id": product.id,
            "headers": {
                "Cookie": f"access_token={token}; csrf_token={_TEST_CSRF_TOKEN}",
                "X-CSRF-Token": _TEST_CSRF_TOKEN,
            },
        }


async def _create(api_client: AsyncClient, seeded: dict, **extra) -> Response:
    return await api_client.post(
        "/api/v1/tasks/",
        headers=seeded["headers"],
        json={"title": "undecided", "description": "park it", "product_id": seeded["product_id"], **extra},
    )


async def _row(db_manager, task_id: str, tenant_key: str) -> Task:
    async with db_manager.get_session_async(tenant_key=tenant_key) as session:
        row = await session.get(Task, task_id)
    assert row is not None
    return row


def test_on_hold_is_a_canonical_status_labelled_on_hold() -> None:
    meta = TASK_STATUS_META[TaskStatus("on_hold")]
    assert meta.label == "On hold"
    assert meta.is_lifecycle_finished is False
    assert meta.color_token != TASK_STATUS_META[TaskStatus.IN_PROGRESS].color_token


@pytest.mark.asyncio
async def test_rest_create_accepts_on_hold_and_does_not_stamp_started_at(
    api_client: AsyncClient, db_manager, seeded: dict
) -> None:
    resp = await _create(api_client, seeded, status="on_hold")
    assert resp.status_code in (200, 201), resp.text
    assert resp.json()["status"] == "on_hold"

    row = await _row(db_manager, resp.json()["id"], seeded["tenant_key"])
    assert row.status == "on_hold"
    assert row.started_at is None


@pytest.mark.asyncio
async def test_rest_patch_accepts_on_hold_and_in_progress_still_stamps_started_at(
    api_client: AsyncClient, db_manager, seeded: dict
) -> None:
    created = await _create(api_client, seeded)
    assert created.status_code in (200, 201), created.text
    task_id = created.json()["id"]

    resp = await api_client.patch(f"/api/v1/tasks/{task_id}", headers=seeded["headers"], json={"status": "on_hold"})
    assert resp.status_code == 200, resp.text
    row = await _row(db_manager, task_id, seeded["tenant_key"])
    assert row.status == "on_hold"
    assert row.started_at is None, "on_hold must never stamp started_at"

    resp = await api_client.patch(f"/api/v1/tasks/{task_id}", headers=seeded["headers"], json={"status": "in_progress"})
    assert resp.status_code == 200, resp.text
    row = await _row(db_manager, task_id, seeded["tenant_key"])
    assert row.status == "in_progress"
    assert row.started_at is not None


@pytest.mark.asyncio
async def test_rest_status_only_endpoint_accepts_on_hold(api_client: AsyncClient, db_manager, seeded: dict) -> None:
    created = await _create(api_client, seeded)
    task_id = created.json()["id"]
    resp = await api_client.patch(
        f"/api/v1/tasks/{task_id}/status/", headers=seeded["headers"], json={"status": "on_hold"}
    )
    assert resp.status_code == 200, resp.text
    assert (await _row(db_manager, task_id, seeded["tenant_key"])).status == "on_hold"


@pytest.mark.asyncio
async def test_on_hold_counts_as_open_in_every_open_task_reader(
    api_client: AsyncClient, db_manager, seeded: dict
) -> None:
    resp = await _create(api_client, seeded, status="on_hold")
    assert resp.status_code in (200, 201), resp.text
    task_id = resp.json()["id"]

    result = await get_tasks(product_id=seeded["product_id"], tenant_key=seeded["tenant_key"], db_manager=db_manager)
    assert task_id in {r["task_id"] for r in result["data"]["tasks"]}
    assert result["data"]["open_count"] == 1

    repo = ProductMemoryRepository()
    async with db_manager.get_session_async(tenant_key=seeded["tenant_key"]) as session:
        single = await repo.count_unresolved_tasks(session, seeded["product_id"], seeded["tenant_key"])
        bulk = await repo.count_unresolved_tasks_bulk(session, [seeded["product_id"]], seeded["tenant_key"])
    assert single == 1
    assert bulk == {seeded["product_id"]: 1}

    assert task_list_next_action(["on_hold"]) is not None
