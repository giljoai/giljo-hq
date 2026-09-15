# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import asyncio
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import delete

from giljo_mcp.database import tenant_session_context
from giljo_mcp.models import Project
from giljo_mcp.models.products import Product
from giljo_mcp.repositories.taxonomy_repository import TaxonomyRepository
from giljo_mcp.tenant import TenantManager


@pytest_asyncio.fixture
async def isolated_tenant_key() -> str:
    return TenantManager.generate_tenant_key()


@pytest_asyncio.fixture
async def isolated_product(db_manager, isolated_tenant_key):
    async with db_manager.get_session_async(tenant_key=isolated_tenant_key) as setup:
        product = Product(
            id=str(uuid4()),
            name=f"BE-9486 product {uuid4().hex[:6]}",
            description="BE-9486 series-number race test",
            tenant_key=isolated_tenant_key,
            is_active=True,
        )
        setup.add(product)
        await setup.commit()
        product_id = product.id

    yield {"tenant_key": isolated_tenant_key, "product_id": product_id}

    async with db_manager.get_session_async(tenant_key=isolated_tenant_key) as cleanup:
        with tenant_session_context(cleanup, isolated_tenant_key):
            await cleanup.execute(delete(Project).where(Project.tenant_key == isolated_tenant_key))
            await cleanup.execute(delete(Product).where(Product.tenant_key == isolated_tenant_key))
        await cleanup.commit()


class TestTaxonomySeriesNumberRace:
    @pytest.mark.asyncio
    async def test_two_racers_get_distinct_series_numbers(self, db_manager, isolated_product):
        tenant_key = isolated_product["tenant_key"]
        product_id = isolated_product["product_id"]
        repo = TaxonomyRepository()

        async def racer(name: str) -> int:
            async with db_manager.get_session_async(tenant_key=tenant_key) as session:
                with tenant_session_context(session, tenant_key):
                    n = await repo.get_next_series_number(session, tenant_key, "", product_id)
                    session.add(
                        Project(
                            id=str(uuid4()),
                            name=name,
                            description="BE-9486 racer",
                            mission="m",
                            tenant_key=tenant_key,
                            product_id=product_id,
                            status="inactive",
                            series_number=n,
                        )
                    )
                await session.commit()
                return n

        n_a, n_b = await asyncio.gather(racer("Racer A"), racer("Racer B"))

        assert n_a != n_b, f"series-number race: both racers minted {n_a}"
        assert {n_a, n_b} == {1, 2}
