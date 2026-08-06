# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""Regression test for the 'threads' get_context category (Q-08 / BE-9352).

CTO ruling Q-08: the product already advertises 46 MCP tools, so a read-shaped
feature (surfacing the tenant's Hub threads to fetch_context) arrives as a
CATEGORY of the existing multiplexer, not as new standalone tools
(list_threads / get_thread_history / search_threads stay OFF the advertised
'listing' marketplace-connector profile).

This exercises the fix at the fetch_context dispatch layer: categories=
["threads"] routes through CommThreadService.list_threads (structurally
read-only -- no write path, unlike get_thread_history / get_my_turn which
write behind as_participant/mark_read), tenant-scoped ONLY (never
product-scoped -- see get_threads.py docstring for why product-scoping is
wrong here), capped at a fixed, non-depth-tunable 25.

Parallel-safety: DB-touching; uses the db_manager fixture directly (mirrors
test_fetch_context_chain_category.py) with a function-scoped tenant-key
collector that deletes only the rows this test created -- no module-level
mutable state, no ordering dependency.

Edition Scope: Both.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy import delete

from giljo_mcp.database import tenant_session_context
from giljo_mcp.models.comm import CommThread
from giljo_mcp.models.products import Product
from giljo_mcp.services.comm_thread_service import CommThreadService
from giljo_mcp.services.taxonomy_ops import ensure_default_types_seeded
from giljo_mcp.tenant import TenantManager
from giljo_mcp.tools.context_tools.fetch_context import CATEGORY_TOOLS, fetch_context
from giljo_mcp.tools.context_tools.get_threads import THREADS_CATEGORY_CAP, get_threads


@pytest_asyncio.fixture
async def cleanup_tenants(db_manager):
    """Collect tenant_keys created by a test; delete their rows at teardown."""
    tenants: list[str] = []
    yield tenants
    for tk in tenants:
        async with db_manager.get_session_async(tenant_key=tk) as session:
            await session.execute(delete(CommThread).where(CommThread.tenant_key == tk))
            await session.execute(delete(Product).where(Product.tenant_key == tk))
            await session.commit()


async def _create_product(db_manager, tenant_key: str) -> str:
    product_id = str(uuid.uuid4())
    async with db_manager.get_session_async(tenant_key=tenant_key) as session:
        session.add(Product(id=product_id, tenant_key=tenant_key, name="Threads Category Test Product"))
        await session.commit()
    return product_id


async def _seed_taxonomy(db_manager, tenant_key: str) -> None:
    """comm_thread create_thread mints a CHT-#### serial and 422s if the
    reserved CHT taxonomy type is absent for the tenant (see
    CommThreadRepository._ensure_cht_type) -- a fresh test tenant needs it
    seeded, mirroring test_fetch_context_chain_category.py's setup."""
    async with db_manager.get_session_async(tenant_key=tenant_key) as session:
        with tenant_session_context(session, tenant_key):
            await ensure_default_types_seeded(session, tenant_key)
        await session.commit()


def test_threads_category_is_registered() -> None:
    """RED-first lock: before implementation 'threads' was absent from
    CATEGORY_TOOLS, so fetch_context(categories=['threads']) raised
    ValidationError('Invalid categories...'). Locks the fix in place."""
    assert "threads" in CATEGORY_TOOLS


def test_listing_profile_did_not_grow() -> None:
    """The other half of the Q-08 ruling: the category exists AND the
    advertised 'listing' marketplace-connector profile roster stayed at 11 --
    none of the standalone thread-suite tools were added to reach it."""
    from api.endpoints.mcp_tools._base import _LISTING_PROFILE_TOOLS

    assert {"list_threads", "get_thread_history", "search_threads"} & _LISTING_PROFILE_TOOLS == set()


@pytest.mark.asyncio
async def test_threads_category_is_tenant_scoped_and_includes_null_product(
    db_manager, cleanup_tenants: list[str]
) -> None:
    """Seed TWO tenants -- the only setup that can catch a dropped tenant_key
    filter. Tenant A gets 2 threads (one product-scoped, one standalone with
    product_id=None); tenant B gets 1. fetch_context(categories=['threads'])
    on A must return exactly A's two thread ids, never B's, and MUST include
    the product_id=None thread (Q-08: tenant-scoped only, never product-scoped
    -- product-scoping would silently drop it)."""
    tenant_a = TenantManager.generate_tenant_key()
    tenant_b = TenantManager.generate_tenant_key()
    cleanup_tenants.append(tenant_a)
    cleanup_tenants.append(tenant_b)

    product_a = await _create_product(db_manager, tenant_a)
    product_b = await _create_product(db_manager, tenant_b)
    await _seed_taxonomy(db_manager, tenant_a)
    await _seed_taxonomy(db_manager, tenant_b)

    svc = CommThreadService(db_manager, TenantManager())
    thread_a1 = await svc.create_thread(subject="A product-scoped thread", product_id=product_a, tenant_key=tenant_a)
    thread_a2 = await svc.create_thread(subject="A standalone thread", product_id=None, tenant_key=tenant_a)
    thread_b1 = await svc.create_thread(subject="B thread", product_id=product_b, tenant_key=tenant_b)

    response = await fetch_context(
        product_id=product_a,
        tenant_key=tenant_a,
        categories=["threads"],
        db_manager=db_manager,
    )

    assert "threads" in response["categories_returned"]
    assert "threads" not in response.get("categories_empty", [])
    assert "errors" not in response

    returned_ids = {t["thread_id"] for t in response["data"]["threads"]}
    assert thread_a1["thread_id"] in returned_ids
    assert thread_a2["thread_id"] in returned_ids
    assert thread_b1["thread_id"] not in returned_ids

    null_product_entry = next(t for t in response["data"]["threads"] if t["thread_id"] == thread_a2["thread_id"])
    assert null_product_entry["product_id"] is None


@pytest.mark.asyncio
async def test_threads_category_zero_threads_is_empty_not_an_error(db_manager, cleanup_tenants: list[str]) -> None:
    """A tenant with zero threads gets a clean empty list -- not an error
    string -- so an empty category never reads as a failure."""
    tenant = TenantManager.generate_tenant_key()
    cleanup_tenants.append(tenant)
    product_id = await _create_product(db_manager, tenant)

    response = await fetch_context(
        product_id=product_id,
        tenant_key=tenant,
        categories=["threads"],
        db_manager=db_manager,
    )

    assert response["data"]["threads"] == []
    assert "threads" in response["categories_returned"]
    assert "threads" in response.get("categories_empty", [])
    assert "errors" not in response


@pytest.mark.asyncio
async def test_threads_category_caps_at_25_and_flags_more_available(db_manager, cleanup_tenants: list[str]) -> None:
    """THREADS_CATEGORY_CAP is the one piece of this change that exists purely
    for correctness (see get_threads.py's docstring: unbounded, the response
    ceiling trimmer would strip subject/thread_id/chat_id into truncated husks
    before ever reaching cap) -- and nothing else in this file seeds past it,
    so a deleted cap or a dropped ``+ 1`` would stay green without this case.

    Seeds 26 threads. Exactly 25 must come back through fetch_context (not
    "<= 25" -- exact, so raising the cap fails too). ``more_available`` is
    computed in get_threads.py's own metadata, which fetch_context does not
    currently forward to callers (see the comment at that construction) --
    calling the wrapper directly is the only way to observe the signal today.
    """
    tenant = TenantManager.generate_tenant_key()
    cleanup_tenants.append(tenant)
    product_id = await _create_product(db_manager, tenant)
    await _seed_taxonomy(db_manager, tenant)

    svc = CommThreadService(db_manager, TenantManager())
    for i in range(THREADS_CATEGORY_CAP + 1):
        await svc.create_thread(subject=f"Cap test thread {i}", tenant_key=tenant)

    response = await fetch_context(
        product_id=product_id,
        tenant_key=tenant,
        categories=["threads"],
        db_manager=db_manager,
    )
    assert len(response["data"]["threads"]) == 25

    direct = await get_threads(tenant_key=tenant, db_manager=db_manager)
    assert len(direct["data"]) == 25
    assert direct["metadata"]["more_available"] is True


@pytest.mark.asyncio
async def test_threads_category_at_cap_reports_no_more_available(db_manager, cleanup_tenants: list[str]) -> None:
    """Sibling boundary case: exactly AT the cap (25 threads, not 26),
    ``more_available`` must be False. The off-by-one that would break this
    lives in ``limit=THREADS_CATEGORY_CAP + 1`` -- simplify it to
    ``limit=THREADS_CATEGORY_CAP`` and the wrapper can never see a 26th row
    to know whether more exist."""
    tenant = TenantManager.generate_tenant_key()
    cleanup_tenants.append(tenant)
    await _seed_taxonomy(db_manager, tenant)

    svc = CommThreadService(db_manager, TenantManager())
    for i in range(THREADS_CATEGORY_CAP):
        await svc.create_thread(subject=f"At-cap thread {i}", tenant_key=tenant)

    direct = await get_threads(tenant_key=tenant, db_manager=db_manager)
    assert len(direct["data"]) == 25
    assert direct["metadata"]["more_available"] is False
