# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
Tests for ProjectService auto-assign series_number (Handover 0837a).

Verifies that create_project auto-assigns series_number when not provided,
preventing uq_project_taxonomy constraint violations for MCP callers.
"""

from datetime import UTC
from uuid import uuid4

import pytest

from giljo_mcp.models.products import Product
from giljo_mcp.models.projects import Project
from giljo_mcp.services.project_service import ProjectService


@pytest.fixture
async def project_service(project_service_with_session):
    """Alias for project_service_with_session"""
    return project_service_with_session


class TestAutoAssignSeriesNumber:
    """Test auto-assignment of series_number when not provided."""

    @pytest.mark.asyncio
    async def test_create_project_without_taxonomy_assigns_series_1(
        self, project_service: ProjectService, test_tenant_key: str, test_product
    ):
        """First project without taxonomy gets series_number=1."""
        project = await project_service.create_project(
            name="Project Alpha",
            mission="Test mission",
            tenant_key=test_tenant_key,
            product_id=test_product.id,
        )
        assert project.series_number == 1

    @pytest.mark.asyncio
    async def test_create_two_projects_without_taxonomy_unique_series(
        self, project_service: ProjectService, test_tenant_key: str, test_product
    ):
        """Two projects without taxonomy get sequential series numbers."""
        p1 = await project_service.create_project(
            name="Project One",
            mission="Mission one",
            tenant_key=test_tenant_key,
            product_id=test_product.id,
        )
        p2 = await project_service.create_project(
            name="Project Two",
            mission="Mission two",
            tenant_key=test_tenant_key,
            product_id=test_product.id,
        )
        assert p1.series_number == 1
        assert p2.series_number == 2

    @pytest.mark.asyncio
    async def test_create_many_projects_without_taxonomy(
        self, project_service: ProjectService, test_tenant_key: str, test_product
    ):
        """Can create 5+ projects without taxonomy — no constraint violation."""
        projects = []
        for i in range(5):
            p = await project_service.create_project(
                name=f"Project {i}",
                mission=f"Mission {i}",
                tenant_key=test_tenant_key,
                product_id=test_product.id,
            )
            projects.append(p)

        series_numbers = [p.series_number for p in projects]
        assert series_numbers == [1, 2, 3, 4, 5]

    @pytest.mark.asyncio
    async def test_explicit_taxonomy_still_works(
        self, project_service: ProjectService, test_tenant_key: str, test_product
    ):
        """Explicit series_number is preserved (no auto-assign)."""
        project = await project_service.create_project(
            name="Explicit Project",
            mission="Test mission",
            series_number=42,
            tenant_key=test_tenant_key,
            product_id=test_product.id,
        )
        assert project.series_number == 42

    @pytest.mark.asyncio
    async def test_auto_series_shared_globally_across_types(
        self, project_service: ProjectService, test_tenant_key: str, db_session, test_product
    ):
        """BE-6049b: auto-series is ONE global line per product, shared across types.

        Previously each ``project_type_id`` counted independently (FE=1, BE=1).
        BE-6049b decouples the tag from the number: the counter is now keyed on
        ``(tenant, product)`` only, so an FE project then a BE project get 1, 2 —
        a single continue-upward sequence regardless of tag.
        """
        from giljo_mcp.models.projects import TaxonomyType

        # Create two project types
        pt1 = TaxonomyType(
            id=str(uuid4()),
            tenant_key=test_tenant_key,
            label="Frontend",
            abbreviation="FE",
        )
        pt2 = TaxonomyType(
            id=str(uuid4()),
            tenant_key=test_tenant_key,
            label="Backend",
            abbreviation="BE",
        )
        db_session.add_all([pt1, pt2])
        await db_session.commit()

        p1 = await project_service.create_project(
            name="FE Project",
            mission="Frontend work",
            project_type_id=pt1.id,
            tenant_key=test_tenant_key,
            product_id=test_product.id,
        )
        p2 = await project_service.create_project(
            name="BE Project",
            mission="Backend work",
            project_type_id=pt2.id,
            tenant_key=test_tenant_key,
            product_id=test_product.id,
        )
        # One global line: the BE project continues from the FE project's number.
        assert p1.series_number == 1
        assert p2.series_number == 2

    @pytest.mark.asyncio
    async def test_auto_series_excludes_soft_deleted(
        self, project_service: ProjectService, test_tenant_key: str, db_session, test_product
    ):
        """Auto-series EXCLUDES soft-deleted rows from the high-water mark.

        BE-5065 / serial-counter fix (decision C): the next series_number is
        computed over the ACTIVE pool only (``deleted_at IS NULL``). A
        soft-deleted ``9999`` left in the max would otherwise mint ``10000`` —
        the root cause of the 5-digit serials seen in prod. The partial unique
        index on ``series_number`` (``WHERE deleted_at IS NULL``) lets the new
        active row reuse the soft-deleted row's number without colliding.
        """
        from datetime import datetime

        # Create a soft-deleted project with series_number=1
        deleted_project = Project(
            id=str(uuid4()),
            name="Deleted Project",
            description="Deleted project description",
            mission="Old mission",
            tenant_key=test_tenant_key,
            status="inactive",
            series_number=1,
            product_id=test_product.id,
            deleted_at=datetime.now(UTC),
        )
        db_session.add(deleted_project)
        await db_session.commit()

        # New project reuses series_number=1: the soft-deleted row is excluded
        # from the high-water mark (active pool is empty -> max(0)+1 == 1).
        project = await project_service.create_project(
            name="New Project",
            mission="New mission",
            tenant_key=test_tenant_key,
            product_id=test_product.id,
        )
        assert project.series_number == 1

    @pytest.mark.asyncio
    async def test_different_tenants_independent_series(
        self, project_service_with_session, test_tenant_key: str, db_manager, tenant_manager, db_session, test_product
    ):
        """Different tenants have independent series numbering."""
        from giljo_mcp.tenant import TenantManager

        # Create project for first tenant
        p1 = await project_service_with_session.create_project(
            name="Tenant1 Project",
            mission="Mission",
            tenant_key=test_tenant_key,
            product_id=test_product.id,
        )
        assert p1.series_number == 1

        # Create project for second tenant. It needs a product of its OWN:
        # product_id is NOT NULL (BE-9437) and the serial line is keyed on
        # (tenant, product), so reusing tenant 1's product would not be a second
        # tenant at all -- it would be the same bucket under a different key.
        other_tenant = TenantManager.generate_tenant_key()
        other_product = Product(
            id=str(uuid4()),
            name=f"Other Tenant Product {uuid4().hex[:6]}",
            description="second tenant's product",
            tenant_key=other_tenant,
            is_active=True,
        )
        db_session.add(other_product)
        await db_session.commit()

        p2 = await project_service_with_session.create_project(
            name="Tenant2 Project",
            mission="Mission",
            tenant_key=other_tenant,
            product_id=other_product.id,
        )
        assert p2.series_number == 1
