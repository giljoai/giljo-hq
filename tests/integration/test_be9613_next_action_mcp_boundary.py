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

from giljo_mcp.models import Product, Project
from giljo_mcp.models.projects import TaxonomyType
from giljo_mcp.services import next_action as na
from giljo_mcp.tenant import TenantManager
from tests.helpers.mcp_session_fixture import create_connected_server_and_client_session
from tests.helpers.test_db_helper import purge_tenant_rows


pytestmark = pytest.mark.asyncio


def _payload(result) -> dict:
    if getattr(result, "structuredContent", None):
        return result.structured_content
    first = result.content[0]
    text = getattr(first, "text", None)
    if text is None:  # pragma: no cover - defensive
        raise AssertionError(f"unexpected content block: {first!r}")
    return json.loads(text)


def _error_text(result) -> str:
    return "\n".join(b.text for b in result.content if getattr(b, "text", None))


class _TenantSwitch:
    def __init__(self, value: str):
        self.value = value


def _install_accessor(state, db_manager, *, test_session=None):
    from giljo_mcp.tools.tool_accessor import ToolAccessor

    if state.tenant_manager is None:
        state.tenant_manager = TenantManager()
    state.db_manager = db_manager
    accessor = ToolAccessor(
        db_manager=db_manager,
        tenant_manager=state.tenant_manager,
        test_session=test_session,
    )
    state.tool_accessor = accessor
    return accessor




@pytest_asyncio.fixture
async def project_context_client(db_manager, monkeypatch):
    from api import app_state
    from api.endpoints import mcp_sdk_server
    from api.endpoints.mcp_tools import _base

    state = app_state.state
    prior_tool_accessor = state.tool_accessor
    prior_tenant_manager = state.tenant_manager
    prior_db_manager = state.db_manager

    tenant_key = TenantManager.generate_tenant_key()
    async with db_manager.get_session_async(tenant_key=tenant_key) as session:
        product = Product(
            id=str(uuid.uuid4()),
            tenant_key=tenant_key,
            name=f"BE-9613 product {uuid.uuid4().hex[:6]}",
            description="seeded",
            is_active=True,
        )
        session.add(product)
        await session.flush()
        staged = Project(
            id=str(uuid.uuid4()),
            name=f"BE-9613 staged {uuid.uuid4().hex[:6]}",
            description="seeded",
            mission="Wait for the go.",
            status="inactive",
            tenant_key=tenant_key,
            product_id=product.id,
            series_number=1,
            execution_mode="claude_code_cli",
            staging_status="staging_complete",
            created_at=datetime.now(UTC),
        )
        done = Project(
            id=str(uuid.uuid4()),
            name=f"BE-9613 done {uuid.uuid4().hex[:6]}",
            description="seeded",
            mission="Be finished.",
            status="completed",
            tenant_key=tenant_key,
            product_id=product.id,
            series_number=2,
            execution_mode="claude_code_cli",
            completed_at=datetime.now(UTC),
            created_at=datetime.now(UTC),
        )
        session.add_all([staged, done])
        await session.commit()
        ids = {"staged": staged.id, "done": done.id, "product": product.id}

    _install_accessor(state, db_manager)
    monkeypatch.setattr(_base, "_resolve_tenant", lambda ctx: tenant_key)
    monkeypatch.setattr(_base, "_resolve_user_id", lambda ctx: None)

    def _new_client():
        return create_connected_server_and_client_session(mcp_sdk_server.mcp)

    try:
        yield _new_client, tenant_key, ids
    finally:
        await purge_tenant_rows(db_manager, tenant_key)
        state.tool_accessor = prior_tool_accessor
        state.tenant_manager = prior_tenant_manager
        state.db_manager = prior_db_manager


async def test_get_context_project_carries_the_hint_over_the_wire(project_context_client):
    new_client, _tenant_key, ids = project_context_client

    async with new_client() as session:
        result = await session.call_tool(
            "get_context",
            {"product_id": ids["product"], "project_id": ids["staged"], "categories": ["project"]},
        )

    assert result.is_error is False, _error_text(result)
    payload = _payload(result)
    data = payload["data"]["project"]
    assert data["next_action"] == {
        "tool": "launch_implementation",
        "args_hint": None,
        "why": na.PROJECT_AWAITING_GO_HINT,
    }


async def test_get_context_omits_the_hint_for_a_completed_project(project_context_client):
    new_client, _tenant_key, ids = project_context_client

    async with new_client() as session:
        result = await session.call_tool(
            "get_context",
            {"product_id": ids["product"], "project_id": ids["done"], "categories": ["project"]},
        )

    assert result.is_error is False, _error_text(result)
    data = _payload(result)["data"]["project"]
    assert "next_action" not in data




@pytest_asyncio.fixture
async def task_list_client(db_manager, db_session, monkeypatch):
    from api import app_state
    from api.endpoints import mcp_sdk_server
    from api.endpoints.mcp_tools import _base
    from giljo_mcp.services.task_service import TaskService

    state = app_state.state
    prior_tool_accessor = state.tool_accessor
    prior_tenant_manager = state.tenant_manager
    prior_db_manager = state.db_manager

    tenant_key = TenantManager.generate_tenant_key()
    product = Product(
        id=str(uuid.uuid4()),
        tenant_key=tenant_key,
        name=f"BE-9613 task product {uuid.uuid4().hex[:6]}",
        description="seeded",
        is_active=True,
    )
    db_session.add(product)
    db_session.add(
        TaxonomyType(id=str(uuid.uuid4()), tenant_key=tenant_key, abbreviation="BE", label="Backend", sort_order=0)
    )
    await db_session.commit()

    accessor = _install_accessor(state, db_manager, test_session=db_session)
    accessor._task_service = TaskService(
        db_manager=db_manager,
        tenant_manager=state.tenant_manager,
        session=db_session,
    )

    monkeypatch.setattr(_base, "_resolve_tenant", lambda ctx: tenant_key)
    monkeypatch.setattr(_base, "_resolve_user_id", lambda ctx: None)

    def _new_client():
        return create_connected_server_and_client_session(mcp_sdk_server.mcp)

    try:
        yield _new_client, tenant_key
    finally:
        state.tool_accessor = prior_tool_accessor
        state.tenant_manager = prior_tenant_manager
        state.db_manager = prior_db_manager


async def test_list_tasks_carries_one_response_level_hint_over_the_wire(task_list_client):
    new_client, _tenant_key = task_list_client

    async with new_client() as session:
        created = await session.call_tool("create_task", {"title": "BE-9613 wire probe", "description": ""})
        assert created.is_error is False, _error_text(created)
        result = await session.call_tool("list_tasks", {"mode": "summary"})

    assert result.is_error is False, _error_text(result)
    payload = _payload(result)
    assert payload["next_action"] == {
        "tool": "update_task",
        "args_hint": None,
        "why": na.TASK_OPEN_HINT,
    }
    assert all("next_action" not in row for row in payload["tasks"])


async def test_list_tasks_index_mode_stays_lean_over_the_wire(task_list_client):
    new_client, _tenant_key = task_list_client

    async with new_client() as session:
        created = await session.call_tool("create_task", {"title": "BE-9613 lean wire probe", "description": ""})
        assert created.is_error is False, _error_text(created)
        result = await session.call_tool("list_tasks", {"mode": "index"})

    assert result.is_error is False, _error_text(result)
    assert "next_action" not in _payload(result)
