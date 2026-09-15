# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.exceptions import ResourceNotFoundError
from giljo_mcp.models import Product, Project
from giljo_mcp.models.sequence_runs import SequenceRun
from giljo_mcp.services.job_completion_service import JobCompletionService
from giljo_mcp.services.project_closeout_service import ProjectCloseoutService
from giljo_mcp.services.project_staging_service import ProjectStagingService
from giljo_mcp.services.sequence_run_service import SequenceRunService
from giljo_mcp.tenant import TenantManager
from giljo_mcp.tools.project_closeout import close_project_and_update_memory


pytestmark = pytest.mark.asyncio


_DB_MANAGER_SENTINEL = object()


def _mock_ws() -> MagicMock:
    ws = MagicMock()
    ws.broadcast_event_to_tenant = AsyncMock()
    ws.broadcast_project_update = AsyncMock()
    ws.broadcast_to_tenant = AsyncMock()
    return ws


def _sequence_updated_events(mock_ws: MagicMock) -> list[dict]:
    events: list[dict] = []
    for call in mock_ws.broadcast_event_to_tenant.await_args_list:
        args, kwargs = call
        event = kwargs.get("event") if "event" in kwargs else (args[1] if len(args) > 1 else None)
        if isinstance(event, dict) and event.get("type") == "sequence:updated":
            events.append(event)
    return events


