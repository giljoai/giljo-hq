# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""FE-9524/D2 -- hidden must never mean inaccessible.

Per the 2026-08-28 multi-product design decision, D2: an
agent holding a ``product_id`` reaches that product whether its tab is shown
or hidden. Verified true on 2026-08-29 by call-path reading (not grep):
``ProductRepository.get_by_id`` filters on ``tenant_key`` and ``deleted_at``
only, never ``is_active`` -- so ``ProductService.resolve_binding_product``
(the MCP-tool binder every create/list/get/search tool routes through) never
excludes a hidden product either.

This is the load-bearing test the project record calls for: pinned here so
nobody "fixes" visibility into an access gate later. It was DEMONSTRATED
FAILING (checker-must-fire) by temporarily adding
``Product.is_active`` to the ``get_by_id`` WHERE clause locally -- both tests
below turned red with a "not found" ValidationError/None result -- then
reverted; that diff is not part of this commit, only its failure is recorded
here for the PR body.
"""

from uuid import uuid4

import pytest

from giljo_mcp.models import Product
from giljo_mcp.repositories.product_repository import ProductRepository
from giljo_mcp.services.product_service import ProductService


@pytest.mark.asyncio
async def test_resolve_binding_product_reaches_a_hidden_product_by_id(db_session, db_manager):
    """A write call (write=True) naming a hidden product's id must bind to it,
    not fall back to the active product and not reject it as unknown."""
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
    """Repository-level pin: the tenant + not-deleted check is the whole
    membership test. No is_active condition may be added to this query --
    that would silently turn "hidden" into "inaccessible" for every caller
    that reaches a product by id (resolve_binding_product included)."""
    tenant_key = str(uuid4())
    hidden = Product(id=str(uuid4()), name="Hidden", tenant_key=tenant_key, is_active=False)
    db_session.add(hidden)
    await db_session.commit()

    repo = ProductRepository()
    found = await repo.get_by_id(db_session, tenant_key, hidden.id)

    assert found is not None
    assert str(found.id) == str(hidden.id)
