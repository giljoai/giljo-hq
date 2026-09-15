# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select

from giljo_mcp.database import tenant_session_context
from giljo_mcp.models import Product, Project
from giljo_mcp.models.agent_identity import AgentExecution, AgentJob
from giljo_mcp.models.comm import CommParticipant
from giljo_mcp.models.tasks import MessageRecipient
from giljo_mcp.services.comm_thread_service import CommThreadService
from giljo_mcp.services.taxonomy_ops import ensure_default_types_seeded
from giljo_mcp.tenant import TenantManager


pytestmark = pytest.mark.asyncio


def _tk(suffix: str) -> str:
    return f"tk_be6141_{suffix}_{uuid.uuid4().hex[:8]}"


def _service(db_manager, db_session) -> CommThreadService:
    return CommThreadService(db_manager, TenantManager(), session=db_session)


async def _seed(db_session, tenant: str) -> None:
    with tenant_session_context(db_session, tenant):
        await ensure_default_types_seeded(db_session, tenant)


async def _seed_project_with_agents(db_session, tenant: str, agents: list[tuple[str, str]]) -> str:
    with tenant_session_context(db_session, tenant):
        _owning_product_project = Product(
            id=str(uuid.uuid4()),
            tenant_key=tenant,
            name=f"Owning Product {uuid.uuid4().hex[:6]}",
            description="seeded",
            is_active=True,
        )
        db_session.add(_owning_product_project)
        project = Project(
            id=str(uuid.uuid4()),
            name=f"BE-6141 {uuid.uuid4().hex[:6]}",
            description="auto-enroll test project",
            mission="exercise broadcast auto-enroll",
            status="active",
            tenant_key=tenant,
            product_id=_owning_product_project.id,
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


async def _participant_ids(db_session, tenant: str, thread_id: str) -> set[str]:
    with tenant_session_context(db_session, tenant):
        rows = (
            (
                await db_session.execute(
                    select(CommParticipant.participant_id).where(
                        CommParticipant.tenant_key == tenant,
                        CommParticipant.thread_id == thread_id,
                    )
                )
            )
            .scalars()
            .all()
        )
    return set(rows)


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


async def test_broadcast_auto_enrolls_unjoined_project_agent(db_manager, db_session):
    tenant = _tk("enroll")
    await _seed(db_session, tenant)
    project_id = await _seed_project_with_agents(db_session, tenant, [("agent-worker", "working")])
    svc = _service(db_manager, db_session)

    thread = await svc.create_thread(
        subject="directive", creator_id="agent-orch", project_id=project_id, tenant_key=tenant
    )
    tid = thread["thread_id"]

    assert "agent-worker" not in await _participant_ids(db_session, tenant, tid)

    result = await svc.post_to_thread(
        thread_id=tid, content="ORCHESTRATOR: ship it", from_agent="agent-orch", tenant_key=tenant
    )

    assert "agent-worker" in result["recipients"]
    assert "agent-orch" not in result["recipients"]
    assert "agent-worker" in await _participant_ids(db_session, tenant, tid)
    assert "agent-worker" in await _recipient_ids(db_session, tenant, result["message_id"])


async def test_already_enrolled_happy_path_and_idempotent(db_manager, db_session):
    tenant = _tk("happy")
    await _seed(db_session, tenant)
    project_id = await _seed_project_with_agents(db_session, tenant, [("agent-worker", "working")])
    svc = _service(db_manager, db_session)

    thread = await svc.create_thread(
        subject="directive", creator_id="agent-orch", project_id=project_id, tenant_key=tenant
    )
    tid = thread["thread_id"]
    await svc.join_thread(thread_id=tid, participant_id="agent-worker", tenant_key=tenant)

    r1 = await svc.post_to_thread(thread_id=tid, content="first", from_agent="agent-orch", tenant_key=tenant)
    assert "agent-worker" in r1["recipients"]
    after_first = await _participant_ids(db_session, tenant, tid)

    r2 = await svc.post_to_thread(thread_id=tid, content="second", from_agent="agent-orch", tenant_key=tenant)
    assert "agent-worker" in r2["recipients"]
    after_second = await _participant_ids(db_session, tenant, tid)
    assert after_first == after_second

    with tenant_session_context(db_session, tenant):
        worker_rows = (
            await db_session.execute(
                select(func.count(CommParticipant.id)).where(
                    CommParticipant.tenant_key == tenant,
                    CommParticipant.thread_id == tid,
                    CommParticipant.participant_id == "agent-worker",
                )
            )
        ).scalar_one()
    assert worker_rows == 1


async def test_standalone_thread_not_auto_enrolled(db_manager, db_session):
    tenant = _tk("standalone")
    await _seed(db_session, tenant)
    await _seed_project_with_agents(db_session, tenant, [("agent-worker", "working")])
    svc = _service(db_manager, db_session)

    thread = await svc.create_thread(subject="standalone", creator_id="agent-orch", tenant_key=tenant)
    tid = thread["thread_id"]
    await svc.join_thread(thread_id=tid, participant_id="agent-beta", tenant_key=tenant)

    result = await svc.post_to_thread(thread_id=tid, content="ping", from_agent="agent-orch", tenant_key=tenant)

    assert "agent-beta" in result["recipients"]
    assert "agent-worker" not in result["recipients"]
    assert "agent-worker" not in await _participant_ids(db_session, tenant, tid)


async def test_terminal_agents_not_enrolled(db_manager, db_session):
    tenant = _tk("terminal")
    await _seed(db_session, tenant)
    project_id = await _seed_project_with_agents(
        db_session,
        tenant,
        [
            ("agent-active", "working"),
            ("agent-complete", "complete"),
            ("agent-closed", "closed"),
            ("agent-decom", "decommissioned"),
        ],
    )
    svc = _service(db_manager, db_session)

    thread = await svc.create_thread(
        subject="directive", creator_id="agent-orch", project_id=project_id, tenant_key=tenant
    )
    tid = thread["thread_id"]

    result = await svc.post_to_thread(
        thread_id=tid, content="ORCHESTRATOR: status?", from_agent="agent-orch", tenant_key=tenant
    )

    assert "agent-active" in result["recipients"]
    for terminal in ("agent-complete", "agent-closed", "agent-decom"):
        assert terminal not in result["recipients"], f"{terminal} must not be auto-enrolled"
        assert terminal not in await _participant_ids(db_session, tenant, tid)


async def test_tenant_isolation_on_auto_enroll(db_manager, db_session):
    tenant_a = _tk("tenantA")
    tenant_b = _tk("tenantB")
    await _seed(db_session, tenant_a)
    await _seed(db_session, tenant_b)

    project_a = await _seed_project_with_agents(db_session, tenant_a, [("agent-a", "working")])
    await _seed_project_with_agents(db_session, tenant_b, [("agent-b", "working")])
    svc = _service(db_manager, db_session)

    thread = await svc.create_thread(
        subject="directive", creator_id="agent-orch", project_id=project_a, tenant_key=tenant_a
    )
    tid = thread["thread_id"]

    result = await svc.post_to_thread(
        thread_id=tid, content="ORCHESTRATOR: tenant scoped", from_agent="agent-orch", tenant_key=tenant_a
    )

    assert "agent-a" in result["recipients"]
    assert "agent-b" not in result["recipients"]
    assert "agent-b" not in await _participant_ids(db_session, tenant_a, tid)
