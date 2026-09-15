# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import random
import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, Mock, patch
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import select

from giljo_mcp.exceptions import ResourceNotFoundError
from giljo_mcp.models import Project
from giljo_mcp.models.agent_identity import AgentExecution, AgentJob, AgentTodoItem
from giljo_mcp.schemas.service_responses import ProgressResult
from giljo_mcp.services.orchestration_service import OrchestrationService
from giljo_mcp.tenant import TenantManager
from giljo_mcp.tools.write_memory_entry import write_360_memory
from tests.helpers.model_factories import make_agent_execution




@pytest.fixture(autouse=True)
def _stub_staleness():

    async def _noop(*args, **kwargs):
        return {"is_stale": False, "projects_since_tune": 0, "threshold": 3, "enabled": True}

    with patch(
        "giljo_mcp.services.product_tuning_service.ProductTuningService.check_tuning_staleness",
        new=_noop,
    ):
        yield


@pytest_asyncio.fixture
async def linked_project(db_session, test_tenant_key, test_product):
    project = Project(
        id=str(uuid.uuid4()),
        name="BE-6211d closeout tolerance project",
        description="closeout tolerance",
        mission="test",
        status="active",
        tenant_key=test_tenant_key,
        product_id=test_product.id,
        series_number=random.randint(1, 9000),
    )
    db_session.add(project)
    await db_session.commit()
    return project


async def _seed_orchestrator_with_todo(db_session, tenant_key, project_id, content, status="in_progress"):
    job_id = str(uuid.uuid4())
    db_session.add(
        AgentJob(
            job_id=job_id,
            tenant_key=tenant_key,
            project_id=project_id,
            job_type="orchestrator",
            mission="coordinate",
            status="active",
        )
    )
    db_session.add(
        AgentExecution(
            job_id=job_id,
            tenant_key=tenant_key,
            agent_display_name="orchestrator",
            status="complete",
            started_at=datetime.now(UTC),
        )
    )
    db_session.add(AgentTodoItem(job_id=job_id, tenant_key=tenant_key, content=content, status=status, sequence=0))
    await db_session.commit()
    return job_id


@pytest.mark.asyncio
async def test_conductor_series_summary_todo_auto_acked(db_session, test_tenant_key, test_product, linked_project):
    job_id = await _seed_orchestrator_with_todo(
        db_session,
        test_tenant_key,
        linked_project.id,
        "Write series summary on head project + complete conductor job",
    )

    result = await write_360_memory(
        project_id=str(linked_project.id),
        tenant_key=test_tenant_key,
        summary="Series summary",
        key_outcomes=["chain complete"],
        decisions_made=["decision"],
        entry_type="project_completion",
        author_job_id=job_id,
        acknowledge_closeout_todo=True,
        user_id=str(uuid4()),
        db_manager=MagicMock(),
        session=db_session,
    )

    assert result.get("entry_id"), result
    assert result.get("error") != "CLOSEOUT_BLOCKED"

    todo = (
        (
            await db_session.execute(
                select(AgentTodoItem).where(AgentTodoItem.job_id == job_id, AgentTodoItem.tenant_key == test_tenant_key)
            )
        )
        .scalars()
        .one()
    )
    assert todo.status == "completed"


@pytest.mark.asyncio
async def test_generic_remaining_work_todo_still_blocks(db_session, test_tenant_key, test_product, linked_project):
    job_id = await _seed_orchestrator_with_todo(db_session, test_tenant_key, linked_project.id, "Fix the failing test")

    result = await write_360_memory(
        project_id=str(linked_project.id),
        tenant_key=test_tenant_key,
        summary="Series summary",
        key_outcomes=["chain complete"],
        decisions_made=["decision"],
        entry_type="project_completion",
        author_job_id=job_id,
        acknowledge_closeout_todo=True,
        user_id=str(uuid4()),
        db_manager=MagicMock(),
        session=db_session,
    )

    assert result.get("error") == "CLOSEOUT_BLOCKED", result




async def _seed_conductor_with_todo(db_session, tenant_key, content, status="in_progress"):
    job_id = str(uuid.uuid4())
    db_session.add(
        AgentJob(
            job_id=job_id,
            tenant_key=tenant_key,
            project_id=None,
            job_type="orchestrator",
            mission="conduct the chain",
            status="active",
            job_metadata={"chain_conductor": True},
        )
    )
    db_session.add(
        AgentExecution(
            job_id=job_id,
            tenant_key=tenant_key,
            agent_display_name="orchestrator",
            status="complete",
            started_at=datetime.now(UTC),
        )
    )
    db_session.add(AgentTodoItem(job_id=job_id, tenant_key=tenant_key, content=content, status=status, sequence=0))
    await db_session.commit()
    return job_id


async def _todo_status(db_session, tenant_key, job_id) -> str:
    return (
        (
            await db_session.execute(
                select(AgentTodoItem).where(AgentTodoItem.job_id == job_id, AgentTodoItem.tenant_key == tenant_key)
            )
        )
        .scalars()
        .one()
    ).status


def test_chain_drive_pattern_matches_conductor_bookkeeping() -> None:
    from giljo_mcp.domain.todo_kinds import CHAIN_DRIVE_TODO_PATTERN

    for content in (
        "Poll P2 for closeout",
        "Advance to P2",
        "Spawn next project",
        "Write the series summary",
        "Chain finale",
        "Drive the chain to completion",
    ):
        assert CHAIN_DRIVE_TODO_PATTERN.search(content), f"must match conductor drive TODO: {content!r}"


