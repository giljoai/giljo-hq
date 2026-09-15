# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from uuid import uuid4

import pytest

from giljo_mcp.exceptions import ValidationError
from giljo_mcp.models.product_agent_assignment import ProductAgentAssignment
from giljo_mcp.models.products import Product
from giljo_mcp.models.templates import AgentTemplate
from giljo_mcp.services.product_agent_assignment_service import ProductAgentAssignmentService


pytestmark = pytest.mark.asyncio


def _template(tenant_key: str, product_id: str) -> AgentTemplate:
    return AgentTemplate(
        id=str(uuid4()),
        tenant_key=tenant_key,
        product_id=product_id,
        name=f"sec9612-{uuid4().hex[:6]}",
        role="tester",
        category="custom",
        system_instructions="seed",
        is_active=True,
    )


async def test_cross_product_rejection_does_not_echo_the_owning_product_id(
    db_session, db_manager, test_tenant_key, test_product
):
    other_product = Product(id=str(uuid4()), tenant_key=test_tenant_key, name="sec9612-other", is_active=True)
    db_session.add(other_product)
    await db_session.flush()

    owned_elsewhere = _template(test_tenant_key, other_product.id)
    db_session.add(owned_elsewhere)
    await db_session.flush()
    await db_session.commit()

    service = ProductAgentAssignmentService(db_manager, test_tenant_key, test_session=db_session)

    with pytest.raises(ValidationError) as excinfo:
        await service.toggle_assignment(test_product.id, owned_elsewhere.id, is_active=True)

    context = excinfo.value.context or {}
    assert "owner_product_id" not in context, f"the refused request echoed an unasked id: {context}"
    assert other_product.id not in str(context), f"the owning product's id reached the caller: {context}"

    assert context.get("template_id") == owned_elsewhere.id
    assert context.get("product_id") == test_product.id
    assert "different product" in excinfo.value.message


async def test_the_serialised_response_body_carries_no_unasked_id(
    db_session, db_manager, test_tenant_key, test_product
):
    other_product = Product(id=str(uuid4()), tenant_key=test_tenant_key, name="sec9612-other-2", is_active=True)
    db_session.add(other_product)
    await db_session.flush()
    owned_elsewhere = _template(test_tenant_key, other_product.id)
    db_session.add(owned_elsewhere)
    await db_session.flush()
    await db_session.commit()

    service = ProductAgentAssignmentService(db_manager, test_tenant_key, test_session=db_session)

    with pytest.raises(ValidationError) as excinfo:
        await service.toggle_assignment(test_product.id, owned_elsewhere.id, is_active=True)

    assert other_product.id not in str(excinfo.value.to_dict())


async def test_a_legitimate_same_product_toggle_still_works(db_session, db_manager, test_tenant_key, test_product):
    owned_here = _template(test_tenant_key, test_product.id)
    db_session.add(owned_here)
    await db_session.flush()
    await db_session.commit()

    service = ProductAgentAssignmentService(db_manager, test_tenant_key, test_session=db_session)
    await service.toggle_assignment(test_product.id, owned_here.id, is_active=True)

    from sqlalchemy import select

    rows = (
        await db_session.execute(
            select(ProductAgentAssignment.id).where(
                ProductAgentAssignment.template_id == owned_here.id,
                ProductAgentAssignment.is_active.is_(True),
            )
        )
    ).all()
    assert len(rows) == 1
