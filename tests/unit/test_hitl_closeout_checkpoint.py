# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

from giljo_mcp.models import AgentExecution, AgentJob
from giljo_mcp.services.job_completion_service import JobCompletionService


@pytest.fixture
def completion_service(db_session, test_tenant_key):
    db_manager = MagicMock()
    tenant_manager = MagicMock()
    tenant_manager.get_current_tenant.return_value = test_tenant_key
    return JobCompletionService(
        db_manager=db_manager,
        tenant_manager=tenant_manager,
        test_session=db_session,
    )


@pytest_asyncio.fixture
async def orchestrator_job(db_session, test_tenant_key, test_project_id):
    job_id = str(uuid.uuid4())
    job = AgentJob(
        job_id=job_id,
        project_id=str(test_project_id),
        mission="Test orchestrator mission",
        job_type="orchestrator",
        status="active",
        tenant_key=test_tenant_key,
    )
    db_session.add(job)
    await db_session.flush()

    execution = AgentExecution(
        id=str(uuid.uuid4()),
        job_id=job_id,
        tenant_key=test_tenant_key,
        agent_name="orchestrator",
        agent_display_name="orchestrator",
        status="working",
        started_at=datetime.now(UTC),
    )
    db_session.add(execution)
    await db_session.commit()
    return job


@pytest_asyncio.fixture
async def implementer_job(db_session, test_tenant_key, test_project_id):
    job_id = str(uuid.uuid4())
    job = AgentJob(
        job_id=job_id,
        project_id=str(test_project_id),
        mission="Test implementer mission",
        job_type="implementer",
        status="active",
        tenant_key=test_tenant_key,
    )
    db_session.add(job)
    await db_session.flush()

    execution = AgentExecution(
        id=str(uuid.uuid4()),
        job_id=job_id,
        tenant_key=test_tenant_key,
        agent_name="implementer",
        agent_display_name="implementer-backend",
        status="working",
        started_at=datetime.now(UTC),
    )
    db_session.add(execution)
    await db_session.commit()
    return job




@pytest.mark.asyncio
async def test_complete_job_orchestrator_includes_closeout_checklist(
    completion_service, orchestrator_job, test_tenant_key
):
    result = await completion_service.complete_job(
        job_id=orchestrator_job.job_id,
        result={"summary": "Project completed successfully"},
        tenant_key=test_tenant_key,
    )
    assert result.status == "success"
    assert hasattr(result, "closeout_checklist")
    assert result.closeout_checklist is not None

    checklist = result.closeout_checklist
    assert "follow_up_items" in checklist
    assert "instruction" in checklist
    assert "request_approval" in checklist["instruction"]
    assert checklist.get("closeout_mode") == "hitl"


@pytest.mark.asyncio
async def test_complete_job_non_orchestrator_no_checklist(completion_service, implementer_job, test_tenant_key):
    result = await completion_service.complete_job(
        job_id=implementer_job.job_id,
        result={"summary": "Implementation done"},
        tenant_key=test_tenant_key,
    )
    assert result.status == "success"
    assert result.closeout_checklist is None




def test_orchestrator_protocol_references_closeout_checklist():
    from giljo_mcp.services.protocol_sections.agent_lifecycle import (
        _build_orchestrator_protocol_body,
    )

    body = _build_orchestrator_protocol_body(
        job_id="test-job",
        tenant_key="test-tenant",
        executor_id="test-executor",
        wake_pattern="test-wake",
        execution_mode="multi_terminal",
        tool="multi_terminal",
    )
    assert "closeout_checklist" in body
    assert "request_approval" in body
    assert "complete_job" in body




@pytest_asyncio.fixture
async def linked_project(db_session, test_tenant_key, test_product):
    import random

    from giljo_mcp.models import Project

    project = Project(
        id=str(uuid.uuid4()),
        name="Test Linked Project",
        description="Project linked to product for closeout testing",
        mission="Test mission",
        status="active",
        tenant_key=test_tenant_key,
        product_id=test_product.id,
        series_number=random.randint(1, 9000),
    )
    db_session.add(project)
    await db_session.commit()
    return project


@pytest.mark.asyncio
async def test_write_360_memory_callable_after_complete_job(db_session, test_tenant_key, test_product, linked_project):
    project_id = str(linked_project.id)

    job_id = str(uuid.uuid4())
    job = AgentJob(
        job_id=job_id,
        project_id=project_id,
        mission="Test orchestrator mission",
        job_type="orchestrator",
        status="active",
        tenant_key=test_tenant_key,
    )
    db_session.add(job)
    await db_session.flush()

    execution = AgentExecution(
        id=str(uuid.uuid4()),
        job_id=job_id,
        tenant_key=test_tenant_key,
        agent_name="orchestrator",
        agent_display_name="orchestrator",
        status="working",
        started_at=datetime.now(UTC),
    )
    db_session.add(execution)
    await db_session.commit()

    db_manager = MagicMock()
    db_manager.get_session_async = MagicMock(return_value=AsyncMock())
    tenant_manager = MagicMock()
    tenant_manager.get_current_tenant.return_value = test_tenant_key
    svc = JobCompletionService(
        db_manager=db_manager,
        tenant_manager=tenant_manager,
        test_session=db_session,
    )

    complete_result = await svc.complete_job(
        job_id=job_id,
        result={"summary": "All work done"},
        tenant_key=test_tenant_key,
    )
    assert complete_result.status == "success"

    from giljo_mcp.tools.write_memory_entry import write_360_memory

    mock_db_manager = MagicMock()

    with patch(
        "giljo_mcp.tools.write_memory_entry._check_and_emit_tuning_staleness",
        new_callable=AsyncMock,
    ):
        memory_result = await write_360_memory(
            project_id=project_id,
            tenant_key=test_tenant_key,
            summary="Sprint completed with HITL closeout",
            key_outcomes=["Implemented closeout checklist"],
            decisions_made=["Used HITL mode by default"],
            entry_type="decision",
            author_job_id=job_id,
            git_commits=[],
            tags=["chore"],
            db_manager=mock_db_manager,
            session=db_session,
        )
    entry_id = memory_result.get("entry_id")
    assert isinstance(entry_id, str)
    assert uuid.UUID(entry_id)
    sequence_number = memory_result.get("sequence_number")
    assert isinstance(sequence_number, int) and sequence_number >= 1

    from sqlalchemy import select as sa_select

    from giljo_mcp.models.agent_identity import AgentExecution as AgentExecutionModel

    exec_stmt = sa_select(AgentExecutionModel).where(
        AgentExecutionModel.job_id == job_id, AgentExecutionModel.tenant_key == test_tenant_key
    )
    exec_res = await db_session.execute(exec_stmt)
    exec_obj = exec_res.scalar_one_or_none()
    assert exec_obj is not None
    if exec_obj.status in ("blocked", "working", "waiting"):
        exec_obj.status = "complete"
        exec_obj.progress = 100
        await db_session.commit()

    from giljo_mcp.tools.project_closeout import close_project_and_update_memory

    closeout_result = await close_project_and_update_memory(
        project_id=project_id,
        summary="Final project closeout",
        key_outcomes=["All tasks complete"],
        decisions_made=["HITL mode used"],
        tenant_key=test_tenant_key,
        db_manager=mock_db_manager,
        session=db_session,
        force=True,
        git_commits=[{"sha": "abc123", "message": "test commit", "author": "test"}],
    )
    assert closeout_result.get("entry_id") is not None
    assert closeout_result.get("message") is not None




def test_resolve_git_commits_helper_exists():
    from giljo_mcp.tools.project_closeout import _resolve_git_commits

    assert callable(_resolve_git_commits)
