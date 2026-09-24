# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import json
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import delete

from giljo_mcp.models.products import Product
from giljo_mcp.models.tasks import Task
from giljo_mcp.services.handover_validation import HANDOVER_CONTENT_CONSTRAINT, REQUIRED_HANDOVER_HEADINGS
from giljo_mcp.tenant import TenantManager
from tests.helpers.mcp_session_fixture import create_connected_server_and_client_session


pytestmark = pytest.mark.asyncio


GOOD_HANDOVER = """Session ended at the rebase. The reviewer holds the merge gate.

## Verify before trusting
- the branch is green -- check with: pytest tests/unit -q

## Waiting on the operator
- nothing

## Cannot testify
- the two-process concurrency behaviour; never observed it
"""

SKELETON = "\n\n".join(REQUIRED_HANDOVER_HEADINGS) + "\n"


def _payload(result) -> dict:
    if getattr(result, "structuredContent", None):
        return result.structured_content
    block = result.content[0]
    text = getattr(block, "text", None)
    if text is None:
        raise AssertionError(f"unexpected content block: {block!r}")
    return json.loads(text)


async def _seed_product(db_manager, tenant_key: str) -> str:
    product_id = str(uuid4())
    async with db_manager.get_session_async(tenant_key=tenant_key) as session:
        session.add(
            Product(
                id=product_id,
                name=f"BE9643a product {uuid4().hex[:6]}",
                description="BE-9643a boundary test product",
                tenant_key=tenant_key,
                is_active=True,
                product_memory={},
            )
        )
        await session.commit()
    return product_id


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
        async with db_manager.get_session_async(tenant_key=tenant_key) as session:
            await session.execute(delete(Task).where(Task.tenant_key == tenant_key))
            await session.execute(delete(Product).where(Product.tenant_key == tenant_key))
            await session.commit()
        state.tool_accessor, state.tenant_manager, state.db_manager = prior


async def _create_handover(client, product_id: str, description: str = GOOD_HANDOVER) -> dict:
    async with client() as s:
        result = await s.call_tool(
            "create_task",
            {
                "title": "Session handover",
                "description": description,
                "task_type": "HND",
                "product_id": product_id,
            },
        )
    return _payload(result)




async def test_create_refuses_a_handover_whose_sections_are_empty(task_boundary):
    client, _tenant_key, product_id = task_boundary
    payload = await _create_handover(client, product_id, SKELETON)

    assert payload["success"] is False, f"an empty handover was stored: {payload}"
    assert payload["error"] == "VALIDATION_ERROR", payload
    assert payload["field"] == "description", payload
    assert payload["constraint"] == HANDOVER_CONTENT_CONSTRAINT, payload


async def test_a_refused_create_writes_nothing(task_boundary, db_manager):
    from sqlalchemy import select

    client, tenant_key, product_id = task_boundary
    await _create_handover(client, product_id, SKELETON)

    async with db_manager.get_session_async(tenant_key=tenant_key) as session:
        rows = (await session.execute(select(Task).where(Task.tenant_key == tenant_key))).scalars().all()
    assert rows == [], "a refused create left a row behind"


async def test_nothing_under_a_heading_is_accepted(task_boundary):
    client, _tenant_key, product_id = task_boundary
    text = "Handover.\n\n" + "\n\n".join(f"{h}\nnothing" for h in REQUIRED_HANDOVER_HEADINGS)

    payload = await _create_handover(client, product_id, text)

    assert payload["success"] is True, payload




async def test_update_refuses_emptying_an_existing_handover(task_boundary):
    client, _tenant_key, product_id = task_boundary
    handover = await _create_handover(client, product_id)

    async with client() as s:
        result = await s.call_tool("update_task", {"task_id": handover["task_id"], "description": SKELETON})

    payload = _payload(result)
    assert payload["success"] is False, f"a handover was emptied by an update: {payload}"
    assert payload["error"] == "VALIDATION_ERROR", payload
    assert payload["field"] == "description", payload
    assert payload["constraint"] == HANDOVER_CONTENT_CONSTRAINT, payload


