# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-9247 -- forward-on-send: a directed, action-required Hub post addressed to
an already-TERMINAL (closed/decommissioned) recipient redirects to the live
orchestrator at SEND time, instead of landing as a delivered row nobody will
ever drain ("MESSAGES WAITING: 2" on a dead agent).

This is P2 in the BE-9242/BE-9247 pair: P1 (merged, BE-9242) resolves a dead
agent's cursors at CLOSE time; this project extends the send-time seam
(``MessageRoutingService._auto_block_completed_recipients`` /
``auto_block_for_thread_post``) so a NEW post never has to wait for a close to
be resolved. Reuses P1's ``forward_action_required_to_orchestrator`` /
``build_forwarded_annotation`` VERBATIM -- no forked annotation shape.

Covered (DoD):
  1. closed recipient -> forwarded to the live orchestrator, sender gets a
     notice, the dead agent's cursor is acked (unread does not linger).
  2. decommissioned recipient -> same redirect.
  3. no live orchestrator -> structured RECIPIENT_FINISHED reject naming the
     thread's baton owner; the dead cursor is left un-acked.
  4. self-forward guard: the SENDER is the live orchestrator itself, recipient
     closed -> no self-addressed forward, notice instead.
  5. a 'complete' recipient still auto-blocks (existing BE-9012b behavior,
     unchanged) -- pinned again at this layer for the sibling regression;
     ``test_be9012b_reactivation_as_post.py`` MUST also stay green.

Parallel-safe: db_session (TransactionalTestContext). Each test owns its
setup. Edition Scope: Both (CE messaging/lifecycle core).
"""

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
    """Persist a thread post exactly as comm_thread_service would: thread_id set,
    project_id = thread.project_id."""
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
    """DoD 1+2: a directed, action-required post to an already-TERMINAL recipient
    is redirected to the live orchestrator; the sender gets a notice; the dead
    agent's cursor is acked so its unread does not linger."""
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

    # No auto-block (nothing to reactivate on a truly-dead agent).
    assert list(outcome) == []
    assert outcome.notice is not None
    assert "tester" in outcome.notice
    assert "forwarded" in outcome.notice.lower()

    # The dead agent's cursor for THIS message is acked -- unread does not linger.
    assert await _is_acked(db_session, test_tenant_key, msg.id, dead.agent_id)

    # Exactly one forwarded message reaches the live orchestrator, carrying the
    # original content and P1's canonical annotation shape.
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
    """DoD 3: with no live orchestrator to redirect to, the sender gets a
    structured RECIPIENT_FINISHED notice naming the thread's baton owner
    (CommThread.next_action_owner fallback), and the dead cursor is left
    un-acked -- never silently dropped."""
    project = await _seed_project(db_session, test_tenant_key)
    # No orchestrator execution seeded at all.
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

    # The dead cursor stays un-acked -- fails open, visibly.
    assert not await _is_acked(db_session, test_tenant_key, msg.id, dead.agent_id)


async def test_self_forward_guard_no_redirect_to_own_author(
    db_session: AsyncSession,
    routing_service: MessageRoutingService,
    test_tenant_key: str,
) -> None:
    """DoD 4: when the resolved live orchestrator IS the sender, the message is
    never forwarded to itself -- a RECIPIENT_FINISHED-style notice is emitted
    instead, and the dead cursor is left un-acked (no forward happened)."""
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
        from_agent_id=orchestrator.agent_id,  # the orchestrator IS the sender
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

    # No forward was created -- the orchestrator's own inbox stays untouched.
    forwarded = await _forwarded_messages_to(db_session, test_tenant_key, project.id, orchestrator.agent_id)
    assert forwarded == []
    # No forward happened, so the dead cursor is NOT acked.
    assert not await _is_acked(db_session, test_tenant_key, msg.id, dead.agent_id)


async def test_self_forward_guard_catches_job_id_self_declaration(
    db_session: AsyncSession,
    routing_service: MessageRoutingService,
    test_tenant_key: str,
) -> None:
    """Regression for BE-9247 audit Finding 1: the shipped AGENT REACTIVATION
    PROTOCOL teaches orchestrators to post with from_agent="{orchestrator_id}",
    and {orchestrator_id} is the JOB_ID -- a different UUID from agent_id. When a
    live orchestrator follows its own protocol and posts a directed
    requires_action message to a since-closed recipient using its job_id, the
    self-forward guard must still fire: no self-addressed forward to the
    orchestrator's own agent_id (which would spuriously gate its own
    complete_job), and the sender gets the RECIPIENT_FINISHED notice instead.

    Fail-first: before the guard recognizes job_id, from_agent_id=job_id misses
    (job_id != agent_id and != "orchestrator" display_name) and a self-addressed
    forward is wrongly created; the forwarded-messages assertion below fails."""
    project = await _seed_project(db_session, test_tenant_key)
    # The orchestrator MUST be discoverable as agent_display_name == "orchestrator"
    # (find_active_orchestrator_in_project keys on that literal); otherwise the code
    # falls through to the no-orchestrator branch and the guard is never exercised.
    # Isolation of the FIX comes from from_agent_id = job_id, a UUID that is neither
    # the agent_id nor the "orchestrator" literal -- so ONLY the job_id membership in
    # the widened identity set can make the guard fire.
    orchestrator = await _seed_execution(
        db_session, test_tenant_key, project.id, display_name="orchestrator", status="working"
    )
    assert orchestrator.job_id != orchestrator.agent_id  # the whole point of the gap
    assert orchestrator.job_id != "orchestrator"
    dead = await _seed_execution(db_session, test_tenant_key, project.id, display_name="tester", status="closed")
    msg, _thread = await _seed_thread_post(
        db_session,
        test_tenant_key,
        project_id=project.id,
        recipient_agent_id=dead.agent_id,
        from_agent_id=orchestrator.job_id,  # the protocol's {orchestrator_id} == job_id
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

    # The guard fired: no self-addressed forward reached the orchestrator's inbox.
    forwarded = await _forwarded_messages_to(db_session, test_tenant_key, project.id, orchestrator.agent_id)
    assert forwarded == []
    # No forward happened, so the dead cursor is NOT acked.
    assert not await _is_acked(db_session, test_tenant_key, msg.id, dead.agent_id)


async def test_self_forward_guard_catches_anonymous_orchestrator_attribution(
    db_session: AsyncSession,
    routing_service: MessageRoutingService,
    test_tenant_key: str,
) -> None:
    """Regression for a gap the self-forward guard would otherwise miss:
    comm_thread_service.post_to_thread falls back to the literal from_agent_id
    "orchestrator" (not a real agent_id) when a post carries no from_agent and no
    authenticated user. The system already treats such a post as
    orchestrator-authored end to end (from_display_name gets the same literal),
    so the guard must recognize this fallback too, not just a real agent_id match."""
    project = await _seed_project(db_session, test_tenant_key)
    await _seed_execution(db_session, test_tenant_key, project.id, display_name="orchestrator", status="working")
    dead = await _seed_execution(db_session, test_tenant_key, project.id, display_name="tester", status="closed")
    msg, _thread = await _seed_thread_post(
        db_session,
        test_tenant_key,
        project_id=project.id,
        recipient_agent_id=dead.agent_id,
        from_agent_id="orchestrator",  # the anonymous-post fallback literal, not a real agent_id
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
    """DoD 5: a 'complete' recipient keeps the existing auto-block/reactivate
    behavior byte-identical -- no notice, no forward, just the pre-existing
    reactivation."""
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
