# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

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
from tests.helpers.taxonomy_seeds import next_series_number


async def _seed_worker_with_plan(session: AsyncSession, tenant_key: str, statuses: list[str]) -> str:
    product = Product(id=str(uuid4()), tenant_key=tenant_key, name="BE-9819 product", product_memory={})
    session.add(product)
    project = Project(
        id=str(uuid4()),
        tenant_key=tenant_key,
        product_id=product.id,
        name="BE-9819 project",
        description="handed-off plan",
        mission="m",
        status="active",
        staging_status="staging_complete",
        implementation_launched_at=datetime.now(UTC) - timedelta(minutes=10),
        created_at=datetime.now(UTC),
        series_number=next_series_number(),
    )
    session.add(project)
    job_id = str(uuid4())
    session.add(
        AgentJob(
            job_id=job_id,
            tenant_key=tenant_key,
            project_id=project.id,
            job_type="implementer",
            mission="w",
            status="active",
        )
    )
    session.add(
        AgentExecution(
            job_id=job_id,
            tenant_key=tenant_key,
            agent_display_name="implementer",
            status="working",
            messages_sent_count=0,
            messages_waiting_count=0,
            messages_read_count=0,
            started_at=datetime.now(UTC) - timedelta(minutes=5),
            project_phase="implementation",
        )
    )
    for i, status in enumerate(statuses):
        content = "HANDOFF TSK-0003: new token issued by the operator" if status == "skipped" else f"step {i + 1}"
        session.add(AgentTodoItem(job_id=job_id, tenant_key=tenant_key, content=content, status=status, sequence=i))
    await session.commit()
    return job_id


def _service(session: AsyncSession, tenant_key: str) -> JobCompletionService:
    tenant_manager = MagicMock()
    tenant_manager.get_current_tenant.return_value = tenant_key
    return JobCompletionService(db_manager=MagicMock(), tenant_manager=tenant_manager, test_session=session)


@pytest.mark.asyncio
async def test_complete_job_accepts_a_handed_off_step(db_session: AsyncSession, test_tenant_key: str):
    job_id = await _seed_worker_with_plan(db_session, test_tenant_key, ["completed", "completed", "skipped"])

    result = await _service(db_session, test_tenant_key).complete_job(
        job_id=job_id, result={"summary": "done; one step handed off"}, tenant_key=test_tenant_key
    )

    assert result.status == "success"
    execution = (await db_session.execute(select(AgentExecution).where(AgentExecution.job_id == job_id))).scalar_one()
    assert execution.status == "complete"


@pytest.mark.asyncio
async def test_complete_job_still_blocks_on_a_pending_step_beside_a_handed_off_one(
    db_session: AsyncSession, test_tenant_key: str
):
    job_id = await _seed_worker_with_plan(db_session, test_tenant_key, ["completed", "skipped", "pending"])

    with pytest.raises(ValidationError) as exc_info:
        await _service(db_session, test_tenant_key).complete_job(
            job_id=job_id, result={"summary": "trying to close early"}, tenant_key=test_tenant_key
        )

    assert "COMPLETION_BLOCKED" in str(exc_info.value)
