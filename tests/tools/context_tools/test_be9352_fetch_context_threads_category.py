# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy import delete

from giljo_mcp.database import tenant_session_context
from giljo_mcp.models.comm import CommThread
from giljo_mcp.models.products import Product
from giljo_mcp.models.sequence_runs import SequenceRun
from giljo_mcp.services.comm_thread_service import CommThreadService
from giljo_mcp.services.taxonomy_ops import ensure_default_types_seeded
from giljo_mcp.tenant import TenantManager
from giljo_mcp.tools.context_tools.fetch_context import CATEGORY_TOOLS, fetch_context
from giljo_mcp.tools.context_tools.get_threads import THREADS_CATEGORY_CAP, get_threads


@pytest_asyncio.fixture
async def cleanup_tenants(db_manager):
    tenants: list[str] = []
    yield tenants
    for tk in tenants:
        async with db_manager.get_session_async(tenant_key=tk) as session:
            await session.execute(delete(CommThread).where(CommThread.tenant_key == tk))
            await session.execute(delete(SequenceRun).where(SequenceRun.tenant_key == tk))
            await session.execute(delete(Product).where(Product.tenant_key == tk))
            await session.commit()


async def _create_product(db_manager, tenant_key: str) -> str:
    product_id = str(uuid.uuid4())
    async with db_manager.get_session_async(tenant_key=tenant_key) as session:
        session.add(Product(id=product_id, tenant_key=tenant_key, name="Threads Category Test Product"))
        await session.commit()
    return product_id


async def _create_sequence_run(db_manager, tenant_key: str) -> str:
    async with db_manager.get_session_async(tenant_key=tenant_key) as session:
        run = SequenceRun(
            tenant_key=tenant_key,
            project_ids=[],
            resolved_order=[],
            execution_mode="multi_terminal",
        )
        session.add(run)
        await session.commit()
        return run.id


async def _seed_taxonomy(db_manager, tenant_key: str) -> None:
    async with db_manager.get_session_async(tenant_key=tenant_key) as session:
        with tenant_session_context(session, tenant_key):
            await ensure_default_types_seeded(session, tenant_key)
        await session.commit()


def test_threads_category_is_registered() -> None:
    assert "threads" in CATEGORY_TOOLS


def test_listing_profile_did_not_grow() -> None:
    from api.endpoints.mcp_tools._base import _LISTING_PROFILE_TOOLS

    assert {"list_threads", "get_thread_history"} & _LISTING_PROFILE_TOOLS == set()


@pytest.mark.asyncio
async def test_threads_category_is_tenant_scoped_and_includes_null_product(
    db_manager, cleanup_tenants: list[str]
) -> None:
    tenant_a = TenantManager.generate_tenant_key()
    tenant_b = TenantManager.generate_tenant_key()
    cleanup_tenants.append(tenant_a)
    cleanup_tenants.append(tenant_b)

    product_a = await _create_product(db_manager, tenant_a)
    product_b = await _create_product(db_manager, tenant_b)
    await _seed_taxonomy(db_manager, tenant_a)
    await _seed_taxonomy(db_manager, tenant_b)
    run_a = await _create_sequence_run(db_manager, tenant_a)

    svc = CommThreadService(db_manager, TenantManager())
    thread_a1 = await svc.create_thread(subject="A product-scoped thread", product_id=product_a, tenant_key=tenant_a)
    thread_a2 = await svc.create_thread(subject="A standalone thread", sequence_run_id=run_a, tenant_key=tenant_a)
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
    tenant = TenantManager.generate_tenant_key()
    cleanup_tenants.append(tenant)
    await _seed_taxonomy(db_manager, tenant)

    svc = CommThreadService(db_manager, TenantManager())
    for i in range(THREADS_CATEGORY_CAP):
        await svc.create_thread(subject=f"At-cap thread {i}", tenant_key=tenant)

    direct = await get_threads(tenant_key=tenant, db_manager=db_manager)
    assert len(direct["data"]) == 25
    assert direct["metadata"]["more_available"] is False
