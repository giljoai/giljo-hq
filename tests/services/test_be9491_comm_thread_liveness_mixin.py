# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from giljo_mcp.database import tenant_session_context
from giljo_mcp.models import Product, Project
from giljo_mcp.models.agent_identity import AgentExecution, AgentJob
from giljo_mcp.models.tasks import Message, MessageRecipient
from giljo_mcp.services.comm_thread_service import CommThreadService
from giljo_mcp.services.taxonomy_ops import ensure_default_types_seeded
from giljo_mcp.tenant import TenantManager


pytestmark = pytest.mark.asyncio


def _tk(suffix: str) -> str:
    return f"tk_be9491_{suffix}_{uuid.uuid4().hex[:8]}"


def _service(db_manager, db_session) -> CommThreadService:
    return CommThreadService(db_manager, TenantManager(), session=db_session)


async def _seed(db_session, tenant: str) -> None:
    with tenant_session_context(db_session, tenant):
        await ensure_default_types_seeded(db_session, tenant)


async def _seed_project_with_agents(db_session, tenant: str, agents: list[tuple[str, str]]) -> str:
    with tenant_session_context(db_session, tenant):
        owning_product = Product(
            id=str(uuid.uuid4()),
            tenant_key=tenant,
            name=f"Owning Product {uuid.uuid4().hex[:6]}",
            description="seeded",
            is_active=False,
        )
        db_session.add(owning_product)
        project = Project(
            id=str(uuid.uuid4()),
            name=f"BE-9491 {uuid.uuid4().hex[:6]}",
            description="finished-agent broadcast filter test project",
            mission="exercise the liveness filter",
            status="active",
            tenant_key=tenant,
            product_id=owning_product.id,
            series_number=1,
            execution_mode="claude_code_cli",
            created_at=datetime.now(UTC),
            implementation_launched_at=datetime.now(UTC),
        )
        db_session.add(project)
        await db_session.flush()

        for agent_id, status in agents:
            job = AgentJob(
                tenant_key=tenant,
                project_id=project.id,
                job_type="implementer",
                mission="do work",
                status="active",
            )
            db_session.add(job)
            await db_session.flush()
            db_session.add(
                AgentExecution(
                    agent_id=agent_id,
                    job_id=job.job_id,
                    tenant_key=tenant,
                    agent_display_name=f"display-{agent_id}",
                    status=status,
                )
            )
        await db_session.flush()
    return project.id


async def _recipient_ids(db_session, tenant: str, message_id: str) -> set[str]:
    with tenant_session_context(db_session, tenant):
        rows = (
            (
                await db_session.execute(
                    select(MessageRecipient.agent_id).where(
                        MessageRecipient.tenant_key == tenant,
                        MessageRecipient.message_id == message_id,
                    )
                )
            )
            .scalars()
            .all()
        )
    return set(rows)


async def _message_exists(db_session, tenant: str, message_id: str) -> bool:
    with tenant_session_context(db_session, tenant):
        row = (
            await db_session.execute(select(Message.id).where(Message.tenant_key == tenant, Message.id == message_id))
        ).scalar_one_or_none()
    return row is not None


async def test_broadcast_skips_terminal_agent_kept_live_agent_and_user(db_manager, db_session):
    tenant = _tk("mix")
    await _seed(db_session, tenant)
    project_id = await _seed_project_with_agents(
        db_session, tenant, [("agent-live", "working"), ("agent-done", "complete")]
    )
    svc = _service(db_manager, db_session)

    thread = await svc.create_thread(
        subject="directive", creator_id="agent-orch", project_id=project_id, tenant_key=tenant
    )
    tid = thread["thread_id"]
    await svc.join_thread(thread_id=tid, participant_id="agent-done", tenant_key=tenant)
    await svc.join_thread(thread_id=tid, participant_id="human-operator", participant_type="user", tenant_key=tenant)

    result = await svc.post_to_thread(
        thread_id=tid, content="status update", from_agent="agent-orch", tenant_key=tenant
    )

    assert "agent-live" in result["recipients"]
    assert "human-operator" in result["recipients"]
    assert "agent-done" not in result["recipients"]
    assert result["skipped_recipients"]
    assert any(s["agent_id"] == "agent-done" for s in result["skipped_recipient_details"])
    assert "agent-done" not in await _recipient_ids(db_session, tenant, result["message_id"])


