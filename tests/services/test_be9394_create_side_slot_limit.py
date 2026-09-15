# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from uuid import uuid4

import pytest
from sqlalchemy import select

from giljo_mcp.models.auth import User
from giljo_mcp.models.product_agent_assignment import ProductAgentAssignment
from giljo_mcp.models.templates import AgentTemplate
from giljo_mcp.services.template_service import USER_MANAGED_AGENT_LIMIT


def _active_template(tenant_key: str, product_id: str, role: str) -> AgentTemplate:
    return AgentTemplate(
        id=str(uuid4()),
        tenant_key=tenant_key,
        product_id=product_id,
        name=f"be9394-slot-{role}",
        role=role,
        category="custom",
        system_instructions="slot seed",
        is_active=True,
    )


def _user(tenant_key: str) -> User:
    return User(
        id=str(uuid4()),
        tenant_key=tenant_key,
        username=f"caller_{uuid4().hex[:6]}",
        email=f"caller_{uuid4().hex[:6]}@example.com",
        password_hash="not-used",
        role="developer",
        is_active=True,
    )


async def _fill_to_cap(db_session, tenant_key: str, product_id: str, count: int) -> None:
    for i in range(count):
        template = _active_template(tenant_key, product_id, f"be9394-role-{i}")
        db_session.add(template)
        db_session.add(
            ProductAgentAssignment(
                id=str(uuid4()),
                product_id=product_id,
                template_id=template.id,
                tenant_key=tenant_key,
                is_active=True,
            )
        )
    await db_session.flush()


async def _is_live_anywhere(db_session, template_id: str) -> bool:
    rows = await db_session.execute(
        select(ProductAgentAssignment.id).where(
            ProductAgentAssignment.template_id == template_id,
            ProductAgentAssignment.is_active.is_(True),
        )
    )
    return rows.first() is not None


def _create_payload(product_id: str, **overrides):
    from api.endpoints.templates.models import TemplateCreate

    kwargs = {
        "product_id": product_id,
        "role": f"be9394-new-{uuid4().hex[:6]}",
        "cli_tool": "claude",
        "is_active": True,
    }
    kwargs.update(overrides)
    return TemplateCreate(**kwargs)


async def test_creating_an_agent_at_the_cap_is_allowed_and_switches_nothing_on(
    db_session, template_service, test_tenant_key, test_product
):
    await _fill_to_cap(db_session, test_tenant_key, test_product.id, USER_MANAGED_AGENT_LIMIT)

    created = await template_service.create_template_from_request(
        db_session, _create_payload(test_product.id), test_tenant_key, "tester"
    )

    assert created.product_id == test_product.id, "a new agent belongs to the product it was created in"
    assert await _is_live_anywhere(db_session, created.id) is False, (
        "creating an agent must never switch it on -- activation is an explicit user act (BE-9400)"
    )


async def test_switching_the_new_agent_on_at_the_cap_is_refused_with_409(
    db_session, db_manager, template_service, test_tenant_key, test_product
):
    from fastapi import HTTPException

    from api.endpoints.products.agent_assignments import ToggleAssignmentRequest, toggle_agent_assignment
    from giljo_mcp.services.product_agent_assignment_service import ProductAgentAssignmentService

    await _fill_to_cap(db_session, test_tenant_key, test_product.id, USER_MANAGED_AGENT_LIMIT)
    created = await template_service.create_template_from_request(
        db_session, _create_payload(test_product.id), test_tenant_key, "tester"
    )
    await db_session.commit()

    service = ProductAgentAssignmentService(db_manager, test_tenant_key, test_session=db_session)

    with pytest.raises(HTTPException) as excinfo:
        await toggle_agent_assignment(
            product_id=test_product.id,
            template_id=created.id,
            body=ToggleAssignmentRequest(is_active=True),
            current_user=_user(test_tenant_key),
            service=service,
        )

    assert excinfo.value.status_code == 409
    assert str(USER_MANAGED_AGENT_LIMIT) in str(excinfo.value.detail)


async def test_the_sixteenth_total_slot_is_still_accepted(
    db_session, db_manager, template_service, test_tenant_key, test_product
):
    from giljo_mcp.services.product_agent_assignment_service import ProductAgentAssignmentService

    await _fill_to_cap(db_session, test_tenant_key, test_product.id, USER_MANAGED_AGENT_LIMIT - 1)
    created = await template_service.create_template_from_request(
        db_session, _create_payload(test_product.id), test_tenant_key, "tester"
    )
    await db_session.commit()

    service = ProductAgentAssignmentService(db_manager, test_tenant_key, test_session=db_session)
    result = await service.toggle_assignment(test_product.id, created.id, is_active=True)

    assert result["is_active"] is True
