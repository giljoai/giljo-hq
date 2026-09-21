# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy import select

from giljo_mcp.domain.project_status import ProjectStatus
from giljo_mcp.exceptions import ResourceNotFoundError
from giljo_mcp.models import Product, Project
from giljo_mcp.models.agent_identity import AgentExecution, AgentJob
from giljo_mcp.models.sequence_runs import SequenceRun
from giljo_mcp.services.sequence_run_service import SequenceRunService
from giljo_mcp.tenant import TenantManager


pytestmark = pytest.mark.asyncio


class _RecordingWS:

    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, Any]]] = []

    async def broadcast_event_to_tenant(self, tenant_key: str, event: dict[str, Any]) -> None:
        self.events.append((tenant_key, event))

    async def broadcast_project_update(self, **kwargs: Any) -> None:
        return None


async def _seed(db_manager) -> tuple[str, str, list[str]]:
    tenant_key = TenantManager.generate_tenant_key()
    pids = [str(uuid.uuid4()) for _ in range(5)]
    run_id = str(uuid.uuid4())
    async with db_manager.get_session_async(tenant_key=tenant_key) as session:
        product = Product(
            id=str(uuid.uuid4()),
            name="Chain Product",
            description="desc",
            tenant_key=tenant_key,
            is_active=True,
        )
        session.add(product)
        for i, pid in enumerate(pids):
            session.add(
                Project(
                    id=pid,
                    name=f"P{i + 1}",
                    description="desc",
                    mission="a real chain mission the orchestrator wrote",
                    status=ProjectStatus.COMPLETED if i == 0 else ProjectStatus.ACTIVE,
                    staging_status="staging_complete",
                    implementation_launched_at=datetime.now(UTC) if i <= 1 else None,
                    product_id=product.id,
                    tenant_key=tenant_key,
                    series_number=i + 1,
                )
            )
        job_id = str(uuid.uuid4())
        session.add(
            AgentJob(
                job_id=job_id,
                job_type="orchestrator",
                tenant_key=tenant_key,
                project_id=pids[1],
                mission="orchestrator mission",
                status="active",
            )
        )
        session.add(
            AgentExecution(
                id=str(uuid.uuid4()),
                agent_id=str(uuid.uuid4()),
                job_id=job_id,
                tenant_key=tenant_key,
                agent_display_name="orchestrator",
                status="working",
                working_started_at=datetime.now(UTC),
            )
        )
        session.add(
            SequenceRun(
                id=run_id,
                tenant_key=tenant_key,
                project_ids=pids,
                resolved_order=pids,
                current_index=1,
                execution_mode="claude_code_cli",
                status="running",
                locked=True,
                conductor_agent_id="cond-1",
                conductor_project_id=pids[0],
                conductor_label="cond-1",
                project_statuses={
                    pids[0]: "completed",
                    pids[1]: "implementing",
                    pids[2]: "pending",
                    pids[3]: "pending",
                    pids[4]: "pending",
                },
            )
        )
        await session.commit()
    return tenant_key, run_id, pids


async def _projects(db_manager, tenant_key: str) -> dict[str, Project]:
    async with db_manager.get_session_async(tenant_key=tenant_key) as session:
        rows = (await session.execute(select(Project).where(Project.tenant_key == tenant_key))).scalars().all()
    return {str(r.id): r for r in rows}


async def _jobs(db_manager, tenant_key: str, project_id: str) -> list[AgentJob]:
    async with db_manager.get_session_async(tenant_key=tenant_key) as session:
        rows = (
            (
                await session.execute(
                    select(AgentJob).where(AgentJob.tenant_key == tenant_key, AgentJob.project_id == project_id)
                )
            )
            .scalars()
            .all()
        )
    return list(rows)


async def _executions(db_manager, tenant_key: str, job_ids: list[str]) -> list[AgentExecution]:
    async with db_manager.get_session_async(tenant_key=tenant_key) as session:
        rows = (
            (
                await session.execute(
                    select(AgentExecution).where(
                        AgentExecution.tenant_key == tenant_key,
                        AgentExecution.job_id.in_(job_ids),
                    )
                )
            )
            .scalars()
            .all()
        )
    return list(rows)


