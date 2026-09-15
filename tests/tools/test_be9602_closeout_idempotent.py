# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import random
import uuid

import pytest
from sqlalchemy import func, select

from giljo_mcp.models.organizations import Organization
from giljo_mcp.models.product_memory_entry import ProductMemoryEntry
from giljo_mcp.models.products import Product
from giljo_mcp.models.projects import Project
from giljo_mcp.tenant import TenantManager
from giljo_mcp.tools.project_closeout import close_project_and_update_memory


pytestmark = pytest.mark.asyncio


async def _seed(session, tenant_key: str):
    suffix = uuid.uuid4().hex[:8]
    session.add(Organization(name=f"Org {suffix}", slug=f"org-{suffix}", tenant_key=tenant_key, is_active=True))
    await session.flush()
    product = Product(
        id=str(uuid.uuid4()),
        name=f"BE9602 Product {suffix}",
        description="closeout idempotency",
        tenant_key=tenant_key,
        is_active=True,
        product_memory={},
    )
    session.add(product)
    await session.flush()
    project = Project(
        id=str(uuid.uuid4()),
        tenant_key=tenant_key,
        product_id=product.id,
        name=f"BE9602 Project {suffix}",
        description="closeout idempotency",
        mission="m",
        status="active",
        staging_status="staging_complete",
        series_number=random.randint(1, 9000),
    )
    session.add(project)
    await session.flush()
    return product, project


async def _closeout(session, db_manager, tenant_key, project_id, *, summary="Shipped the thing"):
    return await close_project_and_update_memory(
        project_id=project_id,
        summary=summary,
        key_outcomes=["one outcome"],
        decisions_made=["one decision"],
        tenant_key=tenant_key,
        db_manager=db_manager,
        session=session,
        git_commits=[{"sha": "abc1234", "message": "Ship it"}],
    )


async def test_second_closeout_returns_first_entry_and_writes_nothing(db_session, db_manager):
    tenant_key = TenantManager.generate_tenant_key()
    _product, project = await _seed(db_session, tenant_key)

    first = await _closeout(db_session, db_manager, tenant_key, project.id)
    assert first.get("entry_id"), first

    second = await _closeout(db_session, db_manager, tenant_key, project.id)

    assert second.get("entry_id") == first["entry_id"], second
    assert second.get("sequence_number") == first["sequence_number"], second
    assert second.get("idempotent") is True, second

    count = await db_session.scalar(
        select(func.count())
        .select_from(ProductMemoryEntry)
        .where(
            ProductMemoryEntry.project_id == project.id,
            ProductMemoryEntry.tenant_key == tenant_key,
            ProductMemoryEntry.entry_type == "project_closeout",
        )
    )
    assert count == 1


async def test_second_closeout_with_different_content_writes_a_new_entry(db_session, db_manager):
    tenant_key = TenantManager.generate_tenant_key()
    _product, project = await _seed(db_session, tenant_key)

    first = await _closeout(db_session, db_manager, tenant_key, project.id)
    second = await _closeout(db_session, db_manager, tenant_key, project.id, summary="Revived and shipped again")

    assert second.get("entry_id") and second["entry_id"] != first["entry_id"], second
    assert second.get("idempotent") is None, second
    assert second["sequence_number"] > first["sequence_number"]

    count = await db_session.scalar(
        select(func.count())
        .select_from(ProductMemoryEntry)
        .where(ProductMemoryEntry.project_id == project.id, ProductMemoryEntry.entry_type == "project_closeout")
    )
    assert count == 2
