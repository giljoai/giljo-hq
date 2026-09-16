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

from api.endpoints.mcp_tools._base import MCP_NAME_MAX
from giljo_mcp.models.products import Product
from giljo_mcp.models.projects import Project
from giljo_mcp.models.tasks import Task
from giljo_mcp.tenant import TenantManager
from tests.helpers.mcp_session_fixture import create_connected_server_and_client_session


pytestmark = pytest.mark.asyncio


def _payload(result) -> dict:
    block = result.content[0]
    text = getattr(block, "text", None)
    if text is None:
        raise AssertionError(f"unexpected content block: {block!r}")
    return json.loads(text)


def _text(result) -> str:
    return "\n".join(getattr(b, "text", "") or "" for b in result.content)


def _assert_validation_rejection(result, *, field: str, constraint: str | None = None) -> dict:
    assert result.is_error is False, f"expected a structured rejection, got isError: {_text(result)!r}"
    payload = _payload(result)
    assert payload.get("success") is False, payload
    assert payload.get("error") == "VALIDATION_ERROR", payload
    assert payload.get("field") == field, payload
    if constraint is not None:
        assert payload.get("constraint") == constraint, payload
    message = payload.get("message", "")
    assert message and isinstance(message, str), payload
    for marker in ("input_value=", "For further information", "validation error for", "[type="):
        assert marker not in message, payload
    return payload


@pytest_asyncio.fixture
async def be9602_client(db_manager, db_session, monkeypatch):
    from api import app_state
    from api.endpoints import mcp_sdk_server
    from api.endpoints.mcp_tools import _base
    from giljo_mcp.services.project_service import ProjectService
    from giljo_mcp.services.task_service import TaskService
    from giljo_mcp.tools.tool_accessor import ToolAccessor

    state = app_state.state
    prior = (state.tool_accessor, state.tenant_manager, state.db_manager)
    if state.tenant_manager is None:
        state.tenant_manager = TenantManager()
    state.db_manager = db_manager

    tenant_key = TenantManager.generate_tenant_key()
    accessor = ToolAccessor(db_manager=db_manager, tenant_manager=state.tenant_manager)
    accessor._task_service = TaskService(db_manager=db_manager, tenant_manager=state.tenant_manager, session=db_session)
    accessor._project_service = ProjectService(
        db_manager=db_manager, tenant_manager=state.tenant_manager, test_session=db_session
    )
    state.tool_accessor = accessor

    monkeypatch.setattr(_base, "_resolve_tenant", lambda ctx: tenant_key)
    monkeypatch.setattr(_base, "_resolve_user_id", lambda ctx: None)

    def _client():
        return create_connected_server_and_client_session(mcp_sdk_server.mcp)

    try:
        yield _client, tenant_key
    finally:
        state.tool_accessor, state.tenant_manager, state.db_manager = prior


async def _seed_product(db_session, tenant_key: str) -> Product:
    product = Product(
        id=str(uuid4()),
        name=f"BE9602 Product {uuid4().hex[:6]}",
        description="reviewer rehearsal boundary test",
        tenant_key=tenant_key,
        is_active=True,
        product_memory={},
    )
    db_session.add(product)
    await db_session.commit()
    return product


async def _seed_project(db_session, tenant_key: str, product_id: str) -> Project:
    project = Project(
        id=str(uuid4()),
        tenant_key=tenant_key,
        product_id=product_id,
        name="Keep this name",
        description="reviewer rehearsal boundary test",
        mission="m",
        status="inactive",
        series_number=random.randint(1, 9000),
    )
    db_session.add(project)
    await db_session.commit()
    return project


async def _seed_task(db_session, tenant_key: str, product_id: str) -> Task:
    task = Task(
        id=str(uuid4()),
        tenant_key=tenant_key,
        product_id=product_id,
        title="Keep this title",
        description="reviewer rehearsal boundary test",
        status="pending",
        priority="medium",
    )
    db_session.add(task)
    await db_session.commit()
    return task




@pytest.mark.parametrize("title", ["", "   ", "\t\n"])
async def test_create_task_blank_title_is_structured_rejection(be9602_client, db_session, title):
    client, tenant_key = be9602_client
    await _seed_product(db_session, tenant_key)

    async with client() as session:
        result = await session.call_tool("create_task", {"title": title, "description": "a real body"})

    _assert_validation_rejection(result, field="title", constraint="non_empty")


