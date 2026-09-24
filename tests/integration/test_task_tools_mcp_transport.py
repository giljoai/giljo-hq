# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import json
import random
from datetime import datetime
from uuid import uuid4

import pytest
import pytest_asyncio

from giljo_mcp.models.organizations import Organization
from giljo_mcp.models.products import Product
from giljo_mcp.models.projects import TaxonomyType
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
    for block in call_tool_result.content:
        text = getattr(block, "text", None)
        if text:
            parts.append(text)
    return "\n".join(parts)


async def _seed_product(db_session, tenant_key: str, *, is_active: bool = True) -> Product:
    suffix = uuid4().hex[:8]
    org = Organization(
        name=f"Org {suffix}",
        slug=f"org-{suffix}",
        tenant_key=tenant_key,
        is_active=True,
    )
    db_session.add(org)
    await db_session.flush()

    product = Product(
        id=str(uuid4()),
        name=f"Transport Test Product {suffix}",
        description="product for transport-layer task tool tests",
        tenant_key=tenant_key,
        is_active=is_active,
    )
    db_session.add(product)
    await db_session.commit()
    await db_session.refresh(product)
    return product


async def _seed_taxonomy(db_session, tenant_key: str) -> None:
    for i, (abbr, label) in enumerate([("BE", "Backend"), ("FE", "Frontend"), ("INF", "Infra")]):
        db_session.add(
            TaxonomyType(
                id=str(uuid4()),
                tenant_key=tenant_key,
                abbreviation=abbr,
                label=label,
                sort_order=i,
            )
        )
    await db_session.commit()




@pytest_asyncio.fixture
async def primary_tenant_key() -> str:
    return TenantManager.generate_tenant_key()


@pytest_asyncio.fixture
async def secondary_tenant_key() -> str:
    return TenantManager.generate_tenant_key()


class _TenantSwitch:

    def __init__(self, value: str):
        self.value = value


@pytest_asyncio.fixture
async def task_mcp_client(db_manager, db_session, primary_tenant_key, monkeypatch):
    from api import app_state
    from api.endpoints import mcp_sdk_server
    from giljo_mcp.services.task_service import TaskService
    from giljo_mcp.tools.tool_accessor import ToolAccessor

    state = app_state.state

    prior_tool_accessor = state.tool_accessor
    prior_tenant_manager = state.tenant_manager
    prior_db_manager = state.db_manager

    if state.tenant_manager is None:
        state.tenant_manager = TenantManager()
    state.db_manager = db_manager

    accessor = ToolAccessor(db_manager=db_manager, tenant_manager=state.tenant_manager)
    accessor._task_service = TaskService(
        db_manager=db_manager,
        tenant_manager=state.tenant_manager,
        session=db_session,
    )
    state.tool_accessor = accessor

    tenant_switch = _TenantSwitch(primary_tenant_key)

    from api.endpoints.mcp_tools import _base

    monkeypatch.setattr(
        _base,
        "_resolve_tenant",
        lambda ctx: tenant_switch.value,
    )
    monkeypatch.setattr(
        _base,
        "_resolve_user_id",
        lambda ctx: None,
    )

    def _new_client():
        return create_connected_server_and_client_session(mcp_sdk_server.mcp)

    try:
        yield _new_client, tenant_switch
    finally:
        state.tool_accessor = prior_tool_accessor
        state.tenant_manager = prior_tenant_manager
        state.db_manager = prior_db_manager




async def test_create_task_happy_path_returns_task_id(task_mcp_client, db_session, primary_tenant_key):
    new_client, _switch = task_mcp_client
    await _seed_product(db_session, primary_tenant_key)
    await _seed_taxonomy(db_session, primary_tenant_key)

    async with new_client() as session:
        result = await session.call_tool(
            "create_task",
            {
                "title": "wire transport tests",
                "description": "exercise wrapper at line 584",
                "priority": "high",
            },
        )

    assert result.is_error is False, _error_text(result)
    payload = _payload(result)
    assert payload["task_id"]
    assert payload.get("task_type") == "TSK"


async def test_create_task_refuses_an_unknown_task_type(task_mcp_client, db_session, primary_tenant_key):
    new_client, _switch = task_mcp_client
    await _seed_product(db_session, primary_tenant_key)
    await _seed_taxonomy(db_session, primary_tenant_key)

    async with new_client() as session:
        result = await session.call_tool(
            "create_task",
            {
                "title": "bogus type is refused",
                "description": "an unknown task_type is refused, not absorbed",
                "task_type": "MADEUP",
            },
        )

    payload = _payload(result)
    assert payload["success"] is False, f"an unknown task_type was absorbed: {payload}"
    assert payload["error"] == "VALIDATION_ERROR"
    assert payload["field"] == "task_type"
    assert "MADEUP" in payload["message"]
    assert "TSK" in payload["message"] and "HND" in payload["message"]
    assert "task_id" not in payload, "a refused create must not have written a row"




