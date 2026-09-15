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
from giljo_mcp.models.tasks import Message, MessageRecipient
from giljo_mcp.services.job_completion_service import JobCompletionService




@pytest.fixture
async def test_product(db_session: AsyncSession, test_tenant_key: str) -> Product:
    product = Product(
        id=str(uuid4()),
        tenant_key=test_tenant_key,
        name="Closeout Ack Test Product",
        description="Product for closeout-ack tests",
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
        name="Closeout Ack Test Project",
        description="Test project for closeout ack",
        mission="Test closeout acknowledgement",
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
) -> tuple[AgentJob, AgentExecution]:
    job_id = str(uuid4())
    job = AgentJob(
        job_id=job_id,
        tenant_key=tenant_key,
        project_id=project_id,
        job_type="orchestrator",
        mission="Coordinate closeout ack tests",
        status="active",
    )
    db_session.add(job)

    now = datetime.now(UTC)
    execution = AgentExecution(
        job_id=job_id,
        tenant_key=tenant_key,
        agent_display_name="orchestrator",
        status="working",
        messages_sent_count=0,
        messages_waiting_count=0,
        messages_read_count=0,
        started_at=now - timedelta(minutes=5),
    )
    db_session.add(execution)

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
    await db_session.refresh(execution)
    return job, execution




@pytest.mark.asyncio
async def test_closeout_todo_auto_acks_without_flag(
    db_session: AsyncSession,
    completion_service: JobCompletionService,
    test_tenant_key: str,
    active_project: Project,
):
    job, _ = await _seed_orchestrator_with_todos(
        db_session,
        test_tenant_key,
        active_project.id,
        todos=[
            {"content": "Closeout: complete orchestrator job", "status": "in_progress"},
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
async def test_ack_only_closeout_todo_succeeds(
    db_session: AsyncSession,
    completion_service: JobCompletionService,
    test_tenant_key: str,
    active_project: Project,
):
    job, _ = await _seed_orchestrator_with_todos(
        db_session,
        test_tenant_key,
        active_project.id,
        todos=[
            {
                "content": "Closeout: complete orchestrator job + close_project_and_update_memory",
                "status": "in_progress",
            },
        ],
    )

    result = await completion_service.complete_job(
        job_id=job.job_id,
        result={"summary": "closeout ok"},
        tenant_key=test_tenant_key,
        acknowledge_closeout_todo=True,
    )
    assert result.status == "success"

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
async def test_ack_with_non_closeout_still_blocks(
    db_session: AsyncSession,
    completion_service: JobCompletionService,
    test_tenant_key: str,
    active_project: Project,
):
    job, _ = await _seed_orchestrator_with_todos(
        db_session,
        test_tenant_key,
        active_project.id,
        todos=[
            {"content": "Closeout: complete orchestrator job", "status": "in_progress"},
            {"content": "Refactor login flow", "status": "in_progress"},
        ],
    )

    with pytest.raises(ValidationError) as exc_info:
        await completion_service.complete_job(
            job_id=job.job_id,
            result={"summary": "test"},
            tenant_key=test_tenant_key,
            acknowledge_closeout_todo=True,
        )
    err = exc_info.value
    assert err.error_code == "COMPLETION_BLOCKED"
    ctx = err.context or {}
    assert ctx.get("incomplete_todos") == 1
    reasons_text = " ".join(ctx.get("reasons", []))
    assert "Refactor login flow" in reasons_text
    assert "Closeout" not in reasons_text


@pytest.mark.asyncio
async def test_ack_no_incomplete_todos_succeeds(
    db_session: AsyncSession,
    completion_service: JobCompletionService,
    test_tenant_key: str,
    active_project: Project,
):
    job, _ = await _seed_orchestrator_with_todos(
        db_session,
        test_tenant_key,
        active_project.id,
        todos=[
            {"content": "Step 1", "status": "completed"},
            {"content": "Step 2", "status": "completed"},
        ],
    )

    result = await completion_service.complete_job(
        job_id=job.job_id,
        result={"summary": "all done"},
        tenant_key=test_tenant_key,
        acknowledge_closeout_todo=True,
    )
    assert result.status == "success"


@pytest.mark.asyncio
async def test_ack_does_not_bypass_unread_messages_gate(
    db_session: AsyncSession,
    completion_service: JobCompletionService,
    test_tenant_key: str,
    active_project: Project,
):
    job, execution = await _seed_orchestrator_with_todos(
        db_session,
        test_tenant_key,
        active_project.id,
        todos=[
            {"content": "Closeout: complete orchestrator job", "status": "in_progress"},
        ],
    )

    sender_id = str(uuid4())
    msg = Message(
        tenant_key=test_tenant_key,
        project_id=active_project.id,
        from_agent_id=sender_id,
        content="Hello orchestrator, please read me",
        status="pending",
        requires_action=True,
        created_at=datetime.now(UTC) - timedelta(minutes=1),
    )
    db_session.add(msg)
    await db_session.flush()
    db_session.add(
        MessageRecipient(
            message_id=msg.id,
            agent_id=execution.agent_id,
            tenant_key=test_tenant_key,
        )
    )
    await db_session.commit()

    with pytest.raises(ValidationError) as exc_info:
        await completion_service.complete_job(
            job_id=job.job_id,
            result={"summary": "test"},
            tenant_key=test_tenant_key,
            acknowledge_closeout_todo=True,
        )
    err = exc_info.value
    assert err.error_code == "COMPLETION_BLOCKED"
    ctx = err.context or {}
    assert ctx.get("unread_messages") == 1
