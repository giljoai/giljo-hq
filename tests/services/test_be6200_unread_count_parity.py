# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import random
import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.models import AgentExecution, AgentJob, Message, Product, Project
from giljo_mcp.models.comm import CommThread
from giljo_mcp.models.tasks import MessageAcknowledgment, MessageRecipient
from giljo_mcp.services.workflow_status_service import WorkflowStatusService
from giljo_mcp.tenant import TenantManager


pytestmark = pytest.mark.asyncio


def _workflow_svc(session: AsyncSession) -> WorkflowStatusService:
    return WorkflowStatusService(db_manager=None, tenant_manager=TenantManager(), test_session=session)


async def _ack_messages_for(session: AsyncSession, tenant_key: str, agent_id: str, n: int) -> None:
    message_ids = (
        (
            await session.execute(
                select(Message.id)
                .join(MessageRecipient, Message.id == MessageRecipient.message_id)
                .where(MessageRecipient.tenant_key == tenant_key, MessageRecipient.agent_id == agent_id)
                .order_by(Message.created_at.asc())
                .limit(n)
            )
        )
        .scalars()
        .all()
    )
    for mid in message_ids:
        session.add(MessageAcknowledgment(message_id=mid, agent_id=agent_id, tenant_key=tenant_key))
    if message_ids:
        await session.commit()


async def _seed_project_with_two_agents(
    session: AsyncSession, tenant_key: str
) -> tuple[str, AgentExecution, AgentExecution]:
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
        name="BE-6200 parity project",
        description="unread parity",
        mission="unread parity mission",
        status="active",
        tenant_key=tenant_key,
        product_id=_owning_product_proj.id,
        execution_mode="multi_terminal",
        series_number=random.randint(1, 9000),
        created_at=datetime.now(UTC),
    )
    session.add(proj)
    await session.commit()

    execs = []
    for display_name in ("orchestrator", "analyzer"):
        job = AgentJob(
            job_id=str(uuid.uuid4()),
            tenant_key=tenant_key,
            project_id=proj.id,
            job_type=display_name,
            mission=f"mission {display_name}",
            status="active",
        )
        session.add(job)
        ex = AgentExecution(
            job_id=job.job_id,
            tenant_key=tenant_key,
            agent_display_name=display_name,
            status="working",
            messages_sent_count=0,
            messages_waiting_count=0,
            messages_read_count=0,
        )
        session.add(ex)
        execs.append(ex)
    await session.commit()
    for ex in execs:
        await session.refresh(ex)
    return proj.id, execs[0], execs[1]


async def _send_pending(
    session: AsyncSession,
    tenant_key: str,
    project_id: str,
    from_agent: AgentExecution,
    to_agent: AgentExecution,
    n: int,
) -> None:
    for i in range(n):
        msg = Message(
            tenant_key=tenant_key,
            project_id=project_id,
            content=f"directive {i}",
            message_type="directive",
            status="pending",
            from_agent_id=str(from_agent.agent_id),
        )
        session.add(msg)
        await session.flush()
        session.add(MessageRecipient(message_id=msg.id, agent_id=to_agent.agent_id, tenant_key=tenant_key))
    await session.commit()


def _unread_for(workflow_status, agent_id: str) -> int:
    for detail in workflow_status.agents:
        if detail.agent_id == agent_id:
            return detail.unread_messages
    raise AssertionError(f"agent {agent_id} not present in workflow status")


async def test_unread_count_parity_with_drifted_denormalized_counter(db_session: AsyncSession) -> None:
    tenant = TenantManager.generate_tenant_key()
    pid, orchestrator, analyzer = await _seed_project_with_two_agents(db_session, tenant)
    await _send_pending(db_session, tenant, pid, from_agent=orchestrator, to_agent=analyzer, n=3)

    analyzer.messages_waiting_count = 99
    await db_session.commit()

    ws = await _workflow_svc(db_session).get_workflow_status(pid, tenant)
    assert _unread_for(ws, analyzer.agent_id) == 3, "get_workflow_status must report the live pending count, not 99"


