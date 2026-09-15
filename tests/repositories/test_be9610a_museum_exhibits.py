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
from giljo_mcp.repositories.product_agent_assignment_repository import (
    ProductAgentAssignmentRepository,
)
from giljo_mcp.tenant import TenantManager
from giljo_mcp.tools.context_tools.get_agent_templates import get_agent_templates


pytestmark = pytest.mark.asyncio




@pytest_asyncio.fixture
async def tenant_key() -> str:
    return TenantManager.generate_tenant_key()


async def _make_product(db_session, tenant_key: str) -> Product:
    row = Product(
        id=str(uuid4()),
        name=f"BE-9610a museum {uuid4().hex[:8]}",
        description="museum-gate fixture",
        tenant_key=tenant_key,
        is_active=True,
        created_at=datetime.now(UTC),
    )
    db_session.add(row)
    await db_session.commit()
    return row


async def _make_template(
    db_session,
    tenant_key: str,
    base: str,
    *,
    is_active: bool = True,
    deleted: bool = False,
) -> AgentTemplate:
    row = AgentTemplate(
        id=str(uuid4()),
        tenant_key=tenant_key,
        name=f"{base}-{uuid4().hex[:8]}",
        role=base,
        category="role",
        description=f"{base} description",
        system_instructions="sys",
        user_instructions="body",
        tool="claude",
        cli_tool="claude",
        is_active=is_active,
        deleted_at=datetime.now(UTC) if deleted else None,
    )
    db_session.add(row)
    await db_session.commit()
    return row


async def _assign(db_session, tenant_key, product, template, *, is_active: bool) -> ProductAgentAssignment:
    row = ProductAgentAssignment(
        id=str(uuid4()),
        tenant_key=tenant_key,
        product_id=product.id,
        template_id=template.id,
        is_active=is_active,
    )
    db_session.add(row)
    await db_session.commit()
    return row


async def _advertised(db_session, tenant_key: str, product: Product) -> set[str]:
    result = await get_agent_templates(
        product_id=product.id,
        tenant_key=tenant_key,
        detail="basic",
        _test_session=db_session,
    )
    return {entry["name"] for entry in result["data"]}




async def test_canary_one_enabled_assignment_advertises_exactly_that_agent(db_session, tenant_key):
    product = await _make_product(db_session, tenant_key)
    wanted = await _make_template(db_session, tenant_key, "implementer")
    other = await _make_template(db_session, tenant_key, "tester")
    await _assign(db_session, tenant_key, product, wanted, is_active=True)
    await _assign(db_session, tenant_key, product, other, is_active=False)

    assert await _advertised(db_session, tenant_key, product) == {wanted.name}




async def test_exhibit_a_a_product_that_enabled_nothing_advertises_nothing(db_session, tenant_key):
    product = await _make_product(db_session, tenant_key)
    switched_off = await _make_template(db_session, tenant_key, "implementer")
    await _make_template(db_session, tenant_key, "tester")
    await _make_template(db_session, tenant_key, "reviewer")

    await _assign(db_session, tenant_key, product, switched_off, is_active=False)

    assert await _advertised(db_session, tenant_key, product) == set()




async def test_exhibit_b_toggling_one_agent_never_moves_another(db_manager, db_session, tenant_key):
    from giljo_mcp.services.product_agent_assignment_service import ProductAgentAssignmentService

    product = await _make_product(db_session, tenant_key)
    target = await _make_template(db_session, tenant_key, "implementer")
    bystanders = [
        await _make_template(db_session, tenant_key, "tester"),
        await _make_template(db_session, tenant_key, "reviewer"),
    ]

    before = await _advertised(db_session, tenant_key, product)

    service = ProductAgentAssignmentService(db_manager, tenant_key, test_session=db_session)
    await service.toggle_assignment(product.id, target.id, is_active=False)

    after = await _advertised(db_session, tenant_key, product)

    moved = {t.name for t in bystanders if (t.name in before) != (t.name in after)}
    assert moved == set(), (
        f"Toggling '{target.name}' changed the advertised state of {sorted(moved)}. "
        "A per-agent switch that moves other agents is the roster collapse BE-9385a/D1 closed."
    )
    assert target.name not in after, "The agent the user switched OFF is still advertised."




async def test_exhibit_c_active_ids_never_names_a_soft_deleted_template(db_session, tenant_key):
    product = await _make_product(db_session, tenant_key)
    live = await _make_template(db_session, tenant_key, "implementer")
    trashed = await _make_template(db_session, tenant_key, "documenter", deleted=True)

    await _assign(db_session, tenant_key, product, live, is_active=True)
    await _assign(db_session, tenant_key, product, trashed, is_active=True)

    repo = ProductAgentAssignmentRepository()
    active_ids = await repo.get_active_template_ids_for_product(db_session, product.id, tenant_key)

    assert trashed.id not in active_ids, (
        "get_active_template_ids_for_product returned a SOFT-DELETED template's id. "
        "That is the BE-9334 defect: a dead assignee engaging the caller's filter."
    )
    assert active_ids == {live.id}


async def test_exhibit_c_a_dead_assignee_does_not_change_a_live_one(db_session, tenant_key):
    product = await _make_product(db_session, tenant_key)
    live = await _make_template(db_session, tenant_key, "implementer")
    await _assign(db_session, tenant_key, product, live, is_active=True)

    before = await _advertised(db_session, tenant_key, product)

    trashed = await _make_template(db_session, tenant_key, "documenter", deleted=True)
    await _assign(db_session, tenant_key, product, trashed, is_active=True)

    after = await _advertised(db_session, tenant_key, product)

    assert after == before, (
        f"A junction row pointing at a soft-deleted template changed the advertised set "
        f"from {sorted(before)} to {sorted(after)}."
    )
