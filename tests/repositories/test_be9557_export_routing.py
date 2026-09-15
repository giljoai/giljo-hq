# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
import pytest_asyncio

from giljo_mcp.models.product_agent_assignment import ProductAgentAssignment
from giljo_mcp.models.products import Product
from giljo_mcp.models.templates import AgentTemplate
from giljo_mcp.tenant import TenantManager
from tests.helpers.product_crew_helper import adopt_all_templates


pytestmark = pytest.mark.asyncio




@pytest_asyncio.fixture
async def tenant_key() -> str:
    return TenantManager.generate_tenant_key()


async def _make_product(db_session, tenant_key, *, is_active: bool, is_default: bool, name: str) -> Product:
    row = Product(
        id=str(uuid4()),
        name=name,
        description="BE-9557 export routing fixture",
        tenant_key=tenant_key,
        is_active=is_active,
        is_default=is_default,
        created_at=datetime.now(UTC),
    )
    db_session.add(row)
    await db_session.flush()
    await adopt_all_templates(db_session, tenant_key, row.id)
    return row


async def _make_template(db_session, tenant_key, name: str) -> AgentTemplate:
    row = AgentTemplate(
        id=str(uuid4()),
        tenant_key=tenant_key,
        name=f"{name}_{uuid4().hex[:6]}",
        role=name.title(),
        description=f"{name} description",
        is_active=True,
    )
    db_session.add(row)
    await db_session.flush()
    return row


async def _assign(db_session, tenant_key, product, template) -> ProductAgentAssignment:
    row = ProductAgentAssignment(
        id=str(uuid4()),
        tenant_key=tenant_key,
        product_id=product.id,
        template_id=template.id,
        is_active=True,
    )
    db_session.add(row)
    await db_session.flush()
    return row


@pytest_asyncio.fixture
async def two_products_disjoint_assignments(db_session, tenant_key):
    default_product = await _make_product(db_session, tenant_key, is_active=False, is_default=True, name="Default")
    shown_product = await _make_product(db_session, tenant_key, is_active=True, is_default=False, name="Shown")

    default_template = await _make_template(db_session, tenant_key, "default_agent")
    shown_template = await _make_template(db_session, tenant_key, "shown_agent")

    await _assign(db_session, tenant_key, default_product, default_template)
    await _assign(db_session, tenant_key, shown_product, shown_template)

    return {
        "default_product": default_product,
        "shown_product": shown_product,
        "default_template": default_template,
        "shown_template": shown_template,
    }




async def test_unscoped_read_resolves_the_default_product_not_an_arbitrary_shown_one(
    db_session, tenant_key, two_products_disjoint_assignments
):
    from giljo_mcp.repositories.product_repository import ProductRepository

    fx = two_products_disjoint_assignments
    resolved = await ProductRepository().get_default_product(db_session, tenant_key, eager_load=False)

    assert resolved is not None
    assert resolved.id == fx["default_product"].id, (
        "an unscoped read must resolve the DEFAULT product (is_default=True), not "
        f"whichever is_active row .first() happened to return. got={resolved.id}"
    )


async def test_the_default_products_own_agents_are_what_it_serves(
    db_session, tenant_key, two_products_disjoint_assignments
):
    from giljo_mcp.repositories.product_agent_selection import template_ids_for_product

    fx = two_products_disjoint_assignments
    ids = await template_ids_for_product(db_session, fx["default_product"].id, tenant_key)

    assert ids == {fx["default_template"].id}, (
        f"the default product must serve its OWN agents, not the shown product's. got={ids}"
    )