async def _create_seed_task(new_client, db_session, tenant_key) -> str:
    await _seed_product(db_session, tenant_key)
    await _seed_taxonomy(db_session, tenant_key)
    async with new_client() as session:
        result = await session.call_tool(
            "create_task",
            {
                "title": "seed",
                "description": "seed for update/complete",
            },
        )
    assert result.is_error is False, _error_text(result)
    return _payload(result)["task_id"]


async def test_update_task_sets_status_via_wrapper(task_mcp_client, db_session, primary_tenant_key):
    new_client, _switch = task_mcp_client
    task_id = await _create_seed_task(new_client, db_session, primary_tenant_key)

    async with new_client() as session:
        result = await session.call_tool(
            "update_task",
            {"task_id": task_id, "status": "in_progress"},
        )

    assert result.is_error is False, _error_text(result)
    payload = _payload(result)
    assert payload["task_id"] == task_id
    assert "status" in payload["updated_fields"]


async def test_update_task_ignores_task_type_immutable(task_mcp_client, db_session, primary_tenant_key):
    new_client, _switch = task_mcp_client
    task_id = await _create_seed_task(new_client, db_session, primary_tenant_key)

    async with new_client() as session:
        result = await session.call_tool(
            "update_task",
            {"task_id": task_id, "task_type": "BOGUS", "title": "renamed"},
        )

    assert result.is_error is False, _error_text(result)
    payload = _payload(result)
    assert "task_type_id" not in payload.get("updated_fields", [])


async def test_update_task_rejects_invalid_status(task_mcp_client, db_session, primary_tenant_key):
    new_client, _switch = task_mcp_client
    task_id = await _create_seed_task(new_client, db_session, primary_tenant_key)

    async with new_client() as session:
        result = await session.call_tool(
            "update_task",
            {"task_id": task_id, "status": "not_a_real_status"},
        )

    assert result.is_error is False, _error_text(result)
    payload = _payload(result)
    assert payload["success"] is False
    assert payload["error"] == "VALIDATION_ERROR"
    assert payload["field"] == "status"




async def test_update_task_completed_with_notes_appends_and_stamps(task_mcp_client, db_session, primary_tenant_key):
    new_client, _switch = task_mcp_client
    task_id = await _create_seed_task(new_client, db_session, primary_tenant_key)

    async with new_client() as session:
        result = await session.call_tool(
            "update_task",
            {"task_id": task_id, "status": "completed", "completion_notes": "all green via transport"},
        )

    assert result.is_error is False, _error_text(result)
    payload = _payload(result)
    assert payload["task_id"] == task_id
    assert "status" in payload["updated_fields"]
    assert "completed_at" in payload["updated_fields"]
    assert payload["completion_notes"] == "all green via transport"

    async with new_client() as session:
        full = await session.call_tool("list_tasks", {"mode": "full"})
    row = next(r for r in _payload(full)["tasks"] if r["task_id"] == task_id)
    assert row["status"] == "completed"
    assert row["completed_at"]
    parsed = datetime.fromisoformat(row["completed_at"])
    assert parsed.tzinfo is not None or parsed <= datetime.now()  # noqa: DTZ005 — stored as naive in DB
    assert "all green via transport" in row["description"]


async def test_update_task_completion_notes_without_completed_is_noop(task_mcp_client, db_session, primary_tenant_key):
    new_client, _switch = task_mcp_client
    task_id = await _create_seed_task(new_client, db_session, primary_tenant_key)

    async with new_client() as session:
        result = await session.call_tool(
            "update_task",
            {"task_id": task_id, "status": "in_progress", "completion_notes": "should not be appended"},
        )

    assert result.is_error is False, _error_text(result)
    payload = _payload(result)
    assert "completion_notes" not in payload

    async with new_client() as session:
        full = await session.call_tool("list_tasks", {"mode": "full"})
    row = next(r for r in _payload(full)["tasks"] if r["task_id"] == task_id)
    assert "should not be appended" not in row["description"]




async def test_list_tasks_summary_mode_field_shape(task_mcp_client, db_session, primary_tenant_key):
    new_client, _switch = task_mcp_client
    await _create_seed_task(new_client, db_session, primary_tenant_key)

    async with new_client() as session:
        result = await session.call_tool("list_tasks", {"mode": "summary"})

    assert result.is_error is False, _error_text(result)
    payload = _payload(result)
    assert "tasks" in payload
    assert len(payload["tasks"]) >= 1
    row = payload["tasks"][0]
    expected = {"task_id", "title", "status", "priority", "task_type", "created_at"}
    assert expected.issubset(set(row.keys()) | {"id"})


async def test_list_tasks_full_mode_respects_memory_limit(task_mcp_client, db_session, primary_tenant_key):
    new_client, _switch = task_mcp_client
    await _create_seed_task(new_client, db_session, primary_tenant_key)

    async with new_client() as session:
        result = await session.call_tool(
            "list_tasks",
            {"mode": "full", "memory_limit": 5},
        )

    assert result.is_error is False, _error_text(result)
    payload = _payload(result)
    rows = payload.get("tasks", [])
    assert rows
    descriptions = [row.get("description", "") for row in rows if "description" in row]
    assert descriptions, "full mode should include description field"
    assert all(len(d) <= 5 + len("...") for d in descriptions), (
        f"memory_limit=5 not honored; descriptions={descriptions!r}"
    )
    assert any(d.endswith("...") for d in descriptions), (
        f"expected at least one truncated description ending with '...'; got {descriptions!r}"
    )


