# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import json
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import delete, select

from giljo_mcp.models.products import Product
from giljo_mcp.models.tasks import Task
from giljo_mcp.tenant import TenantManager
from tests.helpers.mcp_session_fixture import create_connected_server_and_client_session


pytestmark = pytest.mark.asyncio


GOOD_HANDOVER = """Session ended at the rebase.

## Verify before trusting
- the branch is green -- check with: pytest tests/unit -q

## Waiting on the operator
- nothing

## Cannot testify
- the two-process concurrency behaviour; never observed it
"""


def _payload(result) -> dict:
    if getattr(result, "structuredContent", None):
        return result.structured_content
    block = result.content[0]
    text = getattr(block, "text", None)
    if text is None:
        raise AssertionError(f"unexpected content block: {block!r}")
    return json.loads(text)


def _text(result) -> str:
    return "\n".join(t for b in (result.content or []) if (t := getattr(b, "text", None)))


async def _seed_product(db_manager, tenant_key: str) -> str:
    product_id = str(uuid4())
    async with db_manager.get_session_async(tenant_key=tenant_key) as session:
        session.add(
            Product(
                id=product_id,
                name=f"TSK9640 product {uuid4().hex[:6]}",
                description="TSK-9640 boundary test product",
                tenant_key=tenant_key,
                is_active=True,
                product_memory={},
            )
        )
        await session.commit()
    return product_id


async def _cleanup(db_manager, tenant_key: str) -> None:
    async with db_manager.get_session_async(tenant_key=tenant_key) as session:
        await session.execute(delete(Task).where(Task.tenant_key == tenant_key))
        await session.execute(delete(Product).where(Product.tenant_key == tenant_key))
        await session.commit()


@pytest_asyncio.fixture
async def task_boundary(db_manager, monkeypatch):
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
    state.tool_accessor = ToolAccessor(db_manager=db_manager, tenant_manager=state.tenant_manager)
    monkeypatch.setattr(_base, "_resolve_tenant", lambda ctx: tenant_key)
    monkeypatch.setattr(_base, "_resolve_user_id", lambda ctx: None)

    product_id = await _seed_product(db_manager, tenant_key)

    def _client():
        return create_connected_server_and_client_session(mcp_sdk_server.mcp)

    try:
        yield _client, tenant_key, product_id
    finally:
        await _cleanup(db_manager, tenant_key)
        state.tool_accessor, state.tenant_manager, state.db_manager = prior


async def _create(session, product_id: str, **overrides) -> dict:
    args = {"title": "an ordinary task", "description": "Do the thing.", "product_id": product_id}
    args.update(overrides)
    return _payload(await session.call_tool("create_task", args))




async def test_changing_tsk_to_hnd_is_refused_at_the_boundary(task_boundary):
    client, _tenant_key, product_id = task_boundary
    async with client() as s:
        created = await _create(s, product_id)
        result = await s.call_tool("update_task", {"task_id": created["task_id"], "task_type": "HND"})

    assert result.is_error is False, _text(result)
    payload = _payload(result)
    assert payload["success"] is False, f"a task_type change was accepted: {payload}"
    assert payload["error"] == "VALIDATION_ERROR", payload
    assert payload["field"] == "task_type", payload
    assert "TSK" in payload["message"], (
        f"the refusal must name the type the task actually is, got: {payload['message']!r}"
    )
    assert "create_task" in payload["message"], f"the refusal must say what to do instead, got: {payload['message']!r}"


async def test_changing_hnd_to_tsk_is_refused_too(task_boundary):
    client, _tenant_key, product_id = task_boundary
    async with client() as s:
        created = await _create(s, product_id, title="handover", description=GOOD_HANDOVER, task_type="HND")
        result = await s.call_tool("update_task", {"task_id": created["task_id"], "task_type": "TSK"})

    payload = _payload(result)
    assert payload["success"] is False, f"an HND was demoted to TSK: {payload}"
    assert payload["error"] == "VALIDATION_ERROR", payload
    assert payload["field"] == "task_type", payload
    assert "HND" in payload["message"], payload["message"]