def _svc(db_manager, ws: Any | None = None) -> SequenceRunService:
    return SequenceRunService(db_manager=db_manager, tenant_manager=TenantManager(), websocket_manager=ws)


async def test_stop_chain_cancels_the_run(db_manager):
    tenant_key, run_id, _pids = await _seed(db_manager)

    result = await _svc(db_manager).stop_chain(run_id=run_id, tenant_key=tenant_key)

    assert result["status"] == "cancelled", (
        "operator decision #4: Stop chain reuses `cancelled`; a new `stopped` status would "
        "have to be taught to VALID_RUN_STATUSES, the FE finished-set and every consumer"
    )


async def test_stop_chain_leaves_a_completed_member_completed(db_manager):
    tenant_key, run_id, pids = await _seed(db_manager)

    await _svc(db_manager).stop_chain(run_id=run_id, tenant_key=tenant_key)

    assert (await _projects(db_manager, tenant_key))[pids[0]].status == ProjectStatus.COMPLETED


async def test_stop_chain_terminates_the_member_underway_keeping_its_records(db_manager):
    tenant_key, run_id, pids = await _seed(db_manager)

    await _svc(db_manager).stop_chain(run_id=run_id, tenant_key=tenant_key)

    underway = (await _projects(db_manager, tenant_key))[pids[1]]
    assert underway.status == ProjectStatus.TERMINATED

    jobs = await _jobs(db_manager, tenant_key, pids[1])
    assert len(jobs) == 1, "the member underway's agent job must be KEPT, not deleted"
    assert jobs[0].status == "cancelled", "a stopped job is terminal, not still 'active'"

    execs = await _executions(db_manager, tenant_key, [j.job_id for j in jobs])
    assert len(execs) == 1, "the execution row must be KEPT, not deleted"
    assert execs[0].status == "decommissioned", (
        "'decommissioned' is this codebase's terminal-but-preserved execution status "
        "(project_deletion_service, agent_health_monitor); 'terminated' is not a legal value"
    )
    assert execs[0].completed_at is not None


async def test_stop_chain_returns_unstarted_members_to_inactive(db_manager):
    tenant_key, run_id, pids = await _seed(db_manager)

    await _svc(db_manager).stop_chain(run_id=run_id, tenant_key=tenant_key)

    projects = await _projects(db_manager, tenant_key)
    for pid in pids[2:]:
        assert projects[pid].status == ProjectStatus.INACTIVE


async def test_stop_chain_never_deletes_work_that_ran(db_manager):
    tenant_key, run_id, pids = await _seed(db_manager)
    before = len(await _jobs(db_manager, tenant_key, pids[1]))

    await _svc(db_manager).stop_chain(run_id=run_id, tenant_key=tenant_key)

    projects = await _projects(db_manager, tenant_key)
    assert set(projects) == set(pids), "no member project row may be deleted by a stop"
    assert len(await _jobs(db_manager, tenant_key, pids[1])) == before


