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

from giljo_mcp.models.agent_identity import AgentExecution, AgentJob
from giljo_mcp.models.organizations import Organization
from giljo_mcp.models.products import Product
from giljo_mcp.models.projects import Project
from giljo_mcp.tenant import TenantManager
from tests.helpers.mcp_session_fixture import create_connected_server_and_client_session


pytestmark = pytest.mark.asyncio


def _payload(call_tool_result) -> dict:
    if getattr(call_tool_result, "structuredContent", None):
        return call_tool_result.structured_content
    return json.loads(call_tool_result.content[0].text)


def _error_text(call_tool_result) -> str:
    return "\n".join(getattr(b, "text", "") or "" for b in call_tool_result.content)


async def _seed(db_session, tenant_key: str) -> dict:
    suffix = uuid4().hex[:8]
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
        implementation_launched_at=datetime.now(UTC) - timedelta(minutes=15),
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
        created_at=datetime.now(UTC) - timedelta(minutes=30),
    )
    db_session.add(job)
    await db_session.flush()
    db_session.add(
        AgentExecution(
            id=str(uuid4()),
            agent_id=str(uuid4()),
            job_id=job.job_id,
            tenant_key=tenant_key,
            agent_display_name="implementer",
            agent_name="implementer",
            status="waiting",
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


async def test_workflow_status_flags_then_get_job_mission_clears(mcp_client, db_session):
    new_client, tenant_key = mcp_client
    seed = await _seed(db_session, tenant_key)

    async with new_client() as session:
        before = await session.call_tool("get_workflow_status", {"project_id": seed["project_id"]})
        assert before.is_error is False, _error_text(before)
        payload = _payload(before)
        assert payload["not_picked_up_agents"] == 1
        [agent] = payload["agents"]
        assert agent["job_id"] == seed["job_id"]
        assert agent["not_picked_up"] is True
        assert "launch it with the stored prompt" in payload["next_action"]["why"]

        mission = await session.call_tool("get_job_mission", {"job_id": seed["job_id"]})
        assert mission.is_error is False, _error_text(mission)
        assert _payload(mission).get("blocked") is not True, _payload(mission)

        after = await session.call_tool("get_workflow_status", {"project_id": seed["project_id"]})
        assert after.is_error is False, _error_text(after)
        after_payload = _payload(after)
        assert after_payload["not_picked_up_agents"] == 0
        [agent_after] = after_payload["agents"]
        assert agent_after["status"] == "working"
        assert agent_after["not_picked_up"] is False
