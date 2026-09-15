# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from datetime import UTC
from uuid import uuid4

import pytest
import pytest_asyncio

from giljo_mcp.exceptions import ValidationError
from giljo_mcp.models.products import Product
from giljo_mcp.models.projects import TaxonomyType
from giljo_mcp.services.project_service import ProjectService
from giljo_mcp.services.task_service import TaskService


@pytest_asyncio.fixture
async def be_taxonomy(db_session, test_tenant_key) -> TaxonomyType:
    tt = TaxonomyType(
        id=str(uuid4()),
        tenant_key=test_tenant_key,
        abbreviation="BE",
        label="Backend",
        color="#1f6feb",
        sort_order=1,
    )
    db_session.add(tt)
    await db_session.commit()
    await db_session.refresh(tt)
    return tt


@pytest_asyncio.fixture
async def fe_taxonomy(db_session, test_tenant_key) -> TaxonomyType:
    tt = TaxonomyType(
        id=str(uuid4()),
        tenant_key=test_tenant_key,
        abbreviation="FE",
        label="Frontend",
        color="#a371f7",
        sort_order=2,
    )
    db_session.add(tt)
    await db_session.commit()
    await db_session.refresh(tt)
    return tt


@pytest_asyncio.fixture
async def active_product(db_session, test_tenant_key) -> Product:
    product = Product(
        id=str(uuid4()),
        name=f"Shared Counter Product {uuid4().hex[:6]}",
        description="Product for shared-counter tests",
        tenant_key=test_tenant_key,
        is_active=True,
    )
    db_session.add(product)
    await db_session.commit()
    await db_session.refresh(product)
    return product


@pytest_asyncio.fixture
async def project_service(db_manager, db_session, test_tenant_key) -> ProjectService:
    from giljo_mcp.tenant import TenantManager

    tm = TenantManager()
    tm.set_current_tenant(test_tenant_key)
    return ProjectService(db_manager=db_manager, tenant_manager=tm, test_session=db_session)


class TestSharedSeriesCounter:
    @pytest.mark.asyncio
    async def test_project_then_task(
        self,
        task_service: TaskService,
        project_service: ProjectService,
        db_session,
        test_tenant_key: str,
        active_product: Product,
        be_taxonomy: TaxonomyType,
    ):
        project = await project_service.create_project(
            name="P1",
            mission="m1",
            description="d1",
            product_id=active_product.id,
            tenant_key=test_tenant_key,
            project_type_id=be_taxonomy.id,
        )
        task_result = await task_service.create_task_for_mcp(
            title="T1",
            description="t1",
            task_type="BE",
            tenant_key=test_tenant_key,
        )

        from giljo_mcp.models import Task

        task = (
            await db_session.execute(__import__("sqlalchemy").select(Task).where(Task.id == task_result["task_id"]))
        ).scalar_one()
        assert project.series_number == 1
        assert task.series_number == 2

    @pytest.mark.asyncio
    async def test_task_then_project(
        self,
        task_service: TaskService,
        project_service: ProjectService,
        db_session,
        test_tenant_key: str,
        active_product: Product,
        be_taxonomy: TaxonomyType,
    ):
        task_result = await task_service.create_task_for_mcp(
            title="T1",
            description="t1",
            task_type="BE",
            tenant_key=test_tenant_key,
        )
        project = await project_service.create_project(
            name="P1",
            mission="m1",
            description="d1",
            product_id=active_product.id,
            tenant_key=test_tenant_key,
            project_type_id=be_taxonomy.id,
        )

        from sqlalchemy import select

        from giljo_mcp.models import Task

        task = (await db_session.execute(select(Task).where(Task.id == task_result["task_id"]))).scalar_one()
        assert task.series_number == 1
        assert project.series_number == 2

    @pytest.mark.asyncio
    async def test_soft_deleted_project_excluded_from_high_water_mark(
        self,
        project_service: ProjectService,
        db_session,
        test_tenant_key: str,
        active_product: Product,
        be_taxonomy: TaxonomyType,
    ):
        from datetime import datetime

        from sqlalchemy import select

        from giljo_mcp.models.projects import Project

        doomed = await project_service.create_project(
            name="Doomed-9999",
            mission="m",
            description="d",
            product_id=active_product.id,
            tenant_key=test_tenant_key,
            project_type_id=be_taxonomy.id,
        )
        doomed_row = (await db_session.execute(select(Project).where(Project.id == doomed.id))).scalar_one()
        doomed_row.series_number = 9999
        doomed_row.deleted_at = datetime.now(UTC)
        await db_session.commit()

        survivor = await project_service.create_project(
            name="Survivor",
            mission="m",
            description="d",
            product_id=active_product.id,
            tenant_key=test_tenant_key,
            project_type_id=be_taxonomy.id,
        )

        assert survivor.series_number != 10000
        assert survivor.series_number == 1


