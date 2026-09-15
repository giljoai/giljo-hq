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
from giljo_mcp.models.tasks import Message, MessageAcknowledgment, MessageRecipient
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
        name="BE-9247 forward-on-send Product",
        description="forward-on-send",
        product_memory={},
    )
    db_session.add(product)
    await db_session.flush()
    project = Project(
        id=str(uuid4()),
        tenant_key=tenant_key,
        product_id=product.id,
        name="BE-9247 forward-on-send Project",
        description="forward-on-send",
        mission="test",
        status=status,
        created_at=datetime.now(UTC),
        series_number=random.randint(1, 9000),
    )
    db_session.add(project)
    await db_session.commit()
    await db_session.refresh(project)
    return project


async def _seed_execution(
    db_session: AsyncSession,
    tenant_key: str,
    project_id: str,
    *,
    display_name: str,
    status: str,
    started_at: datetime | None = None,
) -> AgentExecution:
    job = AgentJob(
        job_id=str(uuid4()),
        tenant_key=tenant_key,
        project_id=project_id,
        job_type=display_name,
        mission=f"mission {display_name}",
        status="active",
    )
    db_session.add(job)
    execution = AgentExecution(
        job_id=job.job_id,
        tenant_key=tenant_key,
        agent_display_name=display_name,
        status=status,
        started_at=started_at or (datetime.now(UTC) - timedelta(minutes=5)),
        completed_at=datetime.now(UTC) if status in {"complete", "closed", "decommissioned"} else None,
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
    project_id: str,
    recipient_agent_id: str,
    from_agent_id: str = "orchestrator",
    from_display_name: str = "orchestrator",
    next_action_owner: str | None = None,
    requires_action: bool = True,
) -> tuple[Message, CommThread]:
    thread = CommThread(
        id=str(uuid4()),
        tenant_key=tenant_key,
        serial=random.randint(1, 90000),
        subject="BE-9247 thread",
        status="open",
        project_id=project_id,
        next_action_owner=next_action_owner,
    )
    db_session.add(thread)
    await db_session.flush()
    msg = Message(
        tenant_key=tenant_key,
        project_id=project_id,
        thread_id=thread.id,
        from_agent_id=from_agent_id,
        from_display_name=from_display_name,
        content="Please handle this before you finish.",
        status="pending",
        requires_action=requires_action,
        created_at=datetime.now(UTC),
    )
    db_session.add(msg)
    await db_session.flush()
    db_session.add(MessageRecipient(message_id=msg.id, agent_id=recipient_agent_id, tenant_key=tenant_key))
    await db_session.commit()
    await db_session.refresh(msg)
    return msg, thread


async def _is_acked(db_session: AsyncSession, tenant_key: str, message_id: str, agent_id: str) -> bool:
    row = (
        await db_session.execute(
            select(MessageAcknowledgment.id).where(
                MessageAcknowledgment.tenant_key == tenant_key,
                MessageAcknowledgment.message_id == message_id,
                MessageAcknowledgment.agent_id == agent_id,
            )
        )
    ).scalar_one_or_none()
    return row is not None


async def _forwarded_messages_to(
    db_session: AsyncSession, tenant_key: str, project_id: str, orchestrator_agent_id: str
) -> list[Message]:
    stmt = (
        select(Message)
        .join(MessageRecipient, Message.id == MessageRecipient.message_id)
        .where(
            Message.tenant_key == tenant_key,
            Message.project_id == project_id,
            MessageRecipient.agent_id == orchestrator_agent_id,
            Message.requires_action.is_(True),
        )
    )
    return list((await db_session.execute(stmt)).scalars().all())


@pytest.mark.parametrize("dead_status", ["closed", "decommissioned"])
async def test_closed_or_decommissioned_recipient_forwards_to_live_orchestrator(
    db_session: AsyncSession,
    routing_service: MessageRoutingService,
    test_tenant_key: str,
    dead_status: str,
) -> None:
    project = await _seed_project(db_session, test_tenant_key)
    orchestrator = await _seed_execution(
        db_session, test_tenant_key, project.id, display_name="orchestrator", status="working"
    )
    dead = await _seed_execution(db_session, test_tenant_key, project.id, display_name="tester", status=dead_status)
    msg, _thread = await _seed_thread_post(
        db_session,
        test_tenant_key,
        project_id=project.id,
        recipient_agent_id=dead.agent_id,
        from_agent_id="some-other-implementer",
        from_display_name="implementer",
    )

    outcome = await routing_service.auto_block_for_thread_post(
        message_id=msg.id,
        to_participant=dead.agent_id,
        sender_display_name="implementer",
        requires_action=True,
        tenant_key=test_tenant_key,
    )

    assert list(outcome) == []
    assert outcome.notice is not None
    assert "tester" in outcome.notice
    assert "forwarded" in outcome.notice.lower()

    assert await _is_acked(db_session, test_tenant_key, msg.id, dead.agent_id)

    forwarded = await _forwarded_messages_to(db_session, test_tenant_key, project.id, orchestrator.agent_id)
    assert len(forwarded) == 1
    assert "Please handle this before you finish." in forwarded[0].content
    assert "[FORWARDED:" in forwarded[0].content
    assert forwarded[0].auto_generated is False
    assert not await _is_acked(db_session, test_tenant_key, forwarded[0].id, orchestrator.agent_id)


