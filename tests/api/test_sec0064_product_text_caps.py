# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest

from api.endpoints.mcp_tools._base import MCP_DESCRIPTION_MAX
from giljo_mcp.exceptions import ValidationError
from giljo_mcp.models import Product
from giljo_mcp.services.product_service import ProductService
from tests.fixtures.base_fixtures import TestData


OVER = "x" * (MCP_DESCRIPTION_MAX + 1)
AT_CAP = "y" * MCP_DESCRIPTION_MAX
LEGACY = "z" * (MCP_DESCRIPTION_MAX + 5000)


async def _service(db_session, db_manager) -> ProductService:
    return ProductService(db_manager, tenant_key=TestData.generate_tenant_key(), test_session=db_session)


async def _legacy_product(db_session, tenant_key: str) -> Product:
    product = Product(
        id=str(uuid.uuid4()),
        name=f"Legacy {uuid.uuid4().hex[:6]}",
        description=LEGACY,
        core_features=LEGACY,
        tenant_key=tenant_key,
        is_active=True,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    db_session.add(product)
    await db_session.commit()
    return product


def test_both_doors_share_one_number():
    from giljo_mcp.services.product_field_map import PRODUCT_TEXT_MAX_LENGTH

    assert PRODUCT_TEXT_MAX_LENGTH == MCP_DESCRIPTION_MAX


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "field",
    [
        {"description": OVER},
        {"core_features": OVER},
        {"brand_guidelines": OVER},
        {"tech_stack": {"programming_languages": OVER}},
        {"architecture": {"architecture_notes": OVER}},
        {"test_config": {"quality_standards": OVER}},
    ],
)
async def test_create_refuses_a_text_over_the_cap(db_session, db_manager, field):
    service = await _service(db_session, db_manager)

    with pytest.raises(ValidationError, match="Must be at most 20000 characters"):
        await service.create_product(name=f"P {uuid.uuid4().hex[:6]}", **field)


@pytest.mark.asyncio
async def test_a_test_strategy_over_its_column_width_is_refused_not_a_500(db_session, db_manager):
    service = await _service(db_session, db_manager)

    with pytest.raises(ValidationError, match=r"test_config\.test_strategy: Must be at most 50 characters"):
        await service.create_product(name=f"P {uuid.uuid4().hex[:6]}", test_config={"test_strategy": "T" * 51})


@pytest.mark.asyncio
async def test_create_accepts_a_text_at_the_cap(db_session, db_manager):
    service = await _service(db_session, db_manager)

    product = await service.create_product(name=f"P {uuid.uuid4().hex[:6]}", description=AT_CAP)

    assert len(product.description) == MCP_DESCRIPTION_MAX


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "field",
    [
        {"description": OVER},
        {"extraction_custom_instructions": OVER},
        {"tech_stack": {"dev_tools": OVER}},
    ],
)
async def test_update_refuses_a_new_text_over_the_cap(db_session, db_manager, field):
    service = await _service(db_session, db_manager)
    product = await service.create_product(name=f"P {uuid.uuid4().hex[:6]}")

    with pytest.raises(ValidationError, match="Must be at most 20000 characters"):
        await service.update_product(str(product.id), force=True, **field)


@pytest.mark.asyncio
async def test_a_legacy_long_row_still_saves_when_sent_back_unchanged(db_session, db_manager):
    service = await _service(db_session, db_manager)
    product = await _legacy_product(db_session, service.tenant_key)

    updated = await service.update_product(
        str(product.id), force=True, name="Renamed", description=LEGACY, core_features=LEGACY
    )

    assert updated.name == "Renamed"
    assert updated.description == LEGACY


@pytest.mark.asyncio
async def test_a_legacy_long_row_cannot_grow(db_session, db_manager):
    service = await _service(db_session, db_manager)
    product = await _legacy_product(db_session, service.tenant_key)

    with pytest.raises(ValidationError, match="description: Must be at most"):
        await service.update_product(str(product.id), force=True, description=LEGACY + "!")


async def _rest_user(db_manager) -> dict:
    import bcrypt

    from giljo_mcp.auth.jwt_manager import JWTManager
    from giljo_mcp.models.auth import User
    from giljo_mcp.models.organizations import Organization

    tenant_key = TestData.generate_tenant_key()
    unique = uuid.uuid4().hex[:8]
    user_id = str(uuid.uuid4())
    async with db_manager.get_session_async(tenant_key=tenant_key) as session:
        org = Organization(name=f"SEC0064c {unique}", slug=f"sec0064c-{unique}", tenant_key=tenant_key, is_active=True)
        session.add(org)
        await session.flush()
        session.add(
            User(
                id=user_id,
                username=f"sec0064c_{unique}",
                email=f"sec0064c_{unique}@example.com",
                password_hash=bcrypt.hashpw(b"Password1!", bcrypt.gensalt(rounds=4)).decode(),
                tenant_key=tenant_key,
                role="admin",
                org_id=org.id,
                is_active=True,
                token_revocation_epoch=0,
            )
        )
        await session.commit()
    claims = {"tenant_key": tenant_key, "revocation_epoch": 0}
    token = JWTManager.create_access_token(user_id=user_id, username=f"sec0064c_{unique}", role="admin", **claims)
    csrf = uuid.uuid4().hex
    return {"Cookie": f"access_token={token}; csrf_token={csrf}", "X-CSRF-Token": csrf}


@pytest.mark.asyncio
async def test_rest_create_with_an_over_long_text_is_refused(api_client, db_manager, monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "test_secret_key")
    headers = await _rest_user(db_manager)

    resp = await api_client.post(
        "/api/v1/products/",
        json={"name": f"P {uuid.uuid4().hex[:6]}", "tech_stack": {"programming_languages": OVER}},
        headers=headers,
    )

    assert resp.status_code == 400, resp.text
    assert resp.json()["message"] == "tech_stack.programming_languages: Must be at most 20000 characters."
