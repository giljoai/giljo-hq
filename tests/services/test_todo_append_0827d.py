# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import random
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.database import DatabaseManager
from giljo_mcp.exceptions import ValidationError
from giljo_mcp.models.agent_identity import AgentExecution, AgentJob, AgentTodoItem
from giljo_mcp.models.products import Product
from giljo_mcp.models.projects import Project
from giljo_mcp.services.orchestration_service import OrchestrationService
from giljo_mcp.tenant import TenantManager




@pytest.fixture
def mock_websocket_manager():
    mock = MagicMock()
    mock.broadcast_to_tenant = AsyncMock()
    mock.broadcast_message_sent = AsyncMock()
    mock.broadcast_message_received = AsyncMock()
    mock.broadcast_message_acknowledged = AsyncMock()
    mock.broadcast_job_message = AsyncMock()
    mock.broadcast_job_status_change = AsyncMock()
    return mock


@pytest.fixture
async def test_product(db_session: AsyncSession, test_tenant_key: str) -> Product:
    product = Product(
        id=str(uuid4()),
        tenant_key=test_tenant_key,
        name="Todo Append Test Product",
        description="Product for 0827d tests",
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
        name="Todo Append Test Project",
        description="Test project for 0827d",
        mission="Test todo append feature",
        status="active",
        created_at=datetime.now(UTC),
        series_number=random.randint(1, 9000),
    )
    db_session.add(project)
    await db_session.commit()
    await db_session.refresh(project)
    return project


def _create_agent_with_todos(
    db_session: AsyncSession,
    project_id: str,
    tenant_key: str,
    display_name: str,
    status: str = "working",
    todo_items: list[dict] | None = None,
) -> tuple[AgentJob, AgentExecution]:
    job_id = str(uuid4())
    job = AgentJob(
        job_id=job_id,
        tenant_key=tenant_key,
        project_id=project_id,
        job_type="implementer",
        mission=f"Test mission for {display_name}",
        status="active",
    )
    db_session.add(job)

    now = datetime.now(UTC)
    agent = AgentExecution(
        job_id=job_id,
        tenant_key=tenant_key,
        agent_display_name=display_name,
        status=status,
        messages_sent_count=0,
        messages_waiting_count=0,
        messages_read_count=0,
        started_at=now - timedelta(minutes=3),
        completed_at=None,
        accumulated_duration_seconds=0.0,
        reactivation_count=0,
    )
    db_session.add(agent)

    if todo_items:
        for seq, item in enumerate(todo_items):
            todo = AgentTodoItem(
                job_id=job_id,
                tenant_key=tenant_key,
                content=item["content"],
                status=item["status"],
                sequence=seq,
            )
            db_session.add(todo)

    return job, agent


@pytest.fixture
async def working_agent_with_todos(
    db_session: AsyncSession,
    test_tenant_key: str,
    active_project: Project,
) -> tuple[AgentJob, AgentExecution]:
    todo_items = [
        {"content": "Step 1: Setup", "status": "completed"},
        {"content": "Step 2: Implement", "status": "completed"},
        {"content": "Step 3: Test", "status": "completed"},
        {"content": "Step 4: Refactor", "status": "completed"},
        {"content": "Step 5: Document", "status": "completed"},
    ]
    job, agent = _create_agent_with_todos(
        db_session,
        active_project.id,
        test_tenant_key,
        "Folder-Creator",
        status="working",
        todo_items=todo_items,
    )
    await db_session.commit()
    await db_session.refresh(job)
    await db_session.refresh(agent)
    return job, agent


@pytest.fixture
async def orchestration_service(
    db_manager: DatabaseManager,
    db_session: AsyncSession,
    test_tenant_key: str,
    mock_websocket_manager,
) -> OrchestrationService:
    from contextlib import asynccontextmanager
    from unittest.mock import MagicMock

    tenant_manager = MagicMock(spec=TenantManager)
    tenant_manager.get_current_tenant.return_value = test_tenant_key

    @asynccontextmanager
    async def mock_get_session_async():
        yield db_session

    db_manager.get_session_async = mock_get_session_async

    return OrchestrationService(
        db_manager=db_manager,
        tenant_manager=tenant_manager,
        test_session=db_session,
        websocket_manager=mock_websocket_manager,
    )