async def _seed_project(session: AsyncSession, tenant_key: str) -> str:
    product = Product(
        id=str(uuid.uuid4()),
        name=f"BE-6198 LU Product {uuid.uuid4().hex[:6]}",
        description="Chain product.",
        tenant_key=tenant_key,
        is_active=False,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    session.add(product)
    await session.flush()
    project = Project(
        id=str(uuid.uuid4()),
        name=f"BE-6198 LU {uuid.uuid4().hex[:6]}",
        description="Chain member.",
        mission="Be a chain member.",
        status="active",
        tenant_key=tenant_key,
        product_id=product.id,
        series_number=1,
        execution_mode="claude_code_cli",
        created_at=datetime.now(UTC),
    )
    session.add(project)
    session.info["tenant_key"] = tenant_key
    await session.flush()
    return project.id


async def _insert_run(
    session: AsyncSession,
    tenant_key: str,
    project_ids: list[str],
    resolved_order: list[str],
    project_statuses: dict[str, str],
    *,
    status: str = "running",
    current_index: int = 0,
) -> SequenceRun:
    run = SequenceRun(
        id=str(uuid.uuid4()),
        tenant_key=tenant_key,
        project_ids=project_ids,
        resolved_order=resolved_order,
        project_statuses=project_statuses,
        status=status,
        current_index=current_index,
        execution_mode="claude_code_cli",
        review_policy="per_card",
    )
    session.add(run)
    await session.flush()
    return run


def _run_svc(session: AsyncSession) -> SequenceRunService:
    return SequenceRunService(db_manager=None, tenant_manager=TenantManager(), session=session)




async def test_close_out_project_broadcasts_sequence_updated(db_session: AsyncSession) -> None:
    tenant = TenantManager.generate_tenant_key()
    pid = await _seed_project(db_session, tenant)
    await _insert_run(db_session, tenant, [pid], [pid], {pid: "implementing"}, status="running")

    mock_ws = _mock_ws()
    svc = ProjectCloseoutService(
        db_manager=None,
        tenant_manager=TenantManager(),
        test_session=db_session,
        websocket_manager=mock_ws,
    )
    project_row = (await db_session.execute(select(Project).where(Project.id == pid))).scalar_one()
    await svc.close_out_project(pid, tenant)

    events = _sequence_updated_events(mock_ws)
    assert events, "close_out_project must emit sequence:updated via the threaded websocket_manager"

    mock_ws.broadcast_project_update.assert_awaited_once()
    assert mock_ws.broadcast_project_update.await_args.kwargs["project_data"]["product_id"] == project_row.product_id




async def test_mcp_closeout_broadcasts_sequence_updated_and_project_update(
    db_session: AsyncSession, monkeypatch
) -> None:
    tenant = TenantManager.generate_tenant_key()
    pid = await _seed_project(db_session, tenant)
    await _insert_run(db_session, tenant, [pid], [pid], {pid: "implementing"}, status="running")

    mock_ws = _mock_ws()
    monkeypatch.setattr(
        "giljo_mcp.app_registry.service_registry.get_websocket_manager",
        lambda: mock_ws,
    )

    await close_project_and_update_memory(
        project_id=pid,
        summary="done",
        key_outcomes=["x"],
        decisions_made=["y"],
        tenant_key=tenant,
        db_manager=_DB_MANAGER_SENTINEL,
        session=db_session,
        force=True,
    )

    assert _sequence_updated_events(mock_ws), "the MCP closeout must emit sequence:updated for the per-member badge"

    pu_calls = mock_ws.broadcast_project_update.await_args_list
    assert pu_calls, "the chain closeout must emit project_update for the 'Project Completed and Closed' chip"
    last_kwargs = pu_calls[-1].kwargs
    assert last_kwargs.get("update_type") == "status_changed"
    assert last_kwargs.get("project_data", {}).get("status") == "completed"
    assert last_kwargs.get("tenant_key") == tenant


async def test_mcp_closeout_solo_does_not_broadcast_project_update(db_session: AsyncSession, monkeypatch) -> None:
    tenant = TenantManager.generate_tenant_key()
    p_solo = await _seed_project(db_session, tenant)

    mock_ws = _mock_ws()
    monkeypatch.setattr(
        "giljo_mcp.app_registry.service_registry.get_websocket_manager",
        lambda: mock_ws,
    )

    await close_project_and_update_memory(
        project_id=p_solo,
        summary="solo done",
        key_outcomes=["x"],
        decisions_made=["y"],
        tenant_key=tenant,
        db_manager=_DB_MANAGER_SENTINEL,
        session=db_session,
        force=True,
    )

    assert not mock_ws.broadcast_project_update.await_args_list, "solo closeout must NOT emit a chain project_update"
    assert not _sequence_updated_events(mock_ws), "solo closeout has no run to broadcast sequence:updated for"




async def test_launch_implementation_advance_broadcasts_sequence_updated(db_session: AsyncSession) -> None:
    tenant = TenantManager.generate_tenant_key()
    p1 = await _seed_project(db_session, tenant)
    p2 = await _seed_project(db_session, tenant)
    run = await _insert_run(db_session, tenant, [p1, p2], [p1, p2], {p1: "completed"}, current_index=0)

    p1_row = (await db_session.execute(select(Project).where(Project.id == p1))).scalar_one()
    p1_row.closeout_executed_at = datetime.now(UTC)
    p2_row = (await db_session.execute(select(Project).where(Project.id == p2))).scalar_one()
    p2_row.staging_status = "staging_complete"
    p2_row.implementation_launched_at = None
    await db_session.flush()

    mock_ws = _mock_ws()
    staging_svc = ProjectStagingService(
        db_manager=None,
        tenant_manager=TenantManager(),
        test_session=db_session,
        websocket_manager=mock_ws,
        lifecycle_service=None,
    )
    await staging_svc.launch_implementation(project_id=p2, tenant_key=tenant)

    refetched = await _run_svc(db_session).get(run_id=run.id, tenant_key=tenant)
    assert refetched["current_index"] == 1, "launch across the gate must advance current_index to 1"
    assert _sequence_updated_events(mock_ws), "the chain launch advance must emit sequence:updated"




async def _seed_two_project_run_with_conductor(session: AsyncSession, tenant_key: str) -> dict:
    p1 = await _seed_project(session, tenant_key)
    p2 = await _seed_project(session, tenant_key)
    run = await _run_svc(session).create(
        project_ids=[p1, p2],
        resolved_order=[p1, p2],
        execution_mode="claude_code_cli",
        tenant_key=tenant_key,
    )
    run["_project_ids"] = [p1, p2]
    return run


async def test_conductor_final_complete_job_broadcasts_run_finish(db_session: AsyncSession) -> None:
    from giljo_mcp.models.agent_identity import AgentExecution, AgentJob

    tenant = TenantManager.generate_tenant_key()
    run = await _seed_two_project_run_with_conductor(db_session, tenant)
    p1, p2 = run["_project_ids"]
    conductor_agent_id = run["conductor_agent_id"]

    await _run_svc(db_session).update(
        run_id=run["id"],
        tenant_key=tenant,
        project_statuses={p1: "completed", p2: "completed"},
    )

    execution = (
        await db_session.execute(
            select(AgentExecution).where(
                AgentExecution.tenant_key == tenant,
                AgentExecution.agent_id == conductor_agent_id,
            )
        )
    ).scalar_one()
    job = (
        await db_session.execute(
            select(AgentJob).where(AgentJob.tenant_key == tenant, AgentJob.job_id == execution.job_id)
        )
    ).scalar_one()

    mock_ws = _mock_ws()
    completion_svc = JobCompletionService(
        db_manager=None,
        tenant_manager=TenantManager(),
        test_session=db_session,
        websocket_manager=mock_ws,
    )
    await completion_svc.complete_job(job_id=job.job_id, result={"summary": "chain done"}, tenant_key=tenant)

    assert _sequence_updated_events(mock_ws), "the conductor's run-finish must emit sequence:updated"
    with pytest.raises(ResourceNotFoundError):
        await _run_svc(db_session).get(run_id=run["id"], tenant_key=tenant)
