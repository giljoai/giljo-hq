# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-9486: ``TaxonomyRepository.get_next_series_number`` must serialize.

Two concurrent readers of the same ``(tenant_key, product_id)`` bucket must
never observe the same ``max(...) + 1`` watermark and go on to mint the same
``series_number`` -- the class of bug ``uq_project_taxonomy_active`` caught on
master CI run 7803 (BE-9486).

``ProjectRepository.get_next_series_number_shared`` already serializes via
``lock_rows_for_series_shared`` (BE-5065, predates this incident -- see
``tests/services/test_concurrent_taxonomy_assignment.py``). This test covers
the SECOND allocator, ``TaxonomyRepository.get_next_series_number`` (feeds the
``/next-series`` UI preview), which had no such protection: nothing pairs it
with an insert today, but a future caller that treats the preview as an
allocator would inherit the exact same race. This test drives it exactly like
an allocator (read watermark, insert, commit) to prove it can no longer mint a
duplicate.
"""

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
    """Own-committed product in a fresh tenant bucket; cleaned up after."""
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
        """BE-9486 deterministic repro: two racers driving the (unlocked, pre-fix)
        allocator concurrently must not both mint the same series_number.

        Each racer opens its OWN session (own DB connection, like two separate
        API requests), reads the next watermark from
        ``TaxonomyRepository.get_next_series_number``, inserts a ``Project`` with
        it, and commits -- the exact read-then-insert shape any real allocator
        caller would use. Before the BE-9486 fix this reliably fails: both
        connections' SELECT MAX race in the same window, read the same
        watermark, and the second INSERT trips ``uq_project_taxonomy_active``.
        After the fix, ``get_next_series_number`` takes the same
        ``pg_advisory_xact_lock`` bucket as ``ProjectRepository.lock_rows_for_
        series_shared``, so the second racer blocks until the first commits and
        reads a fresh watermark.
        """
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
