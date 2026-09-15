# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from uuid import uuid4

import pytest

from giljo_mcp.models import Product
from giljo_mcp.repositories.product_repository import ProductRepository
from giljo_mcp.services.product_service import ProductService


@pytest.mark.asyncio
async def test_resolve_binding_product_reaches_a_hidden_product_by_id(db_session, db_manager):
    tenant_key = str(uuid4())

    shown = Product(id=str(uuid4()), name="Shown", tenant_key=tenant_key, is_active=True)
    hidden = Product(id=str(uuid4()), name="Hidden", tenant_key=tenant_key, is_active=False)
    db_session.add_all([shown, hidden])
    await db_session.commit()

    service = ProductService(db_manager, tenant_key=tenant_key, test_session=db_session)

    resolved = await service.resolve_binding_product(hidden.id, operation="test_op", write=True)

    assert str(resolved.id) == str(hidden.id)


@pytest.mark.asyncio
async def test_get_by_id_does_not_filter_on_is_active(db_session):
    tenant_key = str(uuid4())
    hidden = Product(id=str(uuid4()), name="Hidden", tenant_key=tenant_key, is_active=False)
    db_session.add(hidden)
    await db_session.commit()

    repo = ProductRepository()
    found = await repo.get_by_id(db_session, tenant_key, hidden.id)

    assert found is not None
    assert str(found.id) == str(hidden.id)
