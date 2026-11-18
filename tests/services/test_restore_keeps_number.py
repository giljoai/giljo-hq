# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import select

from giljo_mcp.models import Task
from giljo_mcp.models.auth import User
from giljo_mcp.models.products import Product
from giljo_mcp.models.projects import Project
from giljo_mcp.repositories.project_repository import ProjectRepository
from giljo_mcp.repositories.taxonomy_repository import TaxonomyRepository
from giljo_mcp.services.project_service import ProjectService


pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def product(db_session, test_tenant_key) -> Product:
    row = Product(
        id=str(uuid4()),
        name=f"Restore Number Product {uuid4().hex[:6]}",
        description="restore keeps number",
        tenant_key=test_tenant_key,
        is_active=True,
    )
    db_session.add(row)
    await db_session.commit()
    return row


@pytest_asyncio.fixture
async def admin_id(db_session, test_tenant_key) -> User:
    user = User(id=str(uuid4()), tenant_key=test_tenant_key, username=f"admin_{uuid4().hex[:6]}", role="admin")
    db_session.add(user)
    await db_session.commit()
    return str(user.id)


@pytest_asyncio.fixture
async def project_service(db_manager, db_session, test_tenant_key) -> ProjectService:
    from giljo_mcp.tenant import TenantManager

    tm = TenantManager()
    tm.set_current_tenant(test_tenant_key)
    return ProjectService(db_manager=db_manager, tenant_manager=tm, test_session=db_session)


async def _new_project(project_service, product, tenant_key, name: str):
    return await project_service.create_project(
        name=name, mission="m", description="d", product_id=product.id, tenant_key=tenant_key
    )


async def _new_task(task_service, product, tenant_key) -> str:
    created = await task_service.create_task_for_mcp(
        title=f"task {uuid4().hex[:6]}",
        description="restore keeps number",
        tenant_key=tenant_key,
        product_id=product.id,
    )
    return created["task_id"]


async def _number(db_session, model, row_id: str) -> int:
    await db_session.commit()
    query = select(model.series_number).where(model.id == row_id)
    return (await db_session.execute(query)).scalar_one()


class TestProjectRestoreKeepsNumber:
    async def test_trash_create_restore_reads_back_the_old_number(
        self, project_service, db_session, test_tenant_key, product
    ):
        a = await _new_project(project_service, product, test_tenant_key, "A")
        b = await _new_project(project_service, product, test_tenant_key, "B")
        assert (a.series_number, b.series_number) == (1, 2)

        await project_service.deletion.delete_project(a.id)
        c = await _new_project(project_service, product, test_tenant_key, "C")
        assert c.series_number == 3

        await project_service.deletion.restore_project(a.id, tenant_key=test_tenant_key)

        assert await _number(db_session, Project, a.id) == 1

    async def test_the_highest_trashed_number_is_not_reused_while_trashed(
        self, project_service, test_tenant_key, product
    ):
        a = await _new_project(project_service, product, test_tenant_key, "A")
        b = await _new_project(project_service, product, test_tenant_key, "B")
        await project_service.deletion.delete_project(b.id)

        c = await _new_project(project_service, product, test_tenant_key, "C")

        assert c.series_number not in (a.series_number, b.series_number)

    async def test_a_live_row_holding_the_number_falls_back_to_the_lowest_free_number(
        self, project_service, db_session, test_tenant_key, product
    ):
        a = await _new_project(project_service, product, test_tenant_key, "A")
        await project_service.deletion.delete_project(a.id)
        squatter = await _new_project(project_service, product, test_tenant_key, "Squatter")
        assert squatter.series_number == 2
        squatter_row = (await db_session.execute(select(Project).where(Project.id == squatter.id))).scalar_one()
        squatter_row.series_number = 1
        await db_session.commit()

        await project_service.deletion.restore_project(a.id, tenant_key=test_tenant_key)

        restored = await _number(db_session, Project, a.id)
        assert restored != 1
        assert restored == 2
        assert await _number(db_session, Project, squatter.id) == 1

    async def test_restore_of_a_cancelled_project_still_keeps_its_number(
        self, project_service, db_session, test_tenant_key, product
    ):
        a = await _new_project(project_service, product, test_tenant_key, "A")
        row = (await db_session.execute(select(Project).where(Project.id == a.id))).scalar_one()
        row.status = "cancelled"
        await db_session.commit()

        await project_service.deletion.restore_project(a.id, tenant_key=test_tenant_key)

        assert await _number(db_session, Project, a.id) == 1


