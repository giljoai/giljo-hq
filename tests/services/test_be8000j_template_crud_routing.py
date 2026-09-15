# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from giljo_mcp.models.auth import User
from giljo_mcp.models.templates import TemplateArchive
from giljo_mcp.template_seeder import _get_mcp_bootstrap_section


pytestmark = pytest.mark.asyncio


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


async def _create(template_service, db_session, user, product_id, **payload_kwargs):
    from api.endpoints.templates.crud import create_template
    from api.endpoints.templates.models import TemplateCreate

    payload = TemplateCreate(product_id=product_id, **payload_kwargs)
    return await create_template(
        template=payload,
        current_user=user,
        session=db_session,
        template_service=template_service,
    )




async def test_create_endpoint_routes_through_service(
    db_session, template_service, test_tenant_key, test_product, monkeypatch
):
    from api.endpoints.templates.crud import create_template
    from api.endpoints.templates.models import TemplateCreate

    user = _user(test_tenant_key)
    spy = AsyncMock(wraps=template_service.create_template_from_request)
    monkeypatch.setattr(template_service, "create_template_from_request", spy)

    resp = await create_template(
        template=TemplateCreate(product_id=test_product.id, role="reviewer", cli_tool="claude"),
        current_user=user,
        session=db_session,
        template_service=template_service,
    )

    spy.assert_awaited_once()
    assert resp.id
    assert resp.role == "reviewer"


async def test_update_endpoint_routes_through_service(
    db_session, template_service, test_tenant_key, test_product, monkeypatch
):
    from api.endpoints.templates.crud import update_template
    from api.endpoints.templates.models import TemplateUpdate

    user = _user(test_tenant_key)
    created = await _create(template_service, db_session, user, test_product.id, role="reviewer", cli_tool="claude")

    spy = AsyncMock(wraps=template_service.update_template_from_request)
    monkeypatch.setattr(template_service, "update_template_from_request", spy)

    resp = await update_template(
        template_id=created.id,
        updates=TemplateUpdate(description="edited via endpoint"),
        current_user=user,
        session=db_session,
        template_service=template_service,
    )

    spy.assert_awaited_once()
    assert resp.description == "edited via endpoint"




async def test_create_injects_canonical_bootstrap(db_session, template_service, test_tenant_key, test_product):
    user = _user(test_tenant_key)
    resp = await _create(
        template_service,
        db_session,
        user,
        test_product.id,
        role="implementer",
        cli_tool="claude",
        system_instructions="INJECTED EVIL INSTRUCTIONS",
        user_instructions="Legitimate role description.",
    )

    assert resp.system_instructions == _get_mcp_bootstrap_section()
    assert "INJECTED EVIL INSTRUCTIONS" not in resp.system_instructions
    assert "health_check" in resp.system_instructions
    assert "get_job_mission" in resp.system_instructions
    assert "full_protocol" in resp.system_instructions


async def test_create_stores_user_instructions(db_session, template_service, test_tenant_key, test_product):
    user = _user(test_tenant_key)
    prose = "You are a senior code reviewer who provides constructive feedback on pull requests."
    resp = await _create(
        template_service, db_session, user, test_product.id, role="reviewer", cli_tool="claude", user_instructions=prose
    )

    assert resp.user_instructions == prose


async def test_create_empty_user_instructions_defaults_to_empty(
    db_session, template_service, test_tenant_key, test_product
):
    user = _user(test_tenant_key)
    resp = await _create(template_service, db_session, user, test_product.id, role="tester", cli_tool="claude")

    assert resp.user_instructions == ""


async def test_update_rejects_system_instructions_with_403(db_session, template_service, test_tenant_key, test_product):
    from api.endpoints.templates.crud import update_template
    from api.endpoints.templates.models import TemplateUpdate

    user = _user(test_tenant_key)
    created = await _create(template_service, db_session, user, test_product.id, role="implementer", cli_tool="claude")

    with pytest.raises(HTTPException) as exc_info:
        await update_template(
            template_id=created.id,
            updates=TemplateUpdate(system_instructions="Attempt to override bootstrap"),
            current_user=user,
            session=db_session,
            template_service=template_service,
        )

    assert exc_info.value.status_code == 403
    assert "system_instructions" in str(exc_info.value.detail).lower()
    assert "read-only" in str(exc_info.value.detail).lower()


async def test_update_stores_user_instructions_and_archives(
    db_session, template_service, test_tenant_key, test_product
):
    from api.endpoints.templates.crud import update_template
    from api.endpoints.templates.models import TemplateUpdate

    user = _user(test_tenant_key)
    created = await _create(
        template_service,
        db_session,
        user,
        test_product.id,
        role="implementer",
        cli_tool="claude",
        user_instructions="Old instructions",
    )

    new_prose = "Updated role description with deep expertise in testing."
    resp = await update_template(
        template_id=created.id,
        updates=TemplateUpdate(user_instructions=new_prose),
        current_user=user,
        session=db_session,
        template_service=template_service,
    )

    assert resp.user_instructions == new_prose

    archives = (
        (await db_session.execute(select(TemplateArchive).where(TemplateArchive.template_id == created.id)))
        .scalars()
        .all()
    )
    assert len(archives) == 1
    assert archives[0].archive_reason == "Update user instructions"
    assert archives[0].archive_type == "auto"
