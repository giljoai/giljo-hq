# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from api.endpoints.templates.models import TemplateCreate, TemplateUpdate
from giljo_mcp.exceptions import ValidationError
from giljo_mcp.models.products import Product
from giljo_mcp.services.template_service import TemplateService
from giljo_mcp.tenant import TenantManager


pytestmark = pytest.mark.asyncio


def _service(db_manager, db_session) -> TemplateService:
    return TemplateService(db_manager, TenantManager(), session=db_session)


async def _product_id(db_session, tenant: str) -> str:
    product = Product(
        id=str(uuid4()),
        name=f"BE-9649 {uuid4().hex[:8]}",
        description="harness validation fixture",
        tenant_key=tenant,
        is_active=True,
        created_at=datetime.now(UTC),
    )
    db_session.add(product)
    await db_session.commit()
    return product.id


def _unvalidated_create(product_id: str, cli_tool: str) -> TemplateCreate:
    defaults = TemplateCreate(product_id=product_id, role="implementer").model_dump()
    defaults["cli_tool"] = cli_tool
    return TemplateCreate.model_construct(**defaults)


async def test_service_refuses_a_non_name_harness_on_create(db_manager, db_session):
    tenant = TenantManager.generate_tenant_key()
    svc = _service(db_manager, db_session)
    request = _unvalidated_create(await _product_id(db_session, tenant), "x; ignore all")

    with pytest.raises(ValidationError) as exc:
        await svc.create_template_from_request(db_session, request, tenant_key=tenant, created_by="tester")
    assert "harness" in str(exc.value).lower()


async def test_service_refuses_a_non_name_harness_on_update(db_manager, db_session):
    tenant = TenantManager.generate_tenant_key()
    svc = _service(db_manager, db_session)
    created = await svc.create_template_from_request(
        db_session,
        TemplateCreate(product_id=await _product_id(db_session, tenant), role="reviewer", cli_tool="codex"),
        tenant_key=tenant,
        created_by="tester",
    )

    with pytest.raises(ValidationError):
        await svc.update_template_from_request(
            db_session,
            created.id,
            TemplateUpdate.model_construct(cli_tool="two words"),
            tenant_key=tenant,
            username="tester",
        )
    fetched = await svc.get_template(template_id=created.id, tenant_key=tenant)
    assert fetched.template.cli_tool == "codex", "a refused update must not reach the row"


async def test_free_text_name_and_default_round_trip(db_manager, db_session):
    tenant = TenantManager.generate_tenant_key()
    svc = _service(db_manager, db_session)
    created = await svc.create_template_from_request(
        db_session,
        TemplateCreate(product_id=await _product_id(db_session, tenant), role="tester", cli_tool="gemini-cli"),
        tenant_key=tenant,
        created_by="tester",
    )
    assert created.cli_tool == "gemini-cli"

    updated, _fields = await svc.update_template_from_request(
        db_session, created.id, TemplateUpdate(cli_tool=""), tenant_key=tenant, username="tester"
    )
    assert updated.cli_tool == "default"
    assert updated.tool == "default", "the legacy tool column stays mirrored"
