# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.database import tenant_isolation_bypass
from giljo_mcp.models import Product, Project
from giljo_mcp.models.agent_identity import AgentExecution, AgentJob
from giljo_mcp.models.sequence_runs import SequenceRun
from giljo_mcp.services.mission_service import MissionService
from giljo_mcp.services.sequence_run_service import SequenceRunService
from giljo_mcp.tenant import TenantManager
from tests.helpers.taxonomy_seeds import next_series_number


pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture(autouse=True)
async def _wipe_sequence_runs(db_manager):
    yield
    async with db_manager.get_session_async() as session:
        with tenant_isolation_bypass(
            session, reason="test teardown: wipe sequence_runs (per-worker DB)", models=(SequenceRun,)
        ):
            await session.execute(delete(SequenceRun))
        await session.commit()


def _run_svc(session: AsyncSession) -> SequenceRunService:
    return SequenceRunService(db_manager=None, tenant_manager=TenantManager(), session=session)


def _mission_svc(session: AsyncSession) -> MissionService:
    return MissionService(db_manager=None, tenant_manager=TenantManager(), test_session=session)


async def _seed_project(session: AsyncSession, tenant_key: str) -> str:
    _owning_product_project = Product(
        id=str(uuid.uuid4()),
        tenant_key=tenant_key,
        name=f"Owning Product {uuid.uuid4().hex[:6]}",
        description="seeded",
        is_active=False,
    )
    session.add(_owning_product_project)
    project = Project(
        id=str(uuid.uuid4()),
        name=f"BE-6186 {uuid.uuid4().hex[:6]}",
        description="Chain member.",
        mission="m",
        status="active",
        tenant_key=tenant_key,
        product_id=_owning_product_project.id,
        series_number=next_series_number(),
        execution_mode="claude_code_cli",
        created_at=datetime.now(UTC),
    )
    session.add(project)
    session.info["tenant_key"] = tenant_key
    await session.flush()
    return project.id


async def _conductor_job_id(session: AsyncSession, tenant_key: str, conductor_agent_id: str) -> str:
    row = await session.execute(
        select(AgentExecution.job_id).where(
            AgentExecution.tenant_key == tenant_key,
            AgentExecution.agent_id == conductor_agent_id,
        )
    )
    return str(row.scalar_one())




async def test_conductor_mission_mirrors_into_chain_mission(db_session: AsyncSession) -> None:
    tenant = TenantManager.generate_tenant_key()
    p1 = await _seed_project(db_session, tenant)
    p2 = await _seed_project(db_session, tenant)

    run = await _run_svc(db_session).create(
        project_ids=[p1, p2],
        resolved_order=[p1, p2],
        execution_mode="claude_code_cli",
        tenant_key=tenant,
    )
    conductor_job_id = await _conductor_job_id(db_session, tenant, run["conductor_agent_id"])

    plan = "Build A, wire A into B, then run the B migration."
    await _mission_svc(db_session).update_agent_mission(conductor_job_id, tenant, plan)

    fetched = await _run_svc(db_session).get(run_id=run["id"], tenant_key=tenant)
    assert fetched["chain_mission"] == plan, "the conductor's job mission must mirror into sequence_runs.chain_mission"


async def test_conductor_mission_write_broadcasts_sequence_updated(db_session: AsyncSession) -> None:
    import sys
    import types
    from unittest.mock import AsyncMock

    if "api" not in sys.modules:
        _api_stub = types.ModuleType("api")
        _api_stub.__path__ = ["api"]
        _api_stub.__package__ = "api"
        sys.modules["api"] = _api_stub
    from api.websocket import WebSocketManager

    tenant = TenantManager.generate_tenant_key()
    p1 = await _seed_project(db_session, tenant)
    p2 = await _seed_project(db_session, tenant)
    run = await _run_svc(db_session).create(
        project_ids=[p1, p2], resolved_order=[p1, p2], execution_mode="claude_code_cli", tenant_key=tenant
    )
    conductor_job_id = await _conductor_job_id(db_session, tenant, run["conductor_agent_id"])

    ws = AsyncMock(spec=WebSocketManager)
    mission_svc = MissionService(
        db_manager=None, tenant_manager=TenantManager(), test_session=db_session, websocket_manager=ws
    )
    await mission_svc.update_agent_mission(conductor_job_id, tenant, "Drive the chain.")

    ws.broadcast_event_to_tenant.assert_any_await(tenant, {"type": "sequence:updated", "data": {"run_id": run["id"]}})




async def test_non_conductor_job_does_not_touch_any_run(db_session: AsyncSession) -> None:
    tenant = TenantManager.generate_tenant_key()
    p1 = await _seed_project(db_session, tenant)
    p2 = await _seed_project(db_session, tenant)

    run = await _run_svc(db_session).create(
        project_ids=[p1, p2],
        resolved_order=[p1, p2],
        execution_mode="claude_code_cli",
        tenant_key=tenant,
    )
    assert run["chain_mission"] is None

    job_id = str(uuid.uuid4())
    db_session.add(
        AgentJob(
            job_id=job_id,
            tenant_key=tenant,
            project_id=p1,
            mission=None,
            job_type="orchestrator",
            status="active",
            job_metadata={},
        )
    )
    db_session.add(
        AgentExecution(
            agent_id=str(uuid.uuid4()),
            job_id=job_id,
            tenant_key=tenant,
            agent_display_name="orchestrator",
            agent_name="Sub",
            status="waiting",
            health_status="unknown",
            project_phase="staging",
        )
    )
    db_session.info["tenant_key"] = tenant
    await db_session.flush()

    await _mission_svc(db_session).update_agent_mission(job_id, tenant, "A non-conductor plan.")

    fetched = await _run_svc(db_session).get(run_id=run["id"], tenant_key=tenant)
    assert fetched["chain_mission"] is None, "a non-conductor job must NOT write chain_mission on any run"




async def test_mirror_is_best_effort_when_run_missing(db_session: AsyncSession) -> None:
    tenant = TenantManager.generate_tenant_key()
    job_id = str(uuid.uuid4())
    db_session.add(
        AgentJob(
            job_id=job_id,
            tenant_key=tenant,
            project_id=None,
            mission=None,
            job_type="orchestrator",
            status="active",
            job_metadata={"chain_conductor": True, "run_id": str(uuid.uuid4())},
        )
    )
    db_session.add(
        AgentExecution(
            agent_id=str(uuid.uuid4()),
            job_id=job_id,
            tenant_key=tenant,
            agent_display_name="orchestrator",
            agent_name="Conductor",
            status="waiting",
            health_status="unknown",
            project_phase="implementation",
        )
    )
    db_session.info["tenant_key"] = tenant
    await db_session.flush()

    result = await _mission_svc(db_session).update_agent_mission(job_id, tenant, "orphan conductor plan")
    assert result.mission_updated is True, "the primary mission write must succeed even when the mirror has no run"
