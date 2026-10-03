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
from giljo_mcp.services.handover_validation import (
    REQUIRED_HANDOVER_HEADINGS,
)
from giljo_mcp.tenant import TenantManager


_TEST_CSRF_TOKEN = secrets.token_urlsafe(32)


GOOD_HANDOVER = """Session ended at the rebase. The reviewer holds the merge gate.

## Verify before trusting
- the branch is green -- check with: pytest tests/unit -q

## Waiting on the operator
- nothing

## Cannot testify
- the two-process concurrency behaviour; never observed it
"""

SKELETON = "\n\n".join(REQUIRED_HANDOVER_HEADINGS) + "\n"

EMPTIED_LAST_SECTION = """Session ended at the rebase.

## Verify before trusting
- the branch is green -- check with: pytest tests/unit -q

## Waiting on the operator
- nothing

## Cannot testify
"""


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


@pytest.mark.asyncio
async def test_rest_create_with_handover_type_lands_as_a_handover(
    api_client: AsyncClient, seeded_product: dict
) -> None:
    resp = await api_client.post(
        "/api/v1/tasks/",
        headers=seeded_product["headers"],
        json={
            "title": "session handover",
            "description": GOOD_HANDOVER,
            "product_id": seeded_product["product_id"],
            "task_type": "HND",
        },
    )
    assert resp.status_code in (200, 201), resp.text
    body = resp.json()
    assert body["task_type"] == "HND", "a handover saved from the dashboard must be typed HND"
    assert (body["taxonomy_alias"] or "").startswith("HND-"), body.get("taxonomy_alias")
    assert body["series_number"] is not None, "a handover draws from the same shared serial"


@pytest.mark.asyncio
async def test_rest_create_accepts_a_human_handover_with_only_prior_work(
    api_client: AsyncClient, seeded_product: dict
) -> None:
    description = "## Where I left off\nStopped at the rebase; the branch is green."
    resp = await api_client.post(
        "/api/v1/tasks/",
        headers=seeded_product["headers"],
        json={
            "title": "one-field handover",
            "description": description,
            "product_id": seeded_product["product_id"],
            "task_type": "HND",
        },
    )
    assert resp.status_code in (200, 201), resp.text
    body = resp.json()
    assert body["task_type"] == "HND"
    assert body["description"] == description


@pytest.mark.asyncio
async def test_rest_create_accepts_a_handover_with_no_description_at_all(
    api_client: AsyncClient, seeded_product: dict
) -> None:
    resp = await api_client.post(
        "/api/v1/tasks/",
        headers=seeded_product["headers"],
        json={
            "title": "empty handover",
            "description": "",
            "product_id": seeded_product["product_id"],
            "task_type": "HND",
        },
    )
    assert resp.status_code in (200, 201), resp.text
    assert resp.json()["task_type"] == "HND"


@pytest.mark.asyncio
async def test_rest_create_refuses_an_unknown_task_type_by_name(api_client: AsyncClient, seeded_product: dict) -> None:
    resp = await api_client.post(
        "/api/v1/tasks/",
        headers=seeded_product["headers"],
        json={
            "title": "wrongly typed task",
            "description": "BE is a project type, not a task type",
            "product_id": seeded_product["product_id"],
            "task_type": "BE",
        },
    )
    assert resp.status_code == 422, resp.text
    body = resp.json()
    assert body["error_code"] == "VALIDATION_ERROR", body
    assert body["context"]["field"] == "task_type", body
    assert "BE" in body["message"], body["message"]
    assert "TSK" in body["message"] and "HND" in body["message"], body["message"]


@pytest.mark.asyncio
async def test_rest_create_without_a_task_type_is_still_tsk(api_client: AsyncClient, seeded_product: dict) -> None:
    resp = await api_client.post(
        "/api/v1/tasks/",
        headers=seeded_product["headers"],
        json={
            "title": "ordinary dashboard task",
            "description": "created via the New Task button",
            "product_id": seeded_product["product_id"],
        },
    )
    assert resp.status_code in (200, 201), resp.text
    body = resp.json()
    assert body["task_type"] == "TSK"
    assert (body["taxonomy_alias"] or "").startswith("TSK-"), body.get("taxonomy_alias")
    assert body["series_number"] is not None


@pytest.mark.asyncio
async def test_rest_update_lets_a_person_clear_a_handover_section(
    api_client: AsyncClient, seeded_product: dict
) -> None:
    created = await api_client.post(
        "/api/v1/tasks/",
        headers=seeded_product["headers"],
        json={
            "title": "handover to edit",
            "description": GOOD_HANDOVER,
            "product_id": seeded_product["product_id"],
            "task_type": "HND",
        },
    )
    assert created.status_code in (200, 201), created.text
    task_id = created.json()["id"]

    resp = await api_client.patch(
        f"/api/v1/tasks/{task_id}",
        headers=seeded_product["headers"],
        json={"description": "## Where I left off\nonly this"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["description"] == "## Where I left off\nonly this"


@pytest.mark.asyncio
async def test_rest_update_of_an_ordinary_task_description_is_untouched(
    api_client: AsyncClient, seeded_product: dict
) -> None:
    created = await api_client.post(
        "/api/v1/tasks/",
        headers=seeded_product["headers"],
        json={
            "title": "ordinary task",
            "description": "first draft",
            "product_id": seeded_product["product_id"],
        },
    )
    assert created.status_code in (200, 201), created.text
    task_id = created.json()["id"]

    resp = await api_client.patch(
        f"/api/v1/tasks/{task_id}",
        headers=seeded_product["headers"],
        json={"description": ""},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["description"] == ""


@pytest.mark.asyncio
async def test_rest_update_of_a_legacy_handover_can_still_change_its_status(
    api_client: AsyncClient, seeded_product: dict, db_manager
) -> None:
    from sqlalchemy import update as sa_update

    created = await api_client.post(
        "/api/v1/tasks/",
        headers=seeded_product["headers"],
        json={
            "title": "handover from before the rule",
            "description": GOOD_HANDOVER,
            "product_id": seeded_product["product_id"],
            "task_type": "HND",
        },
    )
    assert created.status_code in (200, 201), created.text
    task_id = created.json()["id"]

    async with db_manager.get_session_async(tenant_key=seeded_product["tenant_key"]) as session:
        await session.execute(sa_update(Task).where(Task.id == task_id).values(description=SKELETON))
        await session.commit()

    echoed = await api_client.patch(
        f"/api/v1/tasks/{task_id}",
        headers=seeded_product["headers"],
        json={"status": "in_progress", "description": SKELETON},
    )
    assert echoed.status_code == 200, echoed.text
    assert echoed.json()["status"] == "in_progress"

    changed = await api_client.patch(
        f"/api/v1/tasks/{task_id}",
        headers=seeded_product["headers"],
        json={"description": SKELETON + "\n## Cannot testify\n"},
    )
    assert changed.status_code == 200, changed.text
