# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select, text

from giljo_mcp.database import tenant_session_context
from giljo_mcp.domain.project_status import ProjectStatus
from giljo_mcp.models import Product, Project, Task
from giljo_mcp.models.agent_identity import AgentExecution, AgentJob
from giljo_mcp.models.config import Configuration
from giljo_mcp.models.tasks import Message
from giljo_mcp.models.user_approval import UserApproval
from giljo_mcp.services.product_lifecycle_service import ProductLifecycleService
from giljo_mcp.tenant import TenantManager
from tests.fixtures.base_fixtures import TestData


pytestmark = pytest.mark.asyncio


async def _seed_expired_product(db_session, tenant_key: str, *, deleted_days_ago: int = 30) -> dict[str, str]:
    deleted_at = datetime.now(UTC) - timedelta(days=deleted_days_ago)

    product = Product(
        id=str(uuid.uuid4()),
        tenant_key=tenant_key,
        name=f"Expired Product {uuid.uuid4().hex[:8]}",
        description="Soft-deleted past the retention window",
        is_active=False,
        deleted_at=deleted_at,
    )
    db_session.add(product)
    await db_session.flush()

    project = Project(
        id=str(uuid.uuid4()),
        tenant_key=tenant_key,
        product_id=product.id,
        name="Project that ran an agent",
        description="desc",
        mission="mission",
        status=ProjectStatus.INACTIVE,
        series_number=1,
    )
    db_session.add(project)
    await db_session.flush()

    job = AgentJob(
        job_id=str(uuid.uuid4()),
        tenant_key=tenant_key,
        project_id=project.id,
        mission="implement the thing",
        job_type="implementer",
        status="completed",
    )
    db_session.add(job)
    execution = AgentExecution(
        id=str(uuid.uuid4()),
        agent_id=str(uuid.uuid4()),
        job_id=job.job_id,
        tenant_key=tenant_key,
        agent_display_name="implementer",
        status="complete",
        started_at=datetime.now(UTC),
    )
    db_session.add(execution)
    await db_session.flush()

    db_session.add(
        UserApproval(
            id=str(uuid.uuid4()),
            tenant_key=tenant_key,
            agent_execution_id=execution.id,
            job_id=job.job_id,
            project_id=project.id,
            reason="needs a decision",
            options=[{"id": "yes", "label": "Yes"}],
            status="pending",
        )
    )
    db_session.add(
        Configuration(
            id=str(uuid.uuid4()),
            tenant_key=tenant_key,
            project_id=project.id,
            key=f"be9615_{uuid.uuid4().hex[:8]}",
            value={"enabled": True},
        )
    )
    db_session.add(
        Message(
            id=str(uuid.uuid4()),
            tenant_key=tenant_key,
            project_id=project.id,
            content="a project-anchored message",
        )
    )
    db_session.add(
        Task(
            id=str(uuid.uuid4()),
            tenant_key=tenant_key,
            product_id=product.id,
            project_id=project.id,
            title="a task on the project",
            description="task desc",
            status="pending",
            priority="medium",
        )
    )
    await db_session.commit()

    return {
        "product_id": product.id,
        "project_id": project.id,
        "job_id": job.job_id,
        "execution_id": execution.id,
    }


async def _count(db_session, model, column, value) -> int:
    return (await db_session.execute(select(func.count()).select_from(model).where(column == value))).scalar_one()


async def test_purge_removes_another_tenants_expired_product(db_session, db_manager):
    tenant_key = TestData.generate_tenant_key()
    caller_tenant = TestData.generate_tenant_key()

    product = Product(
        id=str(uuid.uuid4()),
        tenant_key=tenant_key,
        name=f"Expired Product {uuid.uuid4().hex[:8]}",
        description="Soft-deleted past the retention window",
        is_active=False,
        deleted_at=datetime.now(UTC) - timedelta(days=30),
    )
    db_session.add(product)
    await db_session.flush()
    project = Project(
        id=str(uuid.uuid4()),
        tenant_key=tenant_key,
        product_id=product.id,
        name="Project that ran an agent",
        description="desc",
        mission="mission",
        status=ProjectStatus.INACTIVE,
        series_number=1,
    )
    db_session.add(project)
    await db_session.flush()
    job = AgentJob(
        job_id=str(uuid.uuid4()),
        tenant_key=tenant_key,
        project_id=project.id,
        mission="implement the thing",
        job_type="implementer",
        status="completed",
    )
    db_session.add(job)
    await db_session.commit()

    service = ProductLifecycleService(db_manager=db_manager, tenant_key=caller_tenant, test_session=db_session)
    result = await service.purge_expired_deleted_products(days_before_purge=10)

    assert product.id in result.purged_ids
    assert await _count(db_session, Product, Product.id, product.id) == 0
    assert await _count(db_session, Project, Project.id, project.id) == 0
    assert await _count(db_session, AgentJob, AgentJob.job_id, job.job_id) == 0