async def test_no_live_orchestrator_rejects_and_leaves_dead_cursor_unacked(
    db_session: AsyncSession,
    routing_service: MessageRoutingService,
    test_tenant_key: str,
) -> None:
    project = await _seed_project(db_session, test_tenant_key)
    dead = await _seed_execution(db_session, test_tenant_key, project.id, display_name="tester", status="closed")
    msg, _thread = await _seed_thread_post(
        db_session,
        test_tenant_key,
        project_id=project.id,
        recipient_agent_id=dead.agent_id,
        from_agent_id="some-implementer",
        from_display_name="implementer",
        next_action_owner="live-participant-42",
    )

    outcome = await routing_service.auto_block_for_thread_post(
        message_id=msg.id,
        to_participant=dead.agent_id,
        sender_display_name="implementer",
        requires_action=True,
        tenant_key=test_tenant_key,
    )

    assert list(outcome) == []
    assert outcome.notice is not None
    assert "RECIPIENT_FINISHED" in outcome.notice
    assert "live-participant-42" in outcome.notice

    assert not await _is_acked(db_session, test_tenant_key, msg.id, dead.agent_id)


async def test_self_forward_guard_no_redirect_to_own_author(
    db_session: AsyncSession,
    routing_service: MessageRoutingService,
    test_tenant_key: str,
) -> None:
    project = await _seed_project(db_session, test_tenant_key)
    orchestrator = await _seed_execution(
        db_session, test_tenant_key, project.id, display_name="orchestrator", status="working"
    )
    dead = await _seed_execution(db_session, test_tenant_key, project.id, display_name="tester", status="closed")
    msg, _thread = await _seed_thread_post(
        db_session,
        test_tenant_key,
        project_id=project.id,
        recipient_agent_id=dead.agent_id,
        from_agent_id=orchestrator.agent_id,
        from_display_name="orchestrator",
    )

    outcome = await routing_service.auto_block_for_thread_post(
        message_id=msg.id,
        to_participant=dead.agent_id,
        sender_display_name="orchestrator",
        requires_action=True,
        tenant_key=test_tenant_key,
    )

    assert list(outcome) == []
    assert outcome.notice is not None
    assert "RECIPIENT_FINISHED" in outcome.notice

    forwarded = await _forwarded_messages_to(db_session, test_tenant_key, project.id, orchestrator.agent_id)
    assert forwarded == []
    assert not await _is_acked(db_session, test_tenant_key, msg.id, dead.agent_id)


async def test_self_forward_guard_catches_job_id_self_declaration(
    db_session: AsyncSession,
    routing_service: MessageRoutingService,
    test_tenant_key: str,
) -> None:
    project = await _seed_project(db_session, test_tenant_key)
    orchestrator = await _seed_execution(
        db_session, test_tenant_key, project.id, display_name="orchestrator", status="working"
    )
    assert orchestrator.job_id != orchestrator.agent_id
    assert orchestrator.job_id != "orchestrator"
    dead = await _seed_execution(db_session, test_tenant_key, project.id, display_name="tester", status="closed")
    msg, _thread = await _seed_thread_post(
        db_session,
        test_tenant_key,
        project_id=project.id,
        recipient_agent_id=dead.agent_id,
        from_agent_id=orchestrator.job_id,
        from_display_name="orchestrator",
    )

    outcome = await routing_service.auto_block_for_thread_post(
        message_id=msg.id,
        to_participant=dead.agent_id,
        sender_display_name="orchestrator",
        requires_action=True,
        tenant_key=test_tenant_key,
    )

    assert list(outcome) == []
    assert outcome.notice is not None
    assert "RECIPIENT_FINISHED" in outcome.notice

    forwarded = await _forwarded_messages_to(db_session, test_tenant_key, project.id, orchestrator.agent_id)
    assert forwarded == []
    assert not await _is_acked(db_session, test_tenant_key, msg.id, dead.agent_id)


async def test_self_forward_guard_catches_anonymous_orchestrator_attribution(
    db_session: AsyncSession,
    routing_service: MessageRoutingService,
    test_tenant_key: str,
) -> None:
    project = await _seed_project(db_session, test_tenant_key)
    await _seed_execution(db_session, test_tenant_key, project.id, display_name="orchestrator", status="working")
    dead = await _seed_execution(db_session, test_tenant_key, project.id, display_name="tester", status="closed")
    msg, _thread = await _seed_thread_post(
        db_session,
        test_tenant_key,
        project_id=project.id,
        recipient_agent_id=dead.agent_id,
        from_agent_id="orchestrator",
        from_display_name="orchestrator",
    )

    outcome = await routing_service.auto_block_for_thread_post(
        message_id=msg.id,
        to_participant=dead.agent_id,
        sender_display_name="orchestrator",
        requires_action=True,
        tenant_key=test_tenant_key,
    )

    assert list(outcome) == []
    assert outcome.notice is not None
    assert "RECIPIENT_FINISHED" in outcome.notice
    assert not await _is_acked(db_session, test_tenant_key, msg.id, dead.agent_id)


async def test_complete_recipient_still_auto_blocks_unchanged(
    db_session: AsyncSession,
    routing_service: MessageRoutingService,
    test_tenant_key: str,
) -> None:
    project = await _seed_project(db_session, test_tenant_key)
    recipient = await _seed_execution(
        db_session, test_tenant_key, project.id, display_name="implementer", status="complete"
    )
    msg, _thread = await _seed_thread_post(
        db_session,
        test_tenant_key,
        project_id=project.id,
        recipient_agent_id=recipient.agent_id,
    )

    outcome = await routing_service.auto_block_for_thread_post(
        message_id=msg.id,
        to_participant=recipient.agent_id,
        sender_display_name="orchestrator",
        requires_action=True,
        tenant_key=test_tenant_key,
    )

    assert outcome == [recipient.agent_id]
    assert outcome.notice is None

    refreshed = (
        await db_session.execute(
            select(AgentExecution).where(
                AgentExecution.agent_id == recipient.agent_id,
                AgentExecution.tenant_key == test_tenant_key,
            )
        )
    ).scalar_one()
    assert refreshed.status == "blocked"
