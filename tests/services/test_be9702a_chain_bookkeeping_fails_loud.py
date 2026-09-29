# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import ast
import uuid
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.exceptions import DatabaseError, ValidationError
from giljo_mcp.models.products import Product
from giljo_mcp.models.projects import Project
from giljo_mcp.models.sequence_runs import SequenceRun
from giljo_mcp.services.project_helpers import advance_chain_member_to_implementing, mark_chain_member_status
from giljo_mcp.services.sequence_run_service import SequenceRunService
from giljo_mcp.tenant import TenantManager
from tests.helpers.taxonomy_seeds import next_series_number


SRC = Path(__file__).resolve().parents[2] / "src" / "giljo_mcp"
_LOOKUPS = {"find_active_run_for_project", "active_chain_run"}
_LOOP_EXEMPT = {"services/silence_detector.py"}
_CHAIN_CHECK_SITES = (
    "services/job_lifecycle_service.py",
    "services/job_completion_service.py",
    "services/job_completion_staging.py",
    "services/mission_implementation_gate.py",
    "services/mission_orchestration_service.py",
    "services/not_picked_up.py",
    "services/mission_service.py",
    "services/job_completion_closeout_gate.py",
    "tools/tool_accessor/_project_tools.py",
)


class _ChainStoreDownError(Exception):
    pass


def _is_broad(handler: ast.ExceptHandler) -> bool:
    types = handler.type.elts if isinstance(handler.type, ast.Tuple) else [handler.type]
    return any(t is None or (isinstance(t, ast.Name) and t.id in {"Exception", "BaseException"}) for t in types)


def _calls_lookup(nodes: list[ast.stmt]) -> bool:
    for stmt in nodes:
        for node in ast.walk(stmt):
            if isinstance(node, ast.Call):
                func = node.func
                name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
                if name in _LOOKUPS:
                    return True
    return False


def test_no_chain_run_lookup_is_wrapped_in_a_swallowing_except() -> None:
    offenders = []
    for path in SRC.rglob("*.py"):
        rel = path.relative_to(SRC).as_posix()
        if rel in _LOOP_EXEMPT:
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not isinstance(node, ast.Try) or not _calls_lookup(node.body):
                continue
            for handler in node.handlers:
                reraises = any(isinstance(n, ast.Raise) for n in ast.walk(handler))
                if _is_broad(handler) and not reraises:
                    offenders.append(f"{rel}:{node.lineno}")
    assert offenders == [], f"chain-run lookups that answer 'solo' on error: {offenders}"


def test_every_chain_check_site_uses_the_one_helper() -> None:
    missing = [rel for rel in _CHAIN_CHECK_SITES if "active_chain_run(" not in (SRC / rel).read_text(encoding="utf-8")]
    assert missing == [], f"chain checks not routed through active_chain_run: {missing}"


async def _seed_project(session: AsyncSession, tenant_key: str, **fields) -> str:
    product = Product(
        id=str(uuid.uuid4()), tenant_key=tenant_key, name=f"P {uuid.uuid4().hex[:6]}", description="x", is_active=False
    )
    session.add(product)
    project = Project(
        id=str(uuid.uuid4()),
        name=f"BE-9702a {uuid.uuid4().hex[:6]}",
        description="chain member",
        mission="m",
        status="active",
        tenant_key=tenant_key,
        product_id=product.id,
        series_number=next_series_number(),
        execution_mode="claude_code_cli",
        created_at=datetime.now(UTC),
        **fields,
    )
    session.add(project)
    session.info["tenant_key"] = tenant_key
    await session.flush()
    return project.id


