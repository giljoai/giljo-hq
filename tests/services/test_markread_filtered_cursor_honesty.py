# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""Regression (service layer): a FILTERED ``mark_read`` must not report a count it
did not earn, and must say out loud that it left the read cursor where it was.

The reported failure was "``get_thread_history(mark_read=true,
action_required_only=true)`` returns ``marked_read: N`` and clears nothing". Half of
that is true and half of it is not, and the tests below pin both halves so neither
can drift:

- The acks ARE written, exactly for the posts returned, and the project-scoped
  completion gate (``agent_completion_repository.get_unread_messages_for_agent``,
  keyed on ``message_acknowledgments``) DOES clear. A filtered drain is a real
  acknowledgement.
- The per-participant cursor deliberately does NOT advance on a narrowed read
  (BE-9012a: the returned set is not the contiguous run up to newest, so advancing
  would skip the posts the filter excluded). That refusal is preserved here.
- What was dishonest is the count. ``marked_read`` was ``len(messages)`` — the posts
  RETURNED — so calling the same filtered read twice reported the same non-zero count
  twice while the second call changed nothing at all. A caller had no way to tell an
  acknowledgement from a no-op, which is exactly the signal the completion gate exists
  to make trustworthy. It now counts acks NEWLY written, and a narrowed read carries
  ``cursor_advanced=false`` plus a note naming the unfiltered call that advances it.

