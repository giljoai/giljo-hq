# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


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
    tenant_key = _tk("ambiguous")
    await _make_products(db_manager, tenant_key, ["Alpha", "Beta"])
    accessor = await _accessor(db_manager, db_session)

    with pytest.raises(ProductAmbiguousError) as exc:
        await accessor.bootstrap_setup(tenant_key=tenant_key, platform="claude_code")

    names = {p["name"] for p in exc.value.products}
    assert names == {"Alpha", "Beta"}, "the refusal must carry the products to choose from"


async def test_the_refusal_happens_before_anything_is_staged(db_manager, db_session):
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
    tenant_key = _tk("single")
    await _make_products(db_manager, tenant_key, ["Solo"])
    accessor = await _accessor(db_manager, db_session)

    result = await accessor.bootstrap_setup(tenant_key=tenant_key, platform="claude_code")

    assert result["status"] == "ready"


async def test_an_explicit_product_id_is_never_ambiguous(db_manager, db_session):
    tenant_key = _tk("explicit")
    ids = await _make_products(db_manager, tenant_key, ["Alpha", "Beta"])
    accessor = await _accessor(db_manager, db_session)

    result = await accessor.bootstrap_setup(tenant_key=tenant_key, platform="claude_code", product_id=ids[1])

    assert result["status"] == "ready"
