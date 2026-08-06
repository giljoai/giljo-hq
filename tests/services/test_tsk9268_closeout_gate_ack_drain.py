# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""TSK-9268 regression (service layer): the project_completion closeout gate reads
the same unread store the drain writes.

Root cause (live 2026-07-22 chain-finale wedge): ``write_memory_entry``'s
closeout gate consumed ``AgentExecution.messages_waiting_count`` — a denormalized,
increment-only column that NOTHING in src/ ever decrements — while the drain
(``get_thread_history(mark_read=True)``) writes ``message_acknowledgments`` rows.
The two never met, so a fully-drained completed agent blocked project_completion
forever with a stuck ``messages_waiting`` count. Meanwhile the post-write
"verified" block reported a hardcoded ``all_messages_read: True`` default whenever
blockers existed, so the session_handover path claimed clean while the
project_completion path claimed blocked — three readers, three answers.

The fix re-keys ``evaluate_closeout_readiness`` (the single readiness source all
closeout readers compose) onto the live ack-based action-required count — the
SAME gate definition ``complete_job`` already uses (BE-9108/BE-9012b:
``requires_action=True``, ``auto_generated=False``, no ack row) — and makes the
post-write verifier report the truth instead of the all-True fallback.

These tests drive the REAL comm-thread drain and the REAL write_360_memory gate
through the shared ``message_acknowledgments`` table — the layer the bug lived at.

Parallel-safe: db_session (TransactionalTestContext); each test owns its setup and
its own generated tenant_key. Edition Scope: CE (core orchestration; identical in SaaS).
"""

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

SENDER = "sender-conductor"  # a distinct author so posts never self-exclude the recipient


def _comm_service(db_manager, db_session: AsyncSession) -> CommThreadService:
    return CommThreadService(db_manager, TenantManager(), session=db_session)


async def _seed_team(
    db_session: AsyncSession,
    tenant_key: str,
    *,
    worker_status: str = "complete",
    stale_waiting_count: int = 0,
) -> tuple[Project, AgentJob, AgentJob, AgentExecution]:
    """Product -> Project -> orchestrator (author) + one worker execution.

    ``stale_waiting_count`` seeds the denormalized ``messages_waiting_count``
    poison value directly — mirroring prod, where increments (e.g. completion
    reports) accumulate and no code path ever decrements the column.
    """
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
    """Project-anchored thread + ``count`` directed requires_action DMs to the
    recipient (the exact shape of the flagged prod DMs). Returns thread_id."""
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


# ---------------------------------------------------------------------------
# (a) THE repro: completed agent, DMs drained via the real mark_read path, stale
#     denormalized counter still >0 -> project_completion must PASS
# ---------------------------------------------------------------------------


async def test_drained_agent_with_stale_counter_passes_project_completion_gate(db_manager, db_session: AsyncSession):
    tenant = TenantManager.generate_tenant_key()
    project, orch_job, _worker_job, worker = await _seed_team(
        db_session, tenant, worker_status="complete", stale_waiting_count=3
    )
    comm = _comm_service(db_manager, db_session)
    tid = await _post_directed_action_required(comm, tenant, project.id, worker.agent_id, count=3)

    # Drain exactly as the CLOSEOUT_BLOCKED hint instructs: read+ack as the recipient.
    drain = await comm.get_thread_history(
        thread_id=tid, as_participant=worker.agent_id, mark_read=True, tenant_key=tenant
    )
    assert drain["marked_read"] >= 3

    # The stale denormalized counter is untouched by the drain (mirrors prod).
    await db_session.refresh(worker)
    assert worker.messages_waiting_count == 3

    result = await _write_completion(db_manager, db_session, tenant, project.id, orch_job.job_id)
    assert result.get("error") != "CLOSEOUT_BLOCKED", f"gate trusted the stale counter: {result}"
    assert "entry_id" in result
    assert result["verified"]["all_messages_read"] is True


# ---------------------------------------------------------------------------
# (b) inverse guard: a genuinely-undrained action-required DM still BLOCKS —
#     even when the stale counter reads 0 (the desync's other direction)
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# (c) three-readers-agree: the gate, diagnose_project_state, and the post-write
#     verifier derive the SAME unread count from the SAME store
# ---------------------------------------------------------------------------


async def test_three_readers_agree_on_unread_count(db_manager, db_session: AsyncSession):
    tenant = TenantManager.generate_tenant_key()
    # Worker deliberately NON-complete so diagnose_project_state renders its
    # blocker row (it filters findings to status != complete); the stale counter
    # is seeded to a discriminating wrong value (7 != the 2 real unread DMs).
    project, orch_job, _worker_job, worker = await _seed_team(
        db_session, tenant, worker_status="blocked", stale_waiting_count=7
    )
    comm = _comm_service(db_manager, db_session)
    tid = await _post_directed_action_required(comm, tenant, project.id, worker.agent_id, count=2)

    closeout_svc = ProjectCloseoutService(db_manager, TenantManager(), test_session=db_session)
    ops_repo = AgentOperationsRepository()

    # Reader 0 (the shared source): live ack-based action-required count == 2.
    live = await ops_repo.get_live_action_required_unread_counts_by_agent(
        db_session, tenant, project.id, [worker.agent_id]
    )
    assert live.get(worker.agent_id, 0) == 2

    # Reader 1 (gate source): evaluate_closeout_readiness must report the SAME 2.
    report = await closeout_svc.evaluate_closeout_readiness(
        db_session, project.id, tenant, orchestrator_job_id=orch_job.job_id
    )
    finding = next(f for f in report.findings if f.job_id == worker.job_id)
    assert finding.messages_waiting == 2, "gate reader diverged from the drain's store"

    # Reader 2 (diagnose_project_state): blocker row carries the SAME 2, not the stale 7.
    diagnosis = await closeout_svc.diagnose_project_state(project.id, tenant_key=tenant)
    diag_row = next(b for b in diagnosis["readiness"]["blockers"] if b["job_id"] == worker.job_id)
    assert diag_row["messages_waiting"] == 2

    # Reader 3 (post-write verifier on a session_handover): must tell the truth
    # (all_messages_read False while undrained), never the all-True fallback.
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
    assert "entry_id" in handover  # handovers are not gated
    assert handover["verified"]["all_messages_read"] is False
    assert handover["verified"]["all_complete"] is False  # worker is blocked, not complete

    # Drain, complete the worker -> all readers agree on ZERO and the gate opens.
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

    # diagnose has no author context, so the still-working orchestrator itself
    # legitimately renders as a blocker row — assert only the WORKER cleared.
    diagnosis_after = await closeout_svc.diagnose_project_state(project.id, tenant_key=tenant)
    assert [b for b in diagnosis_after["readiness"]["blockers"] if b["job_id"] == worker.job_id] == []

    result = await _write_completion(db_manager, db_session, tenant, project.id, orch_job.job_id)
    assert result.get("error") != "CLOSEOUT_BLOCKED", f"drained state must close: {result}"
    assert result["verified"]["all_messages_read"] is True
