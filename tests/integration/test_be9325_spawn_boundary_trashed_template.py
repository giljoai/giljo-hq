# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.models import Product, Project
from giljo_mcp.models.agent_identity import AgentJob
from giljo_mcp.models.templates import AgentTemplate
from giljo_mcp.tenant import TenantManager
from tests.helpers.mcp_session_fixture import create_connected_server_and_client_session


pytestmark = pytest.mark.asyncio


async def _seed_project_and_trashed_template(session: AsyncSession, tenant_key: str, agent_name: str) -> str:
    suffix = uuid.uuid4().hex[:8]
    _owning_product_project = Product(
        id=str(uuid.uuid4()),
        tenant_key=tenant_key,
        name=f"Owning Product {uuid.uuid4().hex[:6]}",
        description="seeded",
        is_active=False,
    )
    session.add(_owning_product_project)
    project = Project(
        id=str(uuid.uuid4()),
        name=f"BE-9325 Boundary {suffix}",
        description="MCP-boundary trashed-template spawn resolution project.",
        mission="Stage then write.",
        status="active",
        tenant_key=tenant_key,
        product_id=_owning_product_project.id,
        series_number=1,
        execution_mode="multi_terminal",
        created_at=datetime.now(UTC),
    )
    session.add(project)
    session.add(
        AgentTemplate(
            id=str(uuid.uuid4()),
            tenant_key=tenant_key,
            name=agent_name,
            category="custom",
            system_instructions="sys",
            is_active=True,
            deleted_at=datetime.now(UTC),
        )
    )
    session.info["tenant_key"] = tenant_key
    await session.flush()
    return project.id


@pytest_asyncio.fixture
async def spawn_boundary_client(monkeypatch, db_manager, db_session):
    from api import app_state
    from api.endpoints import mcp_sdk_server
    from giljo_mcp.tools.tool_accessor import ToolAccessor

    state = app_state.state
    prior_tool_accessor = state.tool_accessor
    prior_tenant_manager = state.tenant_manager
    prior_db_manager = state.db_manager

    tenant_manager = TenantManager()
    state.tenant_manager = tenant_manager
    state.db_manager = db_manager
    state.tool_accessor = ToolAccessor(
        db_manager=db_manager,
        tenant_manager=tenant_manager,
        test_session=db_session,
    )

    tenant_key = TenantManager.generate_tenant_key()
    from api.endpoints.mcp_tools import _base

    monkeypatch.setattr(_base, "_resolve_tenant", lambda ctx: tenant_key)
    monkeypatch.setattr(_base, "_resolve_user_id", lambda ctx: None)

    async def _noop(*args, **kwargs):
        return None

    monkeypatch.setattr("giljo_mcp.services.silence_detector.auto_clear_silent", _noop)
    monkeypatch.setattr("giljo_mcp.services.heartbeat.touch_heartbeat", _noop)

    def _new_client():
        return create_connected_server_and_client_session(mcp_sdk_server.mcp)

    try:
        yield _new_client, tenant_key, db_session
    finally:
        state.tool_accessor = prior_tool_accessor
        state.tenant_manager = prior_tenant_manager
        state.db_manager = prior_db_manager


def _payload(call_tool_result) -> dict:
    if getattr(call_tool_result, "structuredContent", None):
        return call_tool_result.structured_content
    return json.loads(call_tool_result.content[0].text)


def _error_text(call_tool_result) -> str:
    return "\n".join(getattr(b, "text", "") or "" for b in call_tool_result.content)


async def test_spawn_job_does_not_bind_trashed_template_identity(spawn_boundary_client) -> None:
    new_client, tenant_key, db_session = spawn_boundary_client
    agent_name = f"be9325-boundary-{uuid.uuid4().hex[:8]}"
    project_id = await _seed_project_and_trashed_template(db_session, tenant_key, agent_name)

    async with new_client() as session:
        result = await session.call_tool(
            "spawn_job",
            {
                "agent_display_name": "implementer",
                "agent_name": agent_name,
                "project_id": project_id,
                "mission": "Do the work.",
            },
        )

    assert result.is_error is True, (
        "spawn_job accepted a TRASHED agent name. The user deleted this agent, so the spawn "
        f"must be rejected rather than silently producing an agent with no identity. Got: {_payload(result)!r}"
    )
    error_text = _error_text(result)
    assert agent_name in error_text, "The rejection must name the agent that was asked for."

    job_rows = await db_session.execute(select(AgentJob).where(AgentJob.tenant_key == tenant_key))
    assert job_rows.scalars().all() == [], (
        "spawn_job created a job row for a TRASHED agent name. Nothing may be persisted for an agent the user deleted."
    )
