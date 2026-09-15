# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import asyncio
import uuid

import pytest
import pytest_asyncio
from sqlalchemy import delete, select

from giljo_mcp.domain.project_status import ProjectStatus
from giljo_mcp.models import Product, Project
from giljo_mcp.models.agent_identity import AgentExecution, AgentJob
from giljo_mcp.services.project_lifecycle_service import ProjectLifecycleService
from giljo_mcp.tenant import TenantManager


@pytest_asyncio.fixture
async def isolated_tenant_key() -> str:
    return TenantManager.generate_tenant_key()


async def _seed_product(db_manager, tenant_key: str, name: str) -> str:
    product_id = str(uuid.uuid4())
    async with db_manager.get_session_async(tenant_key=tenant_key) as session:
        session.add(Product(id=product_id, name=name, tenant_key=tenant_key, is_active=False))
        await session.commit()
    return product_id


async def _seed_inactive_project(db_manager, tenant_key: str, product_id: str, name: str, series_number: int) -> str:
    project_id = str(uuid.uuid4())
    async with db_manager.get_session_async(tenant_key=tenant_key) as session:
        session.add(
            Project(
                id=project_id,
                tenant_key=tenant_key,
                product_id=product_id,
                name=name,
                description="BE-9502b concurrency proof",
                mission="prove the invariant",
                status=ProjectStatus.INACTIVE,
                series_number=series_number,
            )
        )
        await session.commit()
    return project_id


@pytest_asyncio.fixture
async def two_products(db_manager, isolated_tenant_key):
    tenant_key = isolated_tenant_key
    product_a = await _seed_product(db_manager, tenant_key, "BE-9502b Product A")
    product_b = await _seed_product(db_manager, tenant_key, "BE-9502b Product B")
    project_a = await _seed_inactive_project(db_manager, tenant_key, product_a, "Project A1", series_number=1)
    project_b = await _seed_inactive_project(db_manager, tenant_key, product_b, "Project B1", series_number=1)

    yield {
        "tenant_key": tenant_key,
        "product_a": product_a,
        "product_b": product_b,
        "project_a": project_a,
        "project_b": project_b,
    }

    async with db_manager.get_session_async(tenant_key=tenant_key) as cleanup:
        await cleanup.execute(delete(AgentExecution).where(AgentExecution.tenant_key == tenant_key))
        await cleanup.execute(delete(AgentJob).where(AgentJob.tenant_key == tenant_key))
        await cleanup.execute(delete(Project).where(Project.tenant_key == tenant_key))
        await cleanup.execute(delete(Product).where(Product.tenant_key == tenant_key))
        await cleanup.commit()


def _lifecycle_service(db_manager, tenant_key: str) -> ProjectLifecycleService:
    tm = TenantManager()
    tm.set_current_tenant(tenant_key)
    return ProjectLifecycleService(db_manager=db_manager, tenant_manager=tm)


@pytest.mark.asyncio
async def test_concurrent_activation_across_two_products_does_not_cross_contaminate(db_manager, two_products):
    tenant_key = two_products["tenant_key"]

    async def activate(project_id: str) -> Project:
        svc = _lifecycle_service(db_manager, tenant_key)
        return await svc.activate_project(project_id, tenant_key=tenant_key)

    project_a, project_b = await asyncio.gather(
        activate(two_products["project_a"]),
        activate(two_products["project_b"]),
    )

    assert project_a.status == ProjectStatus.ACTIVE
    assert project_b.status == ProjectStatus.ACTIVE

    async with db_manager.get_session_async(tenant_key=tenant_key) as verify:
        rows = (await verify.execute(select(Project).where(Project.tenant_key == tenant_key))).scalars().all()
    by_id = {p.id: p for p in rows}
    assert by_id[two_products["project_a"]].status == ProjectStatus.ACTIVE
    assert by_id[two_products["project_b"]].status == ProjectStatus.ACTIVE


@pytest.mark.asyncio
async def test_concurrent_activation_within_one_product_both_succeed_active(db_manager, two_products):
    tenant_key = two_products["tenant_key"]
    product_a = two_products["product_a"]
    project_a1 = two_products["project_a"]
    project_a2 = await _seed_inactive_project(db_manager, tenant_key, product_a, "Project A2", series_number=2)

    async def activate(project_id: str):
        svc = _lifecycle_service(db_manager, tenant_key)
        return await svc.activate_project(project_id, tenant_key=tenant_key)

    project_1, project_2 = await asyncio.gather(activate(project_a1), activate(project_a2))

    assert project_1.status == ProjectStatus.ACTIVE
    assert project_2.status == ProjectStatus.ACTIVE

    async with db_manager.get_session_async(tenant_key=tenant_key) as verify:
        rows = (
            (
                await verify.execute(
                    select(Project).where(Project.tenant_key == tenant_key, Project.product_id == product_a)
                )
            )
            .scalars()
            .all()
        )

    active_rows = [p for p in rows if p.status == ProjectStatus.ACTIVE]
    assert len(active_rows) == 2, (
        f"ruling 5 amended: N active projects per product is legal; both concurrent "
        f"activations must persist ACTIVE; got {[(p.id, p.status.value) for p in rows]}"
    )


@pytest.mark.asyncio
async def test_activating_product_b_project_never_touches_product_a_active_state(db_manager, two_products):
    tenant_key = two_products["tenant_key"]
    svc = _lifecycle_service(db_manager, tenant_key)
    await svc.activate_project(two_products["project_a"], tenant_key=tenant_key)

    async def activate_b():
        return await _lifecycle_service(db_manager, tenant_key).activate_project(
            two_products["project_b"], tenant_key=tenant_key
        )

    async def reread_a():
        async with db_manager.get_session_async(tenant_key=tenant_key) as session:
            return (await session.execute(select(Project).where(Project.id == two_products["project_a"]))).scalar_one()

    project_b, project_a_mid_flight = await asyncio.gather(activate_b(), reread_a())

    assert project_b.status == ProjectStatus.ACTIVE
    assert project_a_mid_flight.status == ProjectStatus.ACTIVE

    async with db_manager.get_session_async(tenant_key=tenant_key) as verify:
        project_a_final = (
            await verify.execute(select(Project).where(Project.id == two_products["project_a"]))
        ).scalar_one()
    assert project_a_final.status == ProjectStatus.ACTIVE
