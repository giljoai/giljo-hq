# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import json
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import select

from giljo_mcp.models.auth import User
from giljo_mcp.models.organizations import Organization
from giljo_mcp.models.products import Product
from giljo_mcp.models.projects import Project
from giljo_mcp.models.tasks import Task
from giljo_mcp.tenant import TenantManager
from tests.helpers.mcp_session_fixture import create_connected_server_and_client_session


pytestmark = pytest.mark.asyncio


def _payload(call_tool_result) -> dict:
    if getattr(call_tool_result, "structuredContent", None):
        return call_tool_result.structured_content
    first_block = call_tool_result.content[0]
    text = getattr(first_block, "text", None)
    if text is None:
        raise AssertionError(f"unexpected content block: {first_block!r}")
    return json.loads(text)


def _error_text(call_tool_result) -> str:
    parts = []
    for block in call_tool_result.content or []:
        text = getattr(block, "text", None)
        if text:
            parts.append(text)
    return "\n".join(parts)


class _Seeded:
    def __init__(
        self, *, user_id: str, owner_product_id: str, owner_product_name: str, active_product_id: str, task_id: str
    ):
        self.user_id = user_id
        self.owner_product_id = owner_product_id
        self.owner_product_name = owner_product_name
        self.active_product_id = active_product_id
        self.task_id = task_id


async def _seed_task_on_a_non_active_product(db_session, tenant_key: str) -> _Seeded:
    suffix = uuid4().hex[:8]

    org = Organization(name=f"Org {suffix}", slug=f"org-{suffix}", tenant_key=tenant_key, is_active=True)
    db_session.add(org)
    await db_session.flush()

    user = User(
        id=str(uuid4()),
        username=f"be9415_{suffix}",
        email=f"be9415_{suffix}@example.com",
        tenant_key=tenant_key,
        role="developer",
        password_hash="hashed_password",
        org_id=org.id,
    )
    owner = Product(
        id=str(uuid4()),
        name=f"BE9415 Owner {suffix}",
        description="the product the task actually belongs to",
        tenant_key=tenant_key,
        is_active=False,
    )
    active = Product(
        id=str(uuid4()),
        name=f"BE9415 Active {suffix}",
        description="the ambient active product the conversion must ignore",
        tenant_key=tenant_key,
        is_active=True,
    )
    db_session.add_all([user, owner, active])
    await db_session.flush()

    task = Task(
        id=str(uuid4()),
        tenant_key=tenant_key,
        org_id=org.id,
        product_id=owner.id,
        created_by_user_id=user.id,
        title="Promote me to the right product",
        description="filed under OWNER, converted while ACTIVE is selected",
        status="pending",
        priority="high",
        series_number=31,
    )
    db_session.add(task)
    await db_session.commit()

    return _Seeded(
        user_id=user.id,
        owner_product_id=owner.id,
        owner_product_name=owner.name,
        active_product_id=active.id,
        task_id=task.id,
    )


class _Resolved:
    def __init__(self, tenant_key: str):
        self.tenant_key = tenant_key
        self.user_id: str | None = None


@pytest_asyncio.fixture
async def convert_client(db_manager, db_session, monkeypatch):
    from api import app_state
    from api.endpoints import mcp_sdk_server
    from api.endpoints.mcp_tools import _base
    from giljo_mcp.services.task_service import TaskService
    from giljo_mcp.tools.tool_accessor import ToolAccessor

    state = app_state.state
    prior_tool_accessor = state.tool_accessor
    prior_tenant_manager = state.tenant_manager
    prior_db_manager = state.db_manager

    if state.tenant_manager is None:
        state.tenant_manager = TenantManager()
    state.db_manager = db_manager

    tenant_key = TenantManager.generate_tenant_key()
    accessor = ToolAccessor(db_manager=db_manager, tenant_manager=state.tenant_manager)
    accessor._task_service = TaskService(
        db_manager=db_manager,
        tenant_manager=state.tenant_manager,
        session=db_session,
    )
    state.tool_accessor = accessor

    resolved = _Resolved(tenant_key)
    monkeypatch.setattr(_base, "_resolve_tenant", lambda ctx: resolved.tenant_key)
    monkeypatch.setattr(_base, "_resolve_user_id", lambda ctx: resolved.user_id)

    def _new_client():
        return create_connected_server_and_client_session(mcp_sdk_server.mcp)

    try:
        yield _new_client, resolved, tenant_key
    finally:
        state.tool_accessor = prior_tool_accessor
        state.tenant_manager = prior_tenant_manager
        state.db_manager = prior_db_manager


class TestConvertEchoesBoundProduct:
    async def test_promotion_binds_to_the_tasks_product_over_the_transport(self, convert_client, db_session):
        new_client, resolved, tenant_key = convert_client
        seeded = await _seed_task_on_a_non_active_product(db_session, tenant_key)
        resolved.user_id = seeded.user_id

        async with new_client() as session:
            result = await session.call_tool(
                "update_task",
                {"task_id": seeded.task_id, "convert_to_project": True},
            )

        assert result.is_error is False, _error_text(result)
        payload = _payload(result)

        product_id = (
            await db_session.execute(select(Project.product_id).where(Project.id == payload["project_id"]))
        ).scalar_one()
        assert product_id == seeded.owner_product_id
        assert product_id != seeded.active_product_id

    async def test_response_echoes_the_bound_product_through_the_wrapper(self, convert_client, db_session):
        new_client, resolved, tenant_key = convert_client
        seeded = await _seed_task_on_a_non_active_product(db_session, tenant_key)
        resolved.user_id = seeded.user_id

        async with new_client() as session:
            result = await session.call_tool(
                "update_task",
                {"task_id": seeded.task_id, "convert_to_project": True},
            )

        assert result.is_error is False, _error_text(result)
        payload = _payload(result)

        assert payload["product_id"] == seeded.owner_product_id
        assert payload["product_name"] == seeded.owner_product_name
        assert payload["product_id"] != seeded.active_product_id

    async def test_an_absorbed_product_id_cannot_redirect_the_filing(self, convert_client, db_session):
        new_client, resolved, tenant_key = convert_client
        seeded = await _seed_task_on_a_non_active_product(db_session, tenant_key)
        resolved.user_id = seeded.user_id

        async with new_client() as session:
            tools = {tool.name: tool for tool in (await session.list_tools()).tools}
            assert "product_id" not in tools["update_task"].input_schema.get("properties", {})

            result = await session.call_tool(
                "update_task",
                {
                    "task_id": seeded.task_id,
                    "convert_to_project": True,
                    "product_id": seeded.active_product_id,
                },
            )

        assert result.is_error is False, _error_text(result)
        payload = _payload(result)
        assert payload["product_id"] == seeded.owner_product_id, (
            "an absorbed product_id must not be able to redirect the promotion"
        )

        product_id = (
            await db_session.execute(select(Project.product_id).where(Project.id == payload["project_id"]))
        ).scalar_one()
        assert product_id == seeded.owner_product_id