class TestTaskRestoreKeepsNumber:
    async def test_trash_create_restore_reads_back_the_old_number(
        self, task_service, db_session, test_tenant_key, product, admin_id
    ):
        a = await _new_task(task_service, product, test_tenant_key)
        b = await _new_task(task_service, product, test_tenant_key)
        assert await _number(db_session, Task, a) == 1
        assert await _number(db_session, Task, b) == 2

        await task_service.delete_task(a, admin_id)
        c = await _new_task(task_service, product, test_tenant_key)
        assert await _number(db_session, Task, c) == 3

        restored = await task_service.restore_task(a)

        restored_number = restored.series_number
        assert restored_number == 1
        assert await _number(db_session, Task, a) == 1

    async def test_the_highest_trashed_number_is_not_reused_while_trashed(
        self, task_service, db_session, test_tenant_key, product, admin_id
    ):
        await _new_task(task_service, product, test_tenant_key)
        b = await _new_task(task_service, product, test_tenant_key)
        await task_service.delete_task(b, admin_id)

        c = await _new_task(task_service, product, test_tenant_key)

        assert await _number(db_session, Task, c) == 3

    async def test_a_live_row_holding_the_number_falls_back_to_the_lowest_free_number(
        self, task_service, db_session, test_tenant_key, product, admin_id
    ):
        a = await _new_task(task_service, product, test_tenant_key)
        await task_service.delete_task(a, admin_id)
        squatter = await _new_task(task_service, product, test_tenant_key)
        squatter_row = (await db_session.execute(select(Task).where(Task.id == squatter))).scalar_one()
        squatter_row.series_number = 1
        await db_session.commit()

        restored = await task_service.restore_task(a)

        assert restored.series_number == 2
        assert await _number(db_session, Task, squatter) == 1

    async def test_a_task_and_a_project_never_share_a_restored_number(
        self, task_service, project_service, db_session, test_tenant_key, product, admin_id
    ):
        t = await _new_task(task_service, product, test_tenant_key)
        await task_service.delete_task(t, admin_id)
        p = await _new_project(project_service, product, test_tenant_key, "P")
        assert p.series_number == 2

        restored = await task_service.restore_task(t)

        assert restored.series_number == 1
        assert restored.series_number != p.series_number


class TestHeldNumberShowsAsTakenForHandEntry:
    async def test_check_series_available_reports_a_trashed_projects_number_as_taken(
        self, project_service, db_session, test_tenant_key, product
    ):
        a = await _new_project(project_service, product, test_tenant_key, "A")
        row = (await db_session.execute(select(Project).where(Project.id == a.id))).scalar_one()
        type_id = row.project_type_id
        await project_service.deletion.delete_project(a.id)

        repo = TaxonomyRepository()
        assert (
            await repo.check_series_available(db_session, test_tenant_key, type_id, 1, None, None, product.id) is False
        )
        assert (
            await ProjectRepository().check_duplicate_taxonomy(
                db_session, test_tenant_key, product.id, type_id, 1, None
            )
            is True
        )

    async def test_a_restored_projects_number_is_released_to_nobody_else(
        self, project_service, db_session, test_tenant_key, product
    ):
        a = await _new_project(project_service, product, test_tenant_key, "A")
        await project_service.deletion.delete_project(a.id)
        await project_service.deletion.restore_project(a.id, tenant_key=test_tenant_key)

        nxt = await _new_project(project_service, product, test_tenant_key, "Next")

        assert nxt.series_number == 2


class TestMintersAgree:
    async def test_every_minter_skips_a_trashed_number_and_agrees(
        self, project_service, task_service, db_session, test_tenant_key, product, admin_id
    ):
        a = await _new_project(project_service, product, test_tenant_key, "A")
        await project_service.deletion.delete_project(a.id)

        preview = await TaxonomyRepository().get_next_series_number(db_session, test_tenant_key, "x", product.id)
        shared = await ProjectRepository().get_next_series_number_shared(db_session, test_tenant_key, product.id)
        assert preview == shared == 2

        task_id = await _new_task(task_service, product, test_tenant_key)
        assert await _number(db_session, Task, task_id) == 2
