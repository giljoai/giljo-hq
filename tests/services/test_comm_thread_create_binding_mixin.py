# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest

from giljo_mcp.database import tenant_session_context
from giljo_mcp.models import Product, Project
from giljo_mcp.services.comm_thread_service import CommThreadService
from giljo_mcp.services.product_service import ProductAmbiguousError
from giljo_mcp.services.taxonomy_ops import ensure_default_types_seeded
from giljo_mcp.tenant import TenantManager


pytestmark = pytest.mark.asyncio


def _tk(suffix: str) -> str:
    return f"tk_fe9530_bind_{suffix}_{uuid.uuid4().hex[:8]}"


def _service(db_manager, db_session) -> CommThreadService:
    return CommThreadService(db_manager, TenantManager(), session=db_session)


async def _seed(db_session, tenant: str) -> None:
    with tenant_session_context(db_session, tenant):
        await ensure_default_types_seeded(db_session, tenant)


async def _seed_product(db_session, tenant: str, *, is_active: bool = True) -> str:
    with tenant_session_context(db_session, tenant):
        product = Product(
            id=str(uuid.uuid4()),
            tenant_key=tenant,
            name=f"Bind Product {uuid.uuid4().hex[:6]}",
            description="seeded",
            is_active=is_active,
        )
        db_session.add(product)
        await db_session.flush()
    return product.id


async def _seed_project_for_product(db_session, tenant: str, product_id: str) -> str:
    with tenant_session_context(db_session, tenant):
        project = Project(
            id=str(uuid.uuid4()),
            name=f"Bind Project {uuid.uuid4().hex[:6]}",
            description="binding test project",
            mission="exercise product resolution",
            status="active",
            tenant_key=tenant,
            product_id=product_id,
            series_number=1,
            execution_mode="claude_code_cli",
            created_at=datetime.now(UTC),
        )
        db_session.add(project)
        await db_session.flush()
    return project.id


async def test_project_id_derives_the_projects_own_product(db_manager, db_session):
    tenant = _tk("project")
    await _seed(db_session, tenant)
    project_product = await _seed_product(db_session, tenant, is_active=False)
    decoy_product = await _seed_product(db_session, tenant, is_active=True)
    project_id = await _seed_project_for_product(db_session, tenant, project_product)
    svc = _service(db_manager, db_session)

    async with svc._scoped_session(tenant) as session:
        resolved = await svc._resolve_create_product_id(
            session, tenant, product_id=None, project_id=project_id, sequence_run_id=None
        )

    assert resolved == project_product
    assert resolved != decoy_product


async def test_single_product_resolves_silently(db_manager, db_session):
    tenant = _tk("single")
    await _seed(db_session, tenant)
    product_id = await _seed_product(db_session, tenant, is_active=True)
    svc = _service(db_manager, db_session)

    async with svc._scoped_session(tenant) as session:
        resolved = await svc._resolve_create_product_id(
            session, tenant, product_id=None, project_id=None, sequence_run_id=None
        )

    assert resolved == product_id


async def test_multiple_products_with_no_project_raises_ambiguous(db_manager, db_session):
    tenant = _tk("ambiguous")
    await _seed(db_session, tenant)
    await _seed_product(db_session, tenant, is_active=True)
    await _seed_product(db_session, tenant, is_active=True)
    svc = _service(db_manager, db_session)

    with pytest.raises(ProductAmbiguousError):
        async with svc._scoped_session(tenant) as session:
            await svc._resolve_create_product_id(
                session, tenant, product_id=None, project_id=None, sequence_run_id=None
            )
