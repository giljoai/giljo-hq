# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""Three artefacts promised a product delete cascade that never happens.

``ProductLifecycleService.delete_product`` writes exactly three fields on the
product row -- ``deleted_at``, ``is_active``, ``updated_at`` -- and touches no
child row. Projects, tasks and vision documents belonging to the product stay
live and unmodified. They disappear only at ``purge_product`` (the 10-day hard
delete), where the foreign key ``ondelete="CASCADE"`` finally fires.

Three places claimed otherwise:

* the ``warning`` string ``get_cascade_impact`` hands the delete dialog, which
  said deleting the product would soft-delete all related entities
* a comment on the deleted-products list endpoint, which said a deleted
  product's children are cascade-soft-deleted and therefore its bulk counts come
  back zero-filled
* the delete dialog itself, whose heading read "This will delete:"

The decision was to correct the copy, not to build the cascade: a real cascade
needs a ``deleted_by_cascade`` marker column plus a migration, and project
restore reallocates ``series_number`` and resets ``status``/``completed_at``, so
a cascade delete/restore round-trip would lose data.

The two tests below pin the two halves of the truth the corrected copy now
states:

* **warning** -- fails against the old string. This is the regression test for
  the false promise.
* **children stay live** -- passes against today's code, because the *behaviour*
  was always right and only the prose lied. Its job is forward-looking: if a
  cascade is ever added, the counts go to zero, this fails, and whoever adds it
  is forced back to the copy corrected here.
"""

import random
from uuid import uuid4

import pytest

from giljo_mcp.models.projects import Project
from giljo_mcp.services.product_service import ProductService


async def _product_with_one_project(db_manager, tenant_key: str) -> str:
    """Create a product with a single live child project. Returns the product id."""
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
    """The delete-impact copy must describe what delete_product actually does."""

    async def test_cascade_impact_warning_does_not_promise_a_cascade(self, db_manager):
        """The warning must not claim related entities are deleted by this delete.

        RED against the shipped string "Deleting this product will soft-delete
        all related entities", which is false at every word that matters.
        """
        tenant_key = str(uuid4())
        product_id = await _product_with_one_project(db_manager, tenant_key)
        service = ProductService(db_manager, tenant_key)

        impact = await service.memory.get_cascade_impact(product_id)

        assert "soft-delete all related" not in impact.warning, (
            "warning still promises a cascade that delete_product does not perform"
        )
        # The facts the user actually needs: nothing changes now, and the children
        # go only when the product itself is purged.
        assert "kept" in impact.warning.lower()
        assert "permanently deleted" in impact.warning.lower()

        # BOTH purge routes must be named. The 10-day expiry is not the only one:
        # DeletedProductsRecoveryDialog exposes per-product "Permanently delete
        # product" and "Delete All" buttons that hard-delete immediately, so a
        # warning citing only the 10 days is false in the other direction.
        assert "10 days" in impact.warning
        assert "from the trash" in impact.warning.lower(), (
            "warning names only the automatic expiry, not the user's own purge action"
        )

    async def test_both_cascade_impact_schemas_expose_the_same_fields(self, db_manager):
        """The two CascadeImpact models must stay in step.

        ``api/endpoints/products/lifecycle.py`` bridges the service model into the
        API model with a manual field-by-field copy, so a field added to one and
        not the other is dropped on the floor without any error. The frontend
        delete dialog is generated against the API model, so a silent gap here is
        exactly how the dialog came to render fields the backend never sent.
        """
        from api.endpoints.products.models import CascadeImpact as ApiCascadeImpact
        from giljo_mcp.schemas.service_responses import CascadeImpact as ServiceCascadeImpact

        assert set(ApiCascadeImpact.model_fields) == set(ServiceCascadeImpact.model_fields)

    async def test_children_stay_live_after_product_delete(self, db_manager):
        """Soft-deleting a product leaves its children live, so counts stay real.

        This is what makes the corrected endpoint comment true: the bulk counts
        for a deleted product are its real, still-live child counts, NOT zeros.
        """
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
