# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import json
import random
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import select

from giljo_mcp.models.agent_identity import AgentExecution, AgentJob, AgentTodoItem
from giljo_mcp.models.products import Product
from giljo_mcp.models.projects import Project
from giljo_mcp.models.tasks import Message, MessageRecipient
from giljo_mcp.tenant import TenantManager
from tests.helpers.mcp_session_fixture import create_connected_server_and_client_session


pytestmark = pytest.mark.asyncio


def _payload(call_tool_result) -> dict:
    if getattr(call_tool_result, "structuredContent", None):
        return call_tool_result.structured_content
    text = getattr(call_tool_result.content[0], "text", None)
    if text is None:
        raise AssertionError(f"unexpected content block: {call_tool_result.content[0]!r}")
    return json.loads(text)


def _error_text(call_tool_result) -> str:
    return "\n".join(getattr(b, "text", "") or "" for b in call_tool_result.content)


@pytest_asyncio.fixture
async def boundary_client(db_manager, db_session, monkeypatch):
    from api import app_state
    from api.endpoints import mcp_sdk_server
    from api.endpoints.mcp_tools import _base
    from giljo_mcp.services.job_completion_service import JobCompletionService
    from giljo_mcp.tools.tool_accessor import ToolAccessor

    state = app_state.state
    prior_accessor = state.tool_accessor
    prior_tenant_manager = state.tenant_manager
    prior_db_manager = state.db_manager

    if state.tenant_manager is None:
        state.tenant_manager = TenantManager()
    state.db_manager = db_manager

    tenant_key = TenantManager.generate_tenant_key()

    accessor = ToolAccessor(db_manager=db_manager, tenant_manager=state.tenant_manager)
    accessor._job_completion_service = JobCompletionService(
        db_manager=db_manager,
        tenant_manager=state.tenant_manager,
        test_session=db_session,
    )
    state.tool_accessor = accessor

    monkeypatch.setattr(_base, "_resolve_tenant", lambda ctx: tenant_key)
    monkeypatch.setattr(_base, "_resolve_user_id", lambda ctx: None)

    def _new_client():
        return create_connected_server_and_client_session(mcp_sdk_server.mcp)

    try:
        yield _new_client, tenant_key, db_session
    finally:
        state.tool_accessor = prior_accessor
        state.tenant_manager = prior_tenant_manager
        state.db_manager = prior_db_manager


async def _seed_closeout_orchestrator(db_session, tenant_key: str) -> tuple[AgentJob, AgentExecution]:
    product = Product(
        id=str(uuid4()),
        tenant_key=tenant_key,
        name="BE-9012b boundary product",
        description="closeout dance gone",
        product_memory={},
    )
    db_session.add(product)
    await db_session.flush()
    project = Project(
        id=str(uuid4()),
        tenant_key=tenant_key,
        product_id=product.id,
        name="BE-9012b boundary project",
        description="closeout dance gone",
        mission="test",
        status="active",
        created_at=datetime.now(UTC),
        series_number=random.randint(1, 9000),
    )
    db_session.add(project)
    await db_session.flush()
    job = AgentJob(
        job_id=str(uuid4()),
        tenant_key=tenant_key,
        project_id=project.id,
        job_type="orchestrator",
        mission="coordinate closeout",
        status="active",
        created_at=datetime.now(UTC),
    )
    db_session.add(job)
    await db_session.flush()
    execution = AgentExecution(
        id=str(uuid4()),
        agent_id=str(uuid4()),
        job_id=job.job_id,
        tenant_key=tenant_key,
        agent_display_name="orchestrator",
        status="working",
        started_at=datetime.now(UTC) - timedelta(minutes=5),
    )
    db_session.add(execution)
    db_session.add(
        AgentTodoItem(
            job_id=job.job_id,
            tenant_key=tenant_key,
            content="Closeout: complete orchestrator job",
            status="in_progress",
            sequence=0,
        )
    )
    await db_session.commit()
    await db_session.refresh(job)
    await db_session.refresh(execution)
    return job, execution


async def _add_unread(db_session, tenant_key: str, project_id: str, agent_id: str, *, requires_action: bool) -> None:
    msg = Message(
        tenant_key=tenant_key,
        project_id=project_id,
        from_agent_id=str(uuid4()),
        content="progress note" if not requires_action else "REWORK_REQUIRED please act",
        status="pending",
        requires_action=requires_action,
        created_at=datetime.now(UTC) - timedelta(minutes=1),
    )
    db_session.add(msg)
    await db_session.flush()
    db_session.add(MessageRecipient(message_id=msg.id, agent_id=agent_id, tenant_key=tenant_key))
    await db_session.commit()


async def test_closeout_dance_gone_without_flags_via_mcp(boundary_client):
    new_client, tenant_key, session = boundary_client
    job, execution = await _seed_closeout_orchestrator(session, tenant_key)
    project_id = job.project_id
    await _add_unread(session, tenant_key, project_id, execution.agent_id, requires_action=False)

    async with new_client() as mcp_session:
        result = await mcp_session.call_tool(
            "complete_job",
            {"job_id": job.job_id, "result": {"summary": "closeout, no flags"}},
        )

    assert result.is_error is False, f"closeout dance must be gone; got: {_error_text(result)}"
    payload = _payload(result)
    assert payload.get("status") == "success", payload

    todo = (
        await session.execute(
            select(AgentTodoItem).where(AgentTodoItem.job_id == job.job_id, AgentTodoItem.tenant_key == tenant_key)
        )
    ).scalar_one()
    assert todo.status == "completed"


async def test_action_required_post_still_blocks_via_mcp(boundary_client):
    new_client, tenant_key, session = boundary_client
    job, execution = await _seed_closeout_orchestrator(session, tenant_key)
    await _add_unread(session, tenant_key, job.project_id, execution.agent_id, requires_action=True)

    async with new_client() as mcp_session:
        result = await mcp_session.call_tool(
            "complete_job",
            {"job_id": job.job_id, "result": {"summary": "should be blocked"}},
        )

    assert result.is_error is True, "an unresolved action-required post must block complete_job at the boundary"
    assert "COMPLETION_BLOCKED" in _error_text(result)