async def test_update_task_whitespace_title_is_rejected_and_row_untouched(be9602_client, db_session):
    client, tenant_key = be9602_client
    product = await _seed_product(db_session, tenant_key)
    task = await _seed_task(db_session, tenant_key, product.id)

    async with client() as session:
        result = await session.call_tool("update_task", {"task_id": task.id, "title": "   "})

    _assert_validation_rejection(result, field="title", constraint="non_empty")
    await db_session.refresh(task)
    assert task.title == "Keep this title"


async def test_create_project_whitespace_name_is_structured_rejection(be9602_client, db_session):
    client, tenant_key = be9602_client
    product = await _seed_product(db_session, tenant_key)

    async with client() as session:
        result = await session.call_tool(
            "create_project", {"name": "   ", "description": "body", "product_id": product.id}
        )

    _assert_validation_rejection(result, field="name", constraint="non_empty")


async def test_update_project_whitespace_name_is_rejected_and_row_untouched(be9602_client, db_session):
    client, tenant_key = be9602_client
    product = await _seed_product(db_session, tenant_key)
    project = await _seed_project(db_session, tenant_key, product.id)

    async with client() as session:
        result = await session.call_tool("update_project", {"project_id": project.id, "name": " \t "})

    _assert_validation_rejection(result, field="name", constraint="non_empty")
    await db_session.refresh(project)
    assert project.name == "Keep this name"




async def test_over_long_title_is_structured_not_pydantic_dump(be9602_client):
    client, _tenant_key = be9602_client
    async with client() as session:
        result = await session.call_tool("create_task", {"title": "x" * (MCP_NAME_MAX + 1), "description": "body"})

    payload = _assert_validation_rejection(result, field="title", constraint="string_too_long")
    assert str(MCP_NAME_MAX) in payload["message"]


async def test_wrong_type_is_structured_not_pydantic_dump(be9602_client):
    client, _tenant_key = be9602_client
    async with client() as session:
        result = await session.call_tool("create_task", {"title": "ok", "description": "body", "priority": 5})

    _assert_validation_rejection(result, field="priority")


async def test_missing_required_argument_is_structured(be9602_client):
    client, _tenant_key = be9602_client
    async with client() as session:
        result = await session.call_tool("create_task", {"title": "ok"})

    _assert_validation_rejection(result, field="description", constraint="missing")


async def test_valid_call_is_unaffected_by_the_pre_validation(be9602_client, db_session):
    client, tenant_key = be9602_client
    await _seed_product(db_session, tenant_key)

    async with client() as session:
        result = await session.call_tool("create_task", {"title": "real title", "description": "real body"})

    assert result.is_error is False, _text(result)
    assert _payload(result).get("task_id")




async def test_update_task_empty_title_is_rejected_like_create(be9602_client, db_session):
    client, tenant_key = be9602_client
    product = await _seed_product(db_session, tenant_key)
    task = await _seed_task(db_session, tenant_key, product.id)

    async with client() as session:
        result = await session.call_tool("update_task", {"task_id": task.id, "title": ""})

    _assert_validation_rejection(result, field="title", constraint="non_empty")
    assert "No fields supplied" not in _text(result)
    await db_session.refresh(task)
    assert task.title == "Keep this title"


async def test_update_project_empty_name_is_rejected_like_create(be9602_client, db_session):
    client, tenant_key = be9602_client
    product = await _seed_product(db_session, tenant_key)
    project = await _seed_project(db_session, tenant_key, product.id)

    async with client() as session:
        result = await session.call_tool("update_project", {"project_id": project.id, "name": ""})

    _assert_validation_rejection(result, field="name", constraint="non_empty")
    assert "No fields supplied" not in _text(result)
    await db_session.refresh(project)
    assert project.name == "Keep this name"


async def test_update_task_omitting_title_still_updates_other_fields(be9602_client, db_session):
    client, tenant_key = be9602_client
    product = await _seed_product(db_session, tenant_key)
    task = await _seed_task(db_session, tenant_key, product.id)

    async with client() as session:
        result = await session.call_tool("update_task", {"task_id": task.id, "priority": "high"})

    assert result.is_error is False, _text(result)
    await db_session.refresh(task)
    assert task.priority == "high"
    assert task.title == "Keep this title"


async def test_update_project_omitting_name_still_updates_other_fields(be9602_client, db_session):
    client, tenant_key = be9602_client
    product = await _seed_product(db_session, tenant_key)
    project = await _seed_project(db_session, tenant_key, product.id)

    async with client() as session:
        result = await session.call_tool("update_project", {"project_id": project.id, "description": "a new body"})

    assert result.is_error is False, _text(result)
    await db_session.refresh(project)
    assert project.description == "a new body"
    assert project.name == "Keep this name"
