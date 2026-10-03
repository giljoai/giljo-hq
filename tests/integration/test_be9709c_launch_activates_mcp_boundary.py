# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import json
import random
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import select

from giljo_mcp.models.products import Product
from giljo_mcp.models.projects import Project, ProjectStatus
from giljo_mcp.tenant import TenantManager
from tests.helpers.mcp_session_fixture import create_connected_server_and_client_session


pytestmark = pytest.mark.asyncio


def _payload(call_tool_result) -> dict:
    if getattr(call_tool_result, "structuredContent", None):
        return call_tool_result.structured_content
    return json.loads(call_tool_result.content[0].text)


def _error_text(call_tool_result) -> str:
    return "\n".join(getattr(block, "text", "") or "" for block in call_tool_result.content)


@pytest_asyncio.fixture
async def launch_client(db_manager, db_session, monkeypatch):
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

    tenant_key = TenantManager.generate_tenant_key()
    monkeypatch.setattr(_base, "_resolve_tenant", lambda ctx: tenant_key)
    monkeypatch.setattr(_base, "_resolve_user_id", lambda ctx: "test-human-user")

    try:
        yield (lambda: create_connected_server_and_client_session(mcp_sdk_server.mcp)), tenant_key
    finally:
        state.tool_accessor, state.tenant_manager, state.db_manager = prior


async def _seed_staged_inactive_project(db_session, tenant_key: str) -> str:
    product = Product(
        id=str(uuid4()),
        name=f"BE9709c Product {uuid4().hex[:6]}",
        description="launch activation boundary test",
        tenant_key=tenant_key,
        is_active=True,
        product_memory={},
    )
    db_session.add(product)
    await db_session.flush()
    project = Project(
        id=str(uuid4()),
        tenant_key=tenant_key,
        product_id=product.id,
        name=f"BE9709c Project {uuid4().hex[:6]}",
        description="x",
        mission="x",
        status=ProjectStatus.INACTIVE,
        execution_mode="claude_code_cli",
        staging_status="staging_complete",
        series_number=random.randint(1, 9000),
    )
    db_session.add(project)
    await db_session.commit()
    return project.id


async def _row(db_session, project_id: str, tenant_key: str) -> Project:
    return (
        await db_session.execute(
            select(Project)
            .where(Project.id == project_id, Project.tenant_key == tenant_key)
            .execution_options(populate_existing=True)
        )
    ).scalar_one()


async def test_launch_over_mcp_leaves_the_project_active(launch_client, db_session):
    new_client, tenant_key = launch_client
    project_id = await _seed_staged_inactive_project(db_session, tenant_key)
    before = await _row(db_session, project_id, tenant_key)
    assert before.status == ProjectStatus.INACTIVE
    assert before.implementation_launched_at is None

    async with new_client() as session:
        result = await session.call_tool("launch_implementation", {"project_id": project_id})

    assert result.is_error is False, _error_text(result)
    payload = _payload(result)
    assert payload["status"] == "launched"
    assert payload["already_launched"] is False
    assert payload["project_active"] is True, f"the reply still reports an inactive project: {payload!r}"
    assert "next_action" not in payload, f"nothing further is required, got: {payload.get('next_action')!r}"

    after = await _row(db_session, project_id, tenant_key)
    assert after.implementation_launched_at is not None
    assert after.status == ProjectStatus.ACTIVE