Parallel-safe: db_session (TransactionalTestContext); each test owns its setup and its
own generated tenant_key. Edition Scope: Both.
"""

from __future__ import annotations

import random
import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.database import tenant_session_context
from giljo_mcp.models import AgentExecution, AgentJob, Project
from giljo_mcp.models.comm import CommParticipant
from giljo_mcp.models.products import Product
from giljo_mcp.models.tasks import MessageAcknowledgment
from giljo_mcp.repositories.agent_completion_repository import AgentCompletionRepository
from giljo_mcp.services.comm_thread_service import CommThreadService
from giljo_mcp.services.job_completion_service import JobCompletionService
from giljo_mcp.services.taxonomy_ops import ensure_default_types_seeded
from giljo_mcp.tenant import TenantManager


pytestmark = pytest.mark.asyncio

SENDER = "sender-orch"  # a distinct author so a post never self-excludes the recipient


def _comm_service(db_manager, db_session: AsyncSession) -> CommThreadService:
    return CommThreadService(db_manager, TenantManager(), session=db_session)


def _completion_service(db_session: AsyncSession, tenant_key: str) -> JobCompletionService:
    tenant_manager = MagicMock()
    tenant_manager.get_current_tenant.return_value = tenant_key
    return JobCompletionService(db_manager=MagicMock(), tenant_manager=tenant_manager, test_session=db_session)


async def _seed_project_and_orchestrator(
    db_session: AsyncSession, tenant_key: str
) -> tuple[Project, AgentJob, AgentExecution]:
    """Product -> Project -> orchestrator AgentJob + working AgentExecution."""
    with tenant_session_context(db_session, tenant_key):
        await ensure_default_types_seeded(db_session, tenant_key)

    product = Product(
        id=str(uuid.uuid4()),
        tenant_key=tenant_key,
        name="filtered mark_read product",
        description="filtered mark_read cursor honesty",
        product_memory={},
    )
    db_session.add(product)
    await db_session.flush()

    project = Project(
        id=str(uuid.uuid4()),
        tenant_key=tenant_key,
        product_id=product.id,
        name="filtered mark_read project",
        description="filtered mark_read cursor honesty",
        mission="prove a filtered drain reports only what it changed",
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
        mission="orchestrate the filtered mark_read test",
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


async def _thread_with_mixed_posts(
    comm: CommThreadService, tenant_key: str, project_id: str, recipient: str
) -> tuple[str, list[str], list[str]]:
    """A project thread carrying interleaved informational + action-required posts.

    Interleaving matters: the action-required posts are a NON-CONTIGUOUS subset, which
    is the whole reason a narrowed drain cannot advance a high-water cursor.
    Returns ``(thread_id, action_required_ids, informational_ids)``.
    """
    thread = await comm.create_thread(
        subject="coordination", project_id=project_id, creator_id=SENDER, tenant_key=tenant_key
    )
    tid = thread["thread_id"]
    await comm.join_thread(thread_id=tid, participant_id=recipient, tenant_key=tenant_key)
    action_required: list[str] = []
    informational: list[str] = []
    for index in range(4):
        needs_action = index % 2 == 1
        posted = await comm.post_to_thread(
            thread_id=tid,
            content=f"post {index}",
            from_agent=SENDER,
            to_participant=recipient,
            requires_action=needs_action,
            tenant_key=tenant_key,
        )
        (action_required if needs_action else informational).append(posted["message_id"])
    return tid, action_required, informational


async def _acked_ids(db_session: AsyncSession, tenant_key: str, agent_id: str) -> set[str]:
    rows = (
        await db_session.execute(
            select(MessageAcknowledgment.message_id).where(
                MessageAcknowledgment.agent_id == agent_id,
                MessageAcknowledgment.tenant_key == tenant_key,
            )
        )
    ).scalars()
    return set(rows)


# ---------------------------------------------------------------------------
# The defect: a repeated filtered drain re-reported a count it had not earned
# ---------------------------------------------------------------------------


async def test_repeated_filtered_mark_read_reports_zero_the_second_time(db_manager, db_session: AsyncSession):
    tenant = TenantManager.generate_tenant_key()
    project, _job, execution = await _seed_project_and_orchestrator(db_session, tenant)
    comm = _comm_service(db_manager, db_session)
    tid, action_required, _info = await _thread_with_mixed_posts(comm, tenant, project.id, execution.agent_id)

    drain_args = {
        "thread_id": tid,
        "as_participant": execution.agent_id,
        "unread_only": True,
        "mark_read": True,
        "action_required_only": True,
        "tenant_key": tenant,
    }

    first = await comm.get_thread_history(**drain_args)
    assert first["count"] == len(action_required)
    assert first["marked_read"] == len(action_required), "the first filtered drain really does ack"

    second = await comm.get_thread_history(**drain_args)
    # The same posts come back (the cursor is deliberately unmoved) but NOTHING new was
    # acknowledged, so the count must be 0. Reporting len(messages) here was the defect.
    assert second["count"] == len(action_required)
    assert second["marked_read"] == 0


async def test_filtered_mark_read_declares_the_cursor_did_not_move(db_manager, db_session: AsyncSession):
    tenant = TenantManager.generate_tenant_key()
    project, _job, execution = await _seed_project_and_orchestrator(db_session, tenant)
    comm = _comm_service(db_manager, db_session)
    tid, _action_required, _info = await _thread_with_mixed_posts(comm, tenant, project.id, execution.agent_id)

    drained = await comm.get_thread_history(
        thread_id=tid,
        as_participant=execution.agent_id,
        unread_only=True,
        mark_read=True,
        action_required_only=True,
        tenant_key=tenant,
    )

    assert drained["cursor_advanced"] is False
    note = drained["mark_read_note"]
    assert "cursor" in note.lower()
    assert "unread_only" in note, "the note must name the flag that will keep repeating"

    # And the stored watermark really is untouched (BE-9012a's deliberate refusal).
    participant = (
        await db_session.execute(
            select(CommParticipant).where(
                CommParticipant.tenant_key == tenant,
                CommParticipant.thread_id == tid,
                CommParticipant.participant_id == execution.agent_id,
            )
        )
    ).scalar_one()
    assert participant.last_read_at is None
    assert participant.last_read_message_id is None


# ---------------------------------------------------------------------------
# What the filtered drain DOES honour: exact per-message acks + the gate
# ---------------------------------------------------------------------------


async def test_filtered_mark_read_acks_exactly_the_posts_it_returned(db_manager, db_session: AsyncSession):
    tenant = TenantManager.generate_tenant_key()
    project, _job, execution = await _seed_project_and_orchestrator(db_session, tenant)
    comm = _comm_service(db_manager, db_session)
    tid, action_required, informational = await _thread_with_mixed_posts(comm, tenant, project.id, execution.agent_id)

    await comm.get_thread_history(
        thread_id=tid,
        as_participant=execution.agent_id,
        unread_only=True,
        mark_read=True,
        action_required_only=True,
        tenant_key=tenant,
    )

    acked = await _acked_ids(db_session, tenant, execution.agent_id)
    assert acked == set(action_required), "a filtered drain acks its returned set — no more, no less"
    assert not acked & set(informational)


async def test_filtered_mark_read_clears_the_completion_gate(db_manager, db_session: AsyncSession):
    tenant = TenantManager.generate_tenant_key()
    project, job, execution = await _seed_project_and_orchestrator(db_session, tenant)
    comm = _comm_service(db_manager, db_session)
    tid, action_required, _info = await _thread_with_mixed_posts(comm, tenant, project.id, execution.agent_id)

    blocked = await AgentCompletionRepository().get_unread_messages_for_agent(
        db_session, tenant, project.id, execution.agent_id
    )
    assert {m.id for m in blocked} == set(action_required)

    await comm.get_thread_history(
        thread_id=tid,
        as_participant=execution.agent_id,
        unread_only=True,
        mark_read=True,
        action_required_only=True,
        tenant_key=tenant,
    )

    still_blocking = await AgentCompletionRepository().get_unread_messages_for_agent(
        db_session, tenant, project.id, execution.agent_id
    )
    assert still_blocking == [], "the gate keys on acks, and a filtered drain writes real acks"

    result = await _completion_service(db_session, tenant).complete_job(
        job_id=job.job_id, result={"summary": "closed after a filtered drain"}, tenant_key=tenant
    )
    assert result.status == "success"


# ---------------------------------------------------------------------------
# The unfiltered drain still advances the cursor (the behaviour that must not regress)
# ---------------------------------------------------------------------------


async def test_unfiltered_drain_advances_the_cursor_and_reports_it(db_manager, db_session: AsyncSession):
    tenant = TenantManager.generate_tenant_key()
    project, _job, execution = await _seed_project_and_orchestrator(db_session, tenant)
    comm = _comm_service(db_manager, db_session)
    tid, action_required, informational = await _thread_with_mixed_posts(comm, tenant, project.id, execution.agent_id)

    drained = await comm.get_thread_history(
        thread_id=tid,
        as_participant=execution.agent_id,
        unread_only=True,
        mark_read=True,
        tenant_key=tenant,
    )
    assert drained["marked_read"] == len(action_required) + len(informational)
    assert drained["cursor_advanced"] is True
    assert "mark_read_note" not in drained

    # Cursor moved => the next unread read is empty, and reports no new acks.
    again = await comm.get_thread_history(
        thread_id=tid,
        as_participant=execution.agent_id,
        unread_only=True,
        mark_read=True,
        tenant_key=tenant,
    )
    assert again["count"] == 0
    assert again["marked_read"] == 0
    assert again["cursor_advanced"] is False
