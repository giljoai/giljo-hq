# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
Tests for ProductAgentAssignment service, repository, and model.

Covers:
- Model creation and constraints
- Repository CRUD (tenant-isolated)
- Service validation, toggle, bulk assign
- Tenant isolation (cross-tenant access denied)
"""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
import pytest_asyncio

from giljo_mcp.models.product_agent_assignment import ProductAgentAssignment
from giljo_mcp.models.products import Product
from giljo_mcp.models.templates import AgentTemplate
from giljo_mcp.repositories.product_agent_assignment_repository import (
    ProductAgentAssignmentRepository,
)
from giljo_mcp.services.product_agent_assignment_service import (
    ProductAgentAssignmentService,
)
from giljo_mcp.tenant import TenantManager


# ============================================================================
# Fixtures
# ============================================================================


@pytest_asyncio.fixture
async def tenant_a_key():
    return TenantManager.generate_tenant_key()


@pytest_asyncio.fixture
async def tenant_b_key():
    return TenantManager.generate_tenant_key()


@pytest_asyncio.fixture
async def product_a(db_session, tenant_a_key):
    product = Product(
        id=str(uuid4()),
        name=f"Product A {uuid4().hex[:6]}",
        description="Product for assignment tests",
        tenant_key=tenant_a_key,
        is_active=True,
        created_at=datetime.now(UTC),
    )
    db_session.add(product)
    await db_session.commit()
    await db_session.refresh(product)
    return product


@pytest_asyncio.fixture
async def product_b(db_session, tenant_b_key):
    product = Product(
        id=str(uuid4()),
        name=f"Product B {uuid4().hex[:6]}",
        description="Product for other tenant",
        tenant_key=tenant_b_key,
        is_active=True,
        created_at=datetime.now(UTC),
    )
    db_session.add(product)
    await db_session.commit()
    await db_session.refresh(product)
    return product


@pytest_asyncio.fixture
async def templates_a(db_session, tenant_a_key):
    """Create 3 agent templates for tenant A."""
    templates = []
    for name in ["orchestrator", "implementer", "analyzer"]:
        t = AgentTemplate(
            id=str(uuid4()),
            tenant_key=tenant_a_key,
            name=f"{name}-{uuid4().hex[:4]}",
            role=name,
            description=f"Test {name} template",
            system_instructions=f"You are a {name} agent.",
            is_active=True,
        )
        db_session.add(t)
        templates.append(t)
    await db_session.commit()
    for t in templates:
        await db_session.refresh(t)
    return templates


@pytest_asyncio.fixture
async def templates_b(db_session, tenant_b_key):
    """Create a template for tenant B."""
    t = AgentTemplate(
        id=str(uuid4()),
        tenant_key=tenant_b_key,
        name=f"other-template-{uuid4().hex[:4]}",
        role="implementer",
        description="Other tenant template",
        system_instructions="You are an other-tenant agent.",
        is_active=True,
    )
    db_session.add(t)
    await db_session.commit()
    await db_session.refresh(t)
    return [t]


@pytest_asyncio.fixture
def repo():
    return ProductAgentAssignmentRepository()


@pytest_asyncio.fixture
def service_a(db_manager, tenant_a_key, db_session):
    return ProductAgentAssignmentService(
        db_manager=db_manager,
        tenant_key=tenant_a_key,
        test_session=db_session,
    )


@pytest_asyncio.fixture
def service_b(db_manager, tenant_b_key, db_session):
    return ProductAgentAssignmentService(
        db_manager=db_manager,
        tenant_key=tenant_b_key,
        test_session=db_session,
    )


# ============================================================================
# Model Tests
# ============================================================================


class TestProductAgentAssignmentModel:
    """Test the ORM model structure."""

    def test_table_name(self):
        assert ProductAgentAssignment.__tablename__ == "product_agent_assignments"

    def test_has_tenant_key_column(self):
        col = ProductAgentAssignment.__table__.c.tenant_key
        assert col.nullable is False

    def test_has_product_id_fk(self):
        col = ProductAgentAssignment.__table__.c.product_id
        assert col.nullable is False
        fks = list(col.foreign_keys)
        assert len(fks) == 1
        assert "products.id" in str(fks[0].target_fullname)

    def test_has_template_id_fk(self):
        col = ProductAgentAssignment.__table__.c.template_id
        assert col.nullable is False
        fks = list(col.foreign_keys)
        assert len(fks) == 1
        assert "agent_templates.id" in str(fks[0].target_fullname)

    def test_is_active_defaults_true(self):
        col = ProductAgentAssignment.__table__.c.is_active
        assert col.default.arg is True

    def test_unique_constraint_exists(self):
        constraints = [c.name for c in ProductAgentAssignment.__table__.constraints if hasattr(c, "name") and c.name]
        assert "uq_product_template_assignment" in constraints

    def test_repr(self):
        a = ProductAgentAssignment(
            id="test-id",
            product_id="prod-1",
            template_id="tpl-1",
            is_active=True,
        )
        r = repr(a)
        assert "ProductAgentAssignment" in r
        assert "prod-1" in r
        assert "tpl-1" in r


# ============================================================================
# Repository Tests
# ============================================================================


class TestProductAgentAssignmentRepository:
    """Test the repository layer with real database."""

    @pytest.mark.asyncio
    async def test_upsert_creates_new_assignment(self, db_session, repo, product_a, templates_a, tenant_a_key):
        assignment = await repo.upsert_assignment(
            db_session, product_a.id, templates_a[0].id, tenant_a_key, is_active=True
        )
        assert assignment.product_id == product_a.id
        assert assignment.template_id == templates_a[0].id
        assert assignment.is_active is True
        assert assignment.tenant_key == tenant_a_key

    @pytest.mark.asyncio
    async def test_upsert_updates_existing_assignment(self, db_session, repo, product_a, templates_a, tenant_a_key):
        # Create
        await repo.upsert_assignment(db_session, product_a.id, templates_a[0].id, tenant_a_key, is_active=True)
        # Update
        updated = await repo.upsert_assignment(
            db_session, product_a.id, templates_a[0].id, tenant_a_key, is_active=False
        )
        assert updated.is_active is False

    @pytest.mark.asyncio
    async def test_get_assignments_for_product(self, db_session, repo, product_a, templates_a, tenant_a_key):
        for t in templates_a:
            await repo.upsert_assignment(db_session, product_a.id, t.id, tenant_a_key, is_active=True)
        await db_session.flush()

        assignments = await repo.get_assignments_for_product(db_session, product_a.id, tenant_a_key)
        assert len(assignments) == 3

    @pytest.mark.asyncio
    async def test_get_assignments_active_only(self, db_session, repo, product_a, templates_a, tenant_a_key):
        await repo.upsert_assignment(db_session, product_a.id, templates_a[0].id, tenant_a_key, is_active=True)
        await repo.upsert_assignment(db_session, product_a.id, templates_a[1].id, tenant_a_key, is_active=False)
        await db_session.flush()

        active = await repo.get_assignments_for_product(db_session, product_a.id, tenant_a_key, active_only=True)
        assert len(active) == 1
        assert active[0].template_id == templates_a[0].id

    @pytest.mark.asyncio
    async def test_get_active_template_ids(self, db_session, repo, product_a, templates_a, tenant_a_key):
        await repo.upsert_assignment(db_session, product_a.id, templates_a[0].id, tenant_a_key, is_active=True)
        await repo.upsert_assignment(db_session, product_a.id, templates_a[1].id, tenant_a_key, is_active=False)
        await db_session.flush()

        active_ids = await repo.get_active_template_ids_for_product(db_session, product_a.id, tenant_a_key)
        assert templates_a[0].id in active_ids
        assert templates_a[1].id not in active_ids

    @pytest.mark.asyncio
    async def test_bulk_assign_all_templates(self, db_session, repo, product_a, templates_a, tenant_a_key):
        new_assignments = await repo.bulk_assign_all_templates(db_session, product_a.id, tenant_a_key)
        assert len(new_assignments) == 3

    @pytest.mark.asyncio
    async def test_bulk_assign_skips_existing(self, db_session, repo, product_a, templates_a, tenant_a_key):
        # Assign one first
        await repo.upsert_assignment(db_session, product_a.id, templates_a[0].id, tenant_a_key, is_active=True)
        await db_session.flush()

        # Bulk assign should only create 2 new
        new_assignments = await repo.bulk_assign_all_templates(db_session, product_a.id, tenant_a_key)
        assert len(new_assignments) == 2

    @pytest.mark.asyncio
    async def test_remove_assignments_for_product(self, db_session, repo, product_a, templates_a, tenant_a_key):
        await repo.bulk_assign_all_templates(db_session, product_a.id, tenant_a_key)
        await db_session.flush()

        count = await repo.remove_assignments_for_product(db_session, product_a.id, tenant_a_key)
        assert count == 3

        remaining = await repo.get_assignments_for_product(db_session, product_a.id, tenant_a_key)
        assert len(remaining) == 0

    @pytest.mark.asyncio
    async def test_tenant_isolation_get_assignments(
        self, db_session, repo, product_a, templates_a, tenant_a_key, tenant_b_key
    ):
        """Assignments for product_a with tenant_a_key must not appear under tenant_b_key."""
        await repo.bulk_assign_all_templates(db_session, product_a.id, tenant_a_key)
        await db_session.flush()

        # Query with wrong tenant key
        assignments = await repo.get_assignments_for_product(db_session, product_a.id, tenant_b_key)
        assert len(assignments) == 0


# ============================================================================
# Service Tests
# ============================================================================


class TestProductAgentAssignmentService:
    """Test the service layer with validation and write discipline."""

    @pytest.mark.asyncio
    async def test_toggle_creates_assignment(self, service_a, product_a, templates_a):
        result = await service_a.toggle_assignment(product_a.id, templates_a[0].id, is_active=True)
        assert result["product_id"] == product_a.id
        assert result["template_id"] == templates_a[0].id
        assert result["is_active"] is True

    @pytest.mark.asyncio
    async def test_toggle_updates_assignment(self, service_a, product_a, templates_a):
        await service_a.toggle_assignment(product_a.id, templates_a[0].id, is_active=True)
        result = await service_a.toggle_assignment(product_a.id, templates_a[0].id, is_active=False)
        assert result["is_active"] is False

    @pytest.mark.asyncio
    async def test_list_assignments(self, service_a, product_a, templates_a):
        for t in templates_a:
            await service_a.toggle_assignment(product_a.id, t.id, is_active=True)

        assignments = await service_a.list_assignments(product_a.id)
        assert len(assignments) == 3
        # Check template info is populated
        for a in assignments:
            assert a["template_name"] is not None
            assert a["template_role"] is not None

    @pytest.mark.asyncio
    async def test_assign_all_templates(self, service_a, product_a, templates_a):
        count = await service_a.assign_all_templates(product_a.id)
        assert count == 3

    @pytest.mark.asyncio
    async def test_assign_all_skips_existing(self, db_session, service_a, product_a, templates_a, tenant_a_key):
        # BE-9385a: the single pre-existing row is now written through the
        # REPOSITORY rather than through service.toggle_assignment. The service
        # toggle deliberately materialises the product's whole junction before
        # flipping one row (otherwise the first toggle on an uncurated product
        # switches selection tolerance off and blanks every other agent), so it
        # is no longer a way to create exactly one row. The behaviour under test
        # -- assign_all creates only the MISSING pairs -- is unchanged, and this
        # setup states it directly instead of relying on a side effect.
        await ProductAgentAssignmentRepository().upsert_assignment(
            db_session, product_a.id, templates_a[0].id, tenant_a_key, True
        )
        count = await service_a.assign_all_templates(product_a.id)
        assert count == 2  # Only 2 new ones

    @pytest.mark.asyncio
    async def test_get_active_template_ids(self, service_a, product_a, templates_a):
        await service_a.toggle_assignment(product_a.id, templates_a[0].id, is_active=True)
        await service_a.toggle_assignment(product_a.id, templates_a[1].id, is_active=False)

        active_ids = await service_a.get_active_template_ids(product_a.id)
        assert templates_a[0].id in active_ids
        assert templates_a[1].id not in active_ids

    @pytest.mark.asyncio
    async def test_remove_assignments(self, service_a, product_a, templates_a):
        await service_a.assign_all_templates(product_a.id)
        count = await service_a.remove_assignments(product_a.id)
        assert count == 3

    @pytest.mark.asyncio
    async def test_validation_rejects_empty_product_id(self, service_a, templates_a):
        from giljo_mcp.exceptions import ValidationError

        with pytest.raises(ValidationError):
            await service_a.toggle_assignment("", templates_a[0].id, is_active=True)

    @pytest.mark.asyncio
    async def test_validation_rejects_long_uuid(self, service_a, product_a, templates_a):
        from giljo_mcp.exceptions import ValidationError

        with pytest.raises(ValidationError):
            await service_a.toggle_assignment("x" * 100, templates_a[0].id, is_active=True)

    @pytest.mark.asyncio
    async def test_toggle_rejects_nonexistent_template(self, service_a, product_a):
        from giljo_mcp.exceptions import ResourceNotFoundError

        with pytest.raises(ResourceNotFoundError, match="Template"):
            await service_a.toggle_assignment(product_a.id, str(uuid4()), is_active=True)

    @pytest.mark.asyncio
    async def test_toggle_rejects_nonexistent_product(self, service_a, templates_a):
        from giljo_mcp.exceptions import ResourceNotFoundError

        with pytest.raises(ResourceNotFoundError, match="Product"):
            await service_a.toggle_assignment(str(uuid4()), templates_a[0].id, is_active=True)

    @pytest.mark.asyncio
    async def test_tenant_isolation_toggle(self, service_b, product_a, templates_a):
        """Service B (tenant B) cannot toggle assignments for tenant A's template."""
        from giljo_mcp.exceptions import ResourceNotFoundError

        with pytest.raises(ResourceNotFoundError):
            await service_b.toggle_assignment(product_a.id, templates_a[0].id, is_active=True)

    @pytest.mark.asyncio
    async def test_tenant_isolation_list(self, service_a, service_b, product_a, templates_a):
        """Service B cannot see assignments created by service A."""
        await service_a.assign_all_templates(product_a.id)

        # Service B with different tenant key sees nothing
        assignments = await service_b.list_assignments(product_a.id)
        assert len(assignments) == 0