async def test_list_tasks_is_tenant_scoped_across_two_tenants(
    task_mcp_client,
    db_session,
    primary_tenant_key,
    secondary_tenant_key,
):
    new_client, switch = task_mcp_client

    switch.value = primary_tenant_key
    a_task_id = await _create_seed_task(new_client, db_session, primary_tenant_key)

    await _seed_product(db_session, secondary_tenant_key)
    await _seed_taxonomy(db_session, secondary_tenant_key)
    switch.value = secondary_tenant_key
    async with new_client() as session:
        b_result = await session.call_tool(
            "create_task",
            {"title": "tenant_b task", "description": "x"},
        )
    assert b_result.is_error is False, _error_text(b_result)
    b_task_id = _payload(b_result)["task_id"]
    assert b_task_id != a_task_id

    switch.value = primary_tenant_key
    async with new_client() as session:
        list_result = await session.call_tool("list_tasks", {"mode": "summary"})

    assert list_result.is_error is False, _error_text(list_result)
    ids = {row["task_id"] for row in _payload(list_result)["tasks"]}
    assert a_task_id in ids
    assert b_task_id not in ids, (
        "TENANT LEAK: tenant A's list_tasks returned tenant B's task — wrapper is not propagating tenant_key correctly."
    )




async def test_list_tasks_summary_includes_taxonomy_and_hidden_fields(task_mcp_client, db_session, primary_tenant_key):
    new_client, _switch = task_mcp_client
    await _create_seed_task(new_client, db_session, primary_tenant_key)

    async with new_client() as session:
        result = await session.call_tool("list_tasks", {"mode": "summary"})

    assert result.is_error is False, _error_text(result)
    payload = _payload(result)
    row = payload["tasks"][0]
    for key in ("taxonomy_alias", "series_number", "subseries", "task_type", "hidden"):
        assert key in row, f"FE-5046: summary row missing '{key}'"
    assert isinstance(row["task_type"], dict)
    assert row["task_type"]["abbreviation"] == "TSK"
    assert row["hidden"] is False


async def test_list_tasks_full_includes_taxonomy_and_hidden_fields(task_mcp_client, db_session, primary_tenant_key):
    new_client, _switch = task_mcp_client
    await _create_seed_task(new_client, db_session, primary_tenant_key)

    async with new_client() as session:
        result = await session.call_tool("list_tasks", {"mode": "full"})

    assert result.is_error is False, _error_text(result)
    payload = _payload(result)
    row = payload["tasks"][0]
    for key in ("taxonomy_alias", "series_number", "subseries", "task_type", "hidden"):
        assert key in row, f"FE-5046: full row missing '{key}'"


async def test_update_task_hidden_via_wrapper(task_mcp_client, db_session, primary_tenant_key):
    new_client, _switch = task_mcp_client
    task_id = await _create_seed_task(new_client, db_session, primary_tenant_key)

    async with new_client() as session:
        result = await session.call_tool(
            "update_task",
            {"task_id": task_id, "hidden": "true"},
        )
    assert result.is_error is False, _error_text(result)
    payload = _payload(result)
    assert "hidden" in payload["updated_fields"]

    async with new_client() as session:
        list_result = await session.call_tool("list_tasks", {"mode": "summary"})
    rows = _payload(list_result)["tasks"]
    row = next(r for r in rows if r["task_id"] == task_id)
    assert row["hidden"] is True


async def test_list_tasks_hidden_filter_via_wrapper(task_mcp_client, db_session, primary_tenant_key):
    new_client, _switch = task_mcp_client
    visible_id = await _create_seed_task(new_client, db_session, primary_tenant_key)

    async with new_client() as session:
        h_create = await session.call_tool(
            "create_task",
            {"title": "hidden task", "description": "x"},
        )
    assert h_create.is_error is False, _error_text(h_create)
    hidden_id = _payload(h_create)["task_id"]

    async with new_client() as session:
        await session.call_tool("update_task", {"task_id": hidden_id, "hidden": "true"})

    async with new_client() as session:
        both = await session.call_tool("list_tasks", {"mode": "summary"})
    ids_both = {r["task_id"] for r in _payload(both)["tasks"]}
    assert visible_id in ids_both
    assert hidden_id in ids_both

    async with new_client() as session:
        only_hidden = await session.call_tool("list_tasks", {"mode": "summary", "hidden": "true"})
    ids_h = {r["task_id"] for r in _payload(only_hidden)["tasks"]}
    assert hidden_id in ids_h
    assert visible_id not in ids_h

    async with new_client() as session:
        only_visible = await session.call_tool("list_tasks", {"mode": "summary", "hidden": "false"})
    ids_v = {r["task_id"] for r in _payload(only_visible)["tasks"]}
    assert visible_id in ids_v
    assert hidden_id not in ids_v


_ = random
