# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import random
import uuid
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from sqlalchemy import select

from giljo_mcp.database import TenantIsolationError
from giljo_mcp.exceptions import ResourceNotFoundError
from giljo_mcp.models import Product, Project, Task
from giljo_mcp.services.dto import MemoryEntryCreateParams
from giljo_mcp.services.product_memory_service import ProductMemoryService
from giljo_mcp.services.product_service import ProductService
from giljo_mcp.services.project_service import ProjectService
from giljo_mcp.services.task_service import TaskService
from giljo_mcp.tenant import TenantManager


@pytest_asyncio.fixture(scope="function")
async def two_tenants_full_surface(db_session, db_manager):
    tenant_a = TenantManager.generate_tenant_key()
    tenant_b = TenantManager.generate_tenant_key()

    product_a = Product(
        id=str(uuid.uuid4()),
        name="TSK-9020 Tenant A Product",
        description="Tripwire product for tenant A",
        tenant_key=tenant_a,
        is_active=True,
    )
    product_b = Product(
        id=str(uuid.uuid4()),
        name="TSK-9020 Tenant B Product",
        description="Tripwire product for tenant B -- must never be reachable from tenant A",
        tenant_key=tenant_b,
        is_active=True,
    )
    db_session.add_all([product_a, product_b])
    await db_session.commit()

    project_a = Project(
        id=str(uuid.uuid4()),
        name="TSK-9020 Tenant A Project",
        description="Tripwire project A",
        mission="Tripwire mission A",
        tenant_key=tenant_a,
        product_id=product_a.id,
        status="active",
        series_number=random.randint(1, 900_000),
    )
    project_b = Project(
        id=str(uuid.uuid4()),
        name="TSK-9020 Tenant B Project",
        description="Tripwire project B -- must never be reachable from tenant A",
        mission="Tripwire mission B",
        tenant_key=tenant_b,
        product_id=product_b.id,
        status="active",
        series_number=random.randint(1, 900_000),
    )
    db_session.add_all([project_a, project_b])
    await db_session.commit()

    task_a = Task(
        id=str(uuid.uuid4()),
        title="TSK-9020 Tenant A Task",
        description="Tripwire task A",
        tenant_key=tenant_a,
        product_id=product_a.id,
        project_id=project_a.id,
        status="pending",
    )
    task_b = Task(
        id=str(uuid.uuid4()),
        title="TSK-9020 Tenant B Task",
        description="Tripwire task B -- must never be reachable from tenant A",
        tenant_key=tenant_b,
        product_id=product_b.id,
        project_id=project_b.id,
        status="pending",
    )
    db_session.add_all([task_a, task_b])
    await db_session.commit()

    for obj in (product_a, product_b, project_a, project_b, task_a, task_b):
        await db_session.refresh(obj)

    return {
        "tenant_a": tenant_a,
        "tenant_b": tenant_b,
        "product_a": product_a,
        "product_b": product_b,
        "project_a": project_a,
        "project_b": project_b,
        "task_a": task_a,
        "task_b": task_b,
    }


@pytest.mark.tenant_isolation
@pytest.mark.asyncio
async def test_cross_tenant_read_blocked_across_all_surfaces(db_session, db_manager, two_tenants_full_surface):
    data = two_tenants_full_surface
    tenant_a = data["tenant_a"]

    TenantManager.set_current_tenant(tenant_a)
    try:
        violations: list[str] = []

        project_service = ProjectService(db_manager=db_manager, tenant_manager=TenantManager(), test_session=db_session)
        try:
            await project_service.get_project(project_id=data["project_b"].id, tenant_key=tenant_a)
            violations.append("ProjectService.get_project() returned tenant B's project")
        except ResourceNotFoundError:
            pass

        task_service = TaskService(db_manager=db_manager, tenant_manager=TenantManager(), session=db_session)
        try:
            await task_service.get_task(task_id=data["task_b"].id)
            violations.append("TaskService.get_task() returned tenant B's task")
        except ResourceNotFoundError:
            pass


        product_service = ProductService(db_manager=db_manager, tenant_key=tenant_a, test_session=db_session)
        try:
            await product_service.get_product(product_id=data["product_b"].id)
            violations.append("ProductService.get_product() returned tenant B's product")
        except ResourceNotFoundError:
            pass

        memory_service = ProductMemoryService(db_manager=db_manager, tenant_key=tenant_a, test_session=db_session)
        try:
            await memory_service.search_memory(product_id=data["product_b"].id, query="tripwire")
            violations.append("ProductMemoryService.search_memory() searched tenant B's product")
        except ResourceNotFoundError:
            pass

        assert not violations, "CRITICAL: cross-tenant READ leak(s):\n" + "\n".join(f"- {v}" for v in violations)
    finally:
        TenantManager.clear_current_tenant()


