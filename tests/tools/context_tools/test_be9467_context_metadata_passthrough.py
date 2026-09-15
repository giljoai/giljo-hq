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
from giljo_mcp.models.tasks import Task
from giljo_mcp.services.comm_thread_service import CommThreadService
from giljo_mcp.services.taxonomy_ops import ensure_default_types_seeded
from giljo_mcp.tenant import TenantManager
from giljo_mcp.tools.context_tools.fetch_context import fetch_context
from giljo_mcp.tools.context_tools.get_tasks import get_tasks
from giljo_mcp.tools.context_tools.get_threads import THREADS_CATEGORY_CAP, get_threads


@pytest_asyncio.fixture
async def cleanup_tenants(db_manager):
    tenants: list[str] = []
    yield tenants
    for tk in tenants:
        async with db_manager.get_session_async(tenant_key=tk) as session:
            await session.execute(delete(Task).where(Task.tenant_key == tk))
            await session.execute(delete(CommThread).where(CommThread.tenant_key == tk))
            await session.execute(delete(Product).where(Product.tenant_key == tk))
            await session.commit()


async def _create_product(db_manager, tenant_key: str) -> str:
    product_id = str(uuid.uuid4())
    async with db_manager.get_session_async(tenant_key=tenant_key) as session:
        session.add(Product(id=product_id, tenant_key=tenant_key, name="BE-9467 Test Product"))
        await session.commit()
    return product_id


async def _seed_taxonomy(db_manager, tenant_key: str) -> None:
    async with db_manager.get_session_async(tenant_key=tenant_key) as session:
        with tenant_session_context(session, tenant_key):
            await ensure_default_types_seeded(session, tenant_key)
        await session.commit()


@pytest.mark.asyncio
async def test_threads_truncation_signal_reaches_get_context_caller(db_manager, cleanup_tenants: list[str]) -> None:
    tenant = TenantManager.generate_tenant_key()
    cleanup_tenants.append(tenant)
    product_id = await _create_product(db_manager, tenant)
    await _seed_taxonomy(db_manager, tenant)

    svc = CommThreadService(db_manager, TenantManager())
    for i in range(THREADS_CATEGORY_CAP + 1):
        await svc.create_thread(subject=f"BE-9467 cap test thread {i}", tenant_key=tenant)

    direct = await get_threads(tenant_key=tenant, db_manager=db_manager)
    assert direct["metadata"]["more_available"] is True

    response = await fetch_context(
        product_id=product_id,
        tenant_key=tenant,
        categories=["threads"],
        db_manager=db_manager,
    )

    assert len(response["data"]["threads"]) == THREADS_CATEGORY_CAP

    assert "categories" in response["metadata"], (
        "fetch_context's top-level metadata has no per-category pass-through "
        f"key at all; got metadata={response['metadata']!r}"
    )
    assert response["metadata"]["categories"]["threads"]["more_available"] is True


@pytest.mark.asyncio
async def test_open_count_reports_true_total_not_the_truncated_page(db_manager, cleanup_tenants: list[str]) -> None:
    tenant = TenantManager.generate_tenant_key()
    cleanup_tenants.append(tenant)
    product_id = await _create_product(db_manager, tenant)

    true_open_count = 55
    default_limit = 50
    assert true_open_count > default_limit, "test setup must exceed get_tasks' default limit to be a real repro"

    async with db_manager.get_session_async(tenant_key=tenant) as session:
        session.add_all(
            [
                Task(
                    id=str(uuid.uuid4()),
                    tenant_key=tenant,
                    product_id=product_id,
                    title=f"BE-9467 open task {i}",
                    status="pending",
                )
                for i in range(true_open_count)
            ]
        )
        await session.commit()

    result = await get_tasks(product_id=product_id, tenant_key=tenant, db_manager=db_manager)

    assert len(result["data"]["tasks"]) == default_limit

    assert result["data"]["open_count"] == true_open_count, (
        f"open_count reported {result['data']['open_count']} but the tenant genuinely has "
        f"{true_open_count} open tasks -- it is reporting len(page), not the true count"
    )
    assert result["metadata"]["truncated"] is True


@pytest.mark.asyncio
async def test_open_count_not_truncated_when_page_covers_everything(db_manager, cleanup_tenants: list[str]) -> None:
    tenant = TenantManager.generate_tenant_key()
    cleanup_tenants.append(tenant)
    product_id = await _create_product(db_manager, tenant)

    async with db_manager.get_session_async(tenant_key=tenant) as session:
        session.add_all(
            [
                Task(
                    id=str(uuid.uuid4()),
                    tenant_key=tenant,
                    product_id=product_id,
                    title=f"BE-9467 small board task {i}",
                    status="pending",
                )
                for i in range(3)
            ]
        )
        await session.commit()

    result = await get_tasks(product_id=product_id, tenant_key=tenant, db_manager=db_manager)

    assert len(result["data"]["tasks"]) == 3
    assert result["data"]["open_count"] == 3
    assert result["metadata"]["truncated"] is False
