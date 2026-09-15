# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


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
async def templates_a(db_session, tenant_a_key, product_a):
    templates = []
    for name in ["orchestrator", "implementer", "analyzer"]:
        t = AgentTemplate(
            id=str(uuid4()),
            tenant_key=tenant_a_key,
            product_id=product_a.id,
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
async def templates_b(db_session, tenant_b_key, product_b):
    t = AgentTemplate(
        id=str(uuid4()),
        tenant_key=tenant_b_key,
        product_id=product_b.id,
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




class TestProductAgentAssignmentModel:

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




class TestProductAgentAssignmentRepository:

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
        await repo.upsert_assignment(db_session, product_a.id, templates_a[0].id, tenant_a_key, is_active=True)
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
    async def test_enable_templates_for_product(self, db_session, repo, product_a, templates_a, tenant_a_key):
        ids = [t.id for t in templates_a]
        new_assignments = await repo.enable_templates_for_product(db_session, product_a.id, tenant_a_key, ids)
        assert len(new_assignments) == 3

    @pytest.mark.asyncio
    async def test_enable_templates_skips_existing(self, db_session, repo, product_a, templates_a, tenant_a_key):
        await repo.upsert_assignment(db_session, product_a.id, templates_a[0].id, tenant_a_key, is_active=False)
        await db_session.flush()

        ids = [t.id for t in templates_a]
        new_assignments = await repo.enable_templates_for_product(db_session, product_a.id, tenant_a_key, ids)
        assert len(new_assignments) == 2

        existing = await repo.get_assignment(db_session, product_a.id, templates_a[0].id, tenant_a_key)
        assert existing.is_active is False, "skip-existing must not flip a deliberate OFF back on"

    @pytest.mark.asyncio
    async def test_remove_assignments_for_product(self, db_session, repo, product_a, templates_a, tenant_a_key):
        await repo.enable_templates_for_product(db_session, product_a.id, tenant_a_key, [t.id for t in templates_a])
        await db_session.flush()

        count = await repo.remove_assignments_for_product(db_session, product_a.id, tenant_a_key)
        assert count == 3

        remaining = await repo.get_assignments_for_product(db_session, product_a.id, tenant_a_key)
        assert len(remaining) == 0

    @pytest.mark.asyncio
    async def test_tenant_isolation_get_assignments(
        self, db_session, repo, product_a, templates_a, tenant_a_key, tenant_b_key
    ):
        await repo.enable_templates_for_product(db_session, product_a.id, tenant_a_key, [t.id for t in templates_a])
        await db_session.flush()

        assignments = await repo.get_assignments_for_product(db_session, product_a.id, tenant_b_key)
        assert len(assignments) == 0




class TestProductAgentAssignmentService:

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
        for a in assignments:
            assert a["template_name"] is not None
            assert a["template_role"] is not None

    @pytest.mark.asyncio
    async def test_enable_for_product(self, db_session, service_a, product_a, templates_a):
        count = await service_a.enable_for_product(db_session, product_a.id, [t.id for t in templates_a])
        await db_session.commit()
        assert count == 3

    @pytest.mark.asyncio
    async def test_enable_for_product_skips_existing(self, db_session, service_a, product_a, templates_a, tenant_a_key):
        await ProductAgentAssignmentRepository().upsert_assignment(
            db_session, product_a.id, templates_a[0].id, tenant_a_key, True
        )
        count = await service_a.enable_for_product(db_session, product_a.id, [t.id for t in templates_a])
        await db_session.commit()
        assert count == 2

    @pytest.mark.asyncio
    async def test_toggle_changes_exactly_one_agent(
        self, service_a, product_a, templates_a, db_session, repo, tenant_a_key
    ):
        await service_a.toggle_assignment(product_a.id, templates_a[0].id, is_active=True)

        rows = await repo.get_assignments_for_product(db_session, product_a.id, tenant_a_key)
        assert len(rows) == 1, f"one toggle must write one row, wrote {len(rows)}"
        assert rows[0].template_id == templates_a[0].id

    @pytest.mark.asyncio
    async def test_toggle_refuses_another_products_agent(
        self, db_session, service_a, product_a, templates_a, tenant_a_key
    ):
        from giljo_mcp.exceptions import ValidationError

        other = Product(
            id=str(uuid4()),
            name=f"Other product {uuid4().hex[:6]}",
            description="owns nothing under test",
            tenant_key=tenant_a_key,
            is_active=True,
            created_at=datetime.now(UTC),
        )
        db_session.add(other)
        await db_session.commit()

        with pytest.raises(ValidationError, match="different product"):
            await service_a.toggle_assignment(other.id, templates_a[0].id, is_active=True)

    @pytest.mark.asyncio
    async def test_remove_assignments(self, db_session, service_a, product_a, templates_a):
        await service_a.enable_for_product(db_session, product_a.id, [t.id for t in templates_a])
        await db_session.commit()
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
        from giljo_mcp.exceptions import ResourceNotFoundError

        with pytest.raises(ResourceNotFoundError):
            await service_b.toggle_assignment(product_a.id, templates_a[0].id, is_active=True)

    @pytest.mark.asyncio
    async def test_tenant_isolation_list(self, db_session, service_a, service_b, product_a, templates_a):
        await service_a.enable_for_product(db_session, product_a.id, [t.id for t in templates_a])
        await db_session.commit()

        assignments = await service_b.list_assignments(product_a.id)
        assert len(assignments) == 0
