# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import random
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.database import DatabaseManager
from giljo_mcp.domain.todo_kinds import (
    TODO_KIND_CHAIN_DRIVE,
    TODO_KIND_CLOSEOUT_INTENT,
    TODO_KIND_SELF_CLOSEOUT,
    classify_todo_kind,
)
from giljo_mcp.exceptions import ValidationError
from giljo_mcp.models.agent_identity import AgentExecution, AgentJob, AgentTodoItem
from giljo_mcp.models.products import Product
from giljo_mcp.models.projects import Project
from giljo_mcp.services.job_completion_service import JobCompletionService
from giljo_mcp.services.orchestration_service import OrchestrationService
from giljo_mcp.tenant import TenantManager






def test_classify_narrow_closeout():
    assert classify_todo_kind("Closeout: write the 360 memory") == TODO_KIND_SELF_CLOSEOUT
    assert classify_todo_kind("Conductor self-complete") == TODO_KIND_SELF_CLOSEOUT
    assert classify_todo_kind("call complete_job") == TODO_KIND_SELF_CLOSEOUT


def test_classify_intent_and_chain_drive():
    assert classify_todo_kind("Wrap up and finalize the project") == TODO_KIND_CLOSEOUT_INTENT
    assert classify_todo_kind("Poll P2 and advance the chain") == TODO_KIND_CHAIN_DRIVE


def test_classify_ordinary_work_is_none():
    assert classify_todo_kind("Fix the failing login test") is None
    assert classify_todo_kind("Implement the rate limiter") is None
    assert classify_todo_kind("") is None
    assert classify_todo_kind(None) is None




@pytest.fixture
async def test_product(db_session: AsyncSession, test_tenant_key: str) -> Product:
    product = Product(
        id=str(uuid4()),
        tenant_key=test_tenant_key,
        name="BE-9012b D7 Product",
        description="todo_kind marker",
        product_memory={},
    )
    db_session.add(product)
    await db_session.commit()
    await db_session.refresh(product)
    return product


@pytest.fixture
async def active_project(db_session: AsyncSession, test_tenant_key: str, test_product: Product) -> Project:
    project = Project(
        id=str(uuid4()),
        tenant_key=test_tenant_key,
        product_id=test_product.id,
        name="BE-9012b D7 Project",
        description="todo_kind marker",
        mission="test",
        status="active",
        created_at=datetime.now(UTC),
        series_number=random.randint(1, 9000),
    )
    db_session.add(project)
    await db_session.commit()
    await db_session.refresh(project)
    return project


@pytest.fixture
async def orchestration_service(
    db_manager: DatabaseManager, db_session: AsyncSession, test_tenant_key: str
) -> OrchestrationService:
    tenant_manager = MagicMock(spec=TenantManager)
    tenant_manager.get_current_tenant.return_value = test_tenant_key

    @asynccontextmanager
    async def _mock_get_session_async():
        yield db_session

    db_manager.get_session_async = _mock_get_session_async
    ws = MagicMock()
    ws.broadcast_to_tenant = AsyncMock()
    return OrchestrationService(
        db_manager=db_manager,
        tenant_manager=tenant_manager,
        test_session=db_session,
        websocket_manager=ws,
    )


@pytest.fixture
def completion_service(db_session: AsyncSession, test_tenant_key: str) -> JobCompletionService:
    tenant_manager = MagicMock()
    tenant_manager.get_current_tenant.return_value = test_tenant_key
    return JobCompletionService(db_manager=MagicMock(), tenant_manager=tenant_manager, test_session=db_session)


