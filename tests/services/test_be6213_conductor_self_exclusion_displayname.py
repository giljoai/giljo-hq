# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.exceptions import ValidationError
from giljo_mcp.models.agent_identity import AgentExecution, AgentJob
from giljo_mcp.models.products import Product
from giljo_mcp.models.projects import Project
from giljo_mcp.models.tasks import Message, MessageRecipient
from giljo_mcp.services.job_completion_service import JobCompletionService


@pytest.fixture
async def test_product(db_session: AsyncSession, test_tenant_key: str) -> Product:
    product = Product(
        id=str(uuid4()),
        tenant_key=test_tenant_key,
        name="BE-6213 Product",
        description="conductor self-exclusion by display name",
        product_memory={},
    )
    db_session.add(product)
    await db_session.commit()
    await db_session.refresh(product)
    return product


@pytest.fixture
async def active_project(db_session: AsyncSession, test_tenant_key: str, test_product: Product) -> Project:
    project = Project(
        id=str(uuid4()),
        tenant_key=test_tenant_key,
        product_id=test_product.id,
        name="BE-6213 Project",
        description="conductor self-exclusion by display name",
        mission="test",
        status="active",
        created_at=datetime.now(UTC),
        series_number=random.randint(1, 9000),
    )
    db_session.add(project)
    await db_session.commit()
    await db_session.refresh(project)
    return project


@pytest.fixture
def completion_service(db_session: AsyncSession, test_tenant_key: str) -> JobCompletionService:
    tenant_manager = MagicMock()
    tenant_manager.get_current_tenant.return_value = test_tenant_key
    return JobCompletionService(
        db_manager=MagicMock(),
        tenant_manager=tenant_manager,
        test_session=db_session,
    )


async def _seed_conductor(
    db_session: AsyncSession,
    tenant_key: str,
    *,
    display_name: str = "orchestrator",
    agent_name: str = "Conductor",
    is_conductor: bool = True,
    project_id: str | None = None,
) -> tuple[AgentJob, AgentExecution]:
    job_id = str(uuid4())
    job = AgentJob(
        job_id=job_id,
        tenant_key=tenant_key,
        project_id=project_id,
        job_type="orchestrator",
        mission="drive the chain",
        status="active",
        job_metadata={"chain_conductor": True, "run_id": str(uuid4())} if is_conductor else {},
    )
    db_session.add(job)
    execution = AgentExecution(
        job_id=job_id,
        tenant_key=tenant_key,
        agent_display_name=display_name,
        agent_name=agent_name,
        status="working",
        messages_sent_count=0,
        messages_waiting_count=0,
        messages_read_count=0,
        started_at=datetime.now(UTC) - timedelta(minutes=5),
    )
    db_session.add(execution)
    await db_session.commit()
    await db_session.refresh(job)
    await db_session.refresh(execution)
    return job, execution


async def _add_pending_message(
    db_session: AsyncSession,
    tenant_key: str,
    project_id: str | None,
    from_agent_id: str,
    to_agent_id: str,
) -> None:
    msg = Message(
        tenant_key=tenant_key,
        project_id=project_id,
        from_agent_id=from_agent_id,
        content="chain complete",
        status="pending",
        requires_action=True,
        created_at=datetime.now(UTC) - timedelta(minutes=1),
    )
    db_session.add(msg)
    await db_session.flush()
    db_session.add(MessageRecipient(message_id=msg.id, agent_id=to_agent_id, tenant_key=tenant_key))
    await db_session.commit()


@pytest.mark.asyncio
async def test_conductor_self_post_under_label_does_not_block(
    db_session: AsyncSession,
    completion_service: JobCompletionService,
    test_tenant_key: str,
):
    job, execution = await _seed_conductor(db_session, test_tenant_key)
    await _add_pending_message(db_session, test_tenant_key, None, execution.agent_name, execution.agent_id)

    result = await completion_service.complete_job(
        job_id=job.job_id,
        result={"summary": "chain done"},
        tenant_key=test_tenant_key,
    )
    assert result.status == "success"


@pytest.mark.asyncio
async def test_other_agent_message_still_blocks_conductor(
    db_session: AsyncSession,
    completion_service: JobCompletionService,
    test_tenant_key: str,
):
    job, execution = await _seed_conductor(db_session, test_tenant_key)
    await _add_pending_message(db_session, test_tenant_key, None, "SomeOtherAgent", execution.agent_id)

    with pytest.raises(ValidationError) as exc_info:
        await completion_service.complete_job(
            job_id=job.job_id,
            result={"summary": "chain done"},
            tenant_key=test_tenant_key,
        )
    assert exc_info.value.error_code == "COMPLETION_BLOCKED"
    assert (exc_info.value.context or {}).get("unread_messages") == 1


@pytest.mark.asyncio
async def test_non_conductor_keeps_uuid_only_self_match(
    db_session: AsyncSession,
    completion_service: JobCompletionService,
    test_tenant_key: str,
    active_project: Project,
):
    job, execution = await _seed_conductor(
        db_session,
        test_tenant_key,
        display_name="orchestrator",
        agent_name="orchestrator",
        is_conductor=False,
        project_id=active_project.id,
    )
    await _add_pending_message(db_session, test_tenant_key, active_project.id, "orchestrator", execution.agent_id)

    with pytest.raises(ValidationError) as exc_info:
        await completion_service.complete_job(
            job_id=job.job_id,
            result={"summary": "done"},
            tenant_key=test_tenant_key,
        )
    assert exc_info.value.error_code == "COMPLETION_BLOCKED"
    assert (exc_info.value.context or {}).get("unread_messages") == 1
