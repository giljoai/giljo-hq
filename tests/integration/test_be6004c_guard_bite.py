# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import delete, select, update

from giljo_mcp.database import TenantIsolationError
from giljo_mcp.models.products import Product
from giljo_mcp.tenant import TenantManager
from tests.helpers.test_db_helper import TransactionalTestContext


def _product(tenant_key: str) -> Product:
    return Product(
        id=str(uuid4()),
        name=f"guard-bite {uuid4().hex[:8]}",
        description="BE6004C-6 guard-bite seed",
        tenant_key=tenant_key,
        product_memory={},
    )


def _strip_context(session) -> None:
    session.info.pop("tenant_key", None)
    session.info.pop("tenant_key_source", None)
    TenantManager.clear_current_tenant()


@pytest.mark.parametrize("verb", ["select", "update", "delete"])
@pytest.mark.asyncio
async def test_contextless_tenant_scoped_statement_raises_under_enforce(db_manager, monkeypatch, verb):
    monkeypatch.setenv("GILJO_TENANT_GUARD_MODE", "enforce")
    tenant_key = TenantManager.generate_tenant_key()

    async with TransactionalTestContext(db_manager) as session:
        product = _product(tenant_key)
        session.add(product)
        await session.flush()
        _strip_context(session)

        if verb == "select":
            stmt = select(Product)
        elif verb == "update":
            stmt = update(Product).values(description="should not apply")
        else:
            stmt = delete(Product)

        with pytest.raises(TenantIsolationError):
            await session.execute(stmt)
