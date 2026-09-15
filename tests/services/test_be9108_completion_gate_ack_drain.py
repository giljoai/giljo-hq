# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import random
import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.database import tenant_session_context
from giljo_mcp.exceptions import ValidationError
from giljo_mcp.models import AgentExecution, AgentJob, Project
from giljo_mcp.models.products import Product
from giljo_mcp.models.tasks import MessageAcknowledgment
from giljo_mcp.services.comm_thread_service import CommThreadService
from giljo_mcp.services.job_completion_service import JobCompletionService
from giljo_mcp.services.taxonomy_ops import ensure_default_types_seeded
from giljo_mcp.tenant import TenantManager


pytestmark = pytest.mark.asyncio

SENDER = "sender-orch"


def _completion_service(db_session: AsyncSession, tenant_key: str) -> JobCompletionService:
    tenant_manager = MagicMock()
    tenant_manager.get_current_tenant.return_value = tenant_key
    return JobCompletionService(db_manager=MagicMock(), tenant_manager=tenant_manager, test_session=db_session)


def _comm_service(db_manager, db_session: AsyncSession) -> CommThreadService:
    return CommThreadService(db_manager, TenantManager(), session=db_session)


async def _seed_project_and_orchestrator(
    db_session: AsyncSession, tenant_key: str
) -> tuple[Project, AgentJob, AgentExecution]:
    with tenant_session_context(db_session, tenant_key):
        await ensure_default_types_seeded(db_session, tenant_key)

    product = Product(
        id=str(uuid.uuid4()),
        tenant_key=tenant_key,
        name="BE-9108 gate product",
        description="ack-drain gate regression",
        product_memory={},
    )
    db_session.add(product)
    await db_session.flush()

    project = Project(
        id=str(uuid.uuid4()),
        tenant_key=tenant_key,
        product_id=product.id,
        name="BE-9108 gate project",
        description="ack-drain gate regression",
        mission="verify the completion gate clears on the real drain",
        status="active",
        created_at=datetime.now(UTC),
        series_number=random.randint(1, 9000),
    )
    db_session.add(project)
    await db_session.flush()

    job = AgentJob(
        job_id=str(uuid.uuid4()),
        tenant_key=tenant_key,
        project_id=project.id,
        job_type="orchestrator",
        mission="orchestrate ack-drain gate test",
        status="active",
    )
    db_session.add(job)
    execution = AgentExecution(
        job_id=job.job_id,
        tenant_key=tenant_key,
        agent_display_name="orchestrator",
        status="working",
        messages_sent_count=0,
        messages_waiting_count=0,
        messages_read_count=0,
        started_at=datetime.now(UTC) - timedelta(minutes=5),
    )
    db_session.add(execution)
    await db_session.commit()
    await db_session.refresh(project)
    await db_session.refresh(job)
    await db_session.refresh(execution)
    return project, job, execution


async def _post_action_required_to(
    comm: CommThreadService, tenant_key: str, project_id: str, recipient_agent_id: str
) -> tuple[str, str]:
    thread = await comm.create_thread(
        subject="coordination", project_id=project_id, creator_id=SENDER, tenant_key=tenant_key
    )
    tid = thread["thread_id"]
    await comm.join_thread(thread_id=tid, participant_id=recipient_agent_id, tenant_key=tenant_key)
    posted = await comm.post_to_thread(
        thread_id=tid,
        content="please review the failing test before you close out",
        from_agent=SENDER,
        to_participant=recipient_agent_id,
        requires_action=True,
        tenant_key=tenant_key,
    )
    return tid, posted["message_id"]




async def test_action_required_message_not_drained_blocks_completion(db_manager, db_session: AsyncSession):
    tenant = TenantManager.generate_tenant_key()
    project, job, execution = await _seed_project_and_orchestrator(db_session, tenant)
    comm = _comm_service(db_manager, db_session)
    await _post_action_required_to(comm, tenant, project.id, execution.agent_id)

    with pytest.raises(ValidationError) as exc_info:
        await _completion_service(db_session, tenant).complete_job(
            job_id=job.job_id, result={"summary": "should block"}, tenant_key=tenant
        )
    assert exc_info.value.error_code == "COMPLETION_BLOCKED"
    assert (exc_info.value.context or {}).get("unread_messages") == 1




async def test_action_required_message_drained_via_mark_read_unblocks_completion(db_manager, db_session: AsyncSession):
    tenant = TenantManager.generate_tenant_key()
    project, job, execution = await _seed_project_and_orchestrator(db_session, tenant)
    comm = _comm_service(db_manager, db_session)
    tid, message_id = await _post_action_required_to(comm, tenant, project.id, execution.agent_id)

    with pytest.raises(ValidationError):
        await _completion_service(db_session, tenant).complete_job(
            job_id=job.job_id, result={"summary": "still blocked"}, tenant_key=tenant
        )

    drain = await comm.get_thread_history(
        thread_id=tid, as_participant=execution.agent_id, mark_read=True, tenant_key=tenant
    )
    assert drain["marked_read"] >= 1

    ack = (
        await db_session.execute(
            select(MessageAcknowledgment).where(
                MessageAcknowledgment.message_id == message_id,
                MessageAcknowledgment.agent_id == execution.agent_id,
                MessageAcknowledgment.tenant_key == tenant,
            )
        )
    ).scalar_one_or_none()
    assert ack is not None, "mark_read must have written the ack the gate reads"

    result = await _completion_service(db_session, tenant).complete_job(
        job_id=job.job_id, result={"summary": "drained and closed"}, tenant_key=tenant
    )
    assert result.status == "success"




async def test_drain_by_other_participant_does_not_unblock_recipient(db_manager, db_session: AsyncSession):
    tenant = TenantManager.generate_tenant_key()
    project, job, execution = await _seed_project_and_orchestrator(db_session, tenant)
    comm = _comm_service(db_manager, db_session)
    tid, _message_id = await _post_action_required_to(comm, tenant, project.id, execution.agent_id)

    await comm.join_thread(thread_id=tid, participant_id="other-agent", tenant_key=tenant)
    await comm.get_thread_history(thread_id=tid, as_participant="other-agent", mark_read=True, tenant_key=tenant)

    with pytest.raises(ValidationError) as exc_info:
        await _completion_service(db_session, tenant).complete_job(
            job_id=job.job_id, result={"summary": "must still block"}, tenant_key=tenant
        )
    assert exc_info.value.error_code == "COMPLETION_BLOCKED"
    assert (exc_info.value.context or {}).get("unread_messages") == 1