def test_chain_drive_pattern_excludes_genuine_work() -> None:
    from giljo_mcp.domain.todo_kinds import CHAIN_DRIVE_TODO_PATTERN

    for content in ("Fix the failing test", "Implement the rate limiter", "Review the PR and merge"):
        assert CHAIN_DRIVE_TODO_PATTERN.search(content) is None, f"must NOT match genuine work: {content!r}"


@pytest.mark.asyncio
async def test_conductor_drive_todo_auto_acked_without_flag(db_session, test_tenant_key, test_product, linked_project):
    job_id = await _seed_conductor_with_todo(db_session, test_tenant_key, "Poll P2 and advance the chain")

    await write_360_memory(
        project_id=str(linked_project.id),
        tenant_key=test_tenant_key,
        summary="Chain run done",
        key_outcomes=["chain complete"],
        decisions_made=["auto-continued"],
        entry_type="project_completion",
        author_job_id=job_id,
        acknowledge_closeout_todo=False,
        user_id=str(uuid4()),
        db_manager=MagicMock(),
        session=db_session,
    )

    assert await _todo_status(db_session, test_tenant_key, job_id) == "completed", "conductor drive TODO must auto-ack"


@pytest.mark.asyncio
async def test_solo_with_chain_drive_worded_todo_still_blocks(
    db_session, test_tenant_key, test_product, linked_project
):
    job_id = await _seed_orchestrator_with_todo(
        db_session, test_tenant_key, linked_project.id, "Poll P2 and advance the chain"
    )

    result = await write_360_memory(
        project_id=str(linked_project.id),
        tenant_key=test_tenant_key,
        summary="Series summary",
        key_outcomes=["done"],
        decisions_made=["decision"],
        entry_type="project_completion",
        author_job_id=job_id,
        acknowledge_closeout_todo=True,
        user_id=str(uuid4()),
        db_manager=MagicMock(),
        session=db_session,
    )

    assert await _todo_status(db_session, test_tenant_key, job_id) != "completed", "solo drive-worded TODO must NOT ack"
    assert result.get("error") == "CLOSEOUT_BLOCKED", result


@pytest.mark.asyncio
async def test_conductor_with_genuine_work_todo_still_blocks(db_session, test_tenant_key, test_product, linked_project):
    job_id = await _seed_conductor_with_todo(db_session, test_tenant_key, "Fix the failing test")

    await write_360_memory(
        project_id=str(linked_project.id),
        tenant_key=test_tenant_key,
        summary="Chain run done",
        key_outcomes=["done"],
        decisions_made=["decision"],
        entry_type="project_completion",
        author_job_id=job_id,
        acknowledge_closeout_todo=False,
        user_id=str(uuid4()),
        db_manager=MagicMock(),
        session=db_session,
    )

    assert await _todo_status(db_session, test_tenant_key, job_id) != "completed", "genuine-work TODO must NOT auto-ack"




def _make_mock_execution(status: str, job_id: str, tenant_key: str) -> Mock:
    return make_agent_execution(
        status=status,
        job_id=job_id,
        tenant_key=tenant_key,
        agent_id=str(uuid4()),
        agent_display_name="test-agent",
        started_at=datetime.now(UTC),
    )


def _service_with_sequenced_executions(*scalar_results):
    tenant_key = "test-tenant"
    mock_tenant_manager = MagicMock(spec=TenantManager)
    mock_tenant_manager.get_current_tenant.return_value = tenant_key

    mock_session = AsyncMock()
    mock_session.info = {}
    call_count = {"n": 0}

    async def mock_execute(*args, **kwargs):
        i = call_count["n"]
        call_count["n"] += 1
        result = MagicMock()
        result.scalar_one_or_none.return_value = scalar_results[i] if i < len(scalar_results) else None
        return result

    mock_session.execute = AsyncMock(side_effect=mock_execute)

    return OrchestrationService(
        db_manager=MagicMock(),
        tenant_manager=mock_tenant_manager,
        test_session=mock_session,
    ), tenant_key


@pytest.mark.asyncio
async def test_report_progress_on_completed_execution_is_noop():
    job_id = str(uuid4())
    completed = _make_mock_execution("complete", job_id, "test-tenant")
    service, tenant_key = _service_with_sequenced_executions(None, None, completed)

    result = await service.report_progress(job_id=job_id, progress={"percent": 50}, tenant_key=tenant_key)

    assert isinstance(result, ProgressResult)
    assert result.status != "success", "a post-completion report is a no-op, not a normal success"


@pytest.mark.asyncio
async def test_report_progress_decommissioned_still_raises():
    job_id = str(uuid4())
    decommissioned = _make_mock_execution("decommissioned", job_id, "test-tenant")
    service, tenant_key = _service_with_sequenced_executions(None, decommissioned)

    with pytest.raises(ResourceNotFoundError) as exc:
        await service.report_progress(job_id=job_id, progress={"percent": 50}, tenant_key=tenant_key)
    assert exc.value.context.get("execution_status") == "decommissioned"


@pytest.mark.asyncio
async def test_report_progress_no_execution_at_all_still_raises():
    job_id = str(uuid4())
    service, tenant_key = _service_with_sequenced_executions(None, None, None)

    with pytest.raises(ResourceNotFoundError):
        await service.report_progress(job_id=job_id, progress={"percent": 50}, tenant_key=tenant_key)
