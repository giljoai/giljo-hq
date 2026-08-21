# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""System completion_report messages are NOT "unread work".

Root cause: the server auto-sends a ``completion_report`` message to the
orchestrator whenever a deliverable agent completes (see
``agent_job_repository`` auto_message, ``message_type="completion_report"``).
These are SYSTEM notifications, not action items, yet they:
  (a) blocked the orchestrator's own closeout via the unread-messages gate
      (``agent_completion_repository.get_unread_messages_for_agent``), forcing
      a naive agent into COMPLETION_BLOCKED (the "closeout dance");
  (b) showed as phantom unread badges (UI-1) because
      ``agent_operations_repository.get_live_unread_counts_by_agent`` (the
      get_workflow_status count, BE-6200) counted them.

Fix: exclude ``message_type == "completion_report"`` from BOTH queries — one
definition of "counts as unread work".

BE-9012b (D7, §6 rows 1-2) narrowed the GATE query further: it now blocks ONLY on
``requires_action=True`` AND ``auto_generated=False`` posts (real completion_reports
carry ``auto_generated=True``). Informational agent-to-agent messages no longer gate
— that dissolves the closeout dance server-side. The gate is therefore deliberately
NARROWER than the unread BADGE count (which still surfaces every non-completion_report
unread), so the two intentionally diverge for informational posts; they agree again
for action-required posts.

Parallel-safe: db_session (TransactionalTestContext). Each test owns its setup.
Edition Scope: CE.
"""

from __future__ import annotations

import random
import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.models import AgentExecution, AgentJob, Message, Product, Project
from giljo_mcp.models.tasks import MessageRecipient
from giljo_mcp.repositories.agent_completion_repository import AgentCompletionRepository
from giljo_mcp.repositories.agent_operations_repository import AgentOperationsRepository
from giljo_mcp.tenant import TenantManager


pytestmark = pytest.mark.asyncio


async def _seed_orchestrator(session: AsyncSession, tenant_key: str) -> tuple[str, AgentExecution]:
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
        name="completion_report gate project",
        description="closeout gate",
        mission="closeout gate mission",
        status="active",
        tenant_key=tenant_key,
        product_id=_owning_product_proj.id,
        execution_mode="multi_terminal",
        series_number=random.randint(1, 9000),
        created_at=datetime.now(UTC),
    )
    session.add(proj)
    await session.commit()

    job = AgentJob(
        job_id=str(uuid.uuid4()),
        tenant_key=tenant_key,
        project_id=proj.id,
        job_type="orchestrator",
        mission="orchestrator mission",
        status="active",
    )
    session.add(job)
    ex = AgentExecution(
        job_id=job.job_id,
        tenant_key=tenant_key,
        agent_display_name="orchestrator",
        status="working",
        messages_sent_count=0,
        messages_waiting_count=0,
        messages_read_count=0,
    )
    session.add(ex)
    await session.commit()
    await session.refresh(ex)
    return proj.id, ex


async def _add_pending(
    session: AsyncSession,
    tenant_key: str,
    project_id: str,
    to_agent: AgentExecution,
    message_type: str,
    content: str,
    requires_action: bool = False,
) -> None:
    msg = Message(
        tenant_key=tenant_key,
        project_id=project_id,
        content=content,
        message_type=message_type,
        status="pending",
        requires_action=requires_action,
    )
    session.add(msg)
    await session.flush()
    session.add(MessageRecipient(message_id=msg.id, agent_id=to_agent.agent_id, tenant_key=tenant_key))
    await session.commit()


# ---------------------------------------------------------------------------
# (a) Closeout gate: ONLY completion_reports -> not blocked
# ---------------------------------------------------------------------------


async def test_gate_ignores_only_completion_reports(db_session: AsyncSession) -> None:
    tenant = TenantManager.generate_tenant_key()
    pid, orchestrator = await _seed_orchestrator(db_session, tenant)
    for i in range(3):
        await _add_pending(db_session, tenant, pid, orchestrator, "completion_report", f"agent {i} done")

    repo = AgentCompletionRepository()
    unread = await repo.get_unread_messages_for_agent(db_session, tenant, pid, orchestrator.agent_id)
    assert unread == [], "completion_report notifications must not count as unread work for the closeout gate"


# ---------------------------------------------------------------------------
# (b) Closeout gate: genuine action message STILL blocks
# ---------------------------------------------------------------------------


async def test_gate_still_blocks_on_genuine_message(db_session: AsyncSession) -> None:
    tenant = TenantManager.generate_tenant_key()
    pid, orchestrator = await _seed_orchestrator(db_session, tenant)
    await _add_pending(db_session, tenant, pid, orchestrator, "completion_report", "agent done")
    # BE-9012b (D7): an informational directive (requires_action=False) no longer gates.
    await _add_pending(db_session, tenant, pid, orchestrator, "directive", "FYI sharing results")
    # A genuine ACTION-REQUIRED directive still blocks closeout.
    await _add_pending(
        db_session, tenant, pid, orchestrator, "directive", "please review the failing test", requires_action=True
    )

    repo = AgentCompletionRepository()
    unread = await repo.get_unread_messages_for_agent(db_session, tenant, pid, orchestrator.agent_id)
    assert len(unread) == 1, "only the action-required agent-to-agent message must block closeout (D7)"
    assert unread[0].message_type == "directive"
    assert unread[0].requires_action is True


# ---------------------------------------------------------------------------
# (c) get_workflow_status count excludes completion_reports, includes genuine
# ---------------------------------------------------------------------------


async def test_live_unread_count_excludes_completion_reports(db_session: AsyncSession) -> None:
    tenant = TenantManager.generate_tenant_key()
    pid, orchestrator = await _seed_orchestrator(db_session, tenant)
    for i in range(2):
        await _add_pending(db_session, tenant, pid, orchestrator, "completion_report", f"agent {i} done")

    ops = AgentOperationsRepository()
    counts = await ops.get_live_unread_counts_by_agent(db_session, tenant, pid, [orchestrator.agent_id])
    assert counts.get(orchestrator.agent_id, 0) == 0, "phantom unread badge: completion_reports must not be counted"

    await _add_pending(db_session, tenant, pid, orchestrator, "directive", "action please")
    counts = await ops.get_live_unread_counts_by_agent(db_session, tenant, pid, [orchestrator.agent_id])
    assert counts.get(orchestrator.agent_id, 0) == 1, "genuine unread message must still be counted"


# BE-9012d: (d) test_parity_for_genuine_messages (the gate/count vs.
# MessageService.receive_messages 3-way parity) and (e)
# test_list_messages_view_excludes_completion_reports (MessageService.list_messages,
# the retired /api/v1/messages/ REST view's backing method — that endpoint had zero
# live frontend consumers, confirmed dead) were removed with the bus hard-removal.
# The gate (a)/(b) and live-count (c) contracts above are unaffected — they read
# AgentCompletionRepository / AgentOperationsRepository directly, independent of
# MessageService.
