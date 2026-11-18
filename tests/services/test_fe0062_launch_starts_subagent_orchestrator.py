# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from giljo_mcp.models.agent_identity import AgentExecution, AgentJob
from giljo_mcp.models.products import Product
from giljo_mcp.models.projects import Project, ProjectStatus
from giljo_mcp.services.not_picked_up import not_picked_up_job_ids
from giljo_mcp.services.project_staging_service import ProjectStagingService
from tests.helpers.taxonomy_seeds import next_series_number


pytestmark = pytest.mark.asyncio


def _service(db_manager, tenant_key, db_session, ws=None) -> ProjectStagingService:
    tenant_manager = MagicMock()
    tenant_manager.get_current_tenant.return_value = tenant_key
    return ProjectStagingService(
        db_manager=db_manager, tenant_manager=tenant_manager, websocket_manager=ws, test_session=db_session
    )


async def _staged_project(db_session, tenant_key: str, execution_mode: str, *, parked_orchestrator: bool = True):
    product = Product(id=str(uuid4()), tenant_key=tenant_key, name=f"fe0062-product-{uuid4().hex[:8]}")
    db_session.add(product)
    await db_session.flush()
    project = Project(
        id=str(uuid4()),
        tenant_key=tenant_key,
        product_id=product.id,
        name=f"fe0062-project-{uuid4().hex[:8]}",
        description="FE-0062 probe.",
        mission="FE-0062 probe mission.",
        status=ProjectStatus.INACTIVE,
        staging_status="staging_complete",
        execution_mode=execution_mode,
        series_number=next_series_number(),
        created_at=datetime.now(UTC),
    )
    db_session.add(project)
    db_session.info["tenant_key"] = tenant_key
    await db_session.flush()

    created = datetime.now(UTC) - timedelta(hours=2)
    orch_job = AgentJob(
        job_id=str(uuid4()),
        tenant_key=tenant_key,
        project_id=project.id,
        job_type="orchestrator",
        mission="orchestrate",
        status="active",
        created_at=created,
    )
    worker_job = AgentJob(
        job_id=str(uuid4()),
        tenant_key=tenant_key,
        project_id=project.id,
        job_type="implementer",
        mission="implement",
        status="active",
        created_at=created,
    )
    db_session.add_all([orch_job, worker_job])
    await db_session.flush()
    orch = AgentExecution(
        id=str(uuid4()),
        agent_id=str(uuid4()),
        job_id=orch_job.job_id,
        tenant_key=tenant_key,
        agent_display_name="orchestrator",
        status="waiting",
        result={"summary": "staged"} if parked_orchestrator else None,
    )
    worker = AgentExecution(
        id=str(uuid4()),
        agent_id=str(uuid4()),
        job_id=worker_job.job_id,
        tenant_key=tenant_key,
        agent_display_name="implementer",
        status="working",
    )
    db_session.add_all([orch, worker])
    await db_session.flush()
    return project, orch, worker


async def _status(db_session, tenant_key: str, execution: AgentExecution) -> str:
    await db_session.refresh(execution)
    return execution.status


@pytest.mark.parametrize("origin", ["ui", "mcp"])
async def test_subagent_launch_starts_the_orchestrator_on_both_doors(db_manager, db_session, test_tenant_key, origin):
    ws = MagicMock()
    ws.broadcast_to_tenant = AsyncMock()
    svc = _service(db_manager, test_tenant_key, db_session, ws)
    project, orch, _worker = await _staged_project(db_session, test_tenant_key, "subagent")

    await svc.launch_implementation(project.id, tenant_key=test_tenant_key, origin=origin)

    assert await _status(db_session, test_tenant_key, orch) == "working"
    assert orch.started_at is not None
    assert orch.last_progress_at is not None
    events = [c.kwargs["event_type"] for c in ws.broadcast_to_tenant.call_args_list]
    assert "agent:status_changed" in events
    far_future = datetime.now(UTC) + timedelta(days=1)
    flagged = await not_picked_up_job_ids(
        db_session, test_tenant_key, project, [(orch.job_id, orch.status, orch.job_id)], 5, now=far_future
    )
    assert flagged == set()


async def test_second_launch_does_not_touch_the_orchestrator_again(db_manager, db_session, test_tenant_key):
    svc = _service(db_manager, test_tenant_key, db_session)
    project, orch, _worker = await _staged_project(db_session, test_tenant_key, "subagent")
    await svc.launch_implementation(project.id, tenant_key=test_tenant_key)
    await db_session.refresh(orch)
    first_started = orch.started_at

    again = await svc.launch_implementation(project.id, tenant_key=test_tenant_key)

    assert again["already_launched"] is True
    await db_session.refresh(orch)
    assert orch.status == "working"
    assert orch.started_at == first_started


