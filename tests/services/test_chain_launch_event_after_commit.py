# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import random
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy import select

from giljo_mcp.domain.project_status import ProjectStatus
from giljo_mcp.models import Product, Project
from giljo_mcp.models.agent_identity import AgentExecution, AgentJob
from giljo_mcp.services.job_completion_service import JobCompletionService
from giljo_mcp.services.mission_service import MissionService
from giljo_mcp.services.sequence_run_service import SequenceRunService
from giljo_mcp.tenant import TenantManager
from tests.conftest import _purge_tenant_key


pytestmark = pytest.mark.asyncio

LAUNCH_EVENT = "project:implementation_launched"
STAGING_COMPLETE_EVENT = "project:staging_complete"


class _ObservingWS:

    def __init__(self, db_manager: Any, *, fail_launch_event: bool = False) -> None:
        self._db_manager = db_manager
        self._fail_launch_event = fail_launch_event
        self.calls: list[dict[str, Any]] = []
        self.seen_by_other_session: list[dict[str, Any]] = []
        self.seen_at: dict[str, dict[str, Any]] = {}

    async def broadcast_to_tenant(self, *, tenant_key: str, event_type: str, data: dict, **_: Any) -> int:
        self.calls.append({"tenant_key": tenant_key, "event_type": event_type, "data": data})
        if event_type in (LAUNCH_EVENT, STAGING_COMPLETE_EVENT):
            async with self._db_manager.get_session_async(tenant_key=tenant_key) as other:
                row = (
                    await other.execute(
                        select(Project.implementation_launched_at, Project.status, Project.staging_status).where(
                            Project.id == data["project_id"], Project.tenant_key == tenant_key
                        )
                    )
                ).one()
            seen = {"implementation_launched_at": row[0], "status": row[1], "staging_status": row[2]}
            self.seen_at[event_type] = seen
            if event_type == LAUNCH_EVENT:
                self.seen_by_other_session.append(seen)
                if self._fail_launch_event:
                    raise RuntimeError("simulated WS failure")
        return 0

    def events(self, event_type: str) -> list[dict[str, Any]]:
        return [c for c in self.calls if c["event_type"] == event_type]


async def _seed_member(session, tenant_key: str, product_id: str) -> str:
    project = Project(
        id=str(uuid.uuid4()),
        name=f"Chain member {uuid.uuid4().hex[:6]}",
        description="Chain member.",
        mission="Be a chain member.",
        status=ProjectStatus.INACTIVE,
        tenant_key=tenant_key,
        product_id=product_id,
        series_number=random.randint(1, 9000),
        execution_mode="claude_code_cli",
        staging_status="staging",
        implementation_launched_at=None,
        created_at=datetime.now(UTC),
    )
    session.add(project)
    await session.flush()
    return project.id


def _agent(tenant_key: str, project_id: str, *, job_type: str, status: str, phase: str) -> tuple[AgentJob, Any]:
    job_id = str(uuid.uuid4())
    job = AgentJob(
        job_id=job_id,
        tenant_key=tenant_key,
        project_id=project_id,
        mission="do the work",
        job_type=job_type,
        status="active",
        job_metadata={},
    )
    execution = AgentExecution(
        agent_id=str(uuid.uuid4()),
        job_id=job_id,
        tenant_key=tenant_key,
        agent_display_name=job_type,
        agent_name=job_type,
        status=status,
        health_status="unknown",
        project_phase=phase,
        started_at=datetime.now(UTC),
    )
    return job, execution


@pytest_asyncio.fixture
async def chain_member(db_manager):
    tenant_key = TenantManager.generate_tenant_key()
    async with db_manager.get_session_async(tenant_key=tenant_key) as session:
        product = Product(
            id=str(uuid.uuid4()),
            name=f"Chain product {uuid.uuid4().hex[:6]}",
            description="Chain product.",
            tenant_key=tenant_key,
            is_active=False,
        )
        session.add(product)
        await session.flush()
        first = await _seed_member(session, tenant_key, product.id)
        second = await _seed_member(session, tenant_key, product.id)
        orch_job, orch_exec = _agent(tenant_key, second, job_type="orchestrator", status="waiting", phase="staging")
        worker_job, worker_exec = _agent(
            tenant_key, second, job_type="implementer", status="working", phase="implementation"
        )
        session.add_all([orch_job, worker_job])
        await session.flush()
        session.add_all([orch_exec, worker_exec])
        await SequenceRunService(db_manager=None, tenant_manager=TenantManager(), session=session).create(
            project_ids=[first, second],
            resolved_order=[first, second],
            execution_mode="claude_code_cli",
            tenant_key=tenant_key,
        )
        await session.commit()

    yield {"tenant_key": tenant_key, "project_id": second, "job_id": orch_job.job_id}

    await _purge_tenant_key(db_manager, tenant_key)


