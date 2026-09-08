# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""Tests for UserApprovalRepository (BE-5029 Phase A).

Cross-tenant queries against a real DB must return empty -- this is a
security-critical guarantee, not just a unit-test smoke check.
"""

import random
from datetime import UTC, datetime
from uuid import uuid4

import pytest
import pytest_asyncio

from giljo_mcp.models.agent_identity import AgentExecution, AgentJob
from giljo_mcp.models.products import Product
from giljo_mcp.models.projects import Project
from giljo_mcp.repositories.user_approval_repository import UserApprovalRepository
from giljo_mcp.tenant import TenantManager


@pytest_asyncio.fixture
async def repo(db_manager):
    return UserApprovalRepository(db_manager)


async def _seed(db_session, tenant_key):
    product = Product(
        id=str(uuid4()),
        name=f"P {uuid4().hex[:6]}",
        description="x",
        tenant_key=tenant_key,
        is_active=True,
    )
    db_session.add(product)
    project = Project(
        id=str(uuid4()),
        tenant_key=tenant_key,
        product_id=product.id,
        name="P",
        description="x",
        mission="x",
        status="active",
        series_number=random.randint(1, 9000),
    )
    db_session.add(project)
    await db_session.flush()
    job = AgentJob(
        job_id=str(uuid4()),
        tenant_key=tenant_key,
        project_id=project.id,
        job_type="implementer",
        mission="x",
        status="active",
        created_at=datetime.now(UTC),
    )
    db_session.add(job)
    await db_session.flush()
    execution = AgentExecution(
        id=str(uuid4()),
        agent_id=str(uuid4()),
        job_id=job.job_id,
        tenant_key=tenant_key,
        agent_display_name="implementer",
        status="working",
    )
    db_session.add(execution)
    await db_session.commit()
    return project, job, execution


@pytest.mark.asyncio
async def test_create_and_get_by_id(repo, db_session, test_tenant_key):
    project, job, execution = await _seed(db_session, test_tenant_key)

    approval = await repo.create(
        db_session,
        tenant_key=test_tenant_key,
        agent_execution_id=execution.id,
        job_id=job.job_id,
        project_id=project.id,
        reason="r",
        options=[{"id": "a", "label": "A"}],
        context=None,
    )
    await db_session.commit()

    fetched = await repo.get_by_id(db_session, tenant_key=test_tenant_key, approval_id=approval.id)
    assert fetched is not None
    assert fetched.id == approval.id


@pytest.mark.asyncio
async def test_cross_tenant_get_returns_none(repo, db_session, test_tenant_key):
    project, job, execution = await _seed(db_session, test_tenant_key)

    approval = await repo.create(
        db_session,
        tenant_key=test_tenant_key,
        agent_execution_id=execution.id,
        job_id=job.job_id,
        project_id=project.id,
        reason="r",
        options=[{"id": "a", "label": "A"}],
        context=None,
    )
    await db_session.commit()

    other_tenant = TenantManager.generate_tenant_key()
    fetched = await repo.get_by_id(db_session, tenant_key=other_tenant, approval_id=approval.id)
    assert fetched is None


@pytest.mark.asyncio
async def test_get_pending_for_agent(repo, db_session, test_tenant_key):
    project, job, execution = await _seed(db_session, test_tenant_key)
    approval = await repo.create(
        db_session,
        tenant_key=test_tenant_key,
        agent_execution_id=execution.id,
        job_id=job.job_id,
        project_id=project.id,
        reason="r",
        options=[{"id": "a", "label": "A"}],
        context=None,
    )
    await db_session.commit()

    pending = await repo.get_pending_for_agent(
        db_session,
        tenant_key=test_tenant_key,
        agent_execution_id=execution.id,
    )
    assert pending is not None
    assert pending.id == approval.id


@pytest.mark.asyncio
async def test_cross_tenant_get_pending_for_agent_returns_none(repo, db_session, test_tenant_key):
    """BE-5083: get_pending_for_agent must be tenant-scoped -- a foreign tenant
    sees no pending approval even with the correct agent_execution_id."""
    project, job, execution = await _seed(db_session, test_tenant_key)
    await repo.create(
        db_session,
        tenant_key=test_tenant_key,
        agent_execution_id=execution.id,
        job_id=job.job_id,
        project_id=project.id,
        reason="r",
        options=[{"id": "a", "label": "A"}],
        context=None,
    )
    await db_session.commit()

    other_tenant = TenantManager.generate_tenant_key()
    pending = await repo.get_pending_for_agent(
        db_session,
        tenant_key=other_tenant,
        agent_execution_id=execution.id,
    )
    assert pending is None


@pytest.mark.asyncio
async def test_mark_decided(repo, db_session, test_tenant_key):
    project, job, execution = await _seed(db_session, test_tenant_key)
    approval = await repo.create(
        db_session,
        tenant_key=test_tenant_key,
        agent_execution_id=execution.id,
        job_id=job.job_id,
        project_id=project.id,
        reason="r",
        options=[{"id": "a", "label": "A"}],
        context=None,
    )
    await db_session.commit()

    decided = await repo.mark_decided(
        db_session,
        tenant_key=test_tenant_key,
        approval_id=approval.id,
        decided_option_id="a",
        decided_by_user_id=None,
        decided_via="mcp",
    )
    assert decided is not None
    assert decided.status == "decided"
    assert decided.decided_option_id == "a"
    assert decided.decided_via == "mcp"
    assert decided.decided_at is not None


@pytest.mark.asyncio
async def test_mark_decided_idempotent_on_already_decided(repo, db_session, test_tenant_key):
    project, job, execution = await _seed(db_session, test_tenant_key)
    approval = await repo.create(
        db_session,
        tenant_key=test_tenant_key,
        agent_execution_id=execution.id,
        job_id=job.job_id,
        project_id=project.id,
        reason="r",
        options=[{"id": "a", "label": "A"}],
        context=None,
    )
    await db_session.commit()
    await repo.mark_decided(
        db_session,
        tenant_key=test_tenant_key,
        approval_id=approval.id,
        decided_option_id="a",
        decided_by_user_id=None,
        decided_via="mcp",
    )
    again = await repo.mark_decided(
        db_session,
        tenant_key=test_tenant_key,
        approval_id=approval.id,
        decided_option_id="a",
        decided_by_user_id=None,
        decided_via="mcp",
    )
    assert again is None
