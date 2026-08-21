# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""FE-6199 — chain staging live-fill: sequence:updated broadcast on writes that
arm the chain Implement button.

The chain cockpit's Implement button arms when the run is locked (Stage Chain
pressed) AND chain_mission is written by the conductor. Both writes go through
SequenceRunService.update(), which broadcasts sequence:updated. This file
confirms both broadcasts fire so the FE can live-fill the chain-mission window
and arm the Implement button without a manual page refresh.

1. test_stage_chain_lock_broadcasts_sequence_updated
   PATCH /api/v1/sequence-runs/<id> with locked=True (the Stage Chain FE action)
   routes through SequenceRunService.update() and fires sequence:updated.

2. test_chain_mission_write_broadcasts_sequence_updated
   conductor update_job_mission -> mirror_chain_mission_for_conductor ->
   SequenceRunService.update(chain_mission=...) fires sequence:updated.
   (Companion to test_conductor_mission_write_broadcasts_sequence_updated in
   test_be6186_conductor_mission_mirror.py -- this copy is a focused regression
   pinned to the FE-6199 live-fill fix; that file tests the mirror mechanics.)

Both tests mock WebSocketManager and assert broadcast_event_to_tenant is called
with the correct sequence:updated event. Edition Scope: CE.
"""

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
    """Ensure 'api' package is importable (not present in all test workers)."""
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
    # BE-9437: a project belongs to a product. Its own, so an active
    # seed cannot collide under idx_project_single_active_per_product.
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
        # BE-9429: uq_project_taxonomy_active is NULLS NOT DISTINCT, so these
        # NULL-product/NULL-type rows collide unless the serial differs.
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


# ---------------------------------------------------------------------------
# 1. Stage Chain lock -> sequence:updated
# ---------------------------------------------------------------------------


async def test_stage_chain_lock_broadcasts_sequence_updated(db_session: AsyncSession) -> None:
    """PATCH locked=True (Stage Chain) must broadcast sequence:updated (FE-6199).

    The FE patchRun(runId, {locked: true}) call hits SequenceRunService.update()
    which fires _broadcast_sequence_updated. This test confirms the broadcast so
    the cockpit's chainCtx.locked -> chainImplementReady gate can react live.
    """
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


# ---------------------------------------------------------------------------
# 2. chain_mission write -> sequence:updated (via conductor update_job_mission)
# ---------------------------------------------------------------------------


async def test_chain_mission_write_broadcasts_sequence_updated(db_session: AsyncSession) -> None:
    """conductor update_job_mission -> mirror -> SequenceRunService.update(chain_mission=)
    must broadcast sequence:updated so the cockpit chain-mission window live-fills.

    Regression for the FE-6199 live-fill gap: without the websocket_manager threaded
    through mirror_chain_mission_for_conductor, the SequenceRunService.update() inside
    the mirror had no ws manager -> broadcast was a no-op -> chain-mission window stayed
    blank until a manual refresh.
    """
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
