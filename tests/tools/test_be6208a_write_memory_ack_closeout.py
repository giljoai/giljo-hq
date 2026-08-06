# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-6208a — write_memory_entry honors acknowledge_closeout_todo.

The conductor's own series-summary TODO is a chicken-and-egg: it blocks the
very write_memory_entry that satisfies it. acknowledge_closeout_todo=True
auto-completes the author's self-referential closeout TODO (CLOSEOUT_TODO_PATTERN)
before the closeout-readiness gate evaluates -- the SAME bypass complete_job
uses. Non-closeout TODOs still block.
"""

from __future__ import annotations

import random
import uuid
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest
import pytest_asyncio
from sqlalchemy import select

from giljo_mcp.models import Project
from giljo_mcp.models.agent_identity import AgentExecution, AgentJob, AgentTodoItem
from giljo_mcp.tools.write_memory_entry import write_360_memory


@pytest.fixture(autouse=True)
def _stub_staleness():
    """Staleness check needs a real db_manager; not under test here."""

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
        name="BE-6208a ack closeout project",
        description="ack closeout",
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
            status="complete",
            started_at=datetime.now(UTC),
        )
    )
    db_session.add(
        AgentTodoItem(
            job_id=job_id,
            tenant_key=tenant_key,
            content=content,
            status=status,
            sequence=0,
        )
    )
    await db_session.commit()
    return job_id


@pytest.mark.asyncio
async def test_ack_closeout_todo_unblocks_series_summary_write(
    db_session, test_tenant_key, test_product, linked_project
):
    job_id = await _seed_orchestrator_with_todo(
        db_session, test_tenant_key, linked_project.id, "Write series summary (closeout)"
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
        # user_id supplied so the staleness check (faked by _stub_staleness
        # above) skips its db_manager-backed tenant-user lookup -- db_manager
        # is otherwise unused by this test.
        user_id=str(uuid.uuid4()),
        db_manager=MagicMock(),
        session=db_session,
    )
    assert result.get("entry_id")
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
async def test_without_flag_closeout_todo_still_blocks(db_session, test_tenant_key, test_product, linked_project):
    job_id = await _seed_orchestrator_with_todo(
        db_session, test_tenant_key, linked_project.id, "Write series summary (closeout)"
    )

    result = await write_360_memory(
        project_id=str(linked_project.id),
        tenant_key=test_tenant_key,
        summary="Series summary",
        key_outcomes=["chain complete"],
        decisions_made=["decision"],
        entry_type="project_completion",
        author_job_id=job_id,
        # user_id supplied so the staleness check (faked by _stub_staleness
        # above) skips its db_manager-backed tenant-user lookup -- db_manager
        # is otherwise unused by this test.
        user_id=str(uuid.uuid4()),
        db_manager=MagicMock(),
        session=db_session,
    )
    assert result.get("error") == "CLOSEOUT_BLOCKED"


@pytest.mark.asyncio
async def test_ack_does_not_bypass_non_closeout_todo(db_session, test_tenant_key, test_product, linked_project):
    job_id = await _seed_orchestrator_with_todo(
        db_session, test_tenant_key, linked_project.id, "Refactor the login flow"
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
        # user_id supplied so the staleness check (faked by _stub_staleness
        # above) skips its db_manager-backed tenant-user lookup -- db_manager
        # is otherwise unused by this test.
        user_id=str(uuid.uuid4()),
        db_manager=MagicMock(),
        session=db_session,
    )
    assert result.get("error") == "CLOSEOUT_BLOCKED"
