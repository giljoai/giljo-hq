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
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.models.agent_identity import AgentExecution, AgentJob
from giljo_mcp.models.comm import CommThread
from giljo_mcp.models.products import Product
from giljo_mcp.models.projects import Project
from giljo_mcp.models.tasks import Message, MessageRecipient
from giljo_mcp.services.message_routing_service import MessageRoutingService


pytestmark = pytest.mark.asyncio


@pytest.fixture
def routing_service(db_session: AsyncSession, test_tenant_key: str) -> MessageRoutingService:
    tenant_manager = MagicMock()
    tenant_manager.get_current_tenant.return_value = test_tenant_key
    return MessageRoutingService(
        db_manager=MagicMock(),
        tenant_manager=tenant_manager,
        websocket_manager=None,
        test_session=db_session,
    )


async def _seed_project(db_session: AsyncSession, tenant_key: str, *, status: str = "active") -> Project:
    product = Product(
        id=str(uuid4()),
        tenant_key=tenant_key,
        name="BE-9012b D5 Product",
        description="reactivation-as-post",
        product_memory={},
    )
    db_session.add(product)
    await db_session.flush()
    project = Project(
        id=str(uuid4()),
        tenant_key=tenant_key,
        product_id=product.id,
        name="BE-9012b D5 Project",
        description="reactivation-as-post",
        mission="test",
        status=status,
        created_at=datetime.now(UTC),
        series_number=random.randint(1, 9000),
    )
    db_session.add(project)
    await db_session.commit()
    await db_session.refresh(project)
    return project


async def _seed_completed_recipient(db_session: AsyncSession, tenant_key: str, project_id: str) -> AgentExecution:
    job = AgentJob(
        job_id=str(uuid4()),
        tenant_key=tenant_key,
        project_id=project_id,
        job_type="implementer",
        mission="do work",
        status="active",
    )
    db_session.add(job)
    execution = AgentExecution(
        job_id=job.job_id,
        tenant_key=tenant_key,
        agent_display_name="implementer",
        status="complete",
        completed_at=datetime.now(UTC),
        started_at=datetime.now(UTC) - timedelta(minutes=5),
        messages_sent_count=0,
        messages_waiting_count=0,
        messages_read_count=0,
    )
    db_session.add(execution)
    await db_session.commit()
    await db_session.refresh(execution)
    return execution


async def _seed_thread_post(
    db_session: AsyncSession,
    tenant_key: str,
    *,
    project_id: str | None,
    recipient_agent_id: str,
    requires_action: bool = True,
) -> Message:
    thread = CommThread(
        id=str(uuid4()),
        tenant_key=tenant_key,
        serial=random.randint(1, 90000),
        subject="D5 thread",
        status="open",
        project_id=project_id,
    )
    db_session.add(thread)
    await db_session.flush()
    msg = Message(
        tenant_key=tenant_key,
        project_id=project_id,
        thread_id=thread.id,
        from_agent_id="orchestrator",
        content="REWORK_REQUIRED: please revisit",
        status="pending",
        requires_action=requires_action,
        created_at=datetime.now(UTC),
    )
    db_session.add(msg)
    await db_session.flush()
    db_session.add(MessageRecipient(message_id=msg.id, agent_id=recipient_agent_id, tenant_key=tenant_key))
    await db_session.commit()
    await db_session.refresh(msg)
    return msg


async def _recipient_status(db_session: AsyncSession, tenant_key: str, agent_id: str) -> str:
    row = (
        await db_session.execute(
            select(AgentExecution).where(
                AgentExecution.agent_id == agent_id,
                AgentExecution.tenant_key == tenant_key,
            )
        )
    ).scalar_one()
    return row.status


async def test_project_bound_directed_action_post_blocks_completed_recipient(
    db_session: AsyncSession, routing_service: MessageRoutingService, test_tenant_key: str
):
    project = await _seed_project(db_session, test_tenant_key)
    recipient = await _seed_completed_recipient(db_session, test_tenant_key, project.id)
    msg = await _seed_thread_post(
        db_session, test_tenant_key, project_id=project.id, recipient_agent_id=recipient.agent_id
    )

    blocked = await routing_service.auto_block_for_thread_post(
        message_id=msg.id,
        to_participant=recipient.agent_id,
        sender_display_name="orchestrator",
        requires_action=True,
        tenant_key=test_tenant_key,
    )

    assert blocked == [recipient.agent_id]
    assert await _recipient_status(db_session, test_tenant_key, recipient.agent_id) == "blocked"


async def test_town_square_post_is_side_effect_free(
    db_session: AsyncSession, routing_service: MessageRoutingService, test_tenant_key: str
):
    project = await _seed_project(db_session, test_tenant_key)
    recipient = await _seed_completed_recipient(db_session, test_tenant_key, project.id)
    msg = await _seed_thread_post(db_session, test_tenant_key, project_id=None, recipient_agent_id=recipient.agent_id)

    blocked = await routing_service.auto_block_for_thread_post(
        message_id=msg.id,
        to_participant=recipient.agent_id,
        sender_display_name="orchestrator",
        requires_action=True,
        tenant_key=test_tenant_key,
    )

    assert blocked == []
    assert await _recipient_status(db_session, test_tenant_key, recipient.agent_id) == "complete"


async def test_informational_post_does_not_block(
    db_session: AsyncSession, routing_service: MessageRoutingService, test_tenant_key: str
):
    project = await _seed_project(db_session, test_tenant_key)
    recipient = await _seed_completed_recipient(db_session, test_tenant_key, project.id)
    msg = await _seed_thread_post(
        db_session, test_tenant_key, project_id=project.id, recipient_agent_id=recipient.agent_id, requires_action=False
    )

    blocked = await routing_service.auto_block_for_thread_post(
        message_id=msg.id,
        to_participant=recipient.agent_id,
        sender_display_name="orchestrator",
        requires_action=False,
        tenant_key=test_tenant_key,
    )

    assert blocked == []
    assert await _recipient_status(db_session, test_tenant_key, recipient.agent_id) == "complete"


async def test_broadcast_without_explicit_recipient_does_not_fan_reactivate(
    db_session: AsyncSession, routing_service: MessageRoutingService, test_tenant_key: str
):
    project = await _seed_project(db_session, test_tenant_key)
    recipient = await _seed_completed_recipient(db_session, test_tenant_key, project.id)
    msg = await _seed_thread_post(
        db_session, test_tenant_key, project_id=project.id, recipient_agent_id=recipient.agent_id
    )

    blocked = await routing_service.auto_block_for_thread_post(
        message_id=msg.id,
        to_participant=None,
        sender_display_name="orchestrator",
        requires_action=True,
        tenant_key=test_tenant_key,
    )

    assert blocked == []
    assert await _recipient_status(db_session, test_tenant_key, recipient.agent_id) == "complete"


async def test_terminal_project_skips_auto_block(
    db_session: AsyncSession, routing_service: MessageRoutingService, test_tenant_key: str
):
    project = await _seed_project(db_session, test_tenant_key, status="completed")
    recipient = await _seed_completed_recipient(db_session, test_tenant_key, project.id)
    msg = await _seed_thread_post(
        db_session, test_tenant_key, project_id=project.id, recipient_agent_id=recipient.agent_id
    )

    blocked = await routing_service.auto_block_for_thread_post(
        message_id=msg.id,
        to_participant=recipient.agent_id,
        sender_display_name="orchestrator",
        requires_action=True,
        tenant_key=test_tenant_key,
    )

    assert blocked == []
    assert await _recipient_status(db_session, test_tenant_key, recipient.agent_id) == "complete"