async def test_unread_count_parity_drops_after_acknowledge(db_session: AsyncSession) -> None:
    tenant = TenantManager.generate_tenant_key()
    pid, orchestrator, analyzer = await _seed_project_with_two_agents(db_session, tenant)
    await _send_pending(db_session, tenant, pid, from_agent=orchestrator, to_agent=analyzer, n=4)

    ws_before = await _workflow_svc(db_session).get_workflow_status(pid, tenant)
    assert _unread_for(ws_before, analyzer.agent_id) == 4

    await _ack_messages_for(db_session, tenant, analyzer.agent_id, 2)

    ws_after = await _workflow_svc(db_session).get_workflow_status(pid, tenant)
    remaining_ws = _unread_for(ws_after, analyzer.agent_id)
    assert remaining_ws == 2, f"get_workflow_status remaining should be 2, got {remaining_ws}"


def _detail_for(workflow_status, agent_id: str):
    for detail in workflow_status.agents:
        if detail.agent_id == agent_id:
            return detail
    raise AssertionError(f"agent {agent_id} not present in workflow status")


async def test_per_thread_unread_breakdown_sums_to_project_wide_total(db_session: AsyncSession) -> None:
    tenant = TenantManager.generate_tenant_key()
    pid, orchestrator, analyzer = await _seed_project_with_two_agents(db_session, tenant)

    thread_a = str(uuid.uuid4())
    thread_b = str(uuid.uuid4())
    for serial, thread_id in enumerate((thread_a, thread_b), start=1):
        db_session.add(CommThread(id=thread_id, tenant_key=tenant, serial=serial, project_id=pid))
    await db_session.commit()
    for thread_id, n in ((thread_a, 2), (thread_b, 3)):
        for i in range(n):
            msg = Message(
                tenant_key=tenant,
                project_id=pid,
                thread_id=thread_id,
                content=f"thread {thread_id} msg {i}",
                message_type="direct",
                status="pending",
                from_agent_id=str(orchestrator.agent_id),
            )
            db_session.add(msg)
            await db_session.flush()
            db_session.add(MessageRecipient(message_id=msg.id, agent_id=analyzer.agent_id, tenant_key=tenant))
    await _send_pending(db_session, tenant, pid, from_agent=orchestrator, to_agent=analyzer, n=1)
    await db_session.commit()

    ws = await _workflow_svc(db_session).get_workflow_status(pid, tenant)
    detail = _detail_for(ws, analyzer.agent_id)

    total_from_breakdown = sum(t.unread_count for t in detail.unread_by_thread)
    assert total_from_breakdown == detail.unread_messages, (
        f"sum(per-thread)={total_from_breakdown} must equal the project-wide total={detail.unread_messages}"
    )
    assert detail.unread_messages == 2 + 3 + 1

    by_thread = {t.thread_id: t.unread_count for t in detail.unread_by_thread}
    assert by_thread[thread_a] == 2
    assert by_thread[thread_b] == 3
    assert by_thread[""] == 1, "the no-thread legacy message must be grouped under the '' key, not dropped"


async def test_action_required_unread_is_distinct_subset_of_badge_total(db_session: AsyncSession) -> None:
    tenant = TenantManager.generate_tenant_key()
    pid, orchestrator, analyzer = await _seed_project_with_two_agents(db_session, tenant)

    await _send_pending(db_session, tenant, pid, from_agent=orchestrator, to_agent=analyzer, n=3)
    for i in range(2):
        msg = Message(
            tenant_key=tenant,
            project_id=pid,
            content=f"action required {i}",
            message_type="direct",
            status="pending",
            from_agent_id=str(orchestrator.agent_id),
            requires_action=True,
        )
        db_session.add(msg)
        await db_session.flush()
        db_session.add(MessageRecipient(message_id=msg.id, agent_id=analyzer.agent_id, tenant_key=tenant))
    await db_session.commit()

    ws = await _workflow_svc(db_session).get_workflow_status(pid, tenant)
    detail = _detail_for(ws, analyzer.agent_id)

    assert detail.unread_messages == 5, "badge total must include both informational and action-required posts"
    assert detail.action_required_unread == 2, (
        "action_required_unread must count ONLY the requires_action, non-auto_generated subset"
    )