@pytest.mark.asyncio
async def test_todo_append_preserves_existing_items(
    db_session: AsyncSession,
    orchestration_service: OrchestrationService,
    working_agent_with_todos: tuple[AgentJob, AgentExecution],
    test_tenant_key: str,
):
    job, _agent = working_agent_with_todos

    result = await orchestration_service.report_progress(
        job_id=job.job_id,
        tenant_key=test_tenant_key,
        todo_append=[
            {"content": "Step 6: Fix subfolder", "status": "pending"},
            {"content": "Step 7: Verify fix", "status": "pending"},
        ],
    )

    assert result.status == "success"

    items_result = await db_session.execute(
        select(AgentTodoItem)
        .where(AgentTodoItem.job_id == job.job_id)
        .where(AgentTodoItem.tenant_key == test_tenant_key)
        .order_by(AgentTodoItem.sequence)
    )
    items = items_result.scalars().all()

    assert len(items) == 7

    for i in range(5):
        assert items[i].status == "completed"
        assert items[i].sequence == i

    assert items[5].content == "Step 6: Fix subfolder"
    assert items[5].status == "pending"
    assert items[5].sequence == 5

    assert items[6].content == "Step 7: Verify fix"
    assert items[6].status == "pending"
    assert items[6].sequence == 6


@pytest.mark.asyncio
async def test_todo_append_correct_sequence_after_gap(
    db_session: AsyncSession,
    orchestration_service: OrchestrationService,
    working_agent_with_todos: tuple[AgentJob, AgentExecution],
    test_tenant_key: str,
):
    job, _agent = working_agent_with_todos

    await orchestration_service.report_progress(
        job_id=job.job_id,
        tenant_key=test_tenant_key,
        todo_append=[{"content": "Step 6", "status": "pending"}],
    )

    await orchestration_service.report_progress(
        job_id=job.job_id,
        tenant_key=test_tenant_key,
        todo_append=[{"content": "Step 7", "status": "pending"}],
    )

    items_result = await db_session.execute(
        select(AgentTodoItem)
        .where(AgentTodoItem.job_id == job.job_id)
        .where(AgentTodoItem.tenant_key == test_tenant_key)
        .order_by(AgentTodoItem.sequence)
    )
    items = items_result.scalars().all()

    assert len(items) == 7
    assert [item.sequence for item in items] == [0, 1, 2, 3, 4, 5, 6]


@pytest.mark.asyncio
async def test_todo_append_updates_jsonb_summary(
    db_session: AsyncSession,
    orchestration_service: OrchestrationService,
    working_agent_with_todos: tuple[AgentJob, AgentExecution],
    test_tenant_key: str,
):
    job, _agent = working_agent_with_todos

    await orchestration_service.report_progress(
        job_id=job.job_id,
        tenant_key=test_tenant_key,
        todo_append=[
            {"content": "Step 6", "status": "pending"},
            {"content": "Step 7", "status": "in_progress"},
        ],
    )

    await db_session.refresh(job)
    metadata = job.job_metadata or {}
    todo_steps = metadata.get("todo_steps", {})

    assert todo_steps["total_steps"] == 7
    assert todo_steps["completed_steps"] == 5
    assert todo_steps["skipped_steps"] == 0




@pytest.mark.asyncio
async def test_todo_items_full_replace_still_works(
    db_session: AsyncSession,
    orchestration_service: OrchestrationService,
    working_agent_with_todos: tuple[AgentJob, AgentExecution],
    test_tenant_key: str,
):
    job, _agent = working_agent_with_todos

    result = await orchestration_service.report_progress(
        job_id=job.job_id,
        tenant_key=test_tenant_key,
        todo_items=[
            {"content": "Step 1 (done)", "status": "completed"},
            {"content": "Step 2 (done)", "status": "completed"},
            {"content": "Step 3 (done)", "status": "completed"},
            {"content": "Step 4 (done)", "status": "completed"},
            {"content": "Step 5 (done)", "status": "completed"},
            {"content": "New A", "status": "pending"},
            {"content": "New B", "status": "in_progress"},
        ],
    )

    assert result.status == "success"

    items_result = await db_session.execute(
        select(AgentTodoItem)
        .where(AgentTodoItem.job_id == job.job_id)
        .where(AgentTodoItem.tenant_key == test_tenant_key)
        .order_by(AgentTodoItem.sequence)
    )
    items = items_result.scalars().all()

    assert len(items) == 7
    assert items[5].content == "New A"
    assert items[6].content == "New B"


