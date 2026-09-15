# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from datetime import UTC, datetime
from uuid import uuid4

import pytest

from giljo_mcp.domain.project_status import ProjectStatus
from giljo_mcp.exceptions import ResourceNotFoundError
from giljo_mcp.models import AgentJob, Product, Project
from giljo_mcp.services.product_lifecycle_service import ProductLifecycleService
from giljo_mcp.services.product_service import ProductService




@pytest.mark.tenant_isolation
@pytest.mark.asyncio
async def test_cascade_impact_blocks_cross_tenant(two_tenant_products):
    data = two_tenant_products
    service = ProductService(
        db_manager=data["db_manager"],
        tenant_key=data["tenant_a"],
        test_session=data["db_session"],
    )

    with pytest.raises(ResourceNotFoundError):
        await service.memory.get_cascade_impact(product_id=data["product_b"].id)


@pytest.mark.tenant_isolation
@pytest.mark.asyncio
async def test_cascade_impact_same_tenant_counts_correctly(two_tenant_products):
    data = two_tenant_products
    service = ProductService(
        db_manager=data["db_manager"],
        tenant_key=data["tenant_a"],
        test_session=data["db_session"],
    )

    result = await service.memory.get_cascade_impact(product_id=data["product_a"].id)

    assert result.total_projects >= 1
    assert result.total_tasks >= 1
    assert result.total_vision_documents >= 1




@pytest.mark.tenant_isolation
@pytest.mark.asyncio
async def test_product_statistics_blocks_cross_tenant(two_tenant_products):
    data = two_tenant_products
    service = ProductService(
        db_manager=data["db_manager"],
        tenant_key=data["tenant_a"],
        test_session=data["db_session"],
    )

    with pytest.raises(ResourceNotFoundError):
        await service.memory.get_product_statistics(product_id=data["product_b"].id)


@pytest.mark.tenant_isolation
@pytest.mark.asyncio
async def test_product_statistics_same_tenant_counts_correctly(two_tenant_products):
    data = two_tenant_products
    service = ProductService(
        db_manager=data["db_manager"],
        tenant_key=data["tenant_a"],
        test_session=data["db_session"],
    )

    result = await service.memory.get_product_statistics(product_id=data["product_a"].id)

    assert result.project_count >= 1
    assert result.task_count >= 1
    assert result.vision_documents_count >= 1


@pytest.mark.tenant_isolation
@pytest.mark.asyncio
async def test_deactivate_product_touches_no_project_or_job_of_either_tenant(db_session, two_tenant_products):
    data = two_tenant_products
    data["project_a"].status = ProjectStatus.ACTIVE
    foreign_project = Project(
        id=str(uuid4()),
        name="Tenant B Stray Project",
        description="Foreign tenant row sharing tenant A product_id",
        mission="Tenant B mission",
        tenant_key=data["tenant_b"],
        product_id=data["product_a"].id,
        status=ProjectStatus.INACTIVE,
        series_number=987001,
    )
    foreign_job = AgentJob(
        job_id=str(uuid4()),
        job_type="tester",
        tenant_key=data["tenant_b"],
        project_id=foreign_project.id,
        mission="Foreign tenant job",
        status="active",
        created_at=datetime.now(UTC),
    )
    db_session.add_all([foreign_project, foreign_job])
    await db_session.commit()

    service = ProductLifecycleService(
        db_manager=data["db_manager"],
        tenant_key=data["tenant_a"],
        test_session=db_session,
    )

    result = await service.deactivate_product(data["product_a"].id)

    await db_session.refresh(data["project_a"])
    await db_session.refresh(data["job_a"])
    await db_session.refresh(foreign_project)
    await db_session.refresh(foreign_job)

    assert result.is_active is False
    assert data["project_a"].status == ProjectStatus.ACTIVE
    assert data["job_a"].status == "active"
    assert foreign_project.status == ProjectStatus.INACTIVE
    assert foreign_job.status == "active"


@pytest.mark.tenant_isolation
@pytest.mark.asyncio
async def test_activate_product_touches_no_project_or_job_of_either_tenant(db_session, two_tenant_products):
    data = two_tenant_products
    data["project_a"].status = ProjectStatus.ACTIVE
    new_product = Product(
        id=str(uuid4()),
        name="Tenant A New Product",
        description="A second shown product",
        tenant_key=data["tenant_a"],
        is_active=False,
    )
    foreign_project = Project(
        id=str(uuid4()),
        name="Tenant B Stray Project For Bulk",
        description="Foreign tenant row sharing tenant A product_id",
        mission="Tenant B mission",
        tenant_key=data["tenant_b"],
        product_id=data["product_a"].id,
        status=ProjectStatus.INACTIVE,
        series_number=987002,
    )
    foreign_job = AgentJob(
        job_id=str(uuid4()),
        job_type="tester",
        tenant_key=data["tenant_b"],
        project_id=foreign_project.id,
        mission="Foreign tenant job",
        status="active",
        created_at=datetime.now(UTC),
    )
    db_session.add_all([new_product, foreign_project, foreign_job])
    await db_session.commit()

    service = ProductLifecycleService(
        db_manager=data["db_manager"],
        tenant_key=data["tenant_a"],
        test_session=db_session,
    )

    result = await service.activate_product(new_product.id)

    await db_session.refresh(data["project_a"])
    await db_session.refresh(data["job_a"])
    await db_session.refresh(foreign_project)
    await db_session.refresh(foreign_job)

    assert result.is_active is True
    assert data["project_a"].status == ProjectStatus.ACTIVE
    assert data["job_a"].status == "active"
    assert foreign_project.status == ProjectStatus.INACTIVE
    assert foreign_job.status == "active"
