# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-6008 MCP-boundary regression: spawn_job WITHOUT a mission yields a staged agent.

CLAUDE.md (BE-5042 lesson): the @mcp.tool wrapper layer needs its OWN test —
the service-layer two-phase-spawn test can pass while the FastMCP boundary
(parameter defaults, kwargs assembly, _call_tool dispatch) is broken. This test
exercises spawn_job through the in-memory FastMCP transport, omitting the mission
argument entirely, and asserts the created execution is 'staged' with a NULL job
mission.

The whole spawn chain (boundary -> ToolAccessor -> OrchestrationService ->
JobLifecycleService) runs against the test session, so the staged write is rolled
back at teardown. Parallel-safe: unique tenant per test, no module globals, no
ordering dependency.

Pattern: tests/integration/test_imp6038_giljo_setup_ack_mcp_boundary.py.

Project: BE-6008.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.models import Product, Project
from giljo_mcp.models.agent_identity import AgentExecution, AgentJob
from giljo_mcp.models.templates import AgentTemplate
from giljo_mcp.tenant import TenantManager
from tests.helpers.mcp_session_fixture import create_connected_server_and_client_session


pytestmark = pytest.mark.asyncio


async def _seed_project_and_template(session: AsyncSession, tenant_key: str) -> str:
    suffix = uuid.uuid4().hex[:8]
    # BE-9437: a project belongs to a product. Its own, so an active
    # seed cannot collide under idx_project_single_active_per_product.
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
        name=f"BE-6008 Boundary {suffix}",
        description="MCP-boundary two-phase spawn project.",
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
            name="implementer",
            is_active=True,
        )
    )
    session.info["tenant_key"] = tenant_key
    await session.flush()
    return project.id


@pytest_asyncio.fixture
async def spawn_boundary_client(monkeypatch, db_manager, db_session):
    """In-memory FastMCP client wired to a REAL ToolAccessor on the test session."""
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
    # BE-6042d: _resolve_tenant/_resolve_user_id moved to mcp_tools._base (the
    # _call_tool call site reads them there). Patch _base, not mcp_sdk_server.
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


async def test_spawn_job_without_mission_through_mcp_boundary_is_staged(spawn_boundary_client) -> None:
    """spawn_job called WITHOUT mission through the FastMCP transport creates a 'staged' execution."""
    new_client, tenant_key, db_session = spawn_boundary_client
    project_id = await _seed_project_and_template(db_session, tenant_key)

    async with new_client() as session:
        result = await session.call_tool(
            "spawn_job",
            {
                "agent_display_name": "implementer",
                "agent_name": "implementer",
                "project_id": project_id,
                # mission intentionally omitted -> two-phase spawn
            },
        )

    assert result.is_error is False, _error_text(result)
    job_id = _payload(result)["job_id"]

    exec_row = await db_session.execute(
        select(AgentExecution).where(
            AgentExecution.tenant_key == tenant_key,
            AgentExecution.job_id == job_id,
        )
    )
    execution = exec_row.scalar_one()

    job_row = await db_session.execute(
        select(AgentJob).where(AgentJob.tenant_key == tenant_key, AgentJob.job_id == job_id)
    )
    job = job_row.scalar_one()

    assert execution.status == "staged", "boundary spawn without mission must yield a 'staged' execution"
    assert job.mission is None, "a staged job's mission must be NULL at the boundary"