class TestGlobalSerialCounter:

    @pytest.mark.asyncio
    async def test_counter_is_global_across_two_tags(
        self,
        task_service: TaskService,
        project_service: ProjectService,
        db_session,
        test_tenant_key: str,
        active_product: Product,
        be_taxonomy: TaxonomyType,
        fe_taxonomy: TaxonomyType,
    ):
        from sqlalchemy import select

        from giljo_mcp.models import Task

        be_project = await project_service.create_project(
            name="BE-P",
            mission="m",
            description="d",
            product_id=active_product.id,
            tenant_key=test_tenant_key,
            project_type_id=be_taxonomy.id,
        )
        fe_project = await project_service.create_project(
            name="FE-P",
            mission="m",
            description="d",
            product_id=active_product.id,
            tenant_key=test_tenant_key,
            project_type_id=fe_taxonomy.id,
        )
        task_result = await task_service.create_task_for_mcp(
            title="BE-T",
            description="t",
            task_type="BE",
            tenant_key=test_tenant_key,
        )
        task = (await db_session.execute(select(Task).where(Task.id == task_result["task_id"]))).scalar_one()

        assert be_project.series_number == 1
        assert fe_project.series_number == 2
        assert task.series_number == 3

    @pytest.mark.asyncio
    async def test_project_cap_rejected_above_9999(
        self,
        project_service: ProjectService,
        db_session,
        test_tenant_key: str,
        active_product: Product,
        be_taxonomy: TaxonomyType,
    ):
        from sqlalchemy import select

        from giljo_mcp.models.projects import Project

        seed = await project_service.create_project(
            name="Seed-9999",
            mission="m",
            description="d",
            product_id=active_product.id,
            tenant_key=test_tenant_key,
            project_type_id=be_taxonomy.id,
        )
        seed_row = (await db_session.execute(select(Project).where(Project.id == seed.id))).scalar_one()
        seed_row.series_number = 9999
        await db_session.commit()

        with pytest.raises(ValidationError, match="exhausted"):
            await project_service.create_project(
                name="Overflow",
                mission="m",
                description="d",
                product_id=active_product.id,
                tenant_key=test_tenant_key,
                project_type_id=be_taxonomy.id,
            )

    @pytest.mark.asyncio
    async def test_task_cap_rejected_above_9999(
        self,
        task_service: TaskService,
        project_service: ProjectService,
        db_session,
        test_tenant_key: str,
        active_product: Product,
        be_taxonomy: TaxonomyType,
    ):
        from sqlalchemy import select

        from giljo_mcp.models.projects import Project

        seed = await project_service.create_project(
            name="Seed-9999",
            mission="m",
            description="d",
            product_id=active_product.id,
            tenant_key=test_tenant_key,
            project_type_id=be_taxonomy.id,
        )
        seed_row = (await db_session.execute(select(Project).where(Project.id == seed.id))).scalar_one()
        seed_row.series_number = 9999
        await db_session.commit()

        with pytest.raises(ValidationError, match="exhausted"):
            await task_service.create_task_for_mcp(
                title="Overflow task",
                description="t",
                task_type="BE",
                tenant_key=test_tenant_key,
            )

    @pytest.mark.asyncio
    async def test_soft_delete_frees_and_restore_reallocates_fresh(
        self,
        project_service: ProjectService,
        db_session,
        test_tenant_key: str,
        active_product: Product,
        be_taxonomy: TaxonomyType,
    ):
        from sqlalchemy import select

        from giljo_mcp.models.projects import Project

        first = await project_service.create_project(
            name="First",
            mission="m",
            description="d",
            product_id=active_product.id,
            tenant_key=test_tenant_key,
            project_type_id=be_taxonomy.id,
        )
        assert first.series_number == 1

        await project_service.deletion.delete_project(first.id)

        second = await project_service.create_project(
            name="Second",
            mission="m",
            description="d",
            product_id=active_product.id,
            tenant_key=test_tenant_key,
            project_type_id=be_taxonomy.id,
        )
        assert second.series_number == 1

        await project_service.deletion.restore_project(first.id, tenant_key=test_tenant_key)
        restored = (await db_session.execute(select(Project).where(Project.id == first.id))).scalar_one()

        assert restored.deleted_at is None
        assert restored.series_number == 2
        assert restored.series_number != second.series_number
