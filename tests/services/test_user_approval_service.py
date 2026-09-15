# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import logging
import random
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import select

from giljo_mcp.database import tenant_session_context
from giljo_mcp.exceptions import ResourceNotFoundError, ValidationError
from giljo_mcp.models.agent_identity import AgentExecution, AgentJob
from giljo_mcp.models.products import Product
from giljo_mcp.models.projects import Project
from giljo_mcp.models.user_approval import UserApproval
from giljo_mcp.services.user_approval_service import UserApprovalService
from giljo_mcp.tenant import TenantManager


@pytest_asyncio.fixture
async def approval_seed(db_session, test_tenant_key):
    product = Product(
        id=str(uuid4()),
        name=f"Approval Product {uuid4().hex[:6]}",
        description="Product for approval tests",
        tenant_key=test_tenant_key,
        is_active=True,
    )
    db_session.add(product)

    project = Project(
        id=str(uuid4()),
        tenant_key=test_tenant_key,
        product_id=product.id,
        name="Approval Test Project",
        description="Project for approval tests",
        mission="Test mission",
        status="active",
        series_number=random.randint(1, 9000),
    )
    db_session.add(project)
    await db_session.flush()

    job = AgentJob(
        job_id=str(uuid4()),
        tenant_key=test_tenant_key,
        project_id=project.id,
        job_type="orchestrator",
        mission="orchestrator mission",
        status="active",
        created_at=datetime.now(UTC),
    )
    db_session.add(job)
    await db_session.flush()

    execution = AgentExecution(
        id=str(uuid4()),
        agent_id=str(uuid4()),
        job_id=job.job_id,
        tenant_key=test_tenant_key,
        agent_display_name="orchestrator",
        status="working",
        started_at=datetime.now(UTC),
    )
    db_session.add(execution)
    await db_session.commit()
    await db_session.refresh(execution)
    return {"product": product, "project": project, "job": job, "execution": execution}


@pytest_asyncio.fixture
async def approval_service(db_manager, db_session):
    ws = MagicMock()
    ws.broadcast_to_tenant = AsyncMock()
    return UserApprovalService(
        db_manager=db_manager,
        tenant_manager=TenantManager(),
        websocket_manager=ws,
        test_session=db_session,
    )


@pytest.mark.asyncio
async def test_create_pending_inserts_row_and_flips_status(
    approval_service, approval_seed, test_tenant_key, db_session
):
    job = approval_seed["job"]
    project = approval_seed["project"]

    approval = await approval_service.create_pending(
        tenant_key=test_tenant_key,
        job_id=job.job_id,
        project_id=project.id,
        reason="Need user decision on closeout",
        options=[
            {"id": "approve", "label": "Approve and close"},
            {"id": "rework", "label": "Send back for rework"},
        ],
        context={"deferred_findings": ["finding-1"]},
    )

    assert approval.id is not None
    assert approval.status == "pending"
    assert approval.tenant_key == test_tenant_key

    result = await db_session.execute(select(AgentExecution).where(AgentExecution.id == approval_seed["execution"].id))
    execution = result.scalar_one()
    assert execution.status == "awaiting_user"

    approval_service._websocket_manager.broadcast_to_tenant.assert_awaited()


@pytest.mark.asyncio
async def test_create_pending_rejects_duplicate(approval_service, approval_seed, test_tenant_key):
    job = approval_seed["job"]
    project = approval_seed["project"]

    await approval_service.create_pending(
        tenant_key=test_tenant_key,
        job_id=job.job_id,
        project_id=project.id,
        reason="First request",
        options=[{"id": "ok", "label": "OK"}],
        context=None,
    )

    with pytest.raises(ValidationError, match="already has a pending approval"):
        await approval_service.create_pending(
            tenant_key=test_tenant_key,
            job_id=job.job_id,
            project_id=project.id,
            reason="Second request",
            options=[{"id": "ok", "label": "OK"}],
            context=None,
        )


