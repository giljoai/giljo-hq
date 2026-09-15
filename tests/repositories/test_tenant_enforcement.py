# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select

from giljo_mcp.database import TenantIsolationError, tenant_isolation_bypass
from giljo_mcp.models.agent_identity import AgentExecution, AgentJob
from giljo_mcp.models.auth import User
from giljo_mcp.models.products import Product, ProductArchitecture
from giljo_mcp.models.projects import Project
from giljo_mcp.repositories.agent_operations_repository import AgentOperationsRepository
from giljo_mcp.repositories.auth_repository import AuthRepository
from giljo_mcp.repositories.product_repository import ProductRepository
from giljo_mcp.repositories.product_statistics_repository import ProductStatisticsRepository
from giljo_mcp.tenant import TenantManager


def _tenant_key() -> str:
    return TenantManager.generate_tenant_key()


def _product(tenant_key: str, name: str) -> Product:
    return Product(
        id=str(uuid4()),
        tenant_key=tenant_key,
        name=name,
        description=f"{name} description",
        product_memory={},
    )


def _project(tenant_key: str, product_id: str, name: str, status: str = "active") -> Project:
    return Project(
        id=str(uuid4()),
        tenant_key=tenant_key,
        product_id=product_id,
        name=name,
        description=f"{name} description",
        mission=f"{name} mission",
        status=status,
    )


def _user(tenant_key: str, username: str, email: str) -> User:
    return User(
        id=str(uuid4()),
        tenant_key=tenant_key,
        username=username,
        email=email,
        password_hash="not-used",
        role="developer",
        is_active=True,
    )


@pytest.mark.asyncio
async def test_tenant_session_filters_unqualified_orm_select(db_session):
    tenant_a = _tenant_key()
    tenant_b = _tenant_key()
    product_a = _product(tenant_a, "tenant-a")
    product_b = _product(tenant_b, "tenant-b")
    db_session.add_all([product_a, product_b])
    await db_session.commit()

    db_session.info["tenant_key"] = tenant_a
    result = await db_session.execute(select(Product).order_by(Product.name))

    assert [product.tenant_key for product in result.scalars().all()] == [tenant_a]


@pytest.mark.asyncio
async def test_explicit_conflicting_tenant_predicate_does_not_bypass_active_context(db_session):
    tenant_a = _tenant_key()
    tenant_b = _tenant_key()
    product_a = _product(tenant_a, "tenant-a")
    product_b = _product(tenant_b, "tenant-b")
    project_a = _project(tenant_a, product_a.id, "project-a")
    project_b = _project(tenant_b, product_b.id, "project-b")
    db_session.add_all([product_a, product_b, project_a, project_b])
    await db_session.commit()

    db_session.info["tenant_key"] = tenant_a
    result = await db_session.execute(select(Project).where(Project.tenant_key == tenant_b))

    assert result.scalars().all() == []


@pytest.mark.asyncio
async def test_tenant_scoped_orm_select_fails_without_context(db_session):
    tenant_key = _tenant_key()
    db_session.add(_product(tenant_key, "tenant-a"))
    await db_session.commit()
    db_session.info.pop("tenant_key", None)
    db_session.info.pop("tenant_key_source", None)

    with pytest.raises(TenantIsolationError):
        await db_session.execute(select(Product))


@pytest.mark.asyncio
async def test_explicit_tenant_predicate_fails_without_context(db_session):
    tenant_key = _tenant_key()
    db_session.add(_product(tenant_key, "tenant-a"))
    await db_session.commit()
    db_session.info.pop("tenant_key", None)
    db_session.info.pop("tenant_key_source", None)

    with pytest.raises(TenantIsolationError):
        await db_session.execute(select(Product).where(Product.tenant_key == tenant_key))


@pytest.mark.asyncio
async def test_db_manager_binds_explicit_tenant_context_for_orm_select(db_manager):
    tenant_key = _tenant_key()

    async with db_manager.get_session_async(tenant_key=tenant_key) as session:
        session.add(_product(tenant_key, "tenant-a"))

    async with db_manager.get_session_async(tenant_key=tenant_key) as session:
        result = await session.execute(select(Product).where(Product.tenant_key == tenant_key))

    products = [product for product in result.scalars().all() if product.name == "tenant-a"]
    assert [product.tenant_key for product in products] == [tenant_key]


@pytest.mark.asyncio
async def test_explicit_tenant_predicate_fails_after_flush_derived_context(db_session):
    tenant_a = _tenant_key()
    tenant_b = _tenant_key()
    product_a = _product(tenant_a, "tenant-a")
    product_b = _product(tenant_b, "tenant-b")
    db_session.add_all([product_a, product_b])
    await db_session.commit()
    db_session.info.pop("tenant_key", None)
    db_session.info.pop("tenant_key_source", None)

    db_session.add(_product(tenant_a, "tenant-a-new"))
    await db_session.flush()

    with pytest.raises(TenantIsolationError):
        await db_session.execute(select(Product).where(Product.tenant_key == tenant_b))


@pytest.mark.asyncio
async def test_tenant_bypass_is_model_scoped(db_session):
    tenant_a = _tenant_key()
    tenant_b = _tenant_key()
    product_a = _product(tenant_a, "tenant-a")
    product_b = _product(tenant_b, "tenant-b")
    db_session.add_all([product_a, product_b])
    await db_session.commit()

    with tenant_isolation_bypass(db_session, reason="test cross-tenant product scan", models=(Product,)):
        result = await db_session.execute(select(Product).order_by(Product.name))

    with pytest.raises(TenantIsolationError):
        with tenant_isolation_bypass(db_session, reason="wrong model scope", models=(Project,)):
            await db_session.execute(select(Product))

    products = [product for product in result.scalars().all() if product.id in {product_a.id, product_b.id}]
    assert {product.tenant_key for product in products} == {tenant_a, tenant_b}


