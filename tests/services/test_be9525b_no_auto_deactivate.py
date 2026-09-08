# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-9525b -- ruling 5 amended: activating a project must NOT deactivate any
other project in the same product.

Museum-rule proof: before this project, ``ProjectLifecycleService
.activate_project`` auto-deactivated the product's existing active project
(Handover 0050b) via ``find_active_in_product`` + a flush, to satisfy
``idx_project_single_active_per_product``. This test seeds project A already
ACTIVE, activates sibling project B in the SAME product, and asserts A is
UNCHANGED -- red on pre-BE-9525b code (A gets silently flipped to inactive),
green after (the auto-deactivate step and the index it existed for are both
gone).
"""

import random
from uuid import uuid4

import pytest
import pytest_asyncio

from giljo_mcp.domain.project_status import ProjectStatus
from giljo_mcp.models.products import Product
from giljo_mcp.models.projects import Project
from giljo_mcp.services.project_lifecycle_service import ProjectLifecycleService


@pytest_asyncio.fixture
async def lifecycle_service(db_session, db_manager, tenant_manager, test_tenant_key):
    tenant_manager.set_current_tenant(test_tenant_key)
    return ProjectLifecycleService(
        db_manager=db_manager,
        tenant_manager=tenant_manager,
        test_session=db_session,
    )


@pytest_asyncio.fixture
async def one_active_one_inactive(db_session, test_tenant_key):
    """One product with project A already ACTIVE and project B INACTIVE."""
    product = Product(
        id=str(uuid4()),
        tenant_key=test_tenant_key,
        name=f"BE-9525b Product {uuid4().hex[:6]}",
        description="seeded",
        is_active=False,
    )
    db_session.add(product)
    await db_session.flush()

    project_a = Project(
        id=str(uuid4()),
        name="Project A (already active)",
        mission="stay active",
        description="seeded",
        status=ProjectStatus.ACTIVE,
        tenant_key=test_tenant_key,
        product_id=product.id,
        series_number=random.randint(1, 4000),
    )
    project_b = Project(
        id=str(uuid4()),
        name="Project B (to be activated)",
        mission="get activated",
        description="seeded",
        status=ProjectStatus.INACTIVE,
        tenant_key=test_tenant_key,
        product_id=product.id,
        series_number=random.randint(4001, 9000),
    )
    db_session.add_all([project_a, project_b])
    await db_session.commit()
    await db_session.refresh(project_a)
    await db_session.refresh(project_b)
    return project_a, project_b


@pytest.mark.asyncio
async def test_activating_sibling_project_does_not_deactivate_the_active_one(
    lifecycle_service: ProjectLifecycleService, one_active_one_inactive, db_session, test_tenant_key
):
    project_a, project_b = one_active_one_inactive

    activated_b = await lifecycle_service.activate_project(str(project_b.id), tenant_key=test_tenant_key)

    assert activated_b.status == ProjectStatus.ACTIVE

    await db_session.refresh(project_a)
    assert project_a.status == ProjectStatus.ACTIVE, (
        "activating project B silently deactivated project A -- the ruling-5-amended "
        "auto-deactivate step must be gone, not just error-tolerant"
    )


@pytest.mark.asyncio
async def test_two_projects_active_in_same_product_is_a_legal_end_state(
    lifecycle_service: ProjectLifecycleService, one_active_one_inactive, db_session, test_tenant_key
):
    """DoD: two projects active in one product, both persist, both real rows."""
    project_a, project_b = one_active_one_inactive

    await lifecycle_service.activate_project(str(project_b.id), tenant_key=test_tenant_key)

    await db_session.refresh(project_a)
    await db_session.refresh(project_b)
    assert project_a.status == ProjectStatus.ACTIVE
    assert project_b.status == ProjectStatus.ACTIVE