async def test_multi_terminal_launch_leaves_an_unopened_orchestrator_waiting(db_manager, db_session, test_tenant_key):
    svc = _service(db_manager, test_tenant_key, db_session)
    project, orch, _worker = await _staged_project(db_session, test_tenant_key, "multi_terminal")

    await svc.launch_implementation(project.id, tenant_key=test_tenant_key, origin="ui")

    assert await _status(db_session, test_tenant_key, orch) == "waiting"
    far_future = datetime.now(UTC) + timedelta(days=1)
    await db_session.refresh(project)
    flagged = await not_picked_up_job_ids(
        db_session, test_tenant_key, project, [(orch.job_id, orch.status, orch.job_id)], 5, now=far_future
    )
    assert flagged == {orch.job_id}


async def test_subagent_orchestrator_that_has_not_staged_yet_is_left_to_its_own_start(
    db_manager, db_session, test_tenant_key
):
    svc = _service(db_manager, test_tenant_key, db_session)
    project, orch, _worker = await _staged_project(db_session, test_tenant_key, "subagent", parked_orchestrator=False)

    await svc.launch_implementation(project.id, tenant_key=test_tenant_key)

    assert await _status(db_session, test_tenant_key, orch) == "waiting"


async def _parked_orchestrator(db_session, tenant_key: str, project_id: str, created_at: datetime) -> AgentExecution:
    job = AgentJob(
        job_id=str(uuid4()),
        tenant_key=tenant_key,
        project_id=project_id,
        job_type="orchestrator",
        mission="orchestrate",
        status="active",
        created_at=created_at,
    )
    db_session.add(job)
    await db_session.flush()
    execution = AgentExecution(
        id=str(uuid4()),
        agent_id=str(uuid4()),
        job_id=job.job_id,
        tenant_key=tenant_key,
        agent_display_name="orchestrator",
        status="waiting",
        result={"summary": "staged"},
    )
    db_session.add(execution)
    await db_session.flush()
    return execution


async def test_launch_starts_only_the_launched_projects_orchestrator(db_manager, db_session, test_tenant_key):
    svc = _service(db_manager, test_tenant_key, db_session)
    project, orch, _worker = await _staged_project(db_session, test_tenant_key, "subagent")
    _other_project, other_orch, _w = await _staged_project(db_session, test_tenant_key, "subagent")
    other_orch_job = await db_session.get(AgentJob, other_orch.job_id)
    other_orch_job.created_at = datetime.now(UTC)
    await db_session.flush()

    await svc.launch_implementation(project.id, tenant_key=test_tenant_key)

    assert await _status(db_session, test_tenant_key, orch) == "working"
    assert await _status(db_session, test_tenant_key, other_orch) == "waiting"


async def test_launch_never_starts_another_tenants_orchestrator(db_manager, db_session, test_tenant_key):
    svc = _service(db_manager, test_tenant_key, db_session)
    project, orch, _worker = await _staged_project(db_session, test_tenant_key, "subagent")
    foreign = await _parked_orchestrator(db_session, f"tk_{uuid4().hex}", project.id, datetime.now(UTC))
    db_session.info["tenant_key"] = test_tenant_key

    await svc.launch_implementation(project.id, tenant_key=test_tenant_key)

    assert await _status(db_session, test_tenant_key, orch) == "working"
    assert await _status(db_session, foreign.tenant_key, foreign) == "waiting"


async def test_launch_starts_the_newest_parked_orchestrator(db_manager, db_session, test_tenant_key):
    svc = _service(db_manager, test_tenant_key, db_session)
    project, orch, _worker = await _staged_project(db_session, test_tenant_key, "subagent")
    older_job = await db_session.get(AgentJob, orch.job_id)
    older_job.created_at = datetime.now(UTC) - timedelta(hours=3)
    await db_session.flush()
    newer = await _parked_orchestrator(db_session, test_tenant_key, project.id, datetime.now(UTC) - timedelta(hours=1))

    await svc.launch_implementation(project.id, tenant_key=test_tenant_key)

    assert await _status(db_session, test_tenant_key, newer) == "working"
    assert await _status(db_session, test_tenant_key, orch) == "waiting"