class _FailingAgentState:

    async def _handle_completion_side_effects(self, *_: Any) -> None:
        return None

    async def _resolve_product_id(self, *_: Any) -> None:
        raise RuntimeError("simulated failure after the staging-end write")


def _service(db_manager, tenant_key: str, ws: Any, agent_state: Any = None) -> JobCompletionService:
    tenant_manager = TenantManager()
    tenant_manager.set_current_tenant(tenant_key)
    return JobCompletionService(
        db_manager=db_manager,
        tenant_manager=tenant_manager,
        websocket_manager=ws,
        agent_state_service=agent_state,
    )


async def test_launch_event_is_sent_after_the_row_is_committed(db_manager, chain_member) -> None:
    tenant_key = chain_member["tenant_key"]
    ws = _ObservingWS(db_manager)

    result = await _service(db_manager, tenant_key, ws).complete_job(
        job_id=chain_member["job_id"], result={"summary": "staging done"}, tenant_key=tenant_key
    )

    assert result.phase == "staging_end"
    assert len(ws.events(LAUNCH_EVENT)) == 1
    seen = ws.seen_by_other_session[0]
    assert seen["implementation_launched_at"] is not None, (
        "a separate session must already read the launch stamp when the event is sent"
    )
    assert seen["status"] == ProjectStatus.ACTIVE, (
        "a separate session must already read the project as active when the event is sent"
    )


async def test_no_launch_event_when_the_transaction_rolls_back(db_manager, chain_member) -> None:
    tenant_key = chain_member["tenant_key"]
    ws = _ObservingWS(db_manager)
    service = _service(db_manager, tenant_key, ws, _FailingAgentState())

    with pytest.raises(Exception, match="Failed to complete job"):
        await service.complete_job(
            job_id=chain_member["job_id"], result={"summary": "staging done"}, tenant_key=tenant_key
        )

    assert ws.events(LAUNCH_EVENT) == [], "no launch event may go out for a write that was rolled back"
    async with db_manager.get_session_async(tenant_key=tenant_key) as verify:
        launched_at = (
            await verify.execute(
                select(Project.implementation_launched_at).where(
                    Project.id == chain_member["project_id"], Project.tenant_key == tenant_key
                )
            )
        ).scalar_one()
    assert launched_at is None


async def test_a_failed_launch_event_does_not_fail_the_write(db_manager, chain_member) -> None:
    tenant_key = chain_member["tenant_key"]
    ws = _ObservingWS(db_manager, fail_launch_event=True)

    result = await _service(db_manager, tenant_key, ws).complete_job(
        job_id=chain_member["job_id"], result={"summary": "staging done"}, tenant_key=tenant_key
    )

    assert result.phase == "staging_end"
    async with db_manager.get_session_async(tenant_key=tenant_key) as verify:
        launched_at = (
            await verify.execute(
                select(Project.implementation_launched_at).where(
                    Project.id == chain_member["project_id"], Project.tenant_key == tenant_key
                )
            )
        ).scalar_one()
    assert launched_at is not None


async def _read_project(db_manager, tenant_key: str, project_id: str) -> Project:
    async with db_manager.get_session_async(tenant_key=tenant_key) as session:
        return (
            await session.execute(select(Project).where(Project.id == project_id, Project.tenant_key == tenant_key))
        ).scalar_one()


