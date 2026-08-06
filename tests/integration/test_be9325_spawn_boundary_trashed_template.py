# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-9325 MCP-boundary regression: spawn_job must not hand back a trashed
template's identity through the real transport.

``AgentCompletionRepository.get_template_by_name`` (called by
``JobLifecycleService._resolve_spawn_template``) now filters
``deleted_at IS NULL`` -- fixed and unit-tested at the repository layer in
``tests/services/test_be9325_trashed_template_lifecycle.py``. Per CLAUDE.md's
regression-test rule (BE-5042 lesson), a repository test alone is
insufficient: the agent-facing surface is the @mcp.tool ``spawn_job`` wrapper,
so this exercises the SAME code path through the real FastMCP transport
(boundary -> ToolAccessor -> OrchestrationService -> JobLifecycleService).

Only one template row exists for the spawned agent name, and it is trashed
(``deleted_at`` set, ``is_active`` still True -- exactly what soft-delete
leaves behind). The pre-BE-9325 query matched the trashed row and stamped ITS
id onto the job -- binding a deleted agent's identity to a live spawn.

BE-9337 then fixed the spawn ALLOWLIST (``get_active_template_names``) in the
same repository file, which had still been offering trashed names. With the
allowlist and the lookup finally agreeing, the trashed name is rejected at
validation and no job is created at all -- so the assertion below is now
"rejected", not "succeeded with a NULL template". See the test docstring.

Pattern: tests/integration/test_be6008_spawn_boundary.py.

Projects: BE-9325, BE-9337.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from mcp.shared.memory import create_connected_server_and_client_session
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.models import Project
from giljo_mcp.models.agent_identity import AgentJob
from giljo_mcp.models.templates import AgentTemplate
from giljo_mcp.tenant import TenantManager


pytestmark = pytest.mark.asyncio


async def _seed_project_and_trashed_template(session: AsyncSession, tenant_key: str, agent_name: str) -> str:
    suffix = uuid.uuid4().hex[:8]
    project = Project(
        id=str(uuid.uuid4()),
        name=f"BE-9325 Boundary {suffix}",
        description="MCP-boundary trashed-template spawn resolution project.",
        mission="Stage then write.",
        status="active",
        tenant_key=tenant_key,
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
            is_active=True,  # BE-9325: soft-delete leaves is_active True -- the whole bug.
            deleted_at=datetime.now(UTC),
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
        return call_tool_result.structuredContent
    return json.loads(call_tool_result.content[0].text)


def _error_text(call_tool_result) -> str:
    return "\n".join(getattr(b, "text", "") or "" for b in call_tool_result.content)


async def test_spawn_job_does_not_bind_trashed_template_identity(spawn_boundary_client) -> None:
    """spawn_job through the FastMCP transport must not stamp a trashed
    template's id onto the new job -- the user deleted that agent.

    BE-9337 STRENGTHENED THIS CONTRACT. This test previously asserted that the
    spawn SUCCEEDS with ``template_id`` NULL, and carried a comment noting that
    "succeeds with no template" is not the same as "the user is fine": a
    non-orchestrator job with ``template_id`` NULL gets no identity section from
    ``get_job_mission`` at all (MissionService's fallback is gated to
    orchestrators, ``mission_service.py:583``), so the user asked for agent X
    and silently got a generic one. That was BE-9333, and it was reachable here
    for exactly one reason: the spawn ALLOWLIST
    (``get_active_template_names``) and the spawn LOOKUP
    (``get_template_by_name``) disagreed about trashed rows. BE-9325 fixed the
    lookup; the allowlist still offered the trashed name, so validation passed
    and resolution then found nothing.

    BE-9337 fixed the allowlist, so the two queries are now predicate-identical
    and the disagreement is gone. The trashed name no longer passes validation
    at all: the spawn is REJECTED with a message naming the agents that do
    exist, instead of succeeding into a silent identity-less agent. The
    original intent of this test is preserved and made stronger -- no trashed
    identity is bound, because no job is created.
    """
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

    assert result.isError is True, (
        "spawn_job accepted a TRASHED agent name. The user deleted this agent, so the spawn "
        f"must be rejected rather than silently producing an agent with no identity. Got: {_payload(result)!r}"
    )
    error_text = _error_text(result)
    assert agent_name in error_text, "The rejection must name the agent that was asked for."

    job_rows = await db_session.execute(select(AgentJob).where(AgentJob.tenant_key == tenant_key))
    assert job_rows.scalars().all() == [], (
        "spawn_job created a job row for a TRASHED agent name. Nothing may be persisted for an agent the user deleted."
    )
