# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from uuid import uuid4

import pytest

from api.endpoints.templates.models import TemplateCreate, TemplateUpdate
from giljo_mcp.exceptions import TemplateNotFoundError
from giljo_mcp.services.template_service import TemplateService
from giljo_mcp.tenant import TenantManager


pytestmark = pytest.mark.asyncio


def _service(db_manager, db_session) -> TemplateService:
    return TemplateService(db_manager, TenantManager(), session=db_session)


async def _product_id(db_session, tenant: str) -> str:
    from datetime import UTC, datetime

    from giljo_mcp.models.products import Product

    product = Product(
        id=str(uuid4()),
        name=f"INF-6049c {uuid4().hex[:8]}",
        description="cli_tool round-trip fixture",
        tenant_key=tenant,
        is_active=True,
        created_at=datetime.now(UTC),
    )
    db_session.add(product)
    await db_session.commit()
    return product.id


async def test_create_persists_cli_tool(db_manager, db_session):
    tenant = TenantManager.generate_tenant_key()
    svc = _service(db_manager, db_session)

    created = await svc.create_template_from_request(
        db_session,
        TemplateCreate(product_id=await _product_id(db_session, tenant), role="implementer", cli_tool="codex"),
        tenant_key=tenant,
        created_by="tester",
    )

    fetched = await svc.get_template(template_id=created.id, tenant_key=tenant)
    assert fetched.template.cli_tool == "codex"


async def test_update_to_antigravity_round_trips(db_manager, db_session):
    tenant = TenantManager.generate_tenant_key()
    svc = _service(db_manager, db_session)
    created = await svc.create_template_from_request(
        db_session,
        TemplateCreate(product_id=await _product_id(db_session, tenant), role="reviewer", cli_tool="claude"),
        tenant_key=tenant,
        created_by="tester",
    )

    updated, _fields = await svc.update_template_from_request(
        db_session,
        created.id,
        TemplateUpdate(cli_tool="antigravity"),
        tenant_key=tenant,
        username="tester",
    )
    assert updated.cli_tool == "antigravity"

    fetched = await svc.get_template(template_id=created.id, tenant_key=tenant)
    assert fetched.template.cli_tool == "antigravity"


async def test_cli_tool_defaults_to_claude_when_unset(db_manager, db_session):
    tenant = TenantManager.generate_tenant_key()
    svc = _service(db_manager, db_session)
    created = await svc.create_template_from_request(
        db_session,
        TemplateCreate(product_id=await _product_id(db_session, tenant), role="analyzer"),
        tenant_key=tenant,
        created_by="tester",
    )

    fetched = await svc.get_template(template_id=created.id, tenant_key=tenant)
    assert fetched.template.cli_tool in (None, "claude")


async def test_cli_tool_update_is_tenant_isolated(db_manager, db_session):
    tenant_a = TenantManager.generate_tenant_key()
    tenant_b = TenantManager.generate_tenant_key()
    svc = _service(db_manager, db_session)
    created = await svc.create_template_from_request(
        db_session,
        TemplateCreate(product_id=await _product_id(db_session, tenant_a), role="implementer", cli_tool="codex"),
        tenant_key=tenant_a,
        created_by="tester",
    )

    with pytest.raises(TemplateNotFoundError):
        await svc.update_template_from_request(
            db_session,
            created.id,
            TemplateUpdate(cli_tool="gemini"),
            tenant_key=tenant_b,
            username="tester",
        )

    fetched = await svc.get_template(template_id=created.id, tenant_key=tenant_a)
    assert fetched.template.cli_tool == "codex"
