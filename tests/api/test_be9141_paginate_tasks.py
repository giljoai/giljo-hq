# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-9141 regression — GET /api/v1/tasks/ gains opt-in limit/offset pagination.

Filed from IMP-6263d SYNTHESIS_ROADMAP §4 item 4: the tasks list query was
unbounded (mirrors the /projects and /jobs pagination the dashboard already
uses). This pins the endpoint boundary:

  * default (no limit/offset) is byte-identical to the pre-change behavior —
    all tenant tasks, newest-first (``created_at`` DESC). This is the museum
    characterization that must never regress.
  * ``limit`` caps the row count; ``offset`` skips rows; the two page together
    over the same stable ordering.
  * ``limit`` above the safety ceiling (500) is rejected at the boundary with a
    422 (Query ``le=500``) rather than issuing an unbounded scan.

Tenant isolation is exercised implicitly — every seeded task carries the
authenticated tenant_key and the endpoint filters by it.

**Edition Scope:** CE.
"""

from __future__ import annotations

import secrets
import uuid
from datetime import UTC, datetime

import bcrypt
import pytest
import pytest_asyncio
from httpx import AsyncClient

from giljo_mcp.auth.jwt_manager import JWTManager
from giljo_mcp.models import Product, Task, User
from giljo_mcp.models.organizations import Organization
from giljo_mcp.tenant import TenantManager


_TEST_CSRF_TOKEN = secrets.token_urlsafe(32)

_TASK_COUNT = 5


async def _seed_user_product_and_tasks(db_manager) -> dict:
    """Create org + user + ACTIVE product + N tasks with strictly increasing
    ``created_at`` so the DESC ordering is deterministic. Returns auth + titles
    ordered newest-first (the exact order the endpoint must emit)."""
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
        await session.flush()

        # Distinct created_at values (task-0 oldest ... task-{N-1} newest) so the
        # newest-first ordering is unambiguous and offset paging is stable.
        for i in range(_TASK_COUNT):
            session.add(
                Task(
                    id=str(uuid.uuid4()),
                    tenant_key=tenant_key,
                    product_id=product.id,
                    created_by_user_id=user.id,
                    title=f"task-{i}",
                    status="pending",
                    priority="medium",
                    created_at=datetime(2026, 1, 1, 0, 0, i, tzinfo=UTC),
                )
            )
        await session.commit()

        token = JWTManager.create_access_token(
            user_id=user.id, username=user.username, role="developer", tenant_key=tenant_key
        )
        headers = {
            "Cookie": f"access_token={token}; csrf_token={_TEST_CSRF_TOKEN}",
            "X-CSRF-Token": _TEST_CSRF_TOKEN,
        }
        # Newest-first titles: task-4, task-3, ... task-0
        titles_desc = [f"task-{i}" for i in range(_TASK_COUNT - 1, -1, -1)]
        return {
            "tenant_key": tenant_key,
            "product_id": product.id,
            "headers": headers,
            "titles_desc": titles_desc,
        }


@pytest_asyncio.fixture(scope="function")
async def seeded_tasks(db_manager):
    return await _seed_user_product_and_tasks(db_manager)


@pytest.mark.asyncio
async def test_list_tasks_default_returns_all_newest_first(api_client: AsyncClient, seeded_tasks: dict) -> None:
    """Museum characterization: no limit/offset -> ALL tasks, newest-first."""
    resp = await api_client.get("/api/v1/tasks/", headers=seeded_tasks["headers"])
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert [t["title"] for t in body] == seeded_tasks["titles_desc"]


@pytest.mark.asyncio
async def test_list_tasks_limit_caps_count(api_client: AsyncClient, seeded_tasks: dict) -> None:
    """limit=2 -> the two newest tasks only, preserving the DESC ordering."""
    resp = await api_client.get("/api/v1/tasks/", headers=seeded_tasks["headers"], params={"limit": 2})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert [t["title"] for t in body] == seeded_tasks["titles_desc"][:2]


@pytest.mark.asyncio
async def test_list_tasks_offset_pages_over_stable_order(api_client: AsyncClient, seeded_tasks: dict) -> None:
    """limit=2 & offset=2 -> the next page (rows 3-4) of the same DESC ordering."""
    resp = await api_client.get("/api/v1/tasks/", headers=seeded_tasks["headers"], params={"limit": 2, "offset": 2})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert [t["title"] for t in body] == seeded_tasks["titles_desc"][2:4]


@pytest.mark.asyncio
async def test_list_tasks_offset_only_skips_from_top(api_client: AsyncClient, seeded_tasks: dict) -> None:
    """offset without limit skips the newest rows and returns the remainder."""
    resp = await api_client.get("/api/v1/tasks/", headers=seeded_tasks["headers"], params={"offset": 3})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert [t["title"] for t in body] == seeded_tasks["titles_desc"][3:]


@pytest.mark.asyncio
async def test_list_tasks_limit_above_ceiling_rejected(api_client: AsyncClient, seeded_tasks: dict) -> None:
    """A limit above the 500 safety ceiling is a 422 at the boundary, not an
    unbounded scan (Query le=500)."""
    resp = await api_client.get("/api/v1/tasks/", headers=seeded_tasks["headers"], params={"limit": 999})
    assert resp.status_code == 422, resp.text