@pytest.mark.tenant_isolation
@pytest.mark.asyncio
async def test_cross_tenant_update_blocked_across_all_surfaces(db_session, db_manager, two_tenants_full_surface):
    data = two_tenants_full_surface
    tenant_a = data["tenant_a"]

    TenantManager.set_current_tenant(tenant_a)
    try:
        violations: list[str] = []

        project_service = ProjectService(db_manager=db_manager, tenant_manager=TenantManager(), test_session=db_session)
        try:
            await project_service.update_project(project_id=data["project_b"].id, updates={"name": "pwned"})
            violations.append("ProjectService.update_project() updated tenant B's project")
        except ResourceNotFoundError:
            pass

        task_service = TaskService(db_manager=db_manager, tenant_manager=TenantManager(), session=db_session)
        try:
            await task_service.update_task(task_id=data["task_b"].id, status="in_progress")
            violations.append("TaskService.update_task() updated tenant B's task")
        except ResourceNotFoundError:
            pass


        product_service = ProductService(db_manager=db_manager, tenant_key=tenant_a, test_session=db_session)
        try:
            await product_service.update_product(product_id=data["product_b"].id, name="pwned")
            violations.append("ProductService.update_product() updated tenant B's product")
        except ResourceNotFoundError:
            pass

        assert not violations, "CRITICAL: cross-tenant UPDATE leak(s):\n" + "\n".join(f"- {v}" for v in violations)

        await db_session.refresh(data["project_b"])
        await db_session.refresh(data["task_b"])
        await db_session.refresh(data["product_b"])
        assert data["project_b"].name == "TSK-9020 Tenant B Project"
        assert data["task_b"].status == "pending"
        assert data["product_b"].name == "TSK-9020 Tenant B Product"
    finally:
        TenantManager.clear_current_tenant()


@pytest.mark.tenant_isolation
@pytest.mark.asyncio
async def test_negative_control_unscoped_query_raises(db_session, two_tenants_full_surface):
    data = two_tenants_full_surface
    db_session.info.pop("tenant_key", None)
    db_session.info.pop("tenant_key_source", None)
    previous_tenant = TenantManager.get_current_tenant()
    TenantManager.clear_current_tenant()

    try:
        with pytest.raises(TenantIsolationError):
            await db_session.execute(select(Product).where(Product.id == data["product_b"].id))

        with pytest.raises(TenantIsolationError):
            await db_session.execute(select(Task).where(Task.id == data["task_b"].id))
    finally:
        if previous_tenant:
            TenantManager.set_current_tenant(previous_tenant)


@pytest.mark.tenant_isolation
@pytest.mark.asyncio
async def test_create_entry_rejects_product_tenant_mismatch(db_session, db_manager, two_tenants_full_surface):
    data = two_tenants_full_surface
    tenant_a = data["tenant_a"]
    tenant_b = data["tenant_b"]
    product_b = data["product_b"]

    memory_service = ProductMemoryService(db_manager=db_manager, tenant_key=tenant_a, test_session=db_session)
    mismatched_params = MemoryEntryCreateParams(
        tenant_key=tenant_a,
        product_id=product_b.id,
        sequence=1,
        entry_type="project_completion",
        source="tsk9022_tripwire",
        timestamp=datetime.now(tz=UTC),
        summary="cross-tenant write attempt",
    )

    with pytest.raises(ResourceNotFoundError):
        await memory_service.create_entry(params=mismatched_params, session=db_session)

    await db_session.refresh(product_b)
    assert product_b.name == "TSK-9020 Tenant B Product"

    from giljo_mcp.models.product_memory_entry import ProductMemoryEntry

    TenantManager.set_current_tenant(tenant_b)
    try:
        leaked = await db_session.execute(
            select(ProductMemoryEntry).where(ProductMemoryEntry.product_id == product_b.id)
        )
        assert leaked.scalars().all() == [], "CRITICAL: cross-tenant memory entry write landed"
    finally:
        TenantManager.clear_current_tenant()