async def test_stop_chain_removes_an_unstarted_members_never_run_placeholder(db_manager):
    tenant_key = TenantManager.generate_tenant_key()
    pids = [str(uuid.uuid4()), str(uuid.uuid4())]
    run_id = str(uuid.uuid4())
    async with db_manager.get_session_async(tenant_key=tenant_key) as session:
        product = Product(id=str(uuid.uuid4()), name="P", description="d", tenant_key=tenant_key, is_active=True)
        session.add(product)
        for i, pid in enumerate(pids):
            session.add(
                Project(
                    id=pid,
                    name=f"P{i + 1}",
                    description="d",
                    mission="a staged mission never acted on",
                    status=ProjectStatus.ACTIVE,
                    staging_status="staging_complete",
                    product_id=product.id,
                    tenant_key=tenant_key,
                    series_number=i + 1,
                )
            )
        job_id = str(uuid.uuid4())
        session.add(
            AgentJob(
                job_id=job_id,
                job_type="orchestrator",
                tenant_key=tenant_key,
                project_id=pids[1],
                mission="placeholder",
                status="active",
            )
        )
        session.add(
            AgentExecution(
                id=str(uuid.uuid4()),
                agent_id=str(uuid.uuid4()),
                job_id=job_id,
                tenant_key=tenant_key,
                agent_display_name="orchestrator",
                status="waiting",
                working_started_at=None,
            )
        )
        session.add(
            SequenceRun(
                id=run_id,
                tenant_key=tenant_key,
                project_ids=pids,
                resolved_order=pids,
                current_index=0,
                execution_mode="subagent",
                status="running",
                locked=True,
                project_statuses={pids[0]: "implementing", pids[1]: "staged"},
            )
        )
        await session.commit()

    await _svc(db_manager).stop_chain(run_id=run_id, tenant_key=tenant_key)

    unstarted = (await _projects(db_manager, tenant_key))[pids[1]]
    assert unstarted.status == ProjectStatus.INACTIVE
    assert await _jobs(db_manager, tenant_key, pids[1]) == [], (
        "the never-run placeholder is removed by the owning deactivate writer"
    )
    assert unstarted.mission == "", "the unused staged mission is cleared -- the project must be staged again"


async def test_stop_chain_unlinks_members_but_keeps_the_run_record(db_manager):
    tenant_key, run_id, pids = await _seed(db_manager)

    result = await _svc(db_manager).stop_chain(run_id=run_id, tenant_key=tenant_key)

    assert result["status"] == "cancelled", "terminal => dropped from the active set => Linked clears"
    assert set(result["project_ids"]) == set(pids), (
        "the run row must keep its membership as the durable record; emptying project_ids "
        "would delete the grouping the crash-resume ground truth depends on"
    )


async def test_stop_chain_emits_exactly_one_sequence_updated(db_manager):
    tenant_key, run_id, _pids = await _seed(db_manager)
    ws = _RecordingWS()

    await _svc(db_manager, ws).stop_chain(run_id=run_id, tenant_key=tenant_key)

    seq_events = [evt for _tk, evt in ws.events if evt.get("type") == "sequence:updated"]
    assert len(seq_events) == 1, f"expected exactly one sequence:updated, got {len(seq_events)}"
    assert seq_events[0]["data"]["run_id"] == run_id


async def test_stop_chain_is_idempotent(db_manager):
    tenant_key, run_id, pids = await _seed(db_manager)
    svc = _svc(db_manager)

    await svc.stop_chain(run_id=run_id, tenant_key=tenant_key)
    result = await svc.stop_chain(run_id=run_id, tenant_key=tenant_key)

    assert result["status"] == "cancelled"
    projects = await _projects(db_manager, tenant_key)
    assert projects[pids[0]].status == ProjectStatus.COMPLETED
    assert projects[pids[1]].status == ProjectStatus.TERMINATED
    assert projects[pids[2]].status == ProjectStatus.INACTIVE


async def test_stop_chain_skips_a_hard_deleted_member(db_manager):
    tenant_key, run_id, pids = await _seed(db_manager)
    phantom = str(uuid.uuid4())
    async with db_manager.get_session_async(tenant_key=tenant_key) as session:
        run = (await session.execute(select(SequenceRun).where(SequenceRun.id == run_id))).scalar_one()
        run.resolved_order = [*pids, phantom]
        run.project_ids = [*pids, phantom]
        await session.commit()

    result = await _svc(db_manager).stop_chain(run_id=run_id, tenant_key=tenant_key)

    assert result["status"] == "cancelled"


async def test_stop_chain_unknown_run_raises_not_found(db_manager):
    tenant_key = TenantManager.generate_tenant_key()
    with pytest.raises(ResourceNotFoundError):
        await _svc(db_manager).stop_chain(run_id=str(uuid.uuid4()), tenant_key=tenant_key)


async def test_stop_chain_is_tenant_scoped(db_manager):
    _tenant_key, run_id, _pids = await _seed(db_manager)
    other_tenant = TenantManager.generate_tenant_key()

    with pytest.raises(ResourceNotFoundError):
        await _svc(db_manager).stop_chain(run_id=run_id, tenant_key=other_tenant)
