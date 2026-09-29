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

from giljo_mcp.models.agent_identity import AgentExecution, AgentJob, AgentTodoItem
from giljo_mcp.models.organizations import Organization
from giljo_mcp.models.products import Product
from giljo_mcp.models.projects import Project
from giljo_mcp.models.tasks import Message
from giljo_mcp.tenant import TenantManager
from tests.helpers.mcp_session_fixture import create_connected_server_and_client_session


pytestmark = pytest.mark.asyncio


def _payload(call_tool_result) -> dict:
    if getattr(call_tool_result, "structuredContent", None):
        return call_tool_result.structured_content
    return json.loads(call_tool_result.content[0].text)


def _error_text(call_tool_result) -> str:
    return "\n".join(getattr(b, "text", "") or "" for b in call_tool_result.content)


async def _seed(db_session, tenant_key: str, *, todo_statuses: list[str], quiet_minutes: int) -> dict:
    suffix = uuid4().hex[:8]
    now = datetime.now(UTC)
    db_session.add(Organization(name=f"Org {suffix}", slug=f"org-{suffix}", tenant_key=tenant_key, is_active=True))
    product = Product(id=str(uuid4()), name=f"Product {suffix}", description="x", tenant_key=tenant_key, is_active=True)
    db_session.add(product)
    await db_session.flush()
    project = Project(
        id=str(uuid4()),
        tenant_key=tenant_key,
        product_id=product.id,
        name=f"Project {suffix}",
        description="x",
        mission="x",
        status="active",
        staging_status="staging_complete",
        execution_mode="claude_code_cli",
        series_number=random.randint(1, 9000),
        implementation_launched_at=now - timedelta(minutes=90),
    )
    db_session.add(project)
    await db_session.flush()
    job = AgentJob(
        job_id=str(uuid4()),
        tenant_key=tenant_key,
        project_id=project.id,
        job_type="implementer",
        mission="Implement the thing.",
        status="active",
        created_at=now - timedelta(minutes=80),
    )
    db_session.add(job)
    await db_session.flush()
    agent_id = str(uuid4())
    db_session.add(
        AgentExecution(
            id=str(uuid4()),
            agent_id=agent_id,
            job_id=job.job_id,
            tenant_key=tenant_key,
            agent_display_name="implementer",
            agent_name="implementer",
            status="silent",
            started_at=now - timedelta(minutes=70),
            last_progress_at=now - timedelta(minutes=quiet_minutes),
        )
    )
    for seq, todo_status in enumerate(todo_statuses):
        db_session.add(
            AgentTodoItem(
                job_id=job.job_id, tenant_key=tenant_key, content=f"step {seq}", status=todo_status, sequence=seq
            )
        )
    db_session.add(
        Message(
            tenant_key=tenant_key,
            project_id=project.id,
            content="PR open, holding for the gate.",
            from_agent_id=agent_id,
            from_kind="agent",
            message_type="broadcast",
        )
    )
    await db_session.commit()
    return {"project_id": project.id, "job_id": job.job_id}


class _TenantSwitch:
    def __init__(self, value: str):
        self.value = value


@pytest_asyncio.fixture
async def mcp_client(db_manager, db_session, monkeypatch):
    from api import app_state
    from api.endpoints import mcp_sdk_server
    from api.endpoints.mcp_tools import _base
    from giljo_mcp.tools.tool_accessor import ToolAccessor

    state = app_state.state
    prior = (state.tool_accessor, state.tenant_manager, state.db_manager)
    if state.tenant_manager is None:
        state.tenant_manager = TenantManager()
    state.db_manager = db_manager
    state.tool_accessor = ToolAccessor(
        db_manager=db_manager, tenant_manager=state.tenant_manager, test_session=db_session
    )
    tenant = _TenantSwitch(TenantManager.generate_tenant_key())
    monkeypatch.setattr(_base, "_resolve_tenant", lambda ctx: tenant.value)
    monkeypatch.setattr(_base, "_resolve_user_id", lambda ctx: None)
    try:
        yield (lambda: create_connected_server_and_client_session(mcp_sdk_server.mcp)), tenant.value
    finally:
        state.tool_accessor, state.tenant_manager, state.db_manager = prior


async def test_holding_worker_is_holding_and_not_wedged(mcp_client, db_session):
    new_client, tenant_key = mcp_client
    seed = await _seed(db_session, tenant_key, todo_statuses=["completed", "completed"], quiet_minutes=30)

    async with new_client() as session:
        result = await session.call_tool("get_workflow_status", {"project_id": seed["project_id"]})
        assert result.is_error is False, _error_text(result)
        payload = _payload(result)
        assert "wedged" not in payload["caller_note"]
        assert payload["silent_agents"] == 0
        [agent] = payload["agents"]
        assert agent["job_id"] == seed["job_id"]
        assert agent["activity"] == "holding"
        assert payload["holding_agents"] == 1
        assert "wedged" not in ((payload.get("next_action") or {}).get("why") or "")


async def test_real_stall_is_silent_and_wedged(mcp_client, db_session):
    new_client, tenant_key = mcp_client
    seed = await _seed(db_session, tenant_key, todo_statuses=["completed", "pending"], quiet_minutes=11)

    async with new_client() as session:
        result = await session.call_tool("get_workflow_status", {"project_id": seed["project_id"]})
        assert result.is_error is False, _error_text(result)
        payload = _payload(result)
        [agent] = payload["agents"]
        assert agent["activity"] == "silent"
        assert payload["silent_agents"] == 1
        assert "wedged" in payload["caller_note"]
        assert payload["next_action"]["tool"] == "diagnose_project_state"
