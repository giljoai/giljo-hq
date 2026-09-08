# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""FE-9524 -- a crash caught in review before this change merged.

Dropping idx_product_single_active_per_tenant (D1: several products may be
shown at once) makes ProductRepository.get_active_product's old
scalar_one_or_none() query on is_active unsafe: the instant a tenant shows a
TWO products, that query matches two rows and raises MultipleResultsFound.
That crash reaches every unscoped read in the product (list_tasks,
list_projects, get_roadmap, search_memory, resolve_binding_product's no-
product_id branch, and more -- see the PR body for the full caller
enumeration).

The fix: SHOWN (is_active, several per tenant)
and DEFAULT (is_default, exactly one per tenant, where an unscoped read
resolves) are two different columns now. This test is the pin: two products
SHOWN at once, one unscoped read, asserting the resolution is the DEFAULT
one and that it never raises.

Demonstrated failing against the pre-fix code: temporarily reverted
ProductRepository.get_default_product to its first-draft form (querying
is_active with a bare scalar_one_or_none(), no is_default column) and ran
this file -- both tests below raised MultipleResultsFound. Reverted back
before commit.
"""

from uuid import uuid4

import pytest
from sqlalchemy.exc import MultipleResultsFound

from giljo_mcp.models import Product
from giljo_mcp.services.product_service import ProductService


@pytest.mark.asyncio
async def test_two_shown_products_never_raises_on_an_unscoped_read(db_session, db_manager):
    """The exact crash: two products with is_active=True in one tenant, then
    an unscoped read (resolve_binding_product with no product_id). Must
    resolve cleanly -- to the DEFAULT one -- never raise MultipleResultsFound."""
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
    """Two products shown, NEITHER explicitly defaulted: an unscoped read
    must degrade to "no default" (ValidationError, the pre-existing legal
    state), never guess between them and never raise MultipleResultsFound."""
    from giljo_mcp.exceptions import ValidationError

    tenant_key = str(uuid4())

    shown_a = Product(id=str(uuid4()), name="Shown A", tenant_key=tenant_key, is_active=True, is_default=False)
    shown_b = Product(id=str(uuid4()), name="Shown B", tenant_key=tenant_key, is_active=True, is_default=False)
    db_session.add_all([shown_a, shown_b])
    await db_session.commit()

    service = ProductService(db_manager, tenant_key=tenant_key, test_session=db_session)

    # BE-9554 re-baseline: the message's WORDING changed (it now names the remedy the
    # caller can actually perform -- pass product_id -- because no MCP tool sets a
    # default). This assertion is deliberately loosened to the stable part of the
    # sentence so it keeps pinning FE-9524's INVARIANT (degrade to a clean
    # ValidationError, never guess between the two, never raise MultipleResultsFound)
    # without re-pinning copy that BE-9554 owns. The remedy wording itself is asserted
    # by tests/services/test_be9554_unscoped_read_names_a_usable_remedy.py.
    with pytest.raises(ValidationError, match="No default product"):
        await service.resolve_binding_product(None, operation="test_op", write=False)
