# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-9502a museum-rule pinning test.

TaskService.list_tasks(filter_type="product_tasks") with no explicit product_id
falls back to the tenant's ACTIVE product (task_service/_query_mixin.py:139-148,
via TaskRepository.get_default_product -> Product.is_active). A tenant with no
active product gets an EMPTY list, not an error and not the whole tenant's tasks.

This call path had zero prior test coverage (found during the BE-9502a is_active
dependents audit). Pinning it here BEFORE any behavior change so a later
active-product-demotion change cannot silently alter it. Both assertions were
verified to fail first against a variant that removed the ``Product.is_active``
predicate from ``TaskRepository.get_default_product`` (it then returned an
arbitrary/most-recent product instead of None, which flipped
``test_falls_back_to_empty_list_with_no_active_product`` from empty to non-empty).
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from giljo_mcp.models import Product
from giljo_mcp.services.task_service import TaskService
from giljo_mcp.services.taxonomy_service import TaxonomyService
from giljo_mcp.tenant import TenantManager


pytestmark = pytest.mark.asyncio


async def test_scopes_to_the_active_product_when_product_id_omitted(db_session, db_manager, two_tenant_service_setup):
    tenant_a = two_tenant_service_setup["tenant_a"]
    product_a = two_tenant_service_setup["product_a"]

    # A second, INACTIVE product in the same tenant with its own task.
    product_a2 = Product(
        id=str(uuid4()),
        name="Service Test Product A2",
        tenant_key=tenant_a,
        is_active=False,
    )
    db_session.add(product_a2)
    await db_session.commit()

    tax = TaxonomyService(db_manager=db_manager, session=db_session)
    await tax.create_type(tenant_key=tenant_a, abbreviation="BE", label="Backend")
    await db_session.commit()

    task_service = TaskService(db_manager=db_manager, tenant_manager=TenantManager(), session=db_session)

    active_task = await task_service.create_task_for_mcp(
        title="On the active product",
        description="x",
        task_type="BE",
        tenant_key=tenant_a,
        db_manager=db_manager,
        product_id=str(product_a.id),
    )
    inactive_task = await task_service.create_task_for_mcp(
        title="On the inactive product",
        description="x",
        task_type="BE",
        tenant_key=tenant_a,
        db_manager=db_manager,
        product_id=str(product_a2.id),
    )
    await db_session.commit()

    tasks = await task_service.list_tasks(filter_type="product_tasks", tenant_key=tenant_a)
    ids = {t.id for t in tasks}

    assert active_task["task_id"] in ids
    assert inactive_task["task_id"] not in ids


async def test_falls_back_to_empty_list_with_no_active_product(db_session, db_manager, two_tenant_service_setup):
    tenant_a = two_tenant_service_setup["tenant_a"]
    product_a = two_tenant_service_setup["product_a"]

    # Deactivate the only product -- the tenant now has NO active product.
    product_a.is_active = False
    await db_session.commit()

    tax = TaxonomyService(db_manager=db_manager, session=db_session)
    await tax.create_type(tenant_key=tenant_a, abbreviation="BE", label="Backend")
    await db_session.commit()

    task_service = TaskService(db_manager=db_manager, tenant_manager=TenantManager(), session=db_session)
    await task_service.create_task_for_mcp(
        title="Orphaned by deactivation",
        description="x",
        task_type="BE",
        tenant_key=tenant_a,
        db_manager=db_manager,
        product_id=str(product_a.id),
    )
    await db_session.commit()

    tasks = await task_service.list_tasks(filter_type="product_tasks", tenant_key=tenant_a)

    assert tasks == []