@pytest.mark.asyncio
async def test_create_pending_rejects_empty_options(approval_service, approval_seed, test_tenant_key):
    job = approval_seed["job"]
    project = approval_seed["project"]

    with pytest.raises(ValueError, match="options must be a non-empty list"):
        await approval_service.create_pending(
            tenant_key=test_tenant_key,
            job_id=job.job_id,
            project_id=project.id,
            reason="No options",
            options=[],
            context=None,
        )


@pytest.mark.asyncio
async def test_create_pending_unknown_job_id_raises(approval_service, test_tenant_key):
    with pytest.raises(ResourceNotFoundError):
        await approval_service.create_pending(
            tenant_key=test_tenant_key,
            job_id=str(uuid4()),
            project_id=str(uuid4()),
            reason="Bogus job",
            options=[{"id": "ok", "label": "OK"}],
            context=None,
        )


@pytest.mark.asyncio
async def test_create_pending_project_id_mismatch_raises(approval_service, approval_seed, test_tenant_key):
    job = approval_seed["job"]

    with pytest.raises(ValidationError, match="does not belong to project"):
        await approval_service.create_pending(
            tenant_key=test_tenant_key,
            job_id=job.job_id,
            project_id=str(uuid4()),
            reason="Wrong project",
            options=[{"id": "ok", "label": "OK"}],
            context=None,
        )


@pytest.mark.asyncio
async def test_create_pending_tenant_isolation(approval_service, approval_seed, test_tenant_key, db_session):
    other_tenant = TenantManager.generate_tenant_key()

    with pytest.raises(ResourceNotFoundError):
        await approval_service.create_pending(
            tenant_key=other_tenant,
            job_id=approval_seed["job"].job_id,
            project_id=approval_seed["project"].id,
            reason="Cross-tenant attempt",
            options=[{"id": "ok", "label": "OK"}],
            context=None,
        )

    with tenant_session_context(db_session, other_tenant):
        result = await db_session.execute(select(UserApproval).where(UserApproval.tenant_key == other_tenant))
    assert result.scalars().all() == []




class _RefusingCommThreadService:

    def __init__(self, response):
        self._response = response
        self.calls = 0

    async def resolve_or_create_bound_thread(self, *, project_id, tenant_key):
        return {"thread_id": "t-approval-1"}

    async def post_to_thread(self, **kwargs):
        self.calls += 1
        return self._response


def _decision_fixture():
    execution = SimpleNamespace(agent_id="Relay")
    decided = SimpleNamespace(
        id="apr-1",
        job_id="job-1",
        project_id="prj-1",
        reason="Ship it?",
        options=[{"id": "yes", "label": "Yes"}],
    )
    return execution, decided


@pytest.mark.asyncio
async def test_a_declined_hub_notice_is_logged_not_swallowed(caplog):
    service = UserApprovalService(db_manager=None, tenant_manager=TenantManager())
    service._comm_thread_service = _RefusingCommThreadService(
        {"success": False, "error": "TARGET_IS_A_DISPLAY_NAME", "requested": "Relay"}
    )
    execution, decided = _decision_fixture()

    with caplog.at_level(logging.WARNING, logger="giljo_mcp.services.user_approval_service"):
        await service._notify_orchestrator_of_decision(
            tenant_key="tk-1", execution=execution, decided=decided, option_id="yes"
        )

    warnings = [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING]
    assert warnings, "a declined approval notice left no trace at all"
    assert any("TARGET_IS_A_DISPLAY_NAME" in m for m in warnings), warnings
    assert any("apr-1" in m for m in warnings), "the operator cannot find the approval this belongs to"


@pytest.mark.asyncio
async def test_an_accepted_hub_notice_stays_quiet(caplog):
    service = UserApprovalService(db_manager=None, tenant_manager=TenantManager())
    service._comm_thread_service = _RefusingCommThreadService({"message_id": "m-1", "baton_passed": False})
    execution, decided = _decision_fixture()

    with caplog.at_level(logging.WARNING, logger="giljo_mcp.services.user_approval_service"):
        await service._notify_orchestrator_of_decision(
            tenant_key="tk-1", execution=execution, decided=decided, option_id="yes"
        )

    assert [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING] == []
