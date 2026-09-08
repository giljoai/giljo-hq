# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-9589 fix 1 — giljo_setup must ASK which product before packaging anything.

THE DEFECT, from the operator's fresh-install transcript: ``giljo_setup`` called
with no ``product_id`` on a 5-product tenant silently packaged a product's agents
and only the repo-binding prose mentioned the ambiguity.

The "never guess" resolution already existed (BE-9523c: ``_resolve_product_binding``
returns ``phase="ambiguous"`` carrying the full product list). It simply did not
stop anything:

    bound_product_id = product_binding.product_id if phase == "bound" else None

``None`` then falls through to ``active_product_template_ids`` -- the DEFAULT
product's junction (file_staging) -- so a zip was minted, staged and served, and
the binding reached only ``build_setup_instructions``. The ambiguity was advisory.

WHAT THESE TESTS PIN, and the second one is the point:

    1. the call is REFUSED with the PRODUCT_AMBIGUOUS house shape, carrying the
       products to choose from;
    2. NOTHING WAS STAGED. A fix that refuses AFTER minting the token would pass a
       test that only checked the refusal, while still burning a download token and
       writing a staging directory for a package nobody asked for. The refusal has
       to come first, so the assertion is on the side effect, not the message.

Single-product and explicit-product callers must be untouched -- they are the
overwhelmingly common path and were never the defect.

Parallel-safe: real DB via the rollback-isolated ``db_session`` fixture, fresh
tenant per test, no module-level mutable state. Edition Scope: Both.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import func, select

from giljo_mcp.database import tenant_session_context
from giljo_mcp.models.config import DownloadToken
from giljo_mcp.services.product_service import ProductAmbiguousError, ProductService
from giljo_mcp.tenant import TenantManager
from giljo_mcp.tools.tool_accessor import ToolAccessor


pytestmark = pytest.mark.asyncio


def _tk(suffix: str) -> str:
    return f"tk_be9589_{suffix}_{uuid.uuid4().hex[:8]}"


async def _accessor(db_manager, db_session) -> ToolAccessor:
    return ToolAccessor(db_manager=db_manager, tenant_manager=TenantManager(), test_session=db_session)


async def _make_products(db_manager, tenant_key: str, names: list[str]) -> list[str]:
    """Real product rows -- the binding resolver counts them, so stubs prove nothing."""
    service = ProductService(db_manager=db_manager, tenant_key=tenant_key)
    ids = []
    for name in names:
        product = await service.create_product(name=name, description=f"{name} for BE-9589")
        ids.append(str(product.id))
    return ids


async def _token_count(db_session, tenant_key: str) -> int:
    with tenant_session_context(db_session, tenant_key):
        return (
            await db_session.execute(
                select(func.count()).select_from(DownloadToken).where(DownloadToken.tenant_key == tenant_key)
            )
        ).scalar_one()


async def test_two_products_and_no_product_id_is_refused(db_manager, db_session):
    """THE DEFECT: today this packages a product's agents instead of asking."""
    tenant_key = _tk("ambiguous")
    await _make_products(db_manager, tenant_key, ["Alpha", "Beta"])
    accessor = await _accessor(db_manager, db_session)

    with pytest.raises(ProductAmbiguousError) as exc:
        await accessor.bootstrap_setup(tenant_key=tenant_key, platform="claude_code")

    names = {p["name"] for p in exc.value.products}
    assert names == {"Alpha", "Beta"}, "the refusal must carry the products to choose from"


async def test_the_refusal_happens_before_anything_is_staged(db_manager, db_session):
    """The assertion that distinguishes a real fix from a late refusal.

    Refusing after ``generate_token`` would satisfy the test above while still
    burning a download token and writing a staging directory for a package nobody
    asked for. The side effect is the evidence, not the message.
    """
    tenant_key = _tk("nostage")
    await _make_products(db_manager, tenant_key, ["Alpha", "Beta"])
    accessor = await _accessor(db_manager, db_session)
    before = await _token_count(db_session, tenant_key)

    with pytest.raises(ProductAmbiguousError):
        await accessor.bootstrap_setup(tenant_key=tenant_key, platform="claude_code")

    assert await _token_count(db_session, tenant_key) == before, (
        "a refused setup must mint no download token -- the refusal has to come before the packaging, not after it"
    )


async def test_a_single_product_tenant_still_binds_silently(db_manager, db_session):
    """Requirement (1), and the negative control for the refusal.

    Without this, a fix that refused whenever product_id was omitted would pass both
    tests above while breaking the overwhelmingly common path.
    """
    tenant_key = _tk("single")
    await _make_products(db_manager, tenant_key, ["Solo"])
    accessor = await _accessor(db_manager, db_session)

    result = await accessor.bootstrap_setup(tenant_key=tenant_key, platform="claude_code")

    assert result["status"] == "ready"


async def test_an_explicit_product_id_is_never_ambiguous(db_manager, db_session):
    """The caller answered the question, so it must not be asked again."""
    tenant_key = _tk("explicit")
    ids = await _make_products(db_manager, tenant_key, ["Alpha", "Beta"])
    accessor = await _accessor(db_manager, db_session)

    result = await accessor.bootstrap_setup(tenant_key=tenant_key, platform="claude_code", product_id=ids[1])

    assert result["status"] == "ready"
