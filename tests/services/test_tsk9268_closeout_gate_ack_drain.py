# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import random
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.database import tenant_session_context
from giljo_mcp.models import AgentExecution, AgentJob, Project
from giljo_mcp.models.products import Product
from giljo_mcp.repositories.agent_operations_repository import AgentOperationsRepository
from giljo_mcp.services.comm_thread_service import CommThreadService
from giljo_mcp.services.project_closeout_service import ProjectCloseoutService
from giljo_mcp.services.taxonomy_ops import ensure_default_types_seeded
from giljo_mcp.tenant import TenantManager
from giljo_mcp.tools.write_memory_entry import write_360_memory


pytestmark = pytest.mark.asyncio

SENDER = "sender-conductor"


def _comm_service(db_manager, db_session: AsyncSession) -> CommThreadService:
    return CommThreadService(db_manager, TenantManager(), session=db_session)


async def _seed_team(
    db_session: AsyncSession,
    tenant_key: str,
    *,
    worker_status: str = "complete",
    stale_waiting_count: int = 0,
) -> tuple[Project, AgentJob, AgentJob, AgentExecution]:
    with tenant_session_context(db_session, tenant_key):
        await ensure_default_types_seeded(db_session, tenant_key)

    product = Product(
        id=str(uuid.uuid4()),
        tenant_key=tenant_key,
        name="TSK-9268 gate product",
        description="closeout-gate unread-store regression",
        product_memory={},
    )
    db_session.add(product)
    await db_session.flush()

    project = Project(
        id=str(uuid.uuid4()),
        tenant_key=tenant_key,
        product_id=product.id,
        name="TSK-9268 gate project",
        description="closeout-gate unread-store regression",
        mission="verify the project_completion gate reads the drain's store",
        status="active",
        created_at=datetime.now(UTC),
        series_number=random.randint(1, 9000),
    )
    db_session.add(project)
    await db_session.flush()

    orch_job = AgentJob(
        job_id=str(uuid.uuid4()),
        tenant_key=tenant_key,
        project_id=project.id,
        job_type="orchestrator",
        mission="orchestrate closeout-gate test",
        status="active",
    )
    db_session.add(orch_job)
    orch_exec = AgentExecution(
        job_id=orch_job.job_id,
        tenant_key=tenant_key,
        agent_display_name="orchestrator",
        status="working",
        messages_sent_count=0,
        messages_waiting_count=0,
        messages_read_count=0,
        started_at=datetime.now(UTC) - timedelta(minutes=10),
    )
    db_session.add(orch_exec)

    worker_job = AgentJob(
        job_id=str(uuid.uuid4()),
        tenant_key=tenant_key,
        project_id=project.id,
        job_type="worker",
        mission="implement the lane",
        status="active",
    )
    db_session.add(worker_job)
    worker_exec = AgentExecution(
        job_id=worker_job.job_id,
        tenant_key=tenant_key,
        agent_display_name="impl-1",
        agent_name="impl-1",
        status=worker_status,
        messages_sent_count=0,
        messages_waiting_count=stale_waiting_count,
        messages_read_count=0,
        started_at=datetime.now(UTC) - timedelta(minutes=8),
    )
    db_session.add(worker_exec)
    await db_session.commit()
    await db_session.refresh(project)
    await db_session.refresh(orch_job)
    await db_session.refresh(worker_exec)
    return project, orch_job, worker_job, worker_exec


async def _post_directed_action_required(
    comm: CommThreadService,
    tenant_key: str,
    project_id: str,
    recipient_agent_id: str,
    count: int,
) -> str:
    thread = await comm.create_thread(
        subject="lane coordination", project_id=project_id, creator_id=SENDER, tenant_key=tenant_key
    )
    tid = thread["thread_id"]
    await comm.join_thread(thread_id=tid, participant_id=recipient_agent_id, tenant_key=tenant_key)
    for n in range(count):
        await comm.post_to_thread(
            thread_id=tid,
            content=f"directive {n + 1}: confirm gate result before closeout",
            from_agent=SENDER,
            to_participant=recipient_agent_id,
            requires_action=True,
            tenant_key=tenant_key,
        )
    return tid


async def _write_completion(db_manager, db_session, tenant_key, project_id, author_job_id):
    return await write_360_memory(
        project_id=project_id,
        tenant_key=tenant_key,
        summary="Lane complete: closeout-gate unread store unified with the drain.",
        key_outcomes=["gate reads ack-based unread"],
        decisions_made=["single unread source of truth"],
        entry_type="project_completion",
        author_job_id=author_job_id,
        db_manager=db_manager,
        session=db_session,
    )




async def test_drained_agent_with_stale_counter_passes_project_completion_gate(db_manager, db_session: AsyncSession):
    tenant = TenantManager.generate_tenant_key()
    project, orch_job, _worker_job, worker = await _seed_team(
        db_session, tenant, worker_status="complete", stale_waiting_count=3
    )
    comm = _comm_service(db_manager, db_session)
    tid = await _post_directed_action_required(comm, tenant, project.id, worker.agent_id, count=3)

    drain = await comm.get_thread_history(
        thread_id=tid, as_participant=worker.agent_id, mark_read=True, tenant_key=tenant
    )
    assert drain["marked_read"] >= 3

    await db_session.refresh(worker)
    assert worker.messages_waiting_count == 3

    result = await _write_completion(db_manager, db_session, tenant, project.id, orch_job.job_id)
    assert result.get("error") != "CLOSEOUT_BLOCKED", f"gate trusted the stale counter: {result}"
    assert "entry_id" in result
    assert result["verified"]["all_messages_read"] is True




