# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

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
        description="be9499b diagnose reverse gear",
        tenant_key=tenant_key,
        is_active=True,
    )
    db_session.add(product)
    await db_session.flush()

    state.tool_accessor = ToolAccessor(
        db_manager=db_manager,
        tenant_manager=state.tenant_manager,
        test_session=db_session,
    )
    monkeypatch.setattr(_base, "_resolve_tenant", lambda ctx: tenant_key)
    monkeypatch.setattr(_base, "_resolve_user_id", lambda ctx: None)

    def _new_client():
        return create_connected_server_and_client_session(mcp_sdk_server.mcp)

    async def _make_project(*, staging_status: str | None, status: ProjectStatus = ProjectStatus.INACTIVE) -> str:
        project = Project(
            id=str(uuid4()),
            tenant_key=tenant_key,
            product_id=product.id,
            name="Diagnostic Project",
            description="d",
            mission="m",
            status=status,
            execution_mode="claude_code_cli",
            staging_status=staging_status,
        )
        db_session.add(project)
        await db_session.commit()
        return project.id

    try:
        yield _new_client, _make_project
    finally:
        state.tool_accessor, state.tenant_manager, state.db_manager = prior


def _payload(result):
    import json

    return json.loads(result.content[0].text)


async def test_staged_with_no_agents_suggests_unstage_not_cancel(diagnose_client):
    new_client, make_project = diagnose_client
    project_id = await make_project(staging_status="staged")

    async with new_client() as session:
        result = await session.call_tool("diagnose_project_state", {"project_id": project_id})

    assert result.is_error is False, result
    payload = _payload(result)
    assert "no_agents_spawned" in payload["stuck_conditions"]
    joined = " ".join(payload["suggested_actions"])
    assert "unstage" in joined
    assert "cancel_staging" not in joined


async def test_staging_with_no_agents_suggests_restage_or_cancel(diagnose_client):
    new_client, make_project = diagnose_client
    project_id = await make_project(staging_status="staging")

    async with new_client() as session:
        result = await session.call_tool("diagnose_project_state", {"project_id": project_id})

    assert result.is_error is False, result
    payload = _payload(result)
    assert "no_agents_spawned" in payload["stuck_conditions"]
    joined = " ".join(payload["suggested_actions"])
    assert "restage" in joined
    assert "cancel_staging" in joined


async def test_staging_but_not_inactive_omits_cancel_staging(diagnose_client):
    new_client, make_project = diagnose_client
    project_id = await make_project(staging_status="staging", status=ProjectStatus.ACTIVE)

    async with new_client() as session:
        result = await session.call_tool("diagnose_project_state", {"project_id": project_id})

    assert result.is_error is False, result
    payload = _payload(result)
    assert "no_agents_spawned" in payload["stuck_conditions"]
    joined = " ".join(payload["suggested_actions"])
    assert "restage" in joined
    assert "cancel_staging" not in joined
