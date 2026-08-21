# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-3006a single-writer rule — REST task-create routed through TaskService.

The REST ``POST /api/v1/tasks`` endpoint used to raw-write the Task row and
validated only HALF of what mattered: it checked the product was active but
SKIPPED the ``project_id`` belonging check; the service checked project
belonging but SKIPPED product-active. BE-3006a merges BOTH halves into
``TaskService.create_task_for_rest`` and deletes the endpoint's raw
``db.add`` / ``db.commit``.

These tests pin the REST boundary two-sided:
- the happy path (valid product, valid/absent project) STILL succeeds, and
- the newly-enforced negatives (foreign/absent project_id, inactive product,
  missing product) return the SAME HTTP responses the inline checks produced.

Plus a static census proving no sync ``bcrypt`` call sites remain in the three
password service files (all hashing now flows through the shared async helper).
"""

from __future__ import annotations

import re
import secrets
import uuid
from pathlib import Path

import bcrypt
import pytest
import pytest_asyncio
from httpx import AsyncClient

from giljo_mcp.auth.jwt_manager import JWTManager
from giljo_mcp.models import Product, Project, User
from giljo_mcp.models.organizations import Organization
from giljo_mcp.tenant import TenantManager


_TEST_CSRF_TOKEN = secrets.token_urlsafe(32)


async def _seed_user_with_product(db_manager, *, product_active: bool = True) -> dict:
    """Create org + user + product (active or not) in a fresh tenant; return auth + ids."""
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
            is_active=product_active,
        )
        session.add(product)

        # A project that genuinely belongs to this product/tenant (for the
        # positive belonging case).
        project = Project(
            id=str(uuid.uuid4()),
            name=f"Project {suffix}",
            description="belongs to the product",
            mission="",
            tenant_key=tenant_key,
            product_id=product.id,
            status="inactive",
            series_number=uuid.uuid4().int % 9000 + 1,
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


@pytest_asyncio.fixture(scope="function")
async def active_product(db_manager) -> dict:
    return await _seed_user_with_product(db_manager, product_active=True)


@pytest_asyncio.fixture(scope="function")
async def inactive_product(db_manager) -> dict:
    return await _seed_user_with_product(db_manager, product_active=False)


# --------------------------------------------------------------------------
# REST task-create: two-sided through the service
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_with_belonging_project_succeeds(api_client: AsyncClient, active_product: dict) -> None:
    """POSITIVE: a project_id that belongs to the product/tenant still creates fine."""
    resp = await api_client.post(
        "/api/v1/tasks/",
        headers=active_product["headers"],
        json={
            "title": "task with a real project",
            "description": "valid belonging",
            "product_id": active_product["product_id"],
            "project_id": active_product["project_id"],
        },
    )
    assert resp.status_code in (200, 201), resp.text
    body = resp.json()
    assert body["project_id"] == active_product["project_id"]
    assert body["task_type"] == "TSK"
    assert (body["taxonomy_alias"] or "").startswith("TSK-")


@pytest.mark.asyncio
async def test_create_without_project_succeeds(api_client: AsyncClient, active_product: dict) -> None:
    """POSITIVE: omitting project_id is still allowed (product-only task)."""
    resp = await api_client.post(
        "/api/v1/tasks/",
        headers=active_product["headers"],
        json={
            "title": "product-only task",
            "description": "no project",
            "product_id": active_product["product_id"],
        },
    )
    assert resp.status_code in (200, 201), resp.text
    assert resp.json()["project_id"] is None


@pytest.mark.asyncio
async def test_create_with_foreign_project_now_rejected(api_client: AsyncClient, active_product: dict) -> None:
    """NEGATIVE (the merged half): a project_id that does NOT belong is now 404.

    The old REST endpoint skipped this check and would have created the task
    with a dangling/foreign project_id. The service half (log_task) enforces it.
    """
    resp = await api_client.post(
        "/api/v1/tasks/",
        headers=active_product["headers"],
        json={
            "title": "task with a foreign project",
            "description": "project does not belong",
            "product_id": active_product["product_id"],
            "project_id": str(uuid.uuid4()),  # not under this product/tenant
        },
    )
    assert resp.status_code == 404, resp.text


@pytest.mark.asyncio
async def test_create_on_inactive_product_rejected(api_client: AsyncClient, inactive_product: dict) -> None:
    """NEGATIVE (the other half): inactive product still returns 400 + same detail."""
    resp = await api_client.post(
        "/api/v1/tasks/",
        headers=inactive_product["headers"],
        json={
            "title": "task on inactive product",
            "description": "must be rejected",
            "product_id": inactive_product["product_id"],
        },
    )
    assert resp.status_code == 400, resp.text
    assert "active product" in resp.text.lower()


@pytest.mark.asyncio
async def test_create_on_missing_product_rejected(api_client: AsyncClient, active_product: dict) -> None:
    """NEGATIVE: an unknown product_id returns 404 + the same detail as before."""
    resp = await api_client.post(
        "/api/v1/tasks/",
        headers=active_product["headers"],
        json={
            "title": "task on missing product",
            "description": "must be rejected",
            "product_id": str(uuid.uuid4()),
        },
    )
    assert resp.status_code == 404, resp.text
    assert "not found" in resp.text.lower()


# --------------------------------------------------------------------------
# Password census: zero sync bcrypt call sites in the password service layer
# --------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parents[2]
_PASSWORD_SERVICE_FILES = [
    _REPO_ROOT / "src" / "giljo_mcp" / "services" / "user_service.py",
    _REPO_ROOT / "src" / "giljo_mcp" / "services" / "auth_service.py",
    _REPO_ROOT / "src" / "giljo_mcp" / "services" / "user_auth_service.py",
]
# Match actual CALLS (trailing "("), so docstring/comment mentions of the word
# "bcrypt.checkpw" without a paren do not count.
_BCRYPT_CALL = re.compile(r"bcrypt\.(hashpw|checkpw|gensalt)\s*\(")


@pytest.mark.parametrize("path", _PASSWORD_SERVICE_FILES, ids=lambda p: p.name)
def test_no_sync_bcrypt_call_sites_in_password_services(path: Path) -> None:
    """Every password/PIN hash + verify in these services routes through the
    shared async helper — so there must be ZERO direct bcrypt calls left."""
    source = path.read_text(encoding="utf-8")
    offenders = _BCRYPT_CALL.findall(source)
    assert not offenders, f"{path.name} still has direct bcrypt call sites: {offenders}"