async def test_a_refused_update_leaves_the_description_intact(task_boundary, db_manager):
    from sqlalchemy import select

    client, tenant_key, product_id = task_boundary
    handover = await _create_handover(client, product_id)

    async with client() as s:
        await s.call_tool("update_task", {"task_id": handover["task_id"], "description": SKELETON})

    async with db_manager.get_session_async(tenant_key=tenant_key) as session:
        row = (await session.execute(select(Task).where(Task.id == handover["task_id"]))).scalar_one()
    assert row.description == GOOD_HANDOVER, "a refused update still wrote"


async def test_update_refuses_dropping_a_heading_too(task_boundary):
    client, _tenant_key, product_id = task_boundary
    handover = await _create_handover(client, product_id)

    async with client() as s:
        result = await s.call_tool(
            "update_task",
            {"task_id": handover["task_id"], "description": "## Verify before trusting\n- x -- check with: y\n"},
        )

    payload = _payload(result)
    assert payload["success"] is False, f"a handover lost a heading on update: {payload}"
    assert payload["error"] == "VALIDATION_ERROR", payload


async def test_a_good_description_edit_still_lands(task_boundary):
    client, _tenant_key, product_id = task_boundary
    handover = await _create_handover(client, product_id)
    edited = GOOD_HANDOVER + "\n## References\n- /reports/run.md\n"

    async with client() as s:
        result = await s.call_tool("update_task", {"task_id": handover["task_id"], "description": edited})

    payload = _payload(result)
    assert "description" in payload.get("updated_fields", []), payload


async def test_editing_an_ordinary_task_is_untouched_by_the_rule(task_boundary):
    client, _tenant_key, product_id = task_boundary
    async with client() as s:
        task = _payload(
            await s.call_tool("create_task", {"title": "ordinary", "description": "d", "product_id": product_id})
        )
        result = await s.call_tool("update_task", {"task_id": task["task_id"], "description": "still ordinary"})

    payload = _payload(result)
    assert "description" in payload.get("updated_fields", []), payload


async def test_a_non_description_edit_never_triggers_the_rule(task_boundary, db_manager):
    from sqlalchemy import select

    client, tenant_key, product_id = task_boundary
    handover = await _create_handover(client, product_id)

    async with db_manager.get_session_async(tenant_key=tenant_key) as session:
        row = (await session.execute(select(Task).where(Task.id == handover["task_id"]))).scalar_one()
        row.description = SKELETON
        await session.commit()

    async with client() as s:
        result = await s.call_tool("update_task", {"task_id": handover["task_id"], "status": "in_progress"})

    payload = _payload(result)
    assert "status" in payload.get("updated_fields", []), payload


async def test_an_old_shape_handover_still_reads(task_boundary, db_manager):
    from sqlalchemy import select

    client, tenant_key, product_id = task_boundary
    handover = await _create_handover(client, product_id)

    async with db_manager.get_session_async(tenant_key=tenant_key) as session:
        row = (await session.execute(select(Task).where(Task.id == handover["task_id"]))).scalar_one()
        row.description = SKELETON
        await session.commit()

    async with client() as s:
        result = await s.call_tool("list_tasks", {"task_type": "HND", "mode": "full", "product_id": product_id})

    payload = _payload(result)
    assert payload.get("tasks"), f"an old-shape handover disappeared from the list: {payload}"




def test_the_two_layers_produce_an_identical_content_rejection() -> None:
    from api.endpoints.mcp_tools._base import VALIDATION_ERROR
    from api.endpoints.mcp_tools._task_tools import _handover_shape_rejection
    from giljo_mcp.exceptions import ValidationError
    from giljo_mcp.services.handover_validation import require_handover_shape

    boundary = _handover_shape_rejection(SKELETON)
    assert boundary is not None, "the boundary accepted a handover with empty sections"
    assert boundary["error"] == VALIDATION_ERROR

    try:
        require_handover_shape(SKELETON, operation="create_task")
    except ValidationError as exc:
        service_message = exc.message
        service_context = exc.context
    else:  # pragma: no cover - the guard states the failure plainly
        raise AssertionError("the service accepted a handover with empty sections")

    assert boundary["message"] == service_message, (
        "the two layers must say the same sentence:\n"
        f"  boundary: {boundary['message']!r}\n"
        f"  service:  {service_message!r}"
    )
    assert boundary["field"] == service_context["field"]
    assert boundary["constraint"] == service_context["constraint"]