async def test_undrained_action_required_dm_still_blocks_project_completion(db_manager, db_session: AsyncSession):
    tenant = TenantManager.generate_tenant_key()
    project, orch_job, _worker_job, worker = await _seed_team(
        db_session, tenant, worker_status="complete", stale_waiting_count=0
    )
    comm = _comm_service(db_manager, db_session)
    await _post_directed_action_required(comm, tenant, project.id, worker.agent_id, count=1)

    result = await _write_completion(db_manager, db_session, tenant, project.id, orch_job.job_id)
    assert result.get("success") is False
    assert result.get("error") == "CLOSEOUT_BLOCKED"
    unread_blockers = [b for b in result["blockers"] if b.get("issue_type") == "unread_messages"]
    assert len(unread_blockers) == 1
    assert unread_blockers[0]["messages_waiting"] == 1




async def test_broadcast_action_required_directive_still_blocks_after_recipient_completes(
    db_manager, db_session: AsyncSession
):
    tenant = TenantManager.generate_tenant_key()
    project, orch_job, _worker_job, worker = await _seed_team(
        db_session, tenant, worker_status="working", stale_waiting_count=0
    )
    comm = _comm_service(db_manager, db_session)

    thread = await comm.create_thread(
        subject="broadcast lane coordination", project_id=project.id, creator_id=SENDER, tenant_key=tenant
    )
    tid = thread["thread_id"]
    await comm.join_thread(thread_id=tid, participant_id=worker.agent_id, tenant_key=tenant)
    post_result = await comm.post_to_thread(
        thread_id=tid,
        content="broadcast directive: confirm gate result before closeout",
        from_agent=SENDER,
        requires_action=True,
        tenant_key=tenant,
    )
    assert worker.agent_id in post_result["recipients"], "must be delivered while the worker is still live"
    assert "skipped_recipients" not in post_result

    worker.status = "complete"
    await db_session.commit()

    ops_repo = AgentOperationsRepository()
    live_action_required = await ops_repo.get_live_action_required_unread_counts_by_agent(
        db_session, tenant, project.id, [worker.agent_id]
    )
    assert live_action_required.get(worker.agent_id, 0) == 1, (
        "a broadcast directive must not vanish from the action-required badge once its recipient completes"
    )

    result = await _write_completion(db_manager, db_session, tenant, project.id, orch_job.job_id)
    assert result.get("success") is False
    assert result.get("error") == "CLOSEOUT_BLOCKED"
    unread_blockers = [b for b in result["blockers"] if b.get("issue_type") == "unread_messages"]
    assert len(unread_blockers) == 1
    assert unread_blockers[0]["messages_waiting"] == 1




async def test_three_readers_agree_on_unread_count(db_manager, db_session: AsyncSession):
    tenant = TenantManager.generate_tenant_key()
    project, orch_job, _worker_job, worker = await _seed_team(
        db_session, tenant, worker_status="blocked", stale_waiting_count=7
    )
    comm = _comm_service(db_manager, db_session)
    tid = await _post_directed_action_required(comm, tenant, project.id, worker.agent_id, count=2)

    closeout_svc = ProjectCloseoutService(db_manager, TenantManager(), test_session=db_session)
    ops_repo = AgentOperationsRepository()

    live = await ops_repo.get_live_action_required_unread_counts_by_agent(
        db_session, tenant, project.id, [worker.agent_id]
    )
    assert live.get(worker.agent_id, 0) == 2

    report = await closeout_svc.evaluate_closeout_readiness(
        db_session, project.id, tenant, orchestrator_job_id=orch_job.job_id
    )
    finding = next(f for f in report.findings if f.job_id == worker.job_id)
    assert finding.messages_waiting == 2, "gate reader diverged from the drain's store"

    diagnosis = await closeout_svc.diagnose_project_state(project.id, tenant_key=tenant)
    diag_row = next(b for b in diagnosis["readiness"]["blockers"] if b["job_id"] == worker.job_id)
    assert diag_row["messages_waiting"] == 2

    handover = await write_360_memory(
        project_id=project.id,
        tenant_key=tenant,
        summary="Handover while a directed action-required DM is still undrained.",
        key_outcomes=["state recorded"],
        decisions_made=["none"],
        entry_type="session_handover",
        author_job_id=orch_job.job_id,
        db_manager=db_manager,
        session=db_session,
    )
    assert "entry_id" in handover
    assert handover["verified"]["all_messages_read"] is False
    assert handover["verified"]["all_complete"] is False

    drain = await comm.get_thread_history(
        thread_id=tid, as_participant=worker.agent_id, mark_read=True, tenant_key=tenant
    )
    assert drain["marked_read"] >= 2
    worker.status = "complete"
    await db_session.commit()

    report_after = await closeout_svc.evaluate_closeout_readiness(
        db_session, project.id, tenant, orchestrator_job_id=orch_job.job_id
    )
    finding_after = next(f for f in report_after.findings if f.job_id == worker.job_id)
    assert finding_after.messages_waiting == 0

    diagnosis_after = await closeout_svc.diagnose_project_state(project.id, tenant_key=tenant)
    assert [b for b in diagnosis_after["readiness"]["blockers"] if b["job_id"] == worker.job_id] == []

    result = await _write_completion(db_manager, db_session, tenant, project.id, orch_job.job_id)
    assert result.get("error") != "CLOSEOUT_BLOCKED", f"drained state must close: {result}"
    assert result["verified"]["all_messages_read"] is True
