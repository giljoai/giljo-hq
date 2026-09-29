# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import select

from giljo_mcp.database import tenant_session_context
from giljo_mcp.models.products import Product
from giljo_mcp.models.projects import Project, TaxonomyType
from giljo_mcp.repositories.project_repository import ProjectRepository
from giljo_mcp.repositories.taxonomy_repository import TaxonomyRepository
from giljo_mcp.services.project_service import ProjectService


@pytest.fixture
async def project_service(project_service_with_session):
    return project_service_with_session


@pytest_asyncio.fixture
async def be_taxonomy(db_session, test_tenant_key) -> TaxonomyType:
    tt = TaxonomyType(
        id=str(uuid4()),
        tenant_key=test_tenant_key,
        abbreviation="BE",
        label="Backend",
        color="#1f6feb",
        sort_order=1,
    )
    db_session.add(tt)
    await db_session.commit()
    await db_session.refresh(tt)
    return tt


@pytest_asyncio.fixture
async def active_product(db_session, test_tenant_key) -> Product:
    product = Product(
        id=str(uuid4()),
        name=f"BE-9663 Preview Product {uuid4().hex[:6]}",
        description="Product for BE-9663 preview/allocator agreement tests",
        tenant_key=test_tenant_key,
        is_active=True,
    )
    db_session.add(product)
    await db_session.commit()
    await db_session.refresh(product)
    return product


class TestPreviewAgreesWithAllocator:

    @pytest.mark.asyncio
    async def test_next_series_agrees_after_a_normal_soft_delete(
        self,
        project_service: ProjectService,
        db_session,
        test_tenant_key: str,
        active_product: Product,
        be_taxonomy: TaxonomyType,
    ):
        taxonomy_repo = TaxonomyRepository()
        project_repo = ProjectRepository()

        doomed = await project_service.create_project(
            name="Doomed",
            mission="m",
            description="d",
            product_id=active_product.id,
            tenant_key=test_tenant_key,
            project_type_id=be_taxonomy.id,
        )
        await project_service.deletion.delete_project(project_id=doomed.id)

        with tenant_session_context(db_session, test_tenant_key):
            preview_next = await taxonomy_repo.get_next_series_number(
                db_session, test_tenant_key, be_taxonomy.id, active_product.id
            )
        allocator_next = await project_repo.get_next_series_number_shared(
            db_session, test_tenant_key, active_product.id
        )

        assert preview_next == allocator_next, (
            f"preview ({preview_next}) and allocator ({allocator_next}) disagree after a normal soft-delete"
        )

    @pytest.mark.asyncio
    async def test_next_series_agrees_on_a_stale_deleted_at_row(
        self,
        project_service: ProjectService,
        db_session,
        test_tenant_key: str,
        active_product: Product,
        be_taxonomy: TaxonomyType,
    ):
        taxonomy_repo = TaxonomyRepository()
        project_repo = ProjectRepository()

        stale = await project_service.create_project(
            name="Stale",
            mission="m",
            description="d",
            product_id=active_product.id,
            tenant_key=test_tenant_key,
            project_type_id=be_taxonomy.id,
        )

        stale_row = (await db_session.execute(select(Project).where(Project.id == stale.id))).scalar_one()
        stale_row.deleted_at = datetime.now(UTC)
        await db_session.commit()

        with tenant_session_context(db_session, test_tenant_key):
            preview_next = await taxonomy_repo.get_next_series_number(
                db_session, test_tenant_key, be_taxonomy.id, active_product.id
            )
        allocator_next = await project_repo.get_next_series_number_shared(
            db_session, test_tenant_key, active_product.id
        )

        assert preview_next == allocator_next == stale.series_number + 1, (
            f"preview ({preview_next}) and allocator ({allocator_next}) disagree on a "
            f"stale-deleted_at row (must both be {stale.series_number + 1})"
        )

    @pytest.mark.asyncio
    async def test_check_series_available_agrees_with_check_duplicate_taxonomy_on_stale_row(
        self,
        project_service: ProjectService,
        db_session,
        test_tenant_key: str,
        active_product: Product,
        be_taxonomy: TaxonomyType,
    ):
        taxonomy_repo = TaxonomyRepository()
        project_repo = ProjectRepository()

        stale = await project_service.create_project(
            name="Stale",
            mission="m",
            description="d",
            product_id=active_product.id,
            tenant_key=test_tenant_key,
            project_type_id=be_taxonomy.id,
        )

        stale_row = (await db_session.execute(select(Project).where(Project.id == stale.id))).scalar_one()
        stale_row.deleted_at = datetime.now(UTC)
        await db_session.commit()

        with tenant_session_context(db_session, test_tenant_key):
            preview_available = await taxonomy_repo.check_series_available(
                db_session,
                test_tenant_key,
                be_taxonomy.id,
                stale.series_number,
                product_id=active_product.id,
            )
        allocator_is_duplicate = await project_repo.check_duplicate_taxonomy(
            db_session,
            test_tenant_key,
            active_product.id,
            be_taxonomy.id,
            stale.series_number,
            None,
        )

        assert preview_available is not allocator_is_duplicate, (
            f"preview says available={preview_available} but allocator says "
            f"is_duplicate={allocator_is_duplicate} for the SAME stale-deleted_at slot"
        )
        assert preview_available is False, "a stale-deleted_at row's slot must be reported unavailable"
