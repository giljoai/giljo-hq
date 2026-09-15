# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import uuid
from datetime import UTC, datetime

import pytest

from giljo_mcp.models import Product
from giljo_mcp.services.product_service import ProductService
from tests.fixtures.base_fixtures import TestData


def _add_product(session, tenant_key: str, name: str, *, is_active: bool, is_default: bool = False) -> Product:
    product = Product(
        id=str(uuid.uuid4()),
        name=name,
        description=f"{name} description",
        tenant_key=tenant_key,
        is_active=is_active,
        is_default=is_default,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    session.add(product)
    return product


@pytest.mark.asyncio
async def test_activate_promotes_sole_shown_products_implicit_default(db_session, db_manager):
    tenant_key = TestData.generate_tenant_key()

    product_a = _add_product(db_session, tenant_key, "Product A", is_active=True, is_default=False)
    product_b = _add_product(db_session, tenant_key, "Product B", is_active=False, is_default=False)
    await db_session.commit()

    service = ProductService(db_manager, tenant_key=tenant_key, test_session=db_session)
    await service.activate_product(product_b.id)

    await db_session.refresh(product_a)
    await db_session.refresh(product_b)

    assert product_a.is_default is True, "the outgoing implicit default must be persisted before it is lost"
    assert product_b.is_default is False, "showing B must not itself become the default"


@pytest.mark.asyncio
async def test_activate_does_not_promote_when_sole_shown_product_already_has_persisted_default(db_session, db_manager):
    tenant_key = TestData.generate_tenant_key()

    product_a = _add_product(db_session, tenant_key, "Product A", is_active=True, is_default=True)
    product_b = _add_product(db_session, tenant_key, "Product B", is_active=False, is_default=False)
    await db_session.commit()

    service = ProductService(db_manager, tenant_key=tenant_key, test_session=db_session)
    await service.activate_product(product_b.id)

    await db_session.refresh(product_a)
    await db_session.refresh(product_b)

    assert product_a.is_default is True
    assert product_b.is_default is False


@pytest.mark.asyncio
async def test_activate_does_not_promote_on_the_zero_to_one_transition(db_session, db_manager):
    tenant_key = TestData.generate_tenant_key()

    product_a = _add_product(db_session, tenant_key, "Product A", is_active=False, is_default=False)
    await db_session.commit()

    service = ProductService(db_manager, tenant_key=tenant_key, test_session=db_session)
    await service.activate_product(product_a.id)

    await db_session.refresh(product_a)

    assert product_a.is_default is False


@pytest.mark.asyncio
async def test_activate_does_not_promote_when_already_two_or_more_shown(db_session, db_manager):
    tenant_key = TestData.generate_tenant_key()

    product_a = _add_product(db_session, tenant_key, "Product A", is_active=True, is_default=False)
    product_b = _add_product(db_session, tenant_key, "Product B", is_active=True, is_default=False)
    product_c = _add_product(db_session, tenant_key, "Product C", is_active=False, is_default=False)
    await db_session.commit()

    service = ProductService(db_manager, tenant_key=tenant_key, test_session=db_session)
    await service.activate_product(product_c.id)

    await db_session.refresh(product_a)
    await db_session.refresh(product_b)
    await db_session.refresh(product_c)

    assert product_a.is_default is False
    assert product_b.is_default is False
    assert product_c.is_default is False


@pytest.mark.asyncio
async def test_activate_re_showing_an_already_shown_product_does_not_promote(db_session, db_manager):
    tenant_key = TestData.generate_tenant_key()

    product_a = _add_product(db_session, tenant_key, "Product A", is_active=True, is_default=False)
    await db_session.commit()

    service = ProductService(db_manager, tenant_key=tenant_key, test_session=db_session)
    await service.activate_product(product_a.id)

    await db_session.refresh(product_a)

    assert product_a.is_default is False