async def test_broadcast_all_terminal_candidates_gives_loud_zero_delivered_notice(db_manager, db_session):
    tenant = _tk("allterminal")
    await _seed(db_session, tenant)
    project_id = await _seed_project_with_agents(db_session, tenant, [("agent-done", "complete")])
    svc = _service(db_manager, db_session)

    thread = await svc.create_thread(
        subject="directive", creator_id="agent-orch", project_id=project_id, tenant_key=tenant
    )
    tid = thread["thread_id"]
    await svc.join_thread(thread_id=tid, participant_id="agent-done", tenant_key=tenant)

    result = await svc.post_to_thread(
        thread_id=tid, content="anyone there?", from_agent="agent-orch", tenant_key=tenant
    )

    assert result["recipients"] == []
    assert "0 of" in result["skipped_recipients"]
    assert "all were finished" in result["skipped_recipients"]
    assert await _message_exists(db_session, tenant, result["message_id"])


async def test_direct_non_action_required_post_to_terminal_agent_writes_message_no_recipient_row(
    db_manager, db_session
):
    tenant = _tk("directskip")
    await _seed(db_session, tenant)
    project_id = await _seed_project_with_agents(db_session, tenant, [("agent-done", "closed")])
    svc = _service(db_manager, db_session)

    thread = await svc.create_thread(subject="fyi", creator_id="agent-orch", project_id=project_id, tenant_key=tenant)
    tid = thread["thread_id"]

    result = await svc.post_to_thread(
        thread_id=tid,
        content="one more thing",
        from_agent="agent-orch",
        to_participant="agent-done",
        requires_action=False,
        tenant_key=tenant,
    )

    assert result["recipients"] == []
    assert result["skipped_recipients"]
    assert await _message_exists(db_session, tenant, result["message_id"])
    assert await _recipient_ids(db_session, tenant, result["message_id"]) == set()


async def test_direct_action_required_post_to_complete_agent_still_delivers(db_manager, db_session):
    tenant = _tk("stillreach")
    await _seed(db_session, tenant)
    project_id = await _seed_project_with_agents(db_session, tenant, [("agent-done", "complete")])
    svc = _service(db_manager, db_session)

    thread = await svc.create_thread(
        subject="rework", creator_id="agent-orch", project_id=project_id, tenant_key=tenant
    )
    tid = thread["thread_id"]

    result = await svc.post_to_thread(
        thread_id=tid,
        content="REWORK_REQUIRED: please revisit",
        from_agent="agent-orch",
        to_participant="agent-done",
        requires_action=True,
        tenant_key=tenant,
    )

    assert result["recipients"] == ["agent-done"]
    assert "skipped_recipients" not in result
    assert "agent-done" in await _recipient_ids(db_session, tenant, result["message_id"])


async def test_direct_non_action_required_post_to_never_tracked_id_is_not_dropped(db_manager, db_session):
    tenant = _tk("neverdrop")
    await _seed(db_session, tenant)
    svc = _service(db_manager, db_session)

    thread = await svc.create_thread(subject="standalone", creator_id="agent-orch", tenant_key=tenant)
    tid = thread["thread_id"]
    never_tracked_id = str(uuid.uuid4())

    result = await svc.post_to_thread(
        thread_id=tid,
        content="fyi, no action needed",
        from_agent="agent-orch",
        to_participant=never_tracked_id,
        requires_action=False,
        tenant_key=tenant,
    )

    assert result["recipients"] == [never_tracked_id]
    assert "skipped_recipients" not in result