async def test_purge_removes_a_product_whose_project_ran_an_agent(db_session, db_manager):
    tenant_key = TestData.generate_tenant_key()
    ids = await _seed_expired_product(db_session, tenant_key)

    service = ProductLifecycleService(db_manager=db_manager, tenant_key=tenant_key, test_session=db_session)
    result = await service.purge_expired_deleted_products(days_before_purge=10)

    assert ids["product_id"] in result.purged_ids

    assert await _count(db_session, Product, Product.id, ids["product_id"]) == 0
    assert await _count(db_session, Project, Project.id, ids["project_id"]) == 0
    assert await _count(db_session, AgentJob, AgentJob.project_id, ids["project_id"]) == 0
    assert await _count(db_session, AgentExecution, AgentExecution.job_id, ids["job_id"]) == 0
    assert await _count(db_session, UserApproval, UserApproval.project_id, ids["project_id"]) == 0
    assert await _count(db_session, Configuration, Configuration.project_id, ids["project_id"]) == 0
    assert await _count(db_session, Message, Message.project_id, ids["project_id"]) == 0
    assert await _count(db_session, Task, Task.project_id, ids["project_id"]) == 0


async def test_purge_leaves_another_tenants_expired_product_alone(db_session, db_manager):
    mine = TestData.generate_tenant_key()
    theirs = TestData.generate_tenant_key()
    my_ids = await _seed_expired_product(db_session, mine)

    survivor = Product(
        id=str(uuid.uuid4()),
        tenant_key=theirs,
        name=f"Live Product {uuid.uuid4().hex[:8]}",
        description="never deleted",
        is_active=True,
    )
    db_session.add(survivor)
    await db_session.flush()
    survivor_project = Project(
        id=str(uuid.uuid4()),
        tenant_key=theirs,
        product_id=survivor.id,
        name="Untouched project",
        description="desc",
        mission="mission",
        status=ProjectStatus.INACTIVE,
        series_number=1,
    )
    db_session.add(survivor_project)
    survivor_job = AgentJob(
        job_id=str(uuid.uuid4()),
        tenant_key=theirs,
        project_id=survivor_project.id,
        mission="keep me",
        job_type="implementer",
        status="active",
    )
    db_session.add(survivor_job)
    await db_session.commit()

    service = ProductLifecycleService(db_manager=db_manager, tenant_key=mine, test_session=db_session)
    await service.purge_expired_deleted_products(days_before_purge=10)

    assert await _count(db_session, Product, Product.id, my_ids["product_id"]) == 0
    assert await _count(db_session, Product, Product.id, survivor.id) == 1
    assert await _count(db_session, Project, Project.id, survivor_project.id) == 1
    assert await _count(db_session, AgentJob, AgentJob.job_id, survivor_job.job_id) == 1


async def test_purge_product_removes_the_same_dependants(db_session, db_manager):
    tenant_key = TestData.generate_tenant_key()
    ids = await _seed_expired_product(db_session, tenant_key, deleted_days_ago=1)

    service = ProductLifecycleService(db_manager=db_manager, tenant_key=tenant_key, test_session=db_session)
    await service.purge_product(ids["product_id"])

    assert await _count(db_session, Product, Product.id, ids["product_id"]) == 0
    assert await _count(db_session, AgentJob, AgentJob.project_id, ids["project_id"]) == 0
    assert await _count(db_session, UserApproval, UserApproval.project_id, ids["project_id"]) == 0


async def test_every_blocking_fk_into_projects_is_swept(db_session):
    swept = {
        ("agent_jobs", "project_id"),
        ("configurations", "project_id"),
        ("messages", "project_id"),
        ("tasks", "project_id"),
        ("tasks", "converted_to_project_id"),
        ("user_approvals", "project_id"),
    }
    rows = (
        await db_session.execute(
            text(
                """
                SELECT c.conrelid::regclass::text AS child, a.attname AS col
                FROM pg_constraint c
                JOIN unnest(c.conkey) WITH ORDINALITY k(attnum, ord) ON true
                JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = k.attnum
                WHERE c.contype = 'f'
                  AND c.confrelid::regclass::text IN ('projects', 'products')
                  AND c.confdeltype IN ('a', 'r')
                """
            )
        )
    ).all()
    assert {(r.child, r.col) for r in rows} == swept


async def test_one_run_purges_several_tenants_and_restores_the_caller_context(db_session, db_manager):
    caller = TestData.generate_tenant_key()
    first = await _seed_expired_product(db_session, TestData.generate_tenant_key())
    second = await _seed_expired_product(db_session, TestData.generate_tenant_key())
    mine = await _seed_expired_product(db_session, caller)

    service = ProductLifecycleService(db_manager=db_manager, tenant_key=caller, test_session=db_session)
    with tenant_session_context(db_session, caller):
        result = await service.purge_expired_deleted_products(days_before_purge=10)

        assert db_session.info["tenant_key"] == caller
        assert TenantManager.get_current_tenant() == caller

    for ids in (first, second, mine):
        assert ids["product_id"] in result.purged_ids
        assert await _count(db_session, Product, Product.id, ids["product_id"]) == 0
        assert await _count(db_session, AgentJob, AgentJob.project_id, ids["project_id"]) == 0
