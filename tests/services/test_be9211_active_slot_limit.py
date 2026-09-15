# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from uuid import uuid4

import pytest
from sqlalchemy import select

from giljo_mcp.exceptions import ProjectStateError
from giljo_mcp.models.product_agent_assignment import ProductAgentAssignment
from giljo_mcp.models.templates import AgentTemplate
from giljo_mcp.services.product_agent_assignment_service import ProductAgentAssignmentService
from giljo_mcp.services.template_service import USER_MANAGED_AGENT_LIMIT


def _active_template(tenant_key: str, product_id: str, role: str) -> AgentTemplate:
    return AgentTemplate(
        id=str(uuid4()),
        tenant_key=tenant_key,
        product_id=product_id,
        name=f"slot-tmpl-{role}",
        role=role,
        category="custom",
        system_instructions="boundary seed",
        is_active=True,
    )


@pytest.mark.asyncio
async def test_active_slot_limit_16th_accepted_17th_rejected(db_session, db_manager, test_tenant_key, test_product):
    service = ProductAgentAssignmentService(db_manager, test_tenant_key, test_session=db_session)

    for i in range(USER_MANAGED_AGENT_LIMIT):
        template = _active_template(test_tenant_key, test_product.id, f"custom-role-{i}")
        db_session.add(template)
        db_session.add(
            ProductAgentAssignment(
                id=str(uuid4()),
                product_id=test_product.id,
                template_id=template.id,
                tenant_key=test_tenant_key,
                is_active=True,
            )
        )
    await db_session.flush()

    candidate = _active_template(test_tenant_key, test_product.id, "custom-role-new")
    db_session.add(candidate)
    await db_session.commit()

    with pytest.raises(ProjectStateError) as excinfo:
        await service.toggle_assignment(test_product.id, candidate.id, is_active=True)
    assert str(USER_MANAGED_AGENT_LIMIT) in excinfo.value.message

    row = (
        await db_session.execute(
            select(AgentTemplate).where(
                AgentTemplate.tenant_key == test_tenant_key,
                AgentTemplate.role == "custom-role-0",
            )
        )
    ).scalar_one()
    await service.toggle_assignment(test_product.id, row.id, is_active=False)

    result = await service.toggle_assignment(test_product.id, candidate.id, is_active=True)
    assert result["is_active"] is True


@pytest.mark.asyncio
async def test_the_budget_is_per_product_not_per_account(db_session, db_manager, test_tenant_key, test_product):
    from datetime import UTC, datetime

    from giljo_mcp.models.products import Product

    service = ProductAgentAssignmentService(db_manager, test_tenant_key, test_session=db_session)

    for i in range(USER_MANAGED_AGENT_LIMIT):
        template = _active_template(test_tenant_key, test_product.id, f"full-role-{i}")
        db_session.add(template)
        db_session.add(
            ProductAgentAssignment(
                id=str(uuid4()),
                product_id=test_product.id,
                template_id=template.id,
                tenant_key=test_tenant_key,
                is_active=True,
            )
        )

    second = Product(
        id=str(uuid4()),
        name=f"Second product {uuid4().hex[:6]}",
        description="its own budget",
        tenant_key=test_tenant_key,
        is_active=True,
        created_at=datetime.now(UTC),
    )
    db_session.add(second)
    mine = _active_template(test_tenant_key, second.id, "full-role-0")
    mine.name = f"slot-tmpl-second-{uuid4().hex[:4]}"
    db_session.add(mine)
    await db_session.commit()

    result = await service.toggle_assignment(second.id, mine.id, is_active=True)
    assert result["is_active"] is True, "a product with an empty roster must be able to fill it"


@pytest.mark.asyncio
async def test_a_second_copy_of_an_enabled_role_is_free(db_session, db_manager, test_tenant_key, test_product):
    service = ProductAgentAssignmentService(db_manager, test_tenant_key, test_session=db_session)

    for i in range(USER_MANAGED_AGENT_LIMIT):
        template = _active_template(test_tenant_key, test_product.id, f"dup-role-{i}")
        db_session.add(template)
        db_session.add(
            ProductAgentAssignment(
                id=str(uuid4()),
                product_id=test_product.id,
                template_id=template.id,
                tenant_key=test_tenant_key,
                is_active=True,
            )
        )
    sibling = _active_template(test_tenant_key, test_product.id, "dup-role-0")
    sibling.name = f"slot-tmpl-sibling-{uuid4().hex[:4]}"
    db_session.add(sibling)
    await db_session.commit()

    result = await service.toggle_assignment(test_product.id, sibling.id, is_active=True)
    assert result["is_active"] is True


def test_active_slot_cap_is_16_total_and_single_source():
    from api.endpoints.templates import crud

    assert USER_MANAGED_AGENT_LIMIT == 15
    assert USER_MANAGED_AGENT_LIMIT + 1 == 16
    assert crud.USER_MANAGED_AGENT_LIMIT == USER_MANAGED_AGENT_LIMIT
