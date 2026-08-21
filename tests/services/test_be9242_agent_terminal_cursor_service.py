# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-9242 -- phantom/lingering "unread messages" accounting.

Root cause #2 (the load-bearing one): no lifecycle hook ever resolved a
closed/decommissioned agent's outstanding message cursors. A dead agent's
unread badge lingered forever (nobody can reactivate it to drain the
cursor), and -- far worse -- a genuinely action-required post addressed to
that agent had no path forward at all: silently invisible work.

TWO-SIDED regression test (DoD, deliverable #1):
  (a) a closed agent's dead unread cursor CLEARS on job close (informational
      posts are auto-acknowledged).
  (b) a genuine action-required post to a since-closed agent SURFACES to the
      live orchestrator (forwarded, never silently swallowed).

Also covers the hard-constraint edge case: with NO live orchestrator to
forward to, the action-required cursor is left un-acked (fails open,
visibly) rather than being dropped.

Failing-layer: OrchestrationAgentStateService.close_job (the real job-close
service call, not a mock) -- this is where the BE-9242 hook was wired in.

Parallel-safe: db_session (TransactionalTestContext). No module-level
mutable state; each test owns its setup. Edition Scope: Both (platform
internals, not CE/SaaS-gated).
"""

from __future__ import annotations

import random
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.models import AgentExecution, AgentJob, Message, Product, Project
from giljo_mcp.models.tasks import MessageAcknowledgment, MessageRecipient
from giljo_mcp.services.orchestration_agent_state_service import (
    OrchestrationAgentStateService,
)
from giljo_mcp.tenant import TenantManager


pytestmark = pytest.mark.asyncio


def _state_service(session: AsyncSession) -> OrchestrationAgentStateService:
    return OrchestrationAgentStateService(db_manager=None, tenant_manager=TenantManager(), test_session=session)


async def _seed_project(session: AsyncSession, tenant_key: str) -> str:
    # BE-9437: a project belongs to a product. Its own, so an active
    # seed cannot collide under idx_project_single_active_per_product.
    _owning_product_proj = Product(
        id=str(uuid.uuid4()),
        tenant_key=tenant_key,
        name=f"Owning Product {uuid.uuid4().hex[:6]}",
        description="seeded",
        is_active=False,
    )
    session.add(_owning_product_proj)
    proj = Project(
        id=str(uuid.uuid4()),
        name="BE-9242 dead cursor project",
        description="dead cursor resolution",
        mission="dead cursor resolution mission",
        status="active",
        tenant_key=tenant_key,
        product_id=_owning_product_proj.id,
        execution_mode="multi_terminal",
        series_number=random.randint(1, 9000),
        created_at=datetime.now(UTC),
    )
    session.add(proj)
    await session.commit()
    return proj.id


async def _seed_execution(
    session: AsyncSession,
    tenant_key: str,
    project_id: str,
    *,
    display_name: str,
    status: str,
    started_at: datetime | None = None,
) -> AgentExecution:
    job = AgentJob(
        job_id=str(uuid.uuid4()),
        tenant_key=tenant_key,
        project_id=project_id,
        job_type=display_name,
        mission=f"mission {display_name}",
        status="active",
    )
    session.add(job)
    ex = AgentExecution(
        job_id=job.job_id,
        tenant_key=tenant_key,
        agent_display_name=display_name,
        status=status,
        started_at=started_at,
        messages_sent_count=0,
        messages_waiting_count=0,
        messages_read_count=0,
    )
    session.add(ex)
    await session.commit()
    await session.refresh(ex)
    return ex


async def _post(
    session: AsyncSession,
    tenant_key: str,
    project_id: str,
    *,
    from_agent: AgentExecution,
    to_agent: AgentExecution,
    content: str,
    requires_action: bool,
    auto_generated: bool = False,
) -> Message:
    msg = Message(
        tenant_key=tenant_key,
        project_id=project_id,
        content=content,
        message_type="direct",
        status="pending",
        from_agent_id=str(from_agent.agent_id),
        from_display_name=from_agent.agent_display_name,
        requires_action=requires_action,
        auto_generated=auto_generated,
    )
    session.add(msg)
    await session.flush()
    session.add(MessageRecipient(message_id=msg.id, agent_id=to_agent.agent_id, tenant_key=tenant_key))
    await session.commit()
    return msg


async def _is_acked(session: AsyncSession, tenant_key: str, message_id: str, agent_id: str) -> bool:
    result = await session.execute(
        select(MessageAcknowledgment.id).where(
            MessageAcknowledgment.tenant_key == tenant_key,
            MessageAcknowledgment.message_id == message_id,
            MessageAcknowledgment.agent_id == agent_id,
        )
    )
    return result.scalar_one_or_none() is not None


async def test_close_job_clears_informational_cursor_and_forwards_action_required(
    db_session: AsyncSession,
) -> None:
    """Two-sided proof for deliverable #1.

    Seeds a LIVE orchestrator + an implementer about to be closed, with one
    informational unread post and one action-required unread post addressed
    to the implementer. After close_job:
      (a) the informational post is acknowledged for the dead implementer
          (its dead cursor is cleared).
      (b) the action-required post is ALSO acknowledged for the dead
          implementer (its cursor is resolved) -- but ONLY because a NEW
          forwarded Message now addresses the live orchestrator, carrying
          the original content and requiring action from THEM. Work is
          never silently dropped.
    """
    tenant = TenantManager.generate_tenant_key()
    project_id = await _seed_project(db_session, tenant)
    orchestrator = await _seed_execution(db_session, tenant, project_id, display_name="orchestrator", status="working")
    implementer = await _seed_execution(db_session, tenant, project_id, display_name="implementer", status="complete")

    informational = await _post(
        db_session,
        tenant,
        project_id,
        from_agent=orchestrator,
        to_agent=implementer,
        content="FYI: nothing to do here.",
        requires_action=False,
    )
    action_required = await _post(
        db_session,
        tenant,
        project_id,
        from_agent=orchestrator,
        to_agent=implementer,
        content="Please also update the changelog before you go.",
        requires_action=True,
    )

    # Sanity: before close, neither is acked for the implementer.
    assert not await _is_acked(db_session, tenant, informational.id, implementer.agent_id)
    assert not await _is_acked(db_session, tenant, action_required.id, implementer.agent_id)

    result = await _state_service(db_session).close_job(job_id=implementer.job_id, tenant_key=tenant)
    assert result["new_status"] == "closed"

    # (a) informational cursor cleared for the now-closed implementer.
    assert await _is_acked(db_session, tenant, informational.id, implementer.agent_id), (
        "an informational unread post must be auto-acked when its recipient closes"
    )

    # (b) action-required cursor also cleared for the dead implementer...
    assert await _is_acked(db_session, tenant, action_required.id, implementer.agent_id), (
        "the dead agent's action-required cursor must resolve once the work has a new live owner"
    )

    # ...but ONLY because it was forwarded to the live orchestrator: a NEW
    # message now addresses the orchestrator, still requires_action, carrying
    # the original content, and is NOT yet acked (i.e. it genuinely gates the
    # orchestrator's own future complete_job).
    forwarded_stmt = (
        select(Message)
        .join(MessageRecipient, Message.id == MessageRecipient.message_id)
        .where(
            Message.tenant_key == tenant,
            Message.project_id == project_id,
            MessageRecipient.agent_id == orchestrator.agent_id,
            Message.requires_action.is_(True),
        )
    )
    forwarded_messages = (await db_session.execute(forwarded_stmt)).scalars().all()
    assert len(forwarded_messages) == 1, "exactly one forwarded message must reach the live orchestrator"
    forwarded = forwarded_messages[0]
    assert "Please also update the changelog before you go." in forwarded.content
    assert implementer.agent_display_name in forwarded.content
    assert forwarded.auto_generated is False, (
        "the forward must NOT be auto_generated or it would be silently exempted "
        "from the orchestrator's own closeout gate"
    )
    assert not await _is_acked(db_session, tenant, forwarded.id, orchestrator.agent_id), (
        "the forwarded message must still be live (unacked) work for the orchestrator"
    )


async def test_close_job_with_no_live_orchestrator_leaves_action_required_cursor_unresolved(
    db_session: AsyncSession,
) -> None:
    """Hard-constraint edge case: if there is no live orchestrator to forward
    to, the action-required post must NOT be silently dropped. It stays
    un-acked (fails open, visibly) rather than being acked into oblivion.
    """
    tenant = TenantManager.generate_tenant_key()
    project_id = await _seed_project(db_session, tenant)
    # No orchestrator execution seeded at all -- find_active_orchestrator_in_project
    # will find nothing live to forward to.
    implementer = await _seed_execution(db_session, tenant, project_id, display_name="implementer", status="complete")
    # A from_agent is required by the Message model's FK-free from_agent_id column;
    # reuse the implementer as its own "sender" for this edge-case fixture.
    action_required = await _post(
        db_session,
        tenant,
        project_id,
        from_agent=implementer,
        to_agent=implementer,
        content="Orphaned action item -- no orchestrator alive to catch it.",
        requires_action=True,
    )

    await _state_service(db_session).close_job(job_id=implementer.job_id, tenant_key=tenant)

    assert not await _is_acked(db_session, tenant, action_required.id, implementer.agent_id), (
        "with no live orchestrator to forward to, the action-required cursor must be "
        "left unresolved, never silently acked away"
    )


async def test_close_job_no_orchestrator_warning_sanitizes_agent_supplied_agent_id(
    db_session: AsyncSession,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """TSK-9369 -- CodeQL py/log-injection (public alert 349) hardening.

    The "no live orchestrator to forward to" warning
    (agent_terminal_cursor_service.py) interpolates ``agent_id``, which can
    originate from agent-supplied input. A value carrying a newline must not
    be able to forge an extra line in the operator log. Drives the exact
    no-live-orchestrator path (see the unresolved-cursor test above) with a
    malicious agent_id and asserts the emitted record renders as ONE line
    with the newline neutralized.
    """
    tenant = TenantManager.generate_tenant_key()
    project_id = await _seed_project(db_session, tenant)
    implementer = await _seed_execution(db_session, tenant, project_id, display_name="implementer", status="complete")
    malicious_agent_id = "evil\nFORGED LINE"
    implementer.agent_id = malicious_agent_id
    await db_session.commit()
    await db_session.refresh(implementer)

    await _post(
        db_session,
        tenant,
        project_id,
        from_agent=implementer,
        to_agent=implementer,
        content="Orphaned action item -- no orchestrator alive to catch it.",
        requires_action=True,
    )

    with caplog.at_level("WARNING", logger="giljo_mcp.services.agent_terminal_cursor_service"):
        await _state_service(db_session).close_job(job_id=implementer.job_id, tenant_key=tenant)

    rendered = [r.getMessage() for r in caplog.records if "no live orchestrator to forward" in r.getMessage()]
    assert len(rendered) == 1, "expected exactly one no-live-orchestrator warning"
    message = rendered[0]

    # The rendered message must be a single line -- no forged extra line --
    # and must not contain the raw, unsanitized newline-bearing agent_id.
    assert "\n" not in message
    assert malicious_agent_id not in message
    assert "evilFORGED LINE" in message


async def test_close_job_forwards_to_successor_when_two_orchestrators_active_during_handover(
    db_session: AsyncSession,
) -> None:
    """Regression for the FIX-1 crash: an orchestrator HANDOVER window leaves
    TWO orchestrator executions active at once (predecessor + successor, both
    waiting/working/blocked -- job_lifecycle_service allows the successor to
    spawn while the predecessor is still live). BE-9242 wired
    find_active_orchestrator_in_project onto the close_job forward path, so an
    UNRELATED agent's close_job (with one outstanding action-required post)
    resolves the live orchestrator during that window.

    Before FIX 1 the resolver ran scalar_one_or_none() with no limit(1) and
    raised sqlalchemy.exc.MultipleResultsFound -- crashing the innocent
    close_job. After FIX 1 it must NOT raise, and must forward to the
    most-recently-STARTED orchestrator (the successor -- the correct live
    forward target during a handover).
    """
    tenant = TenantManager.generate_tenant_key()
    project_id = await _seed_project(db_session, tenant)

    now = datetime.now(UTC)
    # Predecessor started earlier; successor started later. Both still active
    # (the handover window) -- exactly what makes the old query match two rows.
    predecessor = await _seed_execution(
        db_session,
        tenant,
        project_id,
        display_name="orchestrator",
        status="blocked",
        started_at=now - timedelta(hours=2),
    )
    successor = await _seed_execution(
        db_session,
        tenant,
        project_id,
        display_name="orchestrator",
        status="working",
        started_at=now - timedelta(minutes=5),
    )
    implementer = await _seed_execution(db_session, tenant, project_id, display_name="implementer", status="complete")

    action_required = await _post(
        db_session,
        tenant,
        project_id,
        from_agent=predecessor,
        to_agent=implementer,
        content="Please hand the deploy checklist to whoever is driving now.",
        requires_action=True,
    )

    # Must NOT raise MultipleResultsFound (the pre-FIX-1 crash).
    result = await _state_service(db_session).close_job(job_id=implementer.job_id, tenant_key=tenant)
    assert result["new_status"] == "closed"

    # The dead implementer's action-required cursor is resolved (forwarded, then acked).
    assert await _is_acked(db_session, tenant, action_required.id, implementer.agent_id)

    # Exactly one forwarded message, and it addresses the SUCCESSOR (most
    # recently started), never the predecessor.
    forwarded_stmt = (
        select(Message)
        .join(MessageRecipient, Message.id == MessageRecipient.message_id)
        .where(
            Message.tenant_key == tenant,
            Message.project_id == project_id,
            Message.requires_action.is_(True),
            MessageRecipient.agent_id.in_([successor.agent_id, predecessor.agent_id]),
        )
    )
    forwarded = (await db_session.execute(forwarded_stmt)).scalars().all()
    assert len(forwarded) == 1, "exactly one forwarded message must reach a single live orchestrator"
    forwarded_recipient = (
        (
            await db_session.execute(
                select(MessageRecipient.agent_id).where(MessageRecipient.message_id == forwarded[0].id)
            )
        )
        .scalars()
        .all()
    )
    assert successor.agent_id in forwarded_recipient, (
        "the forward must target the most-recently-started (successor) orchestrator"
    )
    assert predecessor.agent_id not in forwarded_recipient
    assert "Please hand the deploy checklist to whoever is driving now." in forwarded[0].content