async def _seed_run(session: AsyncSession, tenant_key: str, order: list[str]) -> str:
    run = SequenceRun(
        id=str(uuid.uuid4()),
        tenant_key=tenant_key,
        project_ids=order,
        resolved_order=order,
        current_index=0,
        execution_mode="claude_code_cli",
        status="running",
        review_policy="per_card",
        project_statuses={},
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    session.add(run)
    await session.flush()
    return run.id


@pytest.mark.asyncio
async def test_spawn_raises_when_chain_lookup_fails(db_session: AsyncSession, db_manager) -> None:
    from giljo_mcp.services.job_lifecycle_service import JobLifecycleService
    from tests.services.test_be6198_cold_start_hardening import _orchestrator_count, _seed_orchestrator

    tenant = TenantManager.generate_tenant_key()
    p1 = await _seed_project(db_session, tenant)
    p2 = await _seed_project(db_session, tenant)
    await _seed_run(db_session, tenant, [p1, p2])
    await _seed_orchestrator(db_session, tenant, p1)
    svc = JobLifecycleService(db_manager=db_manager, tenant_manager=TenantManager(), test_session=db_session)

    with patch.object(SequenceRunService, "find_active_run_for_project", AsyncMock(side_effect=_ChainStoreDownError())):
        with pytest.raises(DatabaseError) as raised:
            await svc.spawn_job(
                agent_display_name="orchestrator", agent_name="orchestrator", project_id=p1, tenant_key=tenant
            )
    assert isinstance(raised.value.__cause__, _ChainStoreDownError)
    assert await _orchestrator_count(db_session, tenant, p1) == 1


@pytest.mark.asyncio
async def test_failing_member_status_write_raises(db_session: AsyncSession) -> None:
    tenant = TenantManager.generate_tenant_key()
    p1 = str(uuid.uuid4())
    await _seed_run(db_session, tenant, [p1])
    with patch.object(SequenceRunService, "update", AsyncMock(side_effect=_ChainStoreDownError())):
        with pytest.raises(_ChainStoreDownError):
            await mark_chain_member_status(
                db_manager=None,
                tenant_manager=TenantManager(),
                project_id=p1,
                tenant_key=tenant,
                status="completed",
                test_session=db_session,
            )


@pytest.mark.asyncio
async def test_failing_advance_write_raises(db_session: AsyncSession) -> None:
    tenant = TenantManager.generate_tenant_key()
    p1 = str(uuid.uuid4())
    await _seed_run(db_session, tenant, [p1])
    with patch.object(SequenceRunService, "update", AsyncMock(side_effect=_ChainStoreDownError())):
        with pytest.raises(_ChainStoreDownError):
            await advance_chain_member_to_implementing(
                db_manager=None, tenant_manager=TenantManager(), project_id=p1, tenant_key=tenant, session=db_session
            )


@pytest.mark.asyncio
async def test_concurrent_member_status_writes_keep_both_updates(db_manager) -> None:
    import asyncio

    from sqlalchemy import delete

    tenant = TenantManager.generate_tenant_key()
    p1, p2 = str(uuid.uuid4()), str(uuid.uuid4())
    async with db_manager.get_session_async(tenant_key=tenant) as session:
        run_id = await _seed_run(session, tenant, [p1, p2])

    async def _mark(session: AsyncSession, project_id: str) -> None:
        await mark_chain_member_status(
            db_manager=None,
            tenant_manager=TenantManager(),
            project_id=project_id,
            tenant_key=tenant,
            status="completed",
            test_session=session,
        )

    async def _second_writer() -> None:
        async with db_manager.get_session_async(tenant_key=tenant) as second:
            await _mark(second, p2)

    try:
        async with db_manager.get_session_async(tenant_key=tenant) as first:
            await _mark(first, p1)
            racer = asyncio.create_task(_second_writer())
            await asyncio.sleep(0.5)
        await asyncio.wait_for(racer, timeout=10)

        async with db_manager.get_session_async(tenant_key=tenant) as session:
            run = await SequenceRunService(session=session).get(run_id=run_id, tenant_key=tenant)
        assert run["project_statuses"] == {p1: "completed", p2: "completed"}
    finally:
        async with db_manager.get_session_async(tenant_key=tenant) as session:
            await session.execute(delete(SequenceRun).where(SequenceRun.id == run_id, SequenceRun.tenant_key == tenant))


@pytest.mark.asyncio
async def test_failed_chain_cascade_rolls_back_the_soft_delete(db_manager) -> None:
    from sqlalchemy import delete, select

    from giljo_mcp.services.project_deletion_service import ProjectDeletionService

    tenant = TenantManager.generate_tenant_key()
    async with db_manager.get_session_async(tenant_key=tenant) as session:
        p1 = await _seed_project(session, tenant)
        p2 = await _seed_project(session, tenant)
        run_id = await _seed_run(session, tenant, [p1, p2])
        run = await session.get(SequenceRun, run_id)
        run.status = "pending"

    svc = ProjectDeletionService(db_manager=db_manager, tenant_manager=Mock(get_current_tenant=lambda: tenant))
    try:
        with patch.object(SequenceRunService, "remove_member", AsyncMock(side_effect=_ChainStoreDownError())):
            with pytest.raises(_ChainStoreDownError):
                await svc.delete_project(p1)
        async with db_manager.get_session_async(tenant_key=tenant) as session:
            deleted_at = (
                await session.execute(select(Project.deleted_at).where(Project.id == p1, Project.tenant_key == tenant))
            ).scalar_one()
        assert deleted_at is None
    finally:
        async with db_manager.get_session_async(tenant_key=tenant) as session:
            await session.execute(delete(SequenceRun).where(SequenceRun.id == run_id, SequenceRun.tenant_key == tenant))
            await session.execute(delete(Project).where(Project.id.in_([p1, p2]), Project.tenant_key == tenant))
            await session.execute(delete(Product).where(Product.tenant_key == tenant))


async def _mark_completed(session: AsyncSession, tenant: str, project_id: str, ws) -> None:
    await mark_chain_member_status(
        db_manager=None,
        tenant_manager=TenantManager(),
        project_id=project_id,
        tenant_key=tenant,
        status="completed",
        test_session=session,
        websocket_manager=ws,
    )


@pytest.mark.asyncio
async def test_deferred_sequence_update_is_not_broadcast_on_rollback(db_manager) -> None:
    from sqlalchemy import delete

    tenant = TenantManager.generate_tenant_key()
    p1 = str(uuid.uuid4())
    async with db_manager.get_session_async(tenant_key=tenant) as session:
        run_id = await _seed_run(session, tenant, [p1])
    ws = Mock(broadcast_event_to_tenant=AsyncMock())
    try:

        async def _write_then_fail() -> None:
            async with db_manager.get_session_async(tenant_key=tenant) as session:
                await _mark_completed(session, tenant, p1, ws)
                raise _ChainStoreDownError

        with pytest.raises(_ChainStoreDownError):
            await _write_then_fail()
        ws.broadcast_event_to_tenant.assert_not_awaited()
    finally:
        async with db_manager.get_session_async(tenant_key=tenant) as session:
            await session.execute(delete(SequenceRun).where(SequenceRun.id == run_id, SequenceRun.tenant_key == tenant))


@pytest.mark.asyncio
async def test_deferred_sequence_updates_broadcast_once_per_run_after_commit(db_manager) -> None:
    from sqlalchemy import delete

    from giljo_mcp.services.sequence_run_service import broadcast_deferred_sequence_updates

    tenant = TenantManager.generate_tenant_key()
    p1, p2 = str(uuid.uuid4()), str(uuid.uuid4())
    async with db_manager.get_session_async(tenant_key=tenant) as session:
        run_id = await _seed_run(session, tenant, [p1, p2])
    ws = Mock(broadcast_event_to_tenant=AsyncMock())
    try:
        async with db_manager.get_session_async(tenant_key=tenant) as session:
            await _mark_completed(session, tenant, p1, ws)
            await _mark_completed(session, tenant, p2, ws)
            ws.broadcast_event_to_tenant.assert_not_awaited()
            await session.commit()
            await broadcast_deferred_sequence_updates(session)
        ws.broadcast_event_to_tenant.assert_awaited_once_with(
            tenant, {"type": "sequence:updated", "data": {"run_id": run_id}}
        )
    finally:
        async with db_manager.get_session_async(tenant_key=tenant) as session:
            await session.execute(delete(SequenceRun).where(SequenceRun.id == run_id, SequenceRun.tenant_key == tenant))


@pytest.mark.asyncio
async def test_launch_fails_when_chain_advance_write_fails(db_session: AsyncSession) -> None:
    from giljo_mcp.services.project_staging_service import ProjectStagingService

    tenant = TenantManager.generate_tenant_key()
    p1 = await _seed_project(db_session, tenant, staging_status="staging_complete")
    await _seed_run(db_session, tenant, [p1])
    svc = ProjectStagingService(db_manager=None, tenant_manager=TenantManager(), test_session=db_session)
    with patch.object(SequenceRunService, "update", AsyncMock(side_effect=_ChainStoreDownError())):
        with pytest.raises(_ChainStoreDownError):
            await svc.launch_implementation(project_id=p1, tenant_key=tenant)


@pytest.mark.asyncio
async def test_conductor_mission_mirror_raises_on_write_failure() -> None:
    from giljo_mcp.services.conductor_mission_mirror import mirror_chain_mission_for_conductor

    job = Mock(job_id="j1", job_metadata={"chain_conductor": True, "run_id": "run-1"})
    with patch.object(SequenceRunService, "update", AsyncMock(side_effect=_ChainStoreDownError())):
        with pytest.raises(_ChainStoreDownError):
            await mirror_chain_mission_for_conductor(
                session=Mock(), job=job, tenant_key="tk", mission="m", db_manager=None, tenant_manager=None, repo=None
            )


@pytest.mark.asyncio
async def test_conductor_mission_mirror_skips_a_locked_run() -> None:
    from giljo_mcp.services.conductor_mission_mirror import mirror_chain_mission_for_conductor

    locked = ValidationError(message="read-only after Implement", error_code="CHAIN_MISSION_LOCKED")
    job = Mock(job_id="j1", job_metadata={"chain_conductor": True, "run_id": "run-1"})
    with patch.object(SequenceRunService, "update", AsyncMock(side_effect=locked)):
        await mirror_chain_mission_for_conductor(
            session=Mock(), job=job, tenant_key="tk", mission="m", db_manager=None, tenant_manager=None, repo=None
        )


@pytest.mark.asyncio
async def test_vision_chunking_failure_is_reported() -> None:
    from giljo_mcp.exceptions import ContextError
    from giljo_mcp.services.product_vision_service import ProductVisionService

    svc = ProductVisionService(db_manager=None, tenant_key="tk")
    with patch(
        "giljo_mcp.context_management.chunker.VisionDocumentChunker.chunk_vision_document",
        AsyncMock(side_effect=ContextError("chunker down")),
    ):
        with pytest.raises(ContextError):
            await svc._chunk_document(Mock(), Mock(id="d1"), "text", True, 1000, 1)


@pytest.mark.asyncio
async def test_archive_surfaces_agent_close_failure() -> None:
    from giljo_mcp.domain.project_status import ProjectStatus
    from giljo_mcp.services.project_service._archive_mixin import ArchiveMixin

    svc = ArchiveMixin()
    svc.tenant_manager = Mock()
    svc._websocket_manager = None
    svc.get_project = AsyncMock(return_value=Mock(status=ProjectStatus.COMPLETED, early_termination=False))
    svc._missing_closeout_blockers = AsyncMock(return_value=None)
    svc.update_project = AsyncMock(return_value=Mock())
    svc.closeout = Mock(close_completed_agents_with_commit=AsyncMock(side_effect=OSError("db connection lost")))
    with pytest.raises(OSError, match="db connection lost"):
        await svc.archive_project(project_id="p1", tenant_key="tk")
