# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""Endpoint-layer regression test for BE6004C-2 (RC-1 + RC-3).

Bug: ``GET /api/v1/taxonomy-types/`` opens its session via ``Depends(get_db)``
and the underlying CRUD helpers filter by an explicit ``WHERE tenant_key=``
predicate. Before the fix the session carried no tenant context (the
AuthMiddleware ContextVar does not cross the BaseHTTPMiddleware -> endpoint task
boundary, RC-1) and the fail-closed guard rejected the explicit predicate as
self-authorization (RC-3), producing an HTTP 500.

The fix threads ``request.state.tenant_key`` (set by AuthMiddleware, survives the
task boundary) into the session factory so ``session.info["tenant_key"]`` is
stamped before any query runs. This test exercises the FAILING layer -- the
endpoint through real FastAPI DI via the ASGI TestClient (NOT a service stub) --
per the CLAUDE.md failing-layer rule (BE-5042 lesson).

Parallel-safe: every test seeds its own unique tenant (``tk_...``) so concurrent
xdist workers never collide; no module-level mutable state; no test ordering
dependency. Isolation is by unique tenant_key (the proven ``tests/api`` pattern),
not transaction rollback, because the ASGI app opens its own pooled connections
that a single ``TransactionalTestContext`` transaction cannot wrap.

Project: BE6004C-2 (RC-1 + RC-3).
"""

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
    """Create org + user + 2 taxonomy types in a fresh tenant; return auth + ids."""
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

        # Two explicit taxonomy types so we can assert tenant-scoped retrieval
        # without depending on the lazy-seeded defaults (which are also created
        # on first GET; we assert OUR rows are present and foreign ones are not).
        #
        # The ``abbreviation`` column is String(4) drawn from a tiny namespace,
        # so two independently-seeded tenants can legitimately mint the SAME
        # code -- it is NOT a tenant-unique identity. We therefore capture each
        # row's unique ``id`` (a UUID) so the no-leak assertion can key on the
        # real isolation boundary (tenant_key / row id) instead of the
        # collision-prone abbreviation (the BE-6162 flake).
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
    """RC-1/RC-3: get_db-backed endpoint with explicit tenant predicates returns 200.

    Before BE6004C-2 this 500'd: no tenant on the get_db session -> fail-closed
    guard rejected the explicit WHERE tenant_key= predicate. After the fix,
    request.state.tenant_key is threaded into the session.
    """
    resp = await api_client.get("/api/v1/taxonomy-types/", headers=seeded_taxonomy["headers"])
    assert resp.status_code == 200, resp.text

    body = resp.json()
    assert isinstance(body, list)

    # Every returned row is scoped to the caller's tenant (no leakage).
    returned_tenants = {row["tenant_key"] for row in body}
    assert returned_tenants == {seeded_taxonomy["tenant_key"]}, returned_tenants

    # The explicitly seeded types for this tenant are present.
    returned_abbrs = {row["abbreviation"] for row in body}
    assert seeded_taxonomy["abbreviations"].issubset(returned_abbrs), returned_abbrs


@pytest.mark.asyncio
async def test_list_taxonomy_types_does_not_leak_other_tenants(api_client: AsyncClient, db_manager) -> None:
    """Tenant A's listing must not include Tenant B's taxonomy types."""
    tenant_a = await _seed_tenant_with_taxonomy(db_manager)
    tenant_b = await _seed_tenant_with_taxonomy(db_manager)

    resp = await api_client.get("/api/v1/taxonomy-types/", headers=tenant_a["headers"])
    assert resp.status_code == 200, resp.text

    body = resp.json()
    # Isolation is keyed on tenant_key (a unique UUID per seed) -- the actual
    # isolation boundary -- so every returned row belongs to tenant A and none
    # to tenant B. We deliberately do NOT compare abbreviations: that column is
    # String(4) from a tiny namespace, so tenant A and tenant B can coincidentally
    # mint the same code, which made the old `isdisjoint(abbreviations)` check
    # fail ~1/256 even with zero leakage (BE-6162). Row `id` (a UUID) is the
    # collision-free way to prove tenant B's specific rows never appear.
    returned_tenants = {row["tenant_key"] for row in body}
    assert returned_tenants == {tenant_a["tenant_key"]}, returned_tenants

    returned_ids = {row["id"] for row in body}
    assert returned_ids.isdisjoint(tenant_b["type_ids"]), returned_ids & tenant_b["type_ids"]
