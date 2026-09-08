# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""Service-layer tests for ``UserApprovalService.mark_decided`` (BE-5059 Phase B).

Covers the atomicity contract: status flip + decided_* fields + agent resume
all happen in one transaction, plus the rejection paths (already-decided,
invalid option_id, cross-tenant).
"""

from __future__ import annotations

import random
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import select

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
        description="x",
        tenant_key=test_tenant_key,
        is_active=True,
    )
    db_session.add(product)

    project = Project(
        id=str(uuid4()),
        tenant_key=test_tenant_key,
        product_id=product.id,
        name="Decide Test Project",
        description="x",
        mission="x",
        status="active",
        series_number=random.randint(1, 9000),
    )
    db_session.add(project)
    await db_session.flush()

    # BE-9054 (a): request_approval is orchestrator-only, so the seed job must be
    # an orchestrator for create_pending to accept it.
    job = AgentJob(
        job_id=str(uuid4()),
        tenant_key=test_tenant_key,
        project_id=project.id,
        job_type="orchestrator",
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


async def _create_pending_approval(service, seed, tenant_key):
    return await service.create_pending(
        tenant_key=tenant_key,
        job_id=seed["job"].job_id,
        project_id=seed["project"].id,
        reason="please decide",
        options=[
            {"id": "approve", "label": "Approve"},
            {"id": "rework", "label": "Send back for rework"},
        ],
        context={"deferred_findings": ["x"]},
    )


@pytest.mark.asyncio
async def test_mark_decided_atomic_flip_resume_and_fields(
    approval_service, approval_seed, test_tenant_key, test_user, db_session
):
    """Decide flips status, sets decided_* fields, and resumes the awaiting agent.

    Single transaction: pending->decided + awaiting_user->working + decided_at/by
    persist together; WebSocket broadcast fires on the existing channel.
    """
    pending = await _create_pending_approval(approval_service, approval_seed, test_tenant_key)
    assert pending.status == "pending"

    user_id = str(test_user.id)
    decided = await approval_service.mark_decided(
        tenant_key=test_tenant_key,
        approval_id=pending.id,
        option_id="approve",
        user_id=user_id,
        decided_via="ui",
    )

    assert decided.status == "decided"
    assert decided.decided_option_id == "approve"
    assert decided.decided_by_user_id == user_id
    assert decided.decided_via == "ui"
    assert decided.decided_at is not None

    row = (await db_session.execute(select(UserApproval).where(UserApproval.id == pending.id))).scalar_one()
    assert row.status == "decided"
    assert row.decided_option_id == "approve"

    execution = (
        await db_session.execute(select(AgentExecution).where(AgentExecution.id == approval_seed["execution"].id))
    ).scalar_one()
    assert execution.status == "working", "awaiting_user must flip back to working on decide"

    approval_service._websocket_manager.broadcast_to_tenant.assert_awaited()


@pytest.mark.asyncio
async def test_mark_decided_rejects_already_decided(approval_service, approval_seed, test_tenant_key):
    pending = await _create_pending_approval(approval_service, approval_seed, test_tenant_key)
    await approval_service.mark_decided(
        tenant_key=test_tenant_key,
        approval_id=pending.id,
        option_id="approve",
        user_id=None,
        decided_via="mcp",
    )

    with pytest.raises(ValidationError, match="is not pending"):
        await approval_service.mark_decided(
            tenant_key=test_tenant_key,
            approval_id=pending.id,
            option_id="approve",
            user_id=None,
            decided_via="mcp",
        )


@pytest.mark.asyncio
async def test_mark_decided_rejects_invalid_option_id(approval_service, approval_seed, test_tenant_key):
    pending = await _create_pending_approval(approval_service, approval_seed, test_tenant_key)

    with pytest.raises(ValidationError, match=r"not in approval\.options"):
        await approval_service.mark_decided(
            tenant_key=test_tenant_key,
            approval_id=pending.id,
            option_id="not-a-real-option",
            user_id=None,
            decided_via="mcp",
        )


@pytest.mark.asyncio
async def test_mark_decided_unknown_id_raises_not_found(approval_service, test_tenant_key):
    with pytest.raises(ResourceNotFoundError):
        await approval_service.mark_decided(
            tenant_key=test_tenant_key,
            approval_id=str(uuid4()),
            option_id="approve",
            user_id=None,
            decided_via="mcp",
        )


@pytest.mark.asyncio
async def test_mark_decided_notifies_orchestrator_via_inbox(
    db_manager, db_session, approval_seed, test_tenant_key, test_user
):
    """Regression: decide() must post a Hub message to the awaiting agent's bound
    thread so the agent learns the chosen option on its next get_thread_history poll.

    Before this fix the gate cleared server-side but the agent had no semantic
    channel to discover which option the user picked — users were forced to
    relay the decision verbally in chat. The Hub post is the explicit
    loop-closure path. BE-9012d: retargeted from the retired bus send_message.
    """
    ws = MagicMock()
    ws.broadcast_to_tenant = AsyncMock()
    comm = MagicMock()
    comm.resolve_or_create_bound_thread = AsyncMock(return_value={"thread_id": "thread-decide-1"})
    comm.post_to_thread = AsyncMock()
    service = UserApprovalService(
        db_manager=db_manager,
        tenant_manager=TenantManager(),
        websocket_manager=ws,
        test_session=db_session,
        comm_thread_service=comm,
    )

    pending = await _create_pending_approval(service, approval_seed, test_tenant_key)
    await service.mark_decided(
        tenant_key=test_tenant_key,
        approval_id=pending.id,
        option_id="rework",
        user_id=str(test_user.id),
        decided_via="ui",
    )

    comm.resolve_or_create_bound_thread.assert_awaited_once()
    resolve_kwargs = comm.resolve_or_create_bound_thread.await_args.kwargs
    assert resolve_kwargs["project_id"] == approval_seed["project"].id
    assert resolve_kwargs["tenant_key"] == test_tenant_key

    comm.post_to_thread.assert_awaited_once()
    call_kwargs = comm.post_to_thread.await_args.kwargs
    assert call_kwargs["thread_id"] == "thread-decide-1"
    assert call_kwargs["to_participant"] == approval_seed["execution"].agent_id
    assert call_kwargs["tenant_key"] == test_tenant_key
    assert call_kwargs["from_agent"] == "user"
    assert call_kwargs["requires_action"] is True
    assert "rework" in call_kwargs["content"].lower() or "send back for rework" in call_kwargs["content"].lower()
    assert "please decide" in call_kwargs["content"]


@pytest.mark.asyncio
async def test_mark_decided_survives_inbox_delivery_failure(
    db_manager, db_session, approval_seed, test_tenant_key, test_user
):
    """If the Hub-notify hiccups, the decide transaction must still succeed.

    The status flip + WebSocket broadcast have already committed by the time
    we hit the Hub post; a delivery failure logs a warning but cannot raise
    (otherwise a transient Hub-service outage would leave the gate visibly
    cleared in the DB but bubble a 5xx to the user).
    """
    ws = MagicMock()
    ws.broadcast_to_tenant = AsyncMock()
    comm = MagicMock()
    comm.resolve_or_create_bound_thread = AsyncMock(return_value={"thread_id": "thread-decide-2"})
    comm.post_to_thread = AsyncMock(side_effect=RuntimeError("transient Hub outage"))
    service = UserApprovalService(
        db_manager=db_manager,
        tenant_manager=TenantManager(),
        websocket_manager=ws,
        test_session=db_session,
        comm_thread_service=comm,
    )

    pending = await _create_pending_approval(service, approval_seed, test_tenant_key)
    decided = await service.mark_decided(
        tenant_key=test_tenant_key,
        approval_id=pending.id,
        option_id="approve",
        user_id=str(test_user.id),
        decided_via="ui",
    )

    assert decided.status == "decided"
    comm.post_to_thread.assert_awaited_once()


@pytest.mark.asyncio
async def test_mark_decided_restores_pre_approval_status(approval_service, approval_seed, test_tenant_key, db_session):
    """BE-9054 (b) regression: decide must restore the pre-approval status, not
    hardcode 'working'.

    An orchestrator that already completed (status='complete') and then requests
    approval used to be resurrected to 'working' on decide — permanently blocking
    its own closeout. create_pending records the pre-approval status; mark_decided
    restores it.
    """
    execution = approval_seed["execution"]
    execution.status = "complete"
    await db_session.commit()

    pending = await _create_pending_approval(approval_service, approval_seed, test_tenant_key)
    await db_session.refresh(execution)
    assert execution.status == "awaiting_user"

    await approval_service.mark_decided(
        tenant_key=test_tenant_key,
        approval_id=pending.id,
        option_id="approve",
        user_id=None,
        decided_via="mcp",
    )

    row = (await db_session.execute(select(AgentExecution).where(AgentExecution.id == execution.id))).scalar_one()
    assert row.status == "complete", (
        "decide must restore the pre-approval status ('complete'), not resurrect the agent to 'working'"
    )


@pytest.mark.asyncio
async def test_create_pending_ignores_agent_spoofed_pre_approval_status(
    approval_service, approval_seed, test_tenant_key, db_session
):
    """The pre_approval_status context key is server-reserved: an agent-supplied
    value must be stripped, never trusted (it could smuggle in 'complete' and
    skip the completion gates on decide)."""
    pending = await approval_service.create_pending(
        tenant_key=test_tenant_key,
        job_id=approval_seed["job"].job_id,
        project_id=approval_seed["project"].id,
        reason="spoof attempt",
        options=[{"id": "approve", "label": "Approve"}],
        context={"pre_approval_status": "complete", "note": "legit payload"},
    )

    row = (await db_session.execute(select(UserApproval).where(UserApproval.id == pending.id))).scalar_one()
    # Pre-approval status was 'working' -> nothing recorded; the spoofed key is gone.
    assert "pre_approval_status" not in (row.context or {})
    assert (row.context or {}).get("note") == "legit payload"

    await approval_service.mark_decided(
        tenant_key=test_tenant_key,
        approval_id=pending.id,
        option_id="approve",
        user_id=None,
        decided_via="mcp",
    )
    execution = (
        await db_session.execute(select(AgentExecution).where(AgentExecution.id == approval_seed["execution"].id))
    ).scalar_one()
    assert execution.status == "working", "spoofed pre_approval_status must not drive the restore"


@pytest.mark.asyncio
async def test_create_pending_rejects_worker_job(approval_service, approval_seed, test_tenant_key, db_session):
    """BE-9054 (a) service-layer half: a non-orchestrator job is rejected with
    error_code=ORCHESTRATOR_ONLY_APPROVAL and the execution status is untouched."""
    worker_job = AgentJob(
        job_id=str(uuid4()),
        tenant_key=test_tenant_key,
        project_id=approval_seed["project"].id,
        job_type="implementer",
        mission="x",
        status="active",
        created_at=datetime.now(UTC),
    )
    db_session.add(worker_job)
    await db_session.flush()
    worker_execution = AgentExecution(
        id=str(uuid4()),
        agent_id=str(uuid4()),
        job_id=worker_job.job_id,
        tenant_key=test_tenant_key,
        agent_display_name="implementer",
        status="working",
        started_at=datetime.now(UTC),
    )
    db_session.add(worker_execution)
    await db_session.commit()

    with pytest.raises(ValidationError) as excinfo:
        await approval_service.create_pending(
            tenant_key=test_tenant_key,
            job_id=worker_job.job_id,
            project_id=approval_seed["project"].id,
            reason="worker asking for approval",
            options=[{"id": "approve", "label": "Approve"}],
            context=None,
        )
    assert excinfo.value.error_code == "ORCHESTRATOR_ONLY_APPROVAL"

    row = (
        await db_session.execute(select(AgentExecution).where(AgentExecution.id == worker_execution.id))
    ).scalar_one()
    assert row.status == "working", "rejected worker request must not flip the execution status"


@pytest.mark.asyncio
async def test_mark_decided_cross_tenant_returns_not_found(
    approval_service, approval_seed, test_tenant_key, db_session
):
    """Cross-tenant attempts must not leak existence (ResourceNotFoundError)."""
    pending = await _create_pending_approval(approval_service, approval_seed, test_tenant_key)
    other_tenant = TenantManager.generate_tenant_key()

    with pytest.raises(ResourceNotFoundError):
        await approval_service.mark_decided(
            tenant_key=other_tenant,
            approval_id=pending.id,
            option_id="approve",
            user_id=None,
            decided_via="mcp",
        )

    row = (await db_session.execute(select(UserApproval).where(UserApproval.id == pending.id))).scalar_one()
    assert row.status == "pending", "cross-tenant attempt must not mutate"
