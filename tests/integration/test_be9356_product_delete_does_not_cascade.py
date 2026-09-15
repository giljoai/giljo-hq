# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import random
from uuid import uuid4

import pytest

from giljo_mcp.models.projects import Project
from giljo_mcp.services.product_service import ProductService


async def _product_with_one_project(db_manager, tenant_key: str) -> str:
    service = ProductService(db_manager, tenant_key)
    product = await service.create_product(name=f"BE-9356 Product {uuid4().hex[:8]}")
    product_id = str(product.id)

    async with db_manager.get_session_async() as session:
        session.add(
            Project(
                id=str(uuid4()),
                name="Child Project",
                description="child",
                mission="child mission",
                status="inactive",
                product_id=product_id,
                tenant_key=tenant_key,
                series_number=random.randint(1, 9000),
            )
        )
        await session.commit()

    return product_id


@pytest.mark.asyncio
class TestProductDeleteTellsTheTruth:

    async def test_cascade_impact_warning_does_not_promise_a_cascade(self, db_manager):
        tenant_key = str(uuid4())
        product_id = await _product_with_one_project(db_manager, tenant_key)
        service = ProductService(db_manager, tenant_key)

        impact = await service.memory.get_cascade_impact(product_id)

        assert "soft-delete all related" not in impact.warning, (
            "warning still promises a cascade that delete_product does not perform"
        )
        assert "kept" in impact.warning.lower()
        assert "permanently deleted" in impact.warning.lower()

        assert "10 days" in impact.warning
        assert "from the trash" in impact.warning.lower(), (
            "warning names only the automatic expiry, not the user's own purge action"
        )

    async def test_both_cascade_impact_schemas_expose_the_same_fields(self, db_manager):
        from api.endpoints.products.models import CascadeImpact as ApiCascadeImpact
        from giljo_mcp.schemas.service_responses import CascadeImpact as ServiceCascadeImpact

        assert set(ApiCascadeImpact.model_fields) == set(ServiceCascadeImpact.model_fields)

    async def test_children_stay_live_after_product_delete(self, db_manager):
        tenant_key = str(uuid4())
        product_id = await _product_with_one_project(db_manager, tenant_key)
        service = ProductService(db_manager, tenant_key)

        before = await service.memory.get_product_statistics_bulk([product_id])
        assert before[product_id]["project_count"] == 1

        await service.lifecycle.delete_product(product_id)

        after = await service.memory.get_product_statistics_bulk([product_id])
        assert after[product_id]["project_count"] == 1, (
            "child project was cascaded by delete_product -- the delete-impact copy "
            "and the deleted-products endpoint comment both assume it is not"
        )
