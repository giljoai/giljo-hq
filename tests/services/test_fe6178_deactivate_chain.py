# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from giljo_mcp.domain.project_status import ProjectStatus
from giljo_mcp.exceptions import ResourceNotFoundError
from giljo_mcp.models import Product, Project
from giljo_mcp.models.agent_identity import AgentJob
from giljo_mcp.models.sequence_runs import SequenceRun
from giljo_mcp.services.project_staging_service import ProjectStagingService
from giljo_mcp.services.sequence_run_service import SequenceRunService
from giljo_mcp.tenant import TenantManager


pytestmark = pytest.mark.asyncio


async def _seed(db_manager, *, members: int = 2, launched: bool = True) -> tuple[str, str, list[str]]:
    tenant_key = TenantManager.generate_tenant_key()
    pids = [str(uuid.uuid4()) for _ in range(members)]
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
                    status=ProjectStatus.ACTIVE if i == 0 else ProjectStatus.INACTIVE,
                    staging_status="staging_complete",
                    implementation_launched_at=datetime.now(UTC) if launched else None,
                    product_id=product.id,
                    tenant_key=tenant_key,
                    series_number=i + 1,
                )
            )
            session.add(
                AgentJob(
                    job_id=str(uuid.uuid4()),
                    job_type="orchestrator",
                    tenant_key=tenant_key,
                    project_id=pid,
                    mission="orchestrator mission",
                    status="active",
                )
            )
        session.add(
            SequenceRun(
                id=run_id,
                tenant_key=tenant_key,
                project_ids=pids,
                resolved_order=pids,
                current_index=0,
                execution_mode="claude_code_cli",
                status="running",
                locked=True,
                conductor_agent_id="cond-1",
                conductor_project_id=pids[0],
                conductor_label="cond-1",
                project_statuses=dict.fromkeys(pids, "pending"),
            )
        )
        await session.commit()
    return tenant_key, run_id, pids


async def _projects(db_manager, tenant_key: str) -> dict:
    async with db_manager.get_session_async(tenant_key=tenant_key) as session:
        rows = (await session.execute(select(Project).where(Project.tenant_key == tenant_key))).scalars().all()
    return {str(r.id): r for r in rows}


async def _job_count(db_manager, tenant_key: str, project_id: str) -> int:
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
    return len(rows)


def _svc(db_manager) -> SequenceRunService:
    return SequenceRunService(db_manager=db_manager, tenant_manager=TenantManager())


async def test_deactivate_chain_returns_members_to_original_and_dissolves_run(db_manager):
    tenant_key, run_id, pids = await _seed(db_manager)

    result = await _svc(db_manager).deactivate_chain(run_id=run_id, tenant_key=tenant_key)

    assert result["status"] == "cancelled"
    assert result["conductor_agent_id"] is None
    assert result["conductor_project_id"] is None

    projects = await _projects(db_manager, tenant_key)
    for pid in pids:
        p = projects[pid]
        assert p.status == ProjectStatus.INACTIVE
        assert p.staging_status is None
        assert p.implementation_launched_at is None
        assert p.mission == ""
        assert await _job_count(db_manager, tenant_key, pid) == 0


async def test_reset_to_prestage_clears_a_launched_project(db_manager):
    tenant_key, _run_id, pids = await _seed(db_manager, members=1)
    pid = pids[0]

    staging = ProjectStagingService(db_manager=db_manager, tenant_manager=TenantManager())
    out = await staging.reset_to_prestage(pid, tenant_key=tenant_key)

    assert out["deleted"]["jobs"] == 1
    p = (await _projects(db_manager, tenant_key))[pid]
    assert p.staging_status is None
    assert p.implementation_launched_at is None
    assert p.mission == ""
    assert p.status == ProjectStatus.INACTIVE
    assert await _job_count(db_manager, tenant_key, pid) == 0


async def test_hard_deleted_member_is_skipped(db_manager):
    tenant_key, run_id, pids = await _seed(db_manager, members=1)
    phantom = str(uuid.uuid4())
    async with db_manager.get_session_async(tenant_key=tenant_key) as session:
        run = (await session.execute(select(SequenceRun).where(SequenceRun.id == run_id))).scalar_one()
        run.resolved_order = [pids[0], phantom]
        run.project_ids = [pids[0], phantom]
        await session.commit()

    result = await _svc(db_manager).deactivate_chain(run_id=run_id, tenant_key=tenant_key)

    assert result["status"] == "cancelled"
    assert (await _projects(db_manager, tenant_key))[pids[0]].staging_status is None


async def test_unknown_run_raises_not_found(db_manager):
    tenant_key = TenantManager.generate_tenant_key()
    with pytest.raises(ResourceNotFoundError):
        await _svc(db_manager).deactivate_chain(run_id=str(uuid.uuid4()), tenant_key=tenant_key)
