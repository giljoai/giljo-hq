# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.exceptions import ValidationError
from giljo_mcp.models.agent_identity import AgentExecution, AgentJob, AgentTodoItem
from giljo_mcp.models.products import Product
from giljo_mcp.models.projects import Project
from giljo_mcp.services.job_completion_service import JobCompletionService


@pytest.fixture
async def test_product(db_session: AsyncSession, test_tenant_key: str) -> Product:
    product = Product(
        id=str(uuid4()),
        tenant_key=test_tenant_key,
        name="BE6200 Closeout Wording Product",
        description="Product for self-closeout wording tests",
        product_memory={},
    )
    db_session.add(product)
    await db_session.commit()
    await db_session.refresh(product)
    return product


@pytest.fixture
async def active_project(
    db_session: AsyncSession,
    test_tenant_key: str,
    test_product: Product,
) -> Project:
    project = Project(
        id=str(uuid4()),
        tenant_key=test_tenant_key,
        product_id=test_product.id,
        name="BE6200 Closeout Wording Project",
        description="Test project for self-closeout wording",
        mission="Test self-referential closeout TODO wording",
        status="active",
        created_at=datetime.now(UTC),
        series_number=random.randint(1, 9000),
    )
    db_session.add(project)
    await db_session.commit()
    await db_session.refresh(project)
    return project


@pytest.fixture
def completion_service(db_session: AsyncSession, test_tenant_key: str) -> JobCompletionService:
    db_manager = MagicMock()
    tenant_manager = MagicMock()
    tenant_manager.get_current_tenant.return_value = test_tenant_key
    return JobCompletionService(
        db_manager=db_manager,
        tenant_manager=tenant_manager,
        test_session=db_session,
    )


async def _seed_orchestrator_with_todos(
    db_session: AsyncSession,
    tenant_key: str,
    project_id: str,
    todos: list[dict],
) -> AgentJob:
    job_id = str(uuid4())
    job = AgentJob(
        job_id=job_id,
        tenant_key=tenant_key,
        project_id=project_id,
        job_type="orchestrator",
        mission="Coordinate self-closeout wording tests",
        status="active",
    )
    db_session.add(job)

    now = datetime.now(UTC)
    db_session.add(
        AgentExecution(
            job_id=job_id,
            tenant_key=tenant_key,
            agent_display_name="orchestrator",
            status="working",
            messages_sent_count=0,
            messages_waiting_count=0,
            messages_read_count=0,
            started_at=now - timedelta(minutes=5),
        )
    )

    for seq, item in enumerate(todos):
        db_session.add(
            AgentTodoItem(
                job_id=job_id,
                tenant_key=tenant_key,
                content=item["content"],
                status=item["status"],
                sequence=seq,
            )
        )

    await db_session.commit()
    await db_session.refresh(job)
    return job


@pytest.mark.asyncio
async def test_differently_worded_self_closeout_todo_auto_clears(
    db_session: AsyncSession,
    completion_service: JobCompletionService,
    test_tenant_key: str,
    active_project: Project,
):
    job = await _seed_orchestrator_with_todos(
        db_session,
        test_tenant_key,
        active_project.id,
        todos=[
            {"content": "Wrap up and finalize the project", "status": "in_progress"},
        ],
    )

    result = await completion_service.complete_job(
        job_id=job.job_id,
        result={"summary": "test"},
        tenant_key=test_tenant_key,
    )
    assert result.status == "success"
    assert result.phase == "closeout"

    items = (
        (
            await db_session.execute(
                select(AgentTodoItem).where(
                    AgentTodoItem.job_id == job.job_id,
                    AgentTodoItem.tenant_key == test_tenant_key,
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(items) == 1
    assert items[0].status == "completed"


@pytest.mark.asyncio
async def test_genuine_non_closeout_todo_still_blocks(
    db_session: AsyncSession,
    completion_service: JobCompletionService,
    test_tenant_key: str,
    active_project: Project,
):
    job = await _seed_orchestrator_with_todos(
        db_session,
        test_tenant_key,
        active_project.id,
        todos=[
            {"content": "Fix the failing test", "status": "in_progress"},
        ],
    )

    with pytest.raises(ValidationError) as exc_info:
        await completion_service.complete_job(
            job_id=job.job_id,
            result={"summary": "test"},
            tenant_key=test_tenant_key,
        )
    err = exc_info.value
    assert err.error_code == "COMPLETION_BLOCKED"
    ctx = err.context or {}
    assert ctx.get("incomplete_todos") == 1
    reasons_text = " ".join(ctx.get("reasons", []))
    assert "Fix the failing test" in reasons_text
