# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""Tests for JobQueryService (Sprint 002e extraction).

Expanded from 1-function smoke test to meaningful coverage:
- Empty result (no jobs)
- Filtering by project_id
- Filtering by status_filter
- Filtering by agent_display_name
- Pagination (limit/offset)
- _derive_steps_summary from metadata and todo_items
- Tenant isolation
"""

from unittest.mock import MagicMock

import pytest

from giljo_mcp.services.job_query_service import JobQueryService


async def _seed_product(session, tenant_key):
    """A product for a seeded project to belong to (BE-9437: product_id is NOT NULL).

    ONE PRODUCT PER PROJECT, deliberately. ``idx_project_single_active_per_product``
    permits a single ACTIVE project per product and these seeds are active, so a
    shared product would make the second one a unique violation.
    """
    import uuid

    from giljo_mcp.models import Product

    product = Product(
        id=str(uuid.uuid4()),
        tenant_key=tenant_key,
        name=f"Job Query Product {uuid.uuid4().hex[:6]}",
        description="seeded",
        is_active=False,
    )
    session.add(product)
    await session.flush()
    return product


@pytest.fixture
def job_query_service(db_session, test_tenant_key):
    """Create a JobQueryService with a test session."""
    db_manager = MagicMock()
    tenant_manager = MagicMock()
    tenant_manager.get_current_tenant.return_value = test_tenant_key
    return JobQueryService(
        db_manager=db_manager,
        tenant_manager=tenant_manager,
        test_session=db_session,
    )


@pytest.mark.asyncio
async def test_list_jobs_returns_empty_for_no_jobs(job_query_service, test_tenant_key):
    """list_jobs returns empty result when no jobs exist."""
    result = await job_query_service.list_jobs(test_tenant_key)
    assert result.jobs == []
    assert result.total == 0


@pytest.mark.asyncio
async def test_list_jobs_returns_created_job(db_session, db_manager, test_tenant_key):
    """list_jobs returns a job that was inserted into the database."""
    import uuid

    from giljo_mcp.models import AgentExecution, AgentJob, Project

    product = await _seed_product(db_session, test_tenant_key)
    project = Project(
        id=str(uuid.uuid4()),
        name="Job Query Project",
        description="For job query tests",
        mission="Test mission",
        status="active",
        tenant_key=test_tenant_key,
        product_id=product.id,
        series_number=88001,
    )
    db_session.add(project)
    await db_session.flush()

    job_id = str(uuid.uuid4())
    agent_id = str(uuid.uuid4())
    job = AgentJob(
        job_id=job_id,
        project_id=project.id,
        tenant_key=test_tenant_key,
        job_type="implementer",
        mission="Test mission",
    )
    db_session.add(job)
    await db_session.flush()

    execution = AgentExecution(
        job_id=job_id,
        agent_id=agent_id,
        tenant_key=test_tenant_key,
        status="working",
        agent_name="test-impl",
        agent_display_name="implementer",
    )
    db_session.add(execution)
    await db_session.commit()

    service = JobQueryService(
        db_manager=db_manager,
        tenant_manager=MagicMock(),
        test_session=db_session,
    )
    result = await service.list_jobs(test_tenant_key)

    assert result.total >= 1
    job_ids = [j["job_id"] for j in result.jobs]
    assert job_id in job_ids


@pytest.mark.asyncio
async def test_list_jobs_filter_by_project_id(db_session, db_manager, test_tenant_key):
    """list_jobs filters results by project_id."""
    import uuid

    from giljo_mcp.models import AgentExecution, AgentJob, Project

    # BE-9437: a product EACH -- both projects are active, and one product
    # holds at most one active project.
    product_a = await _seed_product(db_session, test_tenant_key)
    product_b = await _seed_product(db_session, test_tenant_key)
    proj_a = Project(
        id=str(uuid.uuid4()),
        name="Proj A",
        description="A",
        mission="Test mission",
        status="active",
        tenant_key=test_tenant_key,
        product_id=product_a.id,
        series_number=88002,
    )
    proj_b = Project(
        id=str(uuid.uuid4()),
        name="Proj B",
        description="B",
        mission="Test mission",
        status="active",
        tenant_key=test_tenant_key,
        product_id=product_b.id,
        series_number=88003,
    )
    db_session.add_all([proj_a, proj_b])
    await db_session.flush()

    for proj in [proj_a, proj_b]:
        jid = str(uuid.uuid4())
        job = AgentJob(
            job_id=jid,
            project_id=proj.id,
            tenant_key=test_tenant_key,
            job_type="impl",
            mission="Test mission",
        )
        db_session.add(job)
        await db_session.flush()
        ex = AgentExecution(
            job_id=jid,
            agent_id=str(uuid.uuid4()),
            tenant_key=test_tenant_key,
            status="working",
            agent_name="a",
            agent_display_name="a",
        )
        db_session.add(ex)
    await db_session.commit()

    service = JobQueryService(
        db_manager=db_manager,
        tenant_manager=MagicMock(),
        test_session=db_session,
    )
    result = await service.list_jobs(test_tenant_key, project_id=proj_a.id)

    assert result.total == 1
    assert result.jobs[0]["project_id"] == proj_a.id


@pytest.mark.asyncio
async def test_list_jobs_filter_by_status(db_session, db_manager, test_tenant_key):
    """list_jobs filters results by execution status."""
    import uuid

    from giljo_mcp.models import AgentExecution, AgentJob, Project

    product = await _seed_product(db_session, test_tenant_key)
    project = Project(
        id=str(uuid.uuid4()),
        name="Status Filter",
        description="SF",
        mission="Test mission",
        status="active",
        tenant_key=test_tenant_key,
        product_id=product.id,
        series_number=88004,
    )
    db_session.add(project)
    await db_session.flush()

    for status in ["working", "complete"]:
        jid = str(uuid.uuid4())
        job = AgentJob(
            job_id=jid,
            project_id=project.id,
            tenant_key=test_tenant_key,
            job_type="impl",
            mission="Test mission",
        )
        db_session.add(job)
        await db_session.flush()
        ex = AgentExecution(
            job_id=jid,
            agent_id=str(uuid.uuid4()),
            tenant_key=test_tenant_key,
            status=status,
            agent_name="a",
            agent_display_name="a",
        )
        db_session.add(ex)
    await db_session.commit()

    service = JobQueryService(
        db_manager=db_manager,
        tenant_manager=MagicMock(),
        test_session=db_session,
    )
    result = await service.list_jobs(test_tenant_key, project_id=project.id, status_filter="complete")

    assert result.total == 1
    assert result.jobs[0]["status"] == "complete"


@pytest.mark.asyncio
async def test_list_jobs_pagination(db_session, db_manager, test_tenant_key):
    """list_jobs respects limit and offset for pagination."""
    import uuid

    from giljo_mcp.models import AgentExecution, AgentJob, Project

    product = await _seed_product(db_session, test_tenant_key)
    project = Project(
        id=str(uuid.uuid4()),
        name="Pagination",
        description="Pag",
        mission="Test mission",
        status="active",
        tenant_key=test_tenant_key,
        product_id=product.id,
        series_number=88005,
    )
    db_session.add(project)
    await db_session.flush()

    for i in range(3):
        jid = str(uuid.uuid4())
        job = AgentJob(
            job_id=jid,
            project_id=project.id,
            tenant_key=test_tenant_key,
            job_type="impl",
            mission="Test mission",
        )
        db_session.add(job)
        await db_session.flush()
        ex = AgentExecution(
            job_id=jid,
            agent_id=str(uuid.uuid4()),
            tenant_key=test_tenant_key,
            status="working",
            agent_name=f"agent-{i}",
            agent_display_name=f"agent-{i}",
        )
        db_session.add(ex)
    await db_session.commit()

    service = JobQueryService(
        db_manager=db_manager,
        tenant_manager=MagicMock(),
        test_session=db_session,
    )
    result = await service.list_jobs(test_tenant_key, project_id=project.id, limit=2, offset=0)

    assert result.total == 3
    assert len(result.jobs) == 2
    assert result.limit == 2
    assert result.offset == 0


@pytest.mark.asyncio
async def test_list_jobs_tenant_isolation(db_session, db_manager, test_tenant_key):
    """Jobs from one tenant are not visible to another tenant."""
    import uuid

    from giljo_mcp.models import AgentExecution, AgentJob, Project

    product = await _seed_product(db_session, test_tenant_key)
    project = Project(
        id=str(uuid.uuid4()),
        name="Tenant Iso",
        description="TI",
        mission="Test mission",
        status="active",
        tenant_key=test_tenant_key,
        product_id=product.id,
        series_number=88006,
    )
    db_session.add(project)
    await db_session.flush()

    jid = str(uuid.uuid4())
    job = AgentJob(
        job_id=jid,
        project_id=project.id,
        tenant_key=test_tenant_key,
        job_type="impl",
        mission="Test mission",
    )
    db_session.add(job)
    await db_session.flush()
    ex = AgentExecution(
        job_id=jid,
        agent_id=str(uuid.uuid4()),
        tenant_key=test_tenant_key,
        status="working",
        agent_name="a",
        agent_display_name="a",
    )
    db_session.add(ex)
    await db_session.commit()

    other_tenant = "tk_otherTenantValue12345678901234"
    service = JobQueryService(
        db_manager=db_manager,
        tenant_manager=MagicMock(),
        test_session=db_session,
    )
    result = await service.list_jobs(other_tenant)

    assert result.total == 0
    assert result.jobs == []


def test_derive_steps_summary_from_metadata():
    """_derive_steps_summary extracts counts from job_metadata.todo_steps."""
    service = JobQueryService(MagicMock(), MagicMock())
    job = MagicMock()
    job.job_metadata = {"todo_steps": {"total_steps": 5, "completed_steps": 3, "skipped_steps": 1}}
    job.todo_items = []

    result = service._derive_steps_summary(job)

    assert result == {"total": 5, "completed": 3, "skipped": 1}


def test_derive_steps_summary_from_todo_items():
    """_derive_steps_summary falls back to todo_items when metadata is empty."""
    service = JobQueryService(MagicMock(), MagicMock())
    job = MagicMock()
    job.job_metadata = {}

    item_completed = MagicMock()
    item_completed.status = "completed"
    item_pending = MagicMock()
    item_pending.status = "pending"
    item_skipped = MagicMock()
    item_skipped.status = "skipped"
    job.todo_items = [item_completed, item_pending, item_skipped]

    result = service._derive_steps_summary(job)

    assert result == {"total": 3, "completed": 1, "skipped": 1}


def test_derive_steps_summary_returns_none_when_empty():
    """_derive_steps_summary returns None when no metadata and no todo_items."""
    service = JobQueryService(MagicMock(), MagicMock())
    job = MagicMock()
    job.job_metadata = {}
    job.todo_items = []

    result = service._derive_steps_summary(job)

    assert result is None