@pytest.mark.asyncio
async def test_todo_items_regression_guard_rejects_lossy_replace(
    orchestration_service: OrchestrationService,
    working_agent_with_todos: tuple[AgentJob, AgentExecution],
    test_tenant_key: str,
):
    job, _agent = working_agent_with_todos

    with pytest.raises(ValidationError, match="regression rejected"):
        await orchestration_service.report_progress(
            job_id=job.job_id,
            tenant_key=test_tenant_key,
            todo_items=[
                {"content": "New A", "status": "pending"},
                {"content": "New B", "status": "completed"},
            ],
        )




@pytest.mark.asyncio
async def test_todo_items_and_todo_append_mutually_exclusive(
    orchestration_service: OrchestrationService,
    working_agent_with_todos: tuple[AgentJob, AgentExecution],
    test_tenant_key: str,
):
    job, _agent = working_agent_with_todos

    with pytest.raises(ValidationError, match="Cannot use both"):
        await orchestration_service.report_progress(
            job_id=job.job_id,
            tenant_key=test_tenant_key,
            todo_items=[{"content": "A", "status": "pending"}],
            todo_append=[{"content": "B", "status": "pending"}],
        )




@pytest.mark.asyncio
async def test_todo_append_on_empty_list(
    db_session: AsyncSession,
    orchestration_service: OrchestrationService,
    active_project: Project,
    test_tenant_key: str,
):
    job, agent = _create_agent_with_todos(
        db_session,
        active_project.id,
        test_tenant_key,
        "Empty-Agent",
        status="working",
        todo_items=None,
    )
    await db_session.commit()
    await db_session.refresh(job)
    await db_session.refresh(agent)

    result = await orchestration_service.report_progress(
        job_id=job.job_id,
        tenant_key=test_tenant_key,
        todo_append=[
            {"content": "First step", "status": "pending"},
            {"content": "Second step", "status": "pending"},
        ],
    )

    assert result.status == "success"

    items_result = await db_session.execute(
        select(AgentTodoItem)
        .where(AgentTodoItem.job_id == job.job_id)
        .where(AgentTodoItem.tenant_key == test_tenant_key)
        .order_by(AgentTodoItem.sequence)
    )
    items = items_result.scalars().all()

    assert len(items) == 2
    assert items[0].sequence == 0
    assert items[1].sequence == 1




def test_job_response_includes_reactivation_fields():
    from api.endpoints.agent_jobs.models import JobResponse

    response = JobResponse(
        id="test-id",
        job_id="test-job",
        tenant_key="tk_test",
        agent_display_name="Test-Agent",
        mission="Test mission",
        status="working",
        created_at=datetime.now(UTC),
        accumulated_duration_seconds=175.5,
        reactivation_count=2,
    )

    assert response.accumulated_duration_seconds == 175.5
    assert response.reactivation_count == 2


def test_job_response_defaults_reactivation_fields():
    from api.endpoints.agent_jobs.models import JobResponse

    response = JobResponse(
        id="test-id",
        job_id="test-job",
        tenant_key="tk_test",
        agent_display_name="Test-Agent",
        mission="Test mission",
        status="working",
        created_at=datetime.now(UTC),
    )

    assert response.accumulated_duration_seconds == 0.0
    assert response.reactivation_count == 0




@pytest.mark.asyncio
async def test_list_jobs_includes_reactivation_fields(
    db_session: AsyncSession,
    orchestration_service: OrchestrationService,
    active_project: Project,
    test_tenant_key: str,
):
    job, agent = _create_agent_with_todos(
        db_session,
        active_project.id,
        test_tenant_key,
        "Reactivated-Agent",
        status="working",
    )
    agent.accumulated_duration_seconds = 180.0
    agent.reactivation_count = 1
    await db_session.commit()

    result = await orchestration_service.list_jobs(
        tenant_key=test_tenant_key,
        project_id=active_project.id,
    )

    assert len(result.jobs) >= 1
    agent_job = next(j for j in result.jobs if j["job_id"] == job.job_id)
    assert agent_job["accumulated_duration_seconds"] == 180.0
    assert agent_job["reactivation_count"] == 1




def test_job_to_response_passes_reactivation_fields():
    from api.endpoints.agent_jobs.status import job_to_response

    job_dict = {
        "agent_id": "test-agent",
        "job_id": "test-job",
        "tenant_key": "tk_test",
        "agent_display_name": "Test-Agent",
        "mission": "Test mission",
        "status": "working",
        "created_at": datetime.now(UTC).isoformat(),
        "accumulated_duration_seconds": 250.0,
        "reactivation_count": 3,
    }

    response = job_to_response(job_dict)
    assert response.accumulated_duration_seconds == 250.0
    assert response.reactivation_count == 3