async def test_a_refused_call_writes_nothing_at_all(task_boundary, db_manager):
    client, tenant_key, product_id = task_boundary
    async with client() as s:
        created = await _create(s, product_id)
        payload = _payload(
            await s.call_tool(
                "update_task",
                {
                    "task_id": created["task_id"],
                    "task_type": "HND",
                    "title": "this title must never land",
                    "status": "completed",
                    "priority": "critical",
                },
            )
        )
    assert payload["success"] is False, payload

    async with db_manager.get_session_async(tenant_key=tenant_key) as session:
        row = (await session.execute(select(Task).where(Task.id == created["task_id"]))).scalars().one()
    assert row.title == "an ordinary task", f"a refused update still wrote the title: {row.title!r}"
    assert str(getattr(row.status, "value", row.status)) != "completed", "a refused update still wrote the status"
    assert str(getattr(row.priority, "value", row.priority)) != "critical", "a refused update still wrote the priority"
    assert row.completed_at is None, "a refused update still stamped completed_at"




async def test_passing_the_same_type_is_accepted_as_a_no_op(task_boundary):
    client, _tenant_key, product_id = task_boundary
    async with client() as s:
        created = await _create(s, product_id)
        result = await s.call_tool(
            "update_task",
            {"task_id": created["task_id"], "task_type": "TSK", "title": "a renamed task"},
        )

    assert result.is_error is False, _text(result)
    payload = _payload(result)
    assert payload.get("success") is not False, f"an unchanged type was refused: {payload}"
    assert "title" in payload["updated_fields"], payload
    assert "task_type" not in payload["updated_fields"], (
        f"task_type must not be reported as written; it is not a writable field: {payload}"
    )


async def test_the_same_type_alone_is_nothing_to_update(task_boundary):
    client, _tenant_key, product_id = task_boundary
    async with client() as s:
        created = await _create(s, product_id)
        payload = _payload(await s.call_tool("update_task", {"task_id": created["task_id"], "task_type": "TSK"}))

    assert payload.get("success") is not False, f"an unchanged type was refused: {payload}"
    assert payload["updated_fields"] == [], payload




async def test_the_owning_service_refuses_the_same_input_independently(db_manager):
    from giljo_mcp.services.task_service import TaskService
    from giljo_mcp.services.task_type_immutability import TaskTypeImmutableError

    tenant_key = TenantManager.generate_tenant_key()
    product_id = await _seed_product(db_manager, tenant_key)
    tenant_manager = TenantManager()
    tenant_manager.set_current_tenant(tenant_key)
    service = TaskService(db_manager=db_manager, tenant_manager=tenant_manager)
    try:
        created = await service.create_task_for_mcp(
            title="an ordinary task",
            description="Do the thing.",
            product_id=product_id,
            tenant_key=tenant_key,
            db_manager=db_manager,
        )
        with pytest.raises(TaskTypeImmutableError) as excinfo:
            await service.update_task(created["task_id"], task_type="HND", title="must not land")

        assert excinfo.value.field == "task_type"
        assert "TSK" in str(excinfo.value), str(excinfo.value)
        assert "create_task" in str(excinfo.value), str(excinfo.value)

        unchanged = await service.get_task(created["task_id"])
        assert unchanged.title == "an ordinary task", "the service refusal still wrote the title"
    finally:
        await _cleanup(db_manager, tenant_key)


async def test_the_owning_service_accepts_the_same_type_as_a_no_op(db_manager):
    from giljo_mcp.services.task_service import TaskService

    tenant_key = TenantManager.generate_tenant_key()
    product_id = await _seed_product(db_manager, tenant_key)
    tenant_manager = TenantManager()
    tenant_manager.set_current_tenant(tenant_key)
    service = TaskService(db_manager=db_manager, tenant_manager=tenant_manager)
    try:
        created = await service.create_task_for_mcp(
            title="an ordinary task",
            description="Do the thing.",
            product_id=product_id,
            tenant_key=tenant_key,
            db_manager=db_manager,
        )
        result = await service.update_task(created["task_id"], task_type="TSK", title="a renamed task")
        assert "title" in result.updated_fields
        assert "task_type" not in result.updated_fields
    finally:
        await _cleanup(db_manager, tenant_key)
