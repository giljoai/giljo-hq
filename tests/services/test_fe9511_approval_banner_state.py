# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""Tests for FE-9511's server-derived approval banner state.

UserApprovalService.list_pending now returns fully-built UserApprovalRead
rows carrying ``banner_state`` (one of VALID_APPROVAL_BANNER_STATES) and
``taxonomy_alias``, computed from the approval's own project + requesting
execution -- approval-scoped, not a
product-wide scan.
"""

import random
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
import pytest_asyncio

from giljo_mcp.models.agent_identity import AgentExecution, AgentJob
from giljo_mcp.models.products import Product
from giljo_mcp.models.projects import Project
from giljo_mcp.schemas.user_approval import VALID_APPROVAL_BANNER_STATES
from giljo_mcp.services.user_approval_service import UserApprovalService
from giljo_mcp.tenant import TenantManager


@pytest_asyncio.fixture
async def banner_seed(db_session, test_tenant_key):
    """Seed a product + project + orchestrator job/execution, override-able per test."""

    async def _seed(*, staging_status=None, implementation_launched_at=None, execution_status="working"):
        product = Product(
            id=str(uuid4()),
            name=f"Banner Product {uuid4().hex[:6]}",
            description="Product for FE-9511 banner-state tests",
            tenant_key=test_tenant_key,
            is_active=True,
        )
        db_session.add(product)

        project = Project(
            id=str(uuid4()),
            tenant_key=test_tenant_key,
            product_id=product.id,
            name="Banner Test Project",
            description="Project for FE-9511 banner-state tests",
            mission="Test mission",
            status="active",
            series_number=random.randint(1, 9000),
            staging_status=staging_status,
            implementation_launched_at=implementation_launched_at,
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
            status=execution_status,
            started_at=datetime.now(UTC),
        )
        db_session.add(execution)
        await db_session.commit()
        await db_session.refresh(execution)
        await db_session.refresh(project)
        return {"product": product, "project": project, "job": job, "execution": execution}

    return _seed


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


async def _create_pending(approval_service, tenant_key, seed):
    return await approval_service.create_pending(
        tenant_key=tenant_key,
        job_id=seed["job"].job_id,
        project_id=seed["project"].id,
        reason="Which option?",
        options=[{"id": "a", "label": "Option A"}],
        context=None,
    )


@pytest.mark.asyncio
async def test_default_state_is_decision_needed(approval_service, banner_seed, test_tenant_key):
    seed = await banner_seed()
    await _create_pending(approval_service, test_tenant_key, seed)

    reads, total = await approval_service.list_pending(tenant_key=test_tenant_key)

    assert total == 1
    assert reads[0].banner_state == "decision_needed"


@pytest.mark.asyncio
async def test_staging_paused_project_reports_waiting_at_staging(approval_service, banner_seed, test_tenant_key):
    seed = await banner_seed(staging_status="staging_complete", implementation_launched_at=None)
    await _create_pending(approval_service, test_tenant_key, seed)

    reads, _ = await approval_service.list_pending(tenant_key=test_tenant_key)

    assert reads[0].banner_state == "waiting_at_staging"


@pytest.mark.asyncio
async def test_launched_project_at_staging_complete_is_not_waiting_at_staging(
    approval_service, banner_seed, test_tenant_key
):
    # implementation_launched_at set -> Implement WAS pressed, so this must not
    # read as "waiting at staging" even though staging_status still says complete.
    seed = await banner_seed(staging_status="staging_complete", implementation_launched_at=datetime.now(UTC))
    await _create_pending(approval_service, test_tenant_key, seed)

    reads, _ = await approval_service.list_pending(tenant_key=test_tenant_key)

    assert reads[0].banner_state == "decision_needed"


@pytest.mark.asyncio
async def test_blocked_execution_reports_blocked(approval_service, banner_seed, test_tenant_key, db_session):
    seed = await banner_seed(execution_status="working")
    await _create_pending(approval_service, test_tenant_key, seed)

    # create_pending parks the execution at "awaiting_user"; simulate the
    # separate, later transition to "blocked" (e.g. a health monitor) that can
    # happen while the approval is still pending.
    seed["execution"].status = "blocked"
    await db_session.commit()

    reads, _ = await approval_service.list_pending(tenant_key=test_tenant_key)

    assert reads[0].banner_state == "blocked"


@pytest.mark.asyncio
async def test_banner_state_is_always_a_member_of_the_closed_set(approval_service, banner_seed, test_tenant_key):
    seed = await banner_seed()
    await _create_pending(approval_service, test_tenant_key, seed)

    reads, _ = await approval_service.list_pending(tenant_key=test_tenant_key)

    assert reads[0].banner_state in VALID_APPROVAL_BANNER_STATES


@pytest.mark.asyncio
async def test_taxonomy_alias_is_carried_on_the_payload_without_a_store_lookup(
    approval_service, banner_seed, test_tenant_key
):
    """FE-9508's trap: the pill must not depend on the project already being
    loaded client-side -- the payload itself must carry taxonomy_alias."""
    seed = await banner_seed()
    await _create_pending(approval_service, test_tenant_key, seed)

    reads, _ = await approval_service.list_pending(tenant_key=test_tenant_key)

    assert reads[0].taxonomy_alias == seed["project"].taxonomy_alias
    assert reads[0].taxonomy_alias  # non-empty
