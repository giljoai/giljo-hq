# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from uuid import uuid4

import pytest

from giljo_mcp.exceptions import ValidationError
from giljo_mcp.models import Product
from giljo_mcp.services.product_service import ProductService


async def _service_with(db_session, db_manager, tenant_key: str, products: list[Product]) -> ProductService:
    if products:
        db_session.add_all(products)
        await db_session.commit()
    return ProductService(db_manager, tenant_key=tenant_key, test_session=db_session)


@pytest.mark.asyncio
async def test_two_shown_no_default_read_names_product_id_not_an_impossible_tool(db_session, db_manager):
    tenant_key = str(uuid4())
    await _service_with(
        db_session,
        db_manager,
        tenant_key,
        [
            Product(id=str(uuid4()), name="Alpha", tenant_key=tenant_key, is_active=True, is_default=False),
            Product(id=str(uuid4()), name="Beta", tenant_key=tenant_key, is_active=True, is_default=False),
        ],
    )
    service = ProductService(db_manager, tenant_key=tenant_key, test_session=db_session)

    with pytest.raises(ValidationError) as exc:
        await service.resolve_binding_product(None, operation="list_projects", action="listed", write=False)

    message = str(exc.value)
    assert "product_id" in message, (
        "The no-default read message must name passing product_id -- the remedy the "
        f"agent can actually perform. Got: {message!r}"
    )
    assert "dashboard" in message.lower(), (
        "Setting a default is a DASHBOARD action (no MCP tool exists for it, per the "
        f"2026-08-15 ruling extended to is_default). The message must say so. Got: {message!r}"
    )


@pytest.mark.asyncio
async def test_sole_shown_product_still_resolves_without_a_default(db_session, db_manager):
    tenant_key = str(uuid4())
    sole = Product(id=str(uuid4()), name="Only", tenant_key=tenant_key, is_active=True, is_default=False)
    await _service_with(db_session, db_manager, tenant_key, [sole])
    service = ProductService(db_manager, tenant_key=tenant_key, test_session=db_session)

    resolved = await service.resolve_binding_product(None, operation="list_projects", action="listed", write=False)

    assert resolved.id == sole.id, "A tenant's sole SHOWN product must still resolve with no is_default set."


@pytest.mark.asyncio
async def test_not_found_message_does_not_route_the_caller_into_product_ambiguous(db_session, db_manager):
    tenant_key = str(uuid4())
    await _service_with(
        db_session,
        db_manager,
        tenant_key,
        [
            Product(id=str(uuid4()), name="Alpha", tenant_key=tenant_key, is_active=True, is_default=True),
            Product(id=str(uuid4()), name="Beta", tenant_key=tenant_key, is_active=True, is_default=False),
        ],
    )
    service = ProductService(db_manager, tenant_key=tenant_key, test_session=db_session)

    with pytest.raises(ValidationError) as exc:
        await service.resolve_binding_product(str(uuid4()), operation="create_project", write=True)

    message = str(exc.value)
    assert "the active product" not in message.lower(), (
        "The fallback target is the DEFAULT product (is_default) since FE-9524. "
        f"'the active product' is the retired vocabulary. Got: {message!r}"
    )
    assert "omit product_id" not in message.lower(), (
        "Advising the caller to omit product_id routes a multi-product write straight "
        f"into PRODUCT_AMBIGUOUS -- a hint that causes a second rejection. Got: {message!r}"
    )


@pytest.mark.asyncio
async def test_ambiguous_write_still_refuses_and_still_carries_the_product_list(db_session, db_manager):
    from giljo_mcp.services.product_service import ProductAmbiguousError

    tenant_key = str(uuid4())
    await _service_with(
        db_session,
        db_manager,
        tenant_key,
        [
            Product(id=str(uuid4()), name="Alpha", tenant_key=tenant_key, is_active=True, is_default=True),
            Product(id=str(uuid4()), name="Beta", tenant_key=tenant_key, is_active=True, is_default=False),
        ],
    )
    service = ProductService(db_manager, tenant_key=tenant_key, test_session=db_session)

    with pytest.raises(ProductAmbiguousError) as exc:
        await service.resolve_binding_product(None, operation="create_project", write=True)

    assert len(exc.value.products) == 2, "PRODUCT_AMBIGUOUS must still carry every product for the retry."
