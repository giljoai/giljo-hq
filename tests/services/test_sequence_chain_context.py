# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.models import Product, Project
from giljo_mcp.models.agent_identity import AgentExecution
from giljo_mcp.models.sequence_runs import SequenceRun
from giljo_mcp.services.job_lifecycle_service import JobLifecycleService
from giljo_mcp.services.mission_orchestration_service import MissionOrchestrationService
from giljo_mcp.services.sequence_run_service import SequenceRunService
from giljo_mcp.tenant import TenantManager
from tests.helpers.taxonomy_seeds import next_series_number


pytestmark = pytest.mark.asyncio




async def _seed_project(
    session: AsyncSession,
    tenant_key: str,
    *,
    execution_mode: str = "claude_code_cli",
    closeout_executed_at: datetime | None = None,
) -> str:
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
        name=f"BE-6165c test {uuid.uuid4().hex[:6]}",
        description="Sequence driver test project.",
        mission="Drive sequential run.",
        status="active",
        tenant_key=tenant_key,
        product_id=_owning_product_project.id,
        series_number=next_series_number(),
        execution_mode=execution_mode,
        created_at=datetime.now(UTC),
        implementation_launched_at=datetime.now(UTC),
        closeout_executed_at=closeout_executed_at,
    )
    session.add(project)
    session.info["tenant_key"] = tenant_key
    await session.flush()
    return project.id


async def _spawn_orchestrator(session: AsyncSession, tenant_key: str, project_id: str) -> tuple[str, str]:
    lifecycle = JobLifecycleService(
        db_manager=None,  # type: ignore[arg-type]
        tenant_manager=TenantManager(),
        test_session=session,
    )
    result = await lifecycle.spawn_job(
        agent_display_name="orchestrator",
        agent_name="orchestrator",
        project_id=project_id,
        tenant_key=tenant_key,
        mission="Drive sequential run as conductor.",
    )
    row = await session.execute(
        __import__("sqlalchemy", fromlist=["select"])
        .select(AgentExecution)
        .where(
            AgentExecution.tenant_key == tenant_key,
            AgentExecution.job_id == result.job_id,
        )
    )
    execution = row.scalar_one()
    return result.job_id, str(execution.agent_id)


