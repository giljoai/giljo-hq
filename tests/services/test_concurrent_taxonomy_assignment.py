# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import asyncio
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import delete, select

from giljo_mcp.database import tenant_session_context
from giljo_mcp.models import Project, Task
from giljo_mcp.models.products import Product
from giljo_mcp.models.projects import TaxonomyType
from giljo_mcp.services.project_service import ProjectService
from giljo_mcp.services.task_service import TaskService
from giljo_mcp.tenant import TenantManager


@pytest_asyncio.fixture
async def isolated_tenant_key() -> str:
    return TenantManager.generate_tenant_key()


@pytest_asyncio.fixture
async def isolated_bucket(db_manager, isolated_tenant_key):
    async with db_manager.get_session_async(tenant_key=isolated_tenant_key) as setup:
        tt = TaxonomyType(
            id=str(uuid4()),
            tenant_key=isolated_tenant_key,
            abbreviation="BE",
            label="Backend",
            color="#1f6feb",
            sort_order=1,
        )
        product = Product(
            id=str(uuid4()),
            name=f"Concurrent product {uuid4().hex[:6]}",
            description="concurrent test",
            tenant_key=isolated_tenant_key,
            is_active=True,
        )
        setup.add(tt)
        setup.add(product)
        await setup.commit()
        tt_id = tt.id
        product_id = product.id

    yield {"tenant_key": isolated_tenant_key, "taxonomy_id": tt_id, "product_id": product_id}

    async with db_manager.get_session_async(tenant_key=isolated_tenant_key) as cleanup:
        with tenant_session_context(cleanup, isolated_tenant_key):
            await cleanup.execute(delete(Task).where(Task.tenant_key == isolated_tenant_key))
            await cleanup.execute(delete(Project).where(Project.tenant_key == isolated_tenant_key))
            await cleanup.execute(delete(Product).where(Product.tenant_key == isolated_tenant_key))
            await cleanup.execute(delete(TaxonomyType).where(TaxonomyType.tenant_key == isolated_tenant_key))
        await cleanup.commit()


class TestConcurrentTaxonomyAssignment:
    @pytest.mark.asyncio
    async def test_concurrent_task_and_project_serialize(self, db_manager, isolated_bucket):
        tenant_key = isolated_bucket["tenant_key"]
        product_id = isolated_bucket["product_id"]
        taxonomy_id = isolated_bucket["taxonomy_id"]

        tm = TenantManager()
        tm.set_current_tenant(tenant_key)

        async def create_task() -> str:
            svc = TaskService(db_manager=db_manager, tenant_manager=tm)
            r = await svc.create_task_for_mcp(
                title=f"Concurrent T {uuid4().hex[:4]}",
                description="concurrent task",
                task_type="BE",
                tenant_key=tenant_key,
            )
            return r["task_id"]

        async def create_project() -> str:
            svc = ProjectService(db_manager=db_manager, tenant_manager=tm)
            p = await svc.create_project(
                name=f"Concurrent P {uuid4().hex[:4]}",
                mission="m",
                description="d",
                product_id=product_id,
                tenant_key=tenant_key,
                project_type_id=taxonomy_id,
            )
            return p.id

        task_id, project_id = await asyncio.gather(create_task(), create_project())

        async with db_manager.get_session_async(tenant_key=tenant_key) as verify:
            task = (await verify.execute(select(Task).where(Task.id == task_id))).scalar_one()
            project = (await verify.execute(select(Project).where(Project.id == project_id))).scalar_one()

        assert task.series_number is not None
        assert project.series_number is not None
        assert task.series_number != project.series_number, (
            f"shared counter violated: task={task.series_number} project={project.series_number}"
        )
        assert {task.series_number, project.series_number} == {1, 2}
