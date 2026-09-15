# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import sys
import types
import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.database import tenant_isolation_bypass
from giljo_mcp.models import Product, Project
from giljo_mcp.models.agent_identity import AgentExecution
from giljo_mcp.models.sequence_runs import SequenceRun
from giljo_mcp.services.sequence_run_service import SequenceRunService
from giljo_mcp.tenant import TenantManager
from tests.helpers.taxonomy_seeds import next_series_number


pytestmark = pytest.mark.asyncio


def _ensure_api_stub() -> None:
    if "api" not in sys.modules:
        stub = types.ModuleType("api")
        stub.__path__ = ["api"]
        stub.__package__ = "api"
        sys.modules["api"] = stub


@pytest_asyncio.fixture(autouse=True)
async def _wipe_sequence_runs(db_manager):
    yield
    async with db_manager.get_session_async() as session:
        with tenant_isolation_bypass(
            session, reason="test teardown: wipe sequence_runs (per-worker DB)", models=(SequenceRun,)
        ):
            await session.execute(delete(SequenceRun))
        await session.commit()


def _run_svc(session: AsyncSession, ws=None) -> SequenceRunService:
    return SequenceRunService(
        db_manager=None,
        tenant_manager=TenantManager(),
        session=session,
        websocket_manager=ws,
    )


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
        name=f"FE-6199 {uuid.uuid4().hex[:6]}",
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




async def test_stage_chain_lock_broadcasts_sequence_updated(db_session: AsyncSession) -> None:
    _ensure_api_stub()
    from api.websocket import WebSocketManager

    tenant = TenantManager.generate_tenant_key()
    p1 = await _seed_project(db_session, tenant)
    p2 = await _seed_project(db_session, tenant)
    ws = AsyncMock(spec=WebSocketManager)
    svc = _run_svc(db_session, ws)
    run = await svc.create(
        project_ids=[p1, p2],
        resolved_order=[p1, p2],
        execution_mode="claude_code_cli",
        tenant_key=tenant,
    )
    run_id = run["id"]

    ws.reset_mock()
    await svc.update(run_id=run_id, tenant_key=tenant, locked=True)

    ws.broadcast_event_to_tenant.assert_any_await(tenant, {"type": "sequence:updated", "data": {"run_id": run_id}})




async def test_chain_mission_write_broadcasts_sequence_updated(db_session: AsyncSession) -> None:
    _ensure_api_stub()
    from api.websocket import WebSocketManager
    from giljo_mcp.services.mission_service import MissionService

    tenant = TenantManager.generate_tenant_key()
    p1 = await _seed_project(db_session, tenant)
    p2 = await _seed_project(db_session, tenant)

    no_ws_svc = _run_svc(db_session)
    run = await no_ws_svc.create(
        project_ids=[p1, p2],
        resolved_order=[p1, p2],
        execution_mode="claude_code_cli",
        tenant_key=tenant,
    )
    conductor_job_id = await _conductor_job_id(db_session, tenant, run["conductor_agent_id"])

    ws = AsyncMock(spec=WebSocketManager)
    mission_svc = MissionService(
        db_manager=None,
        tenant_manager=TenantManager(),
        test_session=db_session,
        websocket_manager=ws,
    )
    await mission_svc.update_agent_mission(conductor_job_id, tenant, "Stage A, then B.")

    ws.broadcast_event_to_tenant.assert_any_await(tenant, {"type": "sequence:updated", "data": {"run_id": run["id"]}})
