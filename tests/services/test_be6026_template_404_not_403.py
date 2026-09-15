# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from uuid import uuid4

import pytest
from fastapi import HTTPException

from giljo_mcp.models.auth import User
from giljo_mcp.models.products import Product
from giljo_mcp.models.templates import AgentTemplate


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


@pytest.mark.asyncio
async def test_update_template_other_tenant_returns_404_not_403(
    db_session, template_service, test_tenant_key, other_tenant_key
):
    from api.endpoints.templates.crud import update_template
    from api.endpoints.templates.models import TemplateUpdate

    other_product = Product(
        id=str(uuid4()),
        name=f"Other Product {uuid4().hex[:6]}",
        description="Other tenant product",
        tenant_key=other_tenant_key,
        is_active=True,
    )
    db_session.add(other_product)
    await db_session.flush()

    foreign_template = AgentTemplate(
        id=str(uuid4()),
        tenant_key=other_tenant_key,
        product_id=other_product.id,
        name="foreign-analyzer",
        role="analyzer",
        category="custom",
        system_instructions="Foreign tenant template.",
        is_active=True,
    )
    db_session.add(foreign_template)
    await db_session.commit()

    caller = _user(test_tenant_key)

    with pytest.raises(HTTPException) as exc_info:
        await update_template(
            template_id=foreign_template.id,
            updates=TemplateUpdate(description="attempted edit"),
            current_user=caller,
            session=db_session,
            template_service=template_service,
        )

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "Template not found"


@pytest.mark.asyncio
async def test_reset_template_other_tenant_returns_404_not_403(
    db_session, template_service, test_tenant_key, other_tenant_key
):
    from api.endpoints.templates.history import reset_template

    other_product = Product(
        id=str(uuid4()),
        name=f"Other Product {uuid4().hex[:6]}",
        description="Other tenant product",
        tenant_key=other_tenant_key,
        is_active=True,
    )
    db_session.add(other_product)
    await db_session.flush()

    foreign_template = AgentTemplate(
        id=str(uuid4()),
        tenant_key=other_tenant_key,
        product_id=other_product.id,
        name="foreign-reviewer",
        role="reviewer",
        category="custom",
        system_instructions="Foreign tenant template.",
        is_active=True,
    )
    db_session.add(foreign_template)
    await db_session.commit()

    caller = _user(test_tenant_key)

    with pytest.raises(HTTPException) as exc_info:
        await reset_template(
            template_id=foreign_template.id,
            current_user=caller,
            session=db_session,
            template_service=template_service,
        )

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "Template not found"


@pytest.mark.asyncio
async def test_update_template_nonexistent_returns_404(db_session, template_service, test_tenant_key):
    from api.endpoints.templates.crud import update_template
    from api.endpoints.templates.models import TemplateUpdate

    caller = _user(test_tenant_key)

    with pytest.raises(HTTPException) as exc_info:
        await update_template(
            template_id=str(uuid4()),
            updates=TemplateUpdate(description="attempted edit"),
            current_user=caller,
            session=db_session,
            template_service=template_service,
        )

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "Template not found"
