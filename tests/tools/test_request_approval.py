# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import random
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from pydantic import ValidationError as PydanticValidationError

from giljo_mcp.exceptions import ValidationError
from giljo_mcp.models.agent_identity import AgentExecution, AgentJob
from giljo_mcp.models.products import Product
from giljo_mcp.models.projects import Project
from giljo_mcp.tenant import TenantManager
from giljo_mcp.tools.tool_accessor import ToolAccessor


@pytest_asyncio.fixture
async def tool_accessor(db_manager, db_session):
    ws = MagicMock()
    ws.broadcast_to_tenant = AsyncMock()
    return ToolAccessor(
        db_manager=db_manager,
        tenant_manager=TenantManager(),
        websocket_manager=ws,
        test_session=db_session,
    )


@pytest_asyncio.fixture
async def seed(db_session, test_tenant_key):
    product = Product(
        id=str(uuid4()),
        name=f"P {uuid4().hex[:6]}",
        description="x",
        tenant_key=test_tenant_key,
        is_active=True,
    )
    db_session.add(product)
    project = Project(
        id=str(uuid4()),
        tenant_key=test_tenant_key,
        product_id=product.id,
        name="P",
        description="x",
        mission="x",
        status="active",
        series_number=random.randint(1, 9000),
    )
    db_session.add(project)
    await db_session.flush()
    job = AgentJob(
        job_id=str(uuid4()),
        tenant_key=test_tenant_key,
        project_id=project.id,
        job_type="orchestrator",
        mission="x",
        status="active",
        created_at=datetime.now(UTC),
    )
    db_session.add(job)
    await db_session.flush()
    execution = AgentExecution(
        id=str(uuid4()),
        agent_id=str(uuid4()),
        job_id=job.job_id,
        tenant_key=test_tenant_key,
        agent_display_name="orchestrator",
        status="working",
        started_at=datetime.now(UTC),
    )
    db_session.add(execution)
    await db_session.commit()
    return {"project": project, "job": job, "execution": execution}


@pytest.mark.asyncio
async def test_request_approval_happy_path(tool_accessor, seed, test_tenant_key):
    result = await tool_accessor.request_approval(
        job_id=seed["job"].job_id,
        project_id=seed["project"].id,
        reason="closeout decision",
        options=[
            {"id": "approve", "label": "Approve"},
            {"id": "rework", "label": "Rework"},
        ],
        context={"deferred": ["x"]},
        tenant_key=test_tenant_key,
    )
    assert set(result.keys()) == {"approval_id", "status"}
    approval_id = result["approval_id"]
    assert isinstance(approval_id, str)
    assert UUID(approval_id)
    assert result["status"] == "pending"


@pytest.mark.asyncio
async def test_request_approval_worker_gets_structured_rejection(tool_accessor, seed, db_session, test_tenant_key):
    worker_job = AgentJob(
        job_id=str(uuid4()),
        tenant_key=test_tenant_key,
        project_id=seed["project"].id,
        job_type="implementer",
        mission="x",
        status="active",
        created_at=datetime.now(UTC),
    )
    db_session.add(worker_job)
    await db_session.flush()
    worker_execution = AgentExecution(
        id=str(uuid4()),
        agent_id=str(uuid4()),
        job_id=worker_job.job_id,
        tenant_key=test_tenant_key,
        agent_display_name="implementer",
        status="working",
        started_at=datetime.now(UTC),
    )
    db_session.add(worker_execution)
    await db_session.commit()

    result = await tool_accessor.request_approval(
        job_id=worker_job.job_id,
        project_id=seed["project"].id,
        reason="worker asking for approval",
        options=[{"id": "approve", "label": "Approve"}],
        context=None,
        tenant_key=test_tenant_key,
    )

    assert result["success"] is False
    assert result["error"] == "ORCHESTRATOR_ONLY_APPROVAL"
    assert result["calling_agent_role"] == "implementer"
    assert "post_to_thread" in result["message"]

    await db_session.refresh(worker_execution)
    assert worker_execution.status == "working", "rejected worker must not be parked in awaiting_user"


@pytest.mark.asyncio
async def test_request_approval_rejects_missing_tenant(tool_accessor, seed):
    with pytest.raises(ValidationError):
        await tool_accessor.request_approval(
            job_id=seed["job"].job_id,
            project_id=seed["project"].id,
            reason="x",
            options=[{"id": "ok", "label": "OK"}],
            context=None,
            tenant_key=None,
        )


@pytest.mark.asyncio
async def test_request_approval_pydantic_rejects_bad_input(tool_accessor, seed, test_tenant_key):
    with pytest.raises(PydanticValidationError):
        await tool_accessor.request_approval(
            job_id=seed["job"].job_id,
            project_id=seed["project"].id,
            reason="x",
            options=[],
            context=None,
            tenant_key=test_tenant_key,
        )


@pytest.mark.asyncio
async def test_request_approval_pydantic_rejects_duplicate_ids(tool_accessor, seed, test_tenant_key):
    with pytest.raises(PydanticValidationError):
        await tool_accessor.request_approval(
            job_id=seed["job"].job_id,
            project_id=seed["project"].id,
            reason="x",
            options=[
                {"id": "dup", "label": "A"},
                {"id": "dup", "label": "B"},
            ],
            context=None,
            tenant_key=test_tenant_key,
        )
