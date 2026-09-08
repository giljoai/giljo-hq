# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-6111c — transport regression for the net-new diagnose_project_state tool.

BE-5042 discipline: a tool can pass every service-layer test yet fail to register
on the FastMCP ``mcp`` instance — so this exercises diagnose_project_state THROUGH
the in-memory MCP transport (registration + wrapper dispatch + real service read +
wire serialization), not just the service. Seeds a project with no agents and
asserts the lifecycle diagnostic (gates + counts + readiness + stuck conditions)
comes back over the wire.

Edition Scope: Both.
"""

from __future__ import annotations

import json
from uuid import uuid4

import pytest
import pytest_asyncio

from giljo_mcp.domain.project_status import ProjectStatus
from giljo_mcp.models.organizations import Organization
from giljo_mcp.models.products import Product
from giljo_mcp.models.projects import Project
from giljo_mcp.tenant import TenantManager
from tests.helpers.mcp_session_fixture import create_connected_server_and_client_session


pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def diagnose_client(db_manager, db_session, monkeypatch):
    """Yield ``(new_client, project_id)`` for the FastMCP transport: a real
    ToolAccessor over the rolled-back test session + a synthetic tenant + a seeded
    no-agents project."""
    from api import app_state
    from api.endpoints import mcp_sdk_server
    from api.endpoints.mcp_tools import _base
    from giljo_mcp.tools.tool_accessor import ToolAccessor

    state = app_state.state
    prior = (state.tool_accessor, state.tenant_manager, state.db_manager)
    if state.tenant_manager is None:
        state.tenant_manager = TenantManager()
    state.db_manager = db_manager

    tenant_key = TenantManager.generate_tenant_key()
    suffix = uuid4().hex[:8]
    org = Organization(name=f"Org {suffix}", slug=f"org-{suffix}", tenant_key=tenant_key, is_active=True)
    db_session.add(org)
    await db_session.flush()
    product = Product(
        id=str(uuid4()),
        name=f"Product {suffix}",
        description="be6111c diagnose",
        tenant_key=tenant_key,
        is_active=True,
    )
    db_session.add(product)
    await db_session.flush()
    project = Project(
        id=str(uuid4()),
        tenant_key=tenant_key,
        product_id=product.id,
        name="Diagnostic Project",
        description="d",
        mission="m",
        status=ProjectStatus.ACTIVE,
        execution_mode="claude_code_cli",
    )
    db_session.add(project)
    await db_session.commit()

    state.tool_accessor = ToolAccessor(
        db_manager=db_manager,
        tenant_manager=state.tenant_manager,
        test_session=db_session,
    )
    monkeypatch.setattr(_base, "_resolve_tenant", lambda ctx: tenant_key)
    monkeypatch.setattr(_base, "_resolve_user_id", lambda ctx: None)

    def _new_client():
        return create_connected_server_and_client_session(mcp_sdk_server.mcp)

    try:
        yield _new_client, project.id, product.id
    finally:
        state.tool_accessor, state.tenant_manager, state.db_manager = prior


def _payload(result):
    text = result.content[0].text
    return json.loads(text)


async def test_diagnose_project_state_dispatches_through_transport(diagnose_client):
    """A no-agents ACTIVE project diagnoses over the wire: gates + zero counts +
    can_close False + the no_agents_spawned stuck condition."""
    new_client, project_id, product_id = diagnose_client

    async with new_client() as session:
        result = await session.call_tool("diagnose_project_state", {"project_id": project_id})

    assert result.is_error is False, f"diagnose_project_state failed at transport: {result}"
    payload = _payload(result)
    assert payload["project_id"] == project_id
    # BE-9525a: diagnose_project_state's return omitted product_id — an orchestrator
    # juggling projects across products had no way to tell which product a diagnosed
    # project belongs to without a second lookup.
    assert payload["product_id"] == product_id
    assert payload["status"] == "active"
    assert payload["execution_mode"] == "claude_code_cli"
    assert payload["agent_status_counts"]["total"] == 0
    assert payload["readiness"]["can_close"] is False
    assert payload["readiness"]["blockers"] == []
    assert "no_agents_spawned" in payload["stuck_conditions"]
    # execution_mode IS set, so that is NOT flagged.
    assert "execution_mode_not_selected" not in payload["stuck_conditions"]


async def test_diagnose_flags_missing_execution_mode(diagnose_client, db_session):
    """A project with NULL execution_mode is flagged execution_mode_not_selected."""
    new_client, project_id, _product_id = diagnose_client

    # Null out execution_mode on the seeded project (same rolled-back txn).
    project = await db_session.get(Project, project_id)
    project.execution_mode = None
    await db_session.commit()

    async with new_client() as session:
        result = await session.call_tool("diagnose_project_state", {"project_id": project_id})

    assert result.is_error is False, result
    payload = _payload(result)
    assert payload["execution_mode"] is None
    assert "execution_mode_not_selected" in payload["stuck_conditions"]
