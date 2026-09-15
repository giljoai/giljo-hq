# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


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




async def test_gate_ignores_only_completion_reports(db_session: AsyncSession) -> None:
    tenant = TenantManager.generate_tenant_key()
    pid, orchestrator = await _seed_orchestrator(db_session, tenant)
    for i in range(3):
        await _add_pending(db_session, tenant, pid, orchestrator, "completion_report", f"agent {i} done")

    repo = AgentCompletionRepository()
    unread = await repo.get_unread_messages_for_agent(db_session, tenant, pid, orchestrator.agent_id)
    assert unread == [], "completion_report notifications must not count as unread work for the closeout gate"




async def test_gate_still_blocks_on_genuine_message(db_session: AsyncSession) -> None:
    tenant = TenantManager.generate_tenant_key()
    pid, orchestrator = await _seed_orchestrator(db_session, tenant)
    await _add_pending(db_session, tenant, pid, orchestrator, "completion_report", "agent done")
    await _add_pending(db_session, tenant, pid, orchestrator, "directive", "FYI sharing results")
    await _add_pending(
        db_session, tenant, pid, orchestrator, "directive", "please review the failing test", requires_action=True
    )

    repo = AgentCompletionRepository()
    unread = await repo.get_unread_messages_for_agent(db_session, tenant, pid, orchestrator.agent_id)
    assert len(unread) == 1, "only the action-required agent-to-agent message must block closeout (D7)"
    assert unread[0].message_type == "directive"
    assert unread[0].requires_action is True




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