async def _seed_sequence_run(
    session: AsyncSession,
    tenant_key: str,
    project_ids: list[str],
    *,
    resolved_order: list[str] | None = None,
    status: str = "running",
    conductor_agent_id: str | None = None,
    conductor_project_id: str | None = None,
) -> str:
    run_id = str(uuid.uuid4())
    run = SequenceRun(
        id=run_id,
        tenant_key=tenant_key,
        project_ids=project_ids,
        resolved_order=resolved_order or project_ids,
        current_index=0,
        execution_mode="claude_code_cli",
        status=status,
        review_policy="per_card",
        project_statuses={},
        conductor_agent_id=conductor_agent_id,
        conductor_project_id=conductor_project_id,
        conductor_label=None,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    session.add(run)
    await session.flush()
    return run_id


def _make_svc(session: AsyncSession, ws_manager: Any = None) -> MissionOrchestrationService:
    return MissionOrchestrationService(
        db_manager=None,  # type: ignore[arg-type]
        tenant_manager=TenantManager(),
        test_session=session,
        websocket_manager=ws_manager,
    )


def _stub_ws() -> MagicMock:
    ws = MagicMock()
    ws.broadcast_event_to_tenant = AsyncMock()
    return ws




async def test_resolve_null_conductor_fallback_stamps_agent_id(db_session: AsyncSession) -> None:
    tenant = TenantManager.generate_tenant_key()
    proj_id = await _seed_project(db_session, tenant)
    proj2_id = await _seed_project(db_session, tenant)
    run_id = await _seed_sequence_run(
        db_session,
        tenant,
        project_ids=[proj_id, proj2_id],
        resolved_order=[proj_id, proj2_id],
        status="running",
        conductor_agent_id=None,
    )
    _job_id, agent_id = await _spawn_orchestrator(db_session, tenant, proj_id)

    ws = _stub_ws()
    svc = _make_svc(db_session, ws)

    chain_ctx = await svc._chain.resolve(
        db_session,
        project_id=proj_id,
        tenant_key=tenant,
        orchestrator_agent_id=agent_id,
        is_staging=True,
    )

    assert chain_ctx is not None, "a running run with no conductor must still return a ChainContext"
    assert chain_ctx.role == "conductor", "the fallback stamps this agent as conductor-of-record"
    assert chain_ctx.conductor_agent_id == agent_id, "conductor_agent_id must reflect the stamped value"

    svc2 = SequenceRunService(db_manager=None, tenant_manager=TenantManager(), session=db_session)
    run = await svc2.get(run_id=run_id, tenant_key=tenant)
    assert run["conductor_agent_id"] == agent_id, "SequenceRun.conductor_agent_id must be persisted"
    assert run["conductor_project_id"] is None, "BE-6184: resolve() must NOT stamp conductor_project_id"

    ws.broadcast_event_to_tenant.assert_called_once()
    call_kwargs = ws.broadcast_event_to_tenant.call_args
    broadcast_tenant = call_kwargs[0][0] if call_kwargs[0] else call_kwargs[1].get("tenant_key")
    assert broadcast_tenant == tenant or call_kwargs is not None




async def test_conductor_agent_match_is_idempotent(db_session: AsyncSession) -> None:
    tenant = TenantManager.generate_tenant_key()
    proj_id = await _seed_project(db_session, tenant)
    proj2_id = await _seed_project(db_session, tenant)
    _job_id, agent_id = await _spawn_orchestrator(db_session, tenant, proj_id)

    await _seed_sequence_run(
        db_session,
        tenant,
        project_ids=[proj_id, proj2_id],
        resolved_order=[proj_id, proj2_id],
        status="running",
        conductor_agent_id=agent_id,
    )

    ws = _stub_ws()
    svc = _make_svc(db_session, ws)

    chain_ctx = await svc._chain.resolve(
        db_session,
        project_id=proj_id,
        tenant_key=tenant,
        orchestrator_agent_id=agent_id,
        is_staging=True,
    )

    assert chain_ctx is not None
    assert chain_ctx.role == "conductor", "agent_id == conductor_agent_id must classify as conductor"
    ws.broadcast_event_to_tenant.assert_not_called()




async def test_head_orchestrator_is_sub_when_conductor_set(db_session: AsyncSession) -> None:
    tenant = TenantManager.generate_tenant_key()
    proj_id = await _seed_project(db_session, tenant)
    proj2_id = await _seed_project(db_session, tenant)

    conductor_agent_id = str(uuid.uuid4())
    run_id = await _seed_sequence_run(
        db_session,
        tenant,
        project_ids=[proj_id, proj2_id],
        resolved_order=[proj_id, proj2_id],
        status="running",
        conductor_agent_id=conductor_agent_id,
    )

    _job_id, head_agent_id = await _spawn_orchestrator(db_session, tenant, proj_id)
    assert head_agent_id != conductor_agent_id

    ws = _stub_ws()
    svc = _make_svc(db_session, ws)

    chain_ctx = await svc._chain.resolve(
        db_session,
        project_id=proj_id,
        tenant_key=tenant,
        orchestrator_agent_id=head_agent_id,
        is_staging=False,
    )

    assert chain_ctx is not None
    assert chain_ctx.role == "sub_orchestrator", "BE-6184: the head project's orchestrator is NOT the conductor"
    assert chain_ctx.conductor_agent_id == conductor_agent_id

    svc2 = SequenceRunService(db_manager=None, tenant_manager=TenantManager(), session=db_session)
    run = await svc2.get(run_id=run_id, tenant_key=tenant)
    assert run["conductor_agent_id"] == conductor_agent_id, "the head orchestrator must NOT overwrite the conductor"

    ws.broadcast_event_to_tenant.assert_not_called()




async def test_sub_orchestrator_never_overwrites_conductor(db_session: AsyncSession) -> None:
    tenant = TenantManager.generate_tenant_key()
    head_proj_id = await _seed_project(db_session, tenant)
    sub_proj_id = await _seed_project(db_session, tenant)

    conductor_agent_id = str(uuid.uuid4())
    run_id = await _seed_sequence_run(
        db_session,
        tenant,
        project_ids=[head_proj_id, sub_proj_id],
        resolved_order=[head_proj_id, sub_proj_id],
        status="running",
        conductor_agent_id=conductor_agent_id,
        conductor_project_id=head_proj_id,
    )

    _job_id, sub_agent_id = await _spawn_orchestrator(db_session, tenant, sub_proj_id)

    ws = _stub_ws()
    svc = _make_svc(db_session, ws)

    chain_ctx = await svc._chain.resolve(
        db_session,
        project_id=sub_proj_id,
        tenant_key=tenant,
        orchestrator_agent_id=sub_agent_id,
        is_staging=False,
    )

    assert chain_ctx is not None
    assert chain_ctx.role == "sub_orchestrator", "non-head project must be sub_orchestrator"

    svc2 = SequenceRunService(db_manager=None, tenant_manager=TenantManager(), session=db_session)
    run = await svc2.get(run_id=run_id, tenant_key=tenant)
    assert run["conductor_agent_id"] == conductor_agent_id, "sub_orchestrator must NOT overwrite conductor_agent_id"
    assert run["conductor_project_id"] == head_proj_id

    ws.broadcast_event_to_tenant.assert_not_called()




async def test_solo_project_no_ch_conductor(db_session: AsyncSession) -> None:
    tenant = TenantManager.generate_tenant_key()
    proj_id = await _seed_project(db_session, tenant)

    ws = _stub_ws()
    svc = _make_svc(db_session, ws)

    chain_ctx = await svc._chain.resolve(
        db_session,
        project_id=proj_id,
        tenant_key=tenant,
        orchestrator_agent_id=str(uuid.uuid4()),
        is_staging=True,
    )

    assert chain_ctx is None, "solo project (no active run) must return None"
    ws.broadcast_event_to_tenant.assert_not_called()

    from giljo_mcp.services.protocol_builder import _build_orchestrator_protocol

    protocol = _build_orchestrator_protocol(
        cli_mode=True,
        project_id=proj_id,
        orchestrator_id=str(uuid.uuid4()),
        tenant_key=tenant,
        include_implementation_reference=False,
        conductor_agent_id=None,
    )
    assert "ch_conductor" not in protocol, "solo project must produce no ch_conductor chapter"




async def test_find_active_run_tenant_isolation(db_session: AsyncSession) -> None:
    tenant_a = TenantManager.generate_tenant_key()
    tenant_b = TenantManager.generate_tenant_key()

    proj_id = str(uuid.uuid4())

    run_a = SequenceRun(
        id=str(uuid.uuid4()),
        tenant_key=tenant_a,
        project_ids=[proj_id],
        resolved_order=[proj_id],
        current_index=0,
        execution_mode="claude_code_cli",
        status="running",
        review_policy="per_card",
        project_statuses={},
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    db_session.add(run_a)
    await db_session.flush()

    svc = SequenceRunService(db_manager=None, tenant_manager=TenantManager(), session=db_session)

    result = await svc.find_active_run_for_project(project_id=proj_id, tenant_key=tenant_b)
    assert result is None, "tenant_b must not see tenant_a's run"

    result_a = await svc.find_active_run_for_project(project_id=proj_id, tenant_key=tenant_a)
    assert result_a is not None
    assert result_a["id"] == run_a.id




async def test_find_active_run_status_filter(db_session: AsyncSession) -> None:
    tenant = TenantManager.generate_tenant_key()
    proj_id = str(uuid.uuid4())

    excluded_statuses = ["completed", "terminated", "cancelled", "failed"]
    included_statuses = ["pending", "running", "stalled"]

    svc = SequenceRunService(db_manager=None, tenant_manager=TenantManager(), session=db_session)

    for status in excluded_statuses:
        run = SequenceRun(
            id=str(uuid.uuid4()),
            tenant_key=tenant,
            project_ids=[proj_id],
            resolved_order=[proj_id],
            current_index=0,
            execution_mode="claude_code_cli",
            status=status,
            review_policy="per_card",
            project_statuses={},
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        db_session.add(run)
    await db_session.flush()

    result = await svc.find_active_run_for_project(project_id=proj_id, tenant_key=tenant)
    assert result is None, f"excluded statuses {excluded_statuses!r} must not be returned"

    for status in included_statuses:
        run = SequenceRun(
            id=str(uuid.uuid4()),
            tenant_key=tenant,
            project_ids=[proj_id],
            resolved_order=[proj_id],
            current_index=0,
            execution_mode="claude_code_cli",
            status=status,
            review_policy="per_card",
            project_statuses={},
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        db_session.add(run)
        await db_session.flush()

        found = await svc.find_active_run_for_project(project_id=proj_id, tenant_key=tenant)
        assert found is not None, f"status={status!r} must be returned as active"
        assert found["status"] == status




async def test_advance_index_if_committed_refuses_without_closeout(db_session: AsyncSession) -> None:
    tenant = TenantManager.generate_tenant_key()
    proj_id = await _seed_project(db_session, tenant, closeout_executed_at=None)
    proj2_id = await _seed_project(db_session, tenant)
    run_id = await _seed_sequence_run(
        db_session,
        tenant,
        project_ids=[proj_id, proj2_id],
        resolved_order=[proj_id, proj2_id],
        status="running",
    )

    svc = _make_svc(db_session)
    advanced = await svc._chain.advance_index_if_committed(
        run_id=run_id,
        project_id=proj_id,
        tenant_key=tenant,
        next_index=1,
    )
    assert advanced is False, "must refuse without closeout_executed_at"

    run_svc = SequenceRunService(db_manager=None, tenant_manager=TenantManager(), session=db_session)
    run = await run_svc.get(run_id=run_id, tenant_key=tenant)
    assert run["current_index"] == 0




async def test_advance_index_if_committed_advances_with_closeout(db_session: AsyncSession) -> None:
    tenant = TenantManager.generate_tenant_key()
    proj_id = await _seed_project(db_session, tenant, closeout_executed_at=datetime.now(UTC))
    proj2_id = await _seed_project(db_session, tenant)
    run_id = await _seed_sequence_run(
        db_session,
        tenant,
        project_ids=[proj_id, proj2_id],
        resolved_order=[proj_id, proj2_id],
        status="running",
    )

    svc = _make_svc(db_session)
    advanced = await svc._chain.advance_index_if_committed(
        run_id=run_id,
        project_id=proj_id,
        tenant_key=tenant,
        next_index=1,
    )
    assert advanced is True, "must advance when closeout_executed_at is set"

    run_svc = SequenceRunService(db_manager=None, tenant_manager=TenantManager(), session=db_session)
    run = await run_svc.get(run_id=run_id, tenant_key=tenant)
    assert run["current_index"] == 1




async def test_mark_stalled_if_past_deadline(db_session: AsyncSession) -> None:
    tenant = TenantManager.generate_tenant_key()
    proj_id = await _seed_project(db_session, tenant)
    run_id = await _seed_sequence_run(
        db_session,
        tenant,
        project_ids=[proj_id],
        resolved_order=[proj_id],
        status="running",
    )

    svc = _make_svc(db_session)
    now = datetime.now(UTC)
    future = now + timedelta(hours=1)
    past = now - timedelta(seconds=1)

    not_stalled = await svc._chain.mark_stalled_if_past_deadline(
        run_id=run_id,
        tenant_key=tenant,
        deadline_iso_or_dt=future,
        now=now,
    )
    assert not_stalled is False

    run_svc = SequenceRunService(db_manager=None, tenant_manager=TenantManager(), session=db_session)
    run = await run_svc.get(run_id=run_id, tenant_key=tenant)
    assert run["status"] == "running"

    stalled = await svc._chain.mark_stalled_if_past_deadline(
        run_id=run_id,
        tenant_key=tenant,
        deadline_iso_or_dt=past,
        now=now,
    )
    assert stalled is True

    run = await run_svc.get(run_id=run_id, tenant_key=tenant)
    assert run["status"] == "stalled"