async def test_a_launch_stamp_already_set_is_kept(db_manager, chain_member) -> None:
    tenant_key = chain_member["tenant_key"]
    first_launch = datetime.now(UTC) - timedelta(minutes=40)
    async with db_manager.get_session_async(tenant_key=tenant_key) as session:
        project = (
            await session.execute(
                select(Project).where(Project.id == chain_member["project_id"], Project.tenant_key == tenant_key)
            )
        ).scalar_one()
        project.implementation_launched_at = first_launch
        project.ever_launched_at = first_launch
        project.status = ProjectStatus.ACTIVE
        await session.commit()
    ws = _ObservingWS(db_manager)

    result = await _service(db_manager, tenant_key, ws).complete_job(
        job_id=chain_member["job_id"], result={"summary": "staging done"}, tenant_key=tenant_key
    )

    assert result.phase == "staging_end"
    project = await _read_project(db_manager, tenant_key, chain_member["project_id"])
    assert project.implementation_launched_at == first_launch, "the first launch time must survive the staging end"
    assert project.ever_launched_at == first_launch
    payload = ws.events(LAUNCH_EVENT)[0]["data"]
    assert payload["implementation_launched_at"] == first_launch.isoformat()


async def test_a_member_launched_by_its_staging_end_records_its_first_launch(db_manager, chain_member) -> None:
    tenant_key = chain_member["tenant_key"]

    await _service(db_manager, tenant_key, _ObservingWS(db_manager)).complete_job(
        job_id=chain_member["job_id"], result={"summary": "staging done"}, tenant_key=tenant_key
    )

    project = await _read_project(db_manager, tenant_key, chain_member["project_id"])
    assert project.implementation_launched_at is not None
    assert project.ever_launched_at == project.implementation_launched_at


async def test_staging_complete_event_from_complete_job_follows_the_commit(db_manager, chain_member) -> None:
    tenant_key = chain_member["tenant_key"]
    ws = _ObservingWS(db_manager)

    await _service(db_manager, tenant_key, ws).complete_job(
        job_id=chain_member["job_id"], result={"summary": "staging done"}, tenant_key=tenant_key
    )

    assert len(ws.events(STAGING_COMPLETE_EVENT)) == 1
    assert ws.seen_at[STAGING_COMPLETE_EVENT]["staging_status"] == "staging_complete", (
        "a separate session must already read staging_complete when the event is sent"
    )


async def test_no_staging_complete_event_when_complete_job_rolls_back(db_manager, chain_member) -> None:
    tenant_key = chain_member["tenant_key"]
    ws = _ObservingWS(db_manager)

    with pytest.raises(Exception, match="Failed to complete job"):
        await _service(db_manager, tenant_key, ws, _FailingAgentState()).complete_job(
            job_id=chain_member["job_id"], result={"summary": "staging done"}, tenant_key=tenant_key
        )

    assert ws.events(STAGING_COMPLETE_EVENT) == []


async def test_staging_complete_event_from_a_mission_write_follows_the_commit(db_manager, chain_member) -> None:
    tenant_key = chain_member["tenant_key"]
    ws = _ObservingWS(db_manager)
    tenant_manager = TenantManager()
    tenant_manager.set_current_tenant(tenant_key)
    service = MissionService(db_manager=db_manager, tenant_manager=tenant_manager, websocket_manager=ws)

    await service.update_agent_mission(chain_member["job_id"], tenant_key, "The plan for this project.")

    event = ws.events(STAGING_COMPLETE_EVENT)
    assert len(event) == 1
    assert event[0]["data"]["agent_count"] == 1
    assert ws.seen_at[STAGING_COMPLETE_EVENT]["staging_status"] == "staging_complete", (
        "a separate session must already read staging_complete when the event is sent"
    )


async def test_a_staging_end_does_not_undo_a_deactivate(db_manager, chain_member) -> None:
    tenant_key = chain_member["tenant_key"]
    first_launch = datetime.now(UTC) - timedelta(minutes=40)
    async with db_manager.get_session_async(tenant_key=tenant_key) as session:
        project = (
            await session.execute(
                select(Project).where(Project.id == chain_member["project_id"], Project.tenant_key == tenant_key)
            )
        ).scalar_one()
        project.implementation_launched_at = first_launch
        project.ever_launched_at = first_launch
        project.status = ProjectStatus.INACTIVE
        await session.commit()

    result = await _service(db_manager, tenant_key, _ObservingWS(db_manager)).complete_job(
        job_id=chain_member["job_id"], result={"summary": "staging done"}, tenant_key=tenant_key
    )

    assert result.phase == "staging_end"
    project = await _read_project(db_manager, tenant_key, chain_member["project_id"])
    assert project.status == ProjectStatus.INACTIVE, "a project deactivated after its launch must stay inactive"
    assert project.implementation_launched_at == first_launch