async def _seed_orchestrator(
    db_session: AsyncSession, tenant_key: str, project_id: str, todos: list[dict] | None = None
) -> AgentJob:
    job_id = str(uuid4())
    job = AgentJob(
        job_id=job_id,
        tenant_key=tenant_key,
        project_id=project_id,
        job_type="orchestrator",
        mission="coordinate",
        status="active",
    )
    db_session.add(job)
    db_session.add(
        AgentExecution(
            job_id=job_id,
            tenant_key=tenant_key,
            agent_display_name="orchestrator",
            status="working",
            started_at=datetime.now(UTC) - timedelta(minutes=5),
            messages_sent_count=0,
            messages_waiting_count=0,
            messages_read_count=0,
        )
    )
    for seq, item in enumerate(todos or []):
        db_session.add(
            AgentTodoItem(
                job_id=job_id,
                tenant_key=tenant_key,
                content=item["content"],
                status=item.get("status", "in_progress"),
                sequence=seq,
                todo_kind=item.get("todo_kind"),
            )
        )
    await db_session.commit()
    await db_session.refresh(job)
    return job




async def test_report_progress_stamps_todo_kind_at_write(
    db_session: AsyncSession,
    orchestration_service: OrchestrationService,
    test_tenant_key: str,
    active_project: Project,
):
    job = await _seed_orchestrator(db_session, test_tenant_key, active_project.id)

    await orchestration_service.report_progress(
        job_id=job.job_id,
        tenant_key=test_tenant_key,
        todo_items=[
            {"content": "Closeout: write the series summary", "status": "pending"},
            {"content": "Poll P2 and advance the chain", "status": "pending"},
            {"content": "Implement the rate limiter", "status": "pending"},
        ],
    )

    rows = {
        r.content: r.todo_kind
        for r in (
            await db_session.execute(
                select(AgentTodoItem).where(
                    AgentTodoItem.job_id == job.job_id, AgentTodoItem.tenant_key == test_tenant_key
                )
            )
        )
        .scalars()
        .all()
    }
    assert rows["Closeout: write the series summary"] == TODO_KIND_SELF_CLOSEOUT
    assert rows["Poll P2 and advance the chain"] == TODO_KIND_CHAIN_DRIVE
    assert rows["Implement the rate limiter"] is None




async def test_gate_auto_clears_via_stored_marker_regardless_of_wording(
    db_session: AsyncSession,
    completion_service: JobCompletionService,
    test_tenant_key: str,
    active_project: Project,
):
    job = await _seed_orchestrator(
        db_session,
        test_tenant_key,
        active_project.id,
        todos=[
            {"content": "Ship the grand finale to prod", "status": "in_progress", "todo_kind": TODO_KIND_SELF_CLOSEOUT},
        ],
    )
    assert classify_todo_kind("Ship the grand finale to prod") != TODO_KIND_SELF_CLOSEOUT

    result = await completion_service.complete_job(
        job_id=job.job_id, result={"summary": "done"}, tenant_key=test_tenant_key
    )
    assert result.status == "success"
    item = (
        await db_session.execute(
            select(AgentTodoItem).where(AgentTodoItem.job_id == job.job_id, AgentTodoItem.tenant_key == test_tenant_key)
        )
    ).scalar_one()
    assert item.status == "completed"




async def test_gate_falls_back_to_classifier_for_legacy_null_kind(
    db_session: AsyncSession,
    completion_service: JobCompletionService,
    test_tenant_key: str,
    active_project: Project,
):
    job = await _seed_orchestrator(
        db_session,
        test_tenant_key,
        active_project.id,
        todos=[{"content": "Closeout: complete orchestrator job", "status": "in_progress"}],
    )

    result = await completion_service.complete_job(
        job_id=job.job_id, result={"summary": "done"}, tenant_key=test_tenant_key
    )
    assert result.status == "success"


async def test_ordinary_work_todo_still_blocks(
    db_session: AsyncSession,
    completion_service: JobCompletionService,
    test_tenant_key: str,
    active_project: Project,
):
    job = await _seed_orchestrator(
        db_session,
        test_tenant_key,
        active_project.id,
        todos=[{"content": "Refactor the login flow", "status": "in_progress"}],
    )

    with pytest.raises(ValidationError) as exc_info:
        await completion_service.complete_job(job_id=job.job_id, result={"summary": "done"}, tenant_key=test_tenant_key)
    assert exc_info.value.error_code == "COMPLETION_BLOCKED"
    assert (exc_info.value.context or {}).get("incomplete_todos") == 1