@pytest.mark.asyncio
async def test_product_repository_list_products_eager_loads_related_models_without_bypass(db_session):
    tenant_a = _tenant_key()
    tenant_b = _tenant_key()
    product_a = _product(tenant_a, "tenant-a")
    product_b = _product(tenant_b, "tenant-b")
    db_session.add_all(
        [
            product_a,
            product_b,
            ProductArchitecture(
                id=str(uuid4()),
                tenant_key=tenant_a,
                product_id=product_a.id,
                primary_pattern="tenant-a-pattern",
            ),
            ProductArchitecture(
                id=str(uuid4()),
                tenant_key=tenant_b,
                product_id=product_b.id,
                primary_pattern="tenant-b-pattern",
            ),
        ]
    )
    await db_session.commit()
    db_session.info["tenant_key"] = tenant_a

    products = await ProductRepository().list_products(db_session, tenant_a, include_inactive=True)

    assert [product.name for product in products] == ["tenant-a"]
    assert products[0].architecture.primary_pattern == "tenant-a-pattern"


@pytest.mark.asyncio
async def test_product_repository_find_expired_deleted_scans_all_tenants_without_context(db_session):
    tenant_a = _tenant_key()
    tenant_b = _tenant_key()
    product_a = _product(tenant_a, "deleted-a")
    product_b = _product(tenant_b, "deleted-b")
    product_fresh = _product(tenant_a, "fresh")
    product_a.deleted_at = datetime.now(UTC) - timedelta(days=20)
    product_b.deleted_at = datetime.now(UTC) - timedelta(days=20)
    product_fresh.deleted_at = datetime.now(UTC)
    db_session.add_all([product_a, product_b, product_fresh])
    await db_session.commit()
    db_session.info.pop("tenant_key", None)
    previous_tenant = TenantManager.get_current_tenant()
    TenantManager.clear_current_tenant()

    try:
        products = await ProductRepository().find_expired_deleted(db_session, days_before_purge=10)
    finally:
        if previous_tenant:
            TenantManager.set_current_tenant(previous_tenant)

    returned_seeded_ids = {
        product.id for product in products if product.id in {product_a.id, product_b.id, product_fresh.id}
    }
    assert returned_seeded_ids == {product_a.id, product_b.id}


@pytest.mark.asyncio
async def test_auth_duplicate_checks_are_global_despite_active_tenant_context(db_session):
    tenant_a = _tenant_key()
    tenant_b = _tenant_key()
    db_session.add(_user(tenant_b, "taken-user", "taken@example.com"))
    await db_session.commit()
    db_session.info["tenant_key"] = tenant_a

    repo = AuthRepository()

    assert await repo.check_username_exists(db_session, "taken-user") is True
    assert await repo.check_email_exists(db_session, "taken@example.com") is True


@pytest.mark.asyncio
async def test_find_stale_working_agents_uses_audited_bypass(db_session):
    tenant_a = _tenant_key()
    tenant_b = _tenant_key()
    product_a = _product(tenant_a, "tenant-a")
    product_b = _product(tenant_b, "tenant-b")
    project_a = _project(tenant_a, product_a.id, "project-a")
    project_b = _project(tenant_b, product_b.id, "project-b")
    cutoff = datetime.now(UTC) - timedelta(minutes=10)
    stale_started = cutoff - timedelta(minutes=1)
    job_a = AgentJob(
        job_id=str(uuid4()),
        tenant_key=tenant_a,
        project_id=project_a.id,
        job_type="worker",
        mission="mission a",
        status="active",
        created_at=stale_started,
        job_metadata={},
    )
    job_b = AgentJob(
        job_id=str(uuid4()),
        tenant_key=tenant_b,
        project_id=project_b.id,
        job_type="worker",
        mission="mission b",
        status="active",
        created_at=stale_started,
        job_metadata={},
    )
    db_session.add_all(
        [
            product_a,
            product_b,
            project_a,
            project_b,
            job_a,
            job_b,
            AgentExecution(
                agent_id=str(uuid4()),
                tenant_key=tenant_a,
                job_id=job_a.job_id,
                agent_display_name="agent-a",
                agent_name="agent-a",
                status="working",
                started_at=stale_started,
            ),
            AgentExecution(
                agent_id=str(uuid4()),
                tenant_key=tenant_b,
                job_id=job_b.job_id,
                agent_display_name="agent-b",
                agent_name="agent-b",
                status="working",
                started_at=stale_started,
            ),
        ]
    )
    await db_session.commit()

    results = await AgentOperationsRepository().find_stale_working_agents(db_session, cutoff)

    executions = [execution for execution in results if execution.agent_name in {"agent-a", "agent-b"}]
    assert {execution.tenant_key for execution in executions} == {tenant_a, tenant_b}


@pytest.mark.asyncio
async def test_product_project_counts_filters_joined_projects_by_tenant(db_session):
    tenant_a = _tenant_key()
    tenant_b = _tenant_key()
    product_a = _product(tenant_a, "tenant-a")
    product_b = _product(tenant_b, "tenant-b")
    cross_tenant_project = _project(tenant_b, product_a.id, "cross-tenant", status="inactive")
    same_tenant_project = _project(tenant_a, product_a.id, "same-tenant")
    db_session.add_all([product_a, product_b, cross_tenant_project, same_tenant_project])
    await db_session.commit()

    db_session.info["tenant_key"] = tenant_a
    rows = await ProductStatisticsRepository(None).get_product_project_counts(db_session, tenant_a)

    counts = {row["product_id"]: row["project_count"] for row in rows}
    assert counts[product_a.id] == 1
