# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from uuid import uuid4

import pytest
from sqlalchemy.exc import MultipleResultsFound

from giljo_mcp.models import Product
from giljo_mcp.services.product_service import ProductService


@pytest.mark.asyncio
async def test_two_shown_products_never_raises_on_an_unscoped_read(db_session, db_manager):
    tenant_key = str(uuid4())

    shown_default = Product(
        id=str(uuid4()), name="Shown Default", tenant_key=tenant_key, is_active=True, is_default=True
    )
    shown_other = Product(id=str(uuid4()), name="Shown Other", tenant_key=tenant_key, is_active=True, is_default=False)
    db_session.add_all([shown_default, shown_other])
    await db_session.commit()

    service = ProductService(db_manager, tenant_key=tenant_key, test_session=db_session)

    try:
        resolved = await service.resolve_binding_product(None, operation="test_op", write=False)
    except MultipleResultsFound:
        pytest.fail(
            "resolve_binding_product raised MultipleResultsFound with two shown "
            "products -- the crash this test exists to pin against."
        )

    assert str(resolved.id) == str(shown_default.id)


@pytest.mark.asyncio
async def test_two_shown_products_neither_default_yields_no_default_not_a_crash(db_session, db_manager):
    from giljo_mcp.exceptions import ValidationError

    tenant_key = str(uuid4())

    shown_a = Product(id=str(uuid4()), name="Shown A", tenant_key=tenant_key, is_active=True, is_default=False)
    shown_b = Product(id=str(uuid4()), name="Shown B", tenant_key=tenant_key, is_active=True, is_default=False)
    db_session.add_all([shown_a, shown_b])
    await db_session.commit()

    service = ProductService(db_manager, tenant_key=tenant_key, test_session=db_session)

    with pytest.raises(ValidationError, match="No default product"):
        await service.resolve_binding_product(None, operation="test_op", write=False)
