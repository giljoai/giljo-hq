# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
import pytest_asyncio

from giljo_mcp.exceptions import ValidationError
from giljo_mcp.models import Product
from giljo_mcp.tenant import TenantManager
from giljo_mcp.tools.setup_instructions import ProductBindingContext
from giljo_mcp.tools.tool_accessor._setup_tools import SetupMiscMixin
from tests.helpers.test_db_helper import purge_tenant_rows


pytestmark = pytest.mark.asyncio


class _Accessor(SetupMiscMixin):

    def __init__(self, db_manager):
        self.db_manager = db_manager


async def _add_product(db_manager, tenant_key: str, name: str, *, is_active: bool = True) -> str:
    product_id = str(uuid.uuid4())
    async with db_manager.get_session_async(tenant_key=tenant_key) as session:
        session.add(
            Product(
                id=product_id,
                name=name,
                description=f"{name} description",
                tenant_key=tenant_key,
                is_active=is_active,
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            )
        )
        await session.commit()
    return product_id


@pytest_asyncio.fixture
async def tenant_key(db_manager):
    key = TenantManager.generate_tenant_key()
    try:
        yield key
    finally:
        await purge_tenant_rows(db_manager, key)


async def test_zero_products_resolves_to_zero_phase(db_manager, tenant_key):
    accessor = _Accessor(db_manager)
    binding = await accessor._resolve_product_binding(tenant_key, None)
    assert binding == ProductBindingContext(phase="zero")


async def test_exactly_one_product_auto_binds_without_product_id(db_manager, tenant_key):
    product_id = await _add_product(db_manager, tenant_key, "Giljo HQ")
    accessor = _Accessor(db_manager)

    binding = await accessor._resolve_product_binding(tenant_key, None)

    assert binding.phase == "bound"
    assert binding.product_id == product_id
    assert binding.product_name == "Giljo HQ"


async def test_multiple_products_without_product_id_is_ambiguous_never_guesses(db_manager, tenant_key):
    id_a = await _add_product(db_manager, tenant_key, "Giljo HQ", is_active=True)
    id_b = await _add_product(db_manager, tenant_key, "Giljo Agent Message Hub", is_active=False)
    accessor = _Accessor(db_manager)

    binding = await accessor._resolve_product_binding(tenant_key, None)

    assert binding.phase == "ambiguous"
    ids = {p["id"] for p in binding.products}
    assert ids == {id_a, id_b}
    by_id = {p["id"]: p for p in binding.products}
    assert by_id[id_a]["name"] == "Giljo HQ"
    assert by_id[id_a]["is_active"] is True
    assert by_id[id_b]["is_active"] is False


async def test_explicit_product_id_binds_even_with_multiple_products(db_manager, tenant_key):
    id_a = await _add_product(db_manager, tenant_key, "Giljo HQ", is_active=True)
    id_b = await _add_product(db_manager, tenant_key, "Giljo Agent Message Hub", is_active=False)
    accessor = _Accessor(db_manager)

    binding = await accessor._resolve_product_binding(tenant_key, id_b)

    assert binding.phase == "bound"
    assert binding.product_id == id_b
    assert binding.product_name == "Giljo Agent Message Hub"
    assert binding.product_id != id_a


async def test_explicit_product_id_is_tenant_scoped_not_trusted_blind(db_manager, tenant_key):
    other_tenant = TenantManager.generate_tenant_key()
    foreign_id = await _add_product(db_manager, other_tenant, "Someone Else's Product")
    accessor = _Accessor(db_manager)

    try:
        with pytest.raises(ValidationError):
            await accessor._resolve_product_binding(tenant_key, foreign_id)
    finally:
        await purge_tenant_rows(db_manager, other_tenant)


async def test_unknown_product_id_is_rejected_not_silently_dropped(db_manager, tenant_key):
    accessor = _Accessor(db_manager)
    with pytest.raises(ValidationError):
        await accessor._resolve_product_binding(tenant_key, str(uuid.uuid4()))
