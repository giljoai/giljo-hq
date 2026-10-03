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
                name=f"BE9637 product {uuid4().hex[:6]}",
                description="BE-9637 boundary test product",
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




async def test_create_task_accepts_the_hnd_type_over_the_real_transport(task_boundary):
    client, _tenant_key, product_id = task_boundary
    async with client() as s:
        result = await s.call_tool(
            "create_task",
            {
                "title": "Session handover",
                "description": GOOD_HANDOVER,
                "task_type": "HND",
                "product_id": product_id,
            },
        )
    assert result.is_error is False, _text(result)
    payload = _payload(result)
    assert payload["success"] is True, payload
    assert payload["task_type"] == "HND", f"asked for HND, got {payload.get('task_type')!r}"
    assert payload["taxonomy_alias"].startswith("HND-"), payload["taxonomy_alias"]


async def test_the_default_is_still_tsk(task_boundary):
    client, _tenant_key, product_id = task_boundary
    async with client() as s:
        result = await s.call_tool(
            "create_task",
            {"title": "An ordinary task", "description": "Do the thing.", "product_id": product_id},
        )
    assert result.is_error is False, _text(result)
    payload = _payload(result)
    assert payload["task_type"] == "TSK", payload
    assert payload["taxonomy_alias"].startswith("TSK-"), payload["taxonomy_alias"]


async def test_an_unknown_task_type_is_refused_and_names_the_valid_ones(task_boundary):
    client, _tenant_key, product_id = task_boundary
    async with client() as s:
        result = await s.call_tool(
            "create_task",
            {"title": "t", "description": "d", "task_type": "XYZ", "product_id": product_id},
        )
    payload = _payload(result)
    assert payload["success"] is False, payload
    assert payload["error"] == "VALIDATION_ERROR", payload
    assert payload["field"] == "task_type", payload
    assert "HND" in payload["message"] and "TSK" in payload["message"], (
        f"the refusal must name every valid type, got: {payload['message']!r}"
    )
    assert "XYZ" in payload["message"], "the refusal must name what it refused"


async def test_hnd_draws_from_the_same_global_serial_as_tsk(task_boundary):
    client, _tenant_key, product_id = task_boundary
    async with client() as s:
        first = _payload(
            await s.call_tool(
                "create_task",
                {"title": "one", "description": "d", "product_id": product_id},
            )
        )
        second = _payload(
            await s.call_tool(
                "create_task",
                {
                    "title": "two",
                    "description": GOOD_HANDOVER,
                    "task_type": "HND",
                    "product_id": product_id,
                },
            )
        )
    tsk_n = int(first["taxonomy_alias"].split("-")[1])
    hnd_n = int(second["taxonomy_alias"].split("-")[1])
    assert hnd_n > tsk_n, (
        f"the HND serial ({second['taxonomy_alias']}) must continue upward from the shared "
        f"counter, not restart per type (TSK was {first['taxonomy_alias']})"
    )




@pytest.mark.parametrize(
    "omitted",
    ["## Verify before trusting", "## Waiting on the operator", "## Cannot testify"],
)
async def test_an_hnd_missing_any_required_heading_is_refused_at_the_boundary(task_boundary, omitted):
    client, _tenant_key, product_id = task_boundary
    description = "\n".join(block for block in GOOD_HANDOVER.split("\n\n") if not block.lstrip().startswith(omitted))
    async with client() as s:
        result = await s.call_tool(
            "create_task",
            {
                "title": "half a handover",
                "description": description,
                "task_type": "HND",
                "product_id": product_id,
            },
        )
    payload = _payload(result)
    assert payload["success"] is False, f"a handover missing {omitted!r} was accepted: {payload}"
    assert payload["error"] == "VALIDATION_ERROR", payload
    assert payload["field"] == "description", payload
    assert omitted in payload["message"], (
        f"the refusal must NAME the missing heading so the author can fix it; got {payload['message']!r}"
    )


async def test_an_hnd_with_only_a_prior_work_section_is_still_refused_over_mcp(task_boundary):
    client, _tenant_key, product_id = task_boundary
    async with client() as s:
        result = await s.call_tool(
            "create_task",
            {
                "title": "agent handover, one section",
                "description": "## Where I left off\nStopped at the rebase.",
                "task_type": "HND",
                "product_id": product_id,
            },
        )
    payload = _payload(result)
    assert payload["success"] is False, payload
    assert payload["error"] == "VALIDATION_ERROR", payload
    for heading in ("## Verify before trusting", "## Waiting on the operator", "## Cannot testify"):
        assert heading in payload["message"], payload["message"]


async def test_a_refused_handover_writes_nothing(task_boundary, db_manager):
    client, tenant_key, product_id = task_boundary
    async with client() as s:
        await s.call_tool(
            "create_task",
            {
                "title": "should not exist",
                "description": "no headings here at all",
                "task_type": "HND",
                "product_id": product_id,
            },
        )
    async with db_manager.get_session_async(tenant_key=tenant_key) as session:
        from sqlalchemy import select

        rows = (await session.execute(select(Task).where(Task.tenant_key == tenant_key))).scalars().all()
    assert rows == [], f"a refused handover still wrote {len(rows)} row(s)"


async def test_a_tsk_is_not_subjected_to_the_handover_shape(task_boundary):
    client, _tenant_key, product_id = task_boundary
    async with client() as s:
        result = await s.call_tool(
            "create_task",
            {"title": "plain task", "description": "no headings, and that is fine", "product_id": product_id},
        )
    assert _payload(result)["success"] is True, _text(result)




async def test_the_service_refuses_the_same_input_independently(db_manager):
    from giljo_mcp.exceptions import ValidationError
    from giljo_mcp.services.task_service import TaskService

    tenant_key = TenantManager.generate_tenant_key()
    product_id = await _seed_product(db_manager, tenant_key)
    service = TaskService(db_manager=db_manager, tenant_manager=TenantManager())
    try:
        with pytest.raises(ValidationError) as excinfo:
            await service.create_task_for_mcp(
                title="half a handover",
                description="## Verify before trusting\n- nothing\n\n## Cannot testify\n- nothing",
                task_type="HND",
                product_id=product_id,
                tenant_key=tenant_key,
                db_manager=db_manager,
            )
        assert "## Waiting on the operator" in excinfo.value.message, excinfo.value.message
        assert excinfo.value.context["field"] == "description"
        assert excinfo.value.context["constraint"] == "handover_headings"
    finally:
        async with db_manager.get_session_async(tenant_key=tenant_key) as session:
            await session.execute(delete(Task).where(Task.tenant_key == tenant_key))
            await session.execute(delete(Product).where(Product.tenant_key == tenant_key))
            await session.commit()


def test_the_two_layers_produce_an_identical_rejection() -> None:
    from api.endpoints.mcp_tools._base import VALIDATION_ERROR
    from api.endpoints.mcp_tools._task_tools import _handover_shape_rejection
    from giljo_mcp.exceptions import ValidationError
    from giljo_mcp.services.handover_validation import require_handover_shape

    description = "## Verify before trusting\n- x\n\n## Waiting on the operator\n- nothing"

    boundary = _handover_shape_rejection(description)
    assert boundary is not None, "the boundary accepted a handover with a missing heading"
    assert boundary["error"] == VALIDATION_ERROR

    try:
        require_handover_shape(description, operation="create_task")
    except ValidationError as exc:
        service_message = exc.message
        service_context = exc.context
    else:  # pragma: no cover - the guard below states the failure plainly
        raise AssertionError("the service accepted a handover with a missing heading")

    assert boundary["message"] == service_message, (
        "the two layers must say the same sentence:\n"
        f"  boundary: {boundary['message']!r}\n"
        f"  service:  {service_message!r}"
    )
    assert boundary["field"] == service_context["field"]
    assert boundary["constraint"] == service_context["constraint"]


def test_a_well_formed_handover_is_accepted_by_both_layers() -> None:
    from api.endpoints.mcp_tools._task_tools import _handover_shape_rejection
    from giljo_mcp.services.handover_validation import require_handover_shape

    assert _handover_shape_rejection(GOOD_HANDOVER) is None
    require_handover_shape(GOOD_HANDOVER, operation="create_task")




async def _create_handover(client, product_id: str) -> dict:
    async with client() as s:
        result = await s.call_tool(
            "create_task",
            {
                "title": "Session handover",
                "description": GOOD_HANDOVER,
                "task_type": "HND",
                "product_id": product_id,
            },
        )
    payload = _payload(result)
    assert payload["success"] is True, payload
    return payload


async def test_converting_a_handover_to_a_project_is_refused(task_boundary):
    client, _tenant_key, product_id = task_boundary
    handover = await _create_handover(client, product_id)

    async with client() as s:
        result = await s.call_tool("update_task", {"task_id": handover["task_id"], "convert_to_project": True})

    payload = _payload(result)
    assert payload["success"] is False, f"a handover was converted to a project: {payload}"
    assert payload["error"] == "HANDOVER_NOT_CONVERTIBLE", payload
    assert handover["task_id"] in json.dumps(payload), "the refusal must name the task it refused"


async def test_a_refused_conversion_leaves_the_handover_intact(task_boundary, db_manager):
    from sqlalchemy import select

    client, tenant_key, product_id = task_boundary
    handover = await _create_handover(client, product_id)

    async with client() as s:
        await s.call_tool("update_task", {"task_id": handover["task_id"], "convert_to_project": True})

    async with db_manager.get_session_async(tenant_key=tenant_key) as session:
        row = (await session.execute(select(Task).where(Task.id == handover["task_id"]))).scalar_one_or_none()
    assert row is not None, "the refused conversion deleted the handover"


async def test_an_ordinary_task_still_converts(task_boundary):
    client, _tenant_key, product_id = task_boundary
    async with client() as s:
        task = _payload(
            await s.call_tool(
                "create_task",
                {"title": "ordinary", "description": "d", "product_id": product_id},
            )
        )
        result = await s.call_tool("update_task", {"task_id": task["task_id"], "convert_to_project": True})

    payload = _payload(result)
    assert payload.get("error") != "HANDOVER_NOT_CONVERTIBLE", (
        f"an ordinary task was refused as if it were a handover: {payload}"
    )




async def test_archiving_a_pending_handover_is_refused(task_boundary):
    client, _tenant_key, product_id = task_boundary
    handover = await _create_handover(client, product_id)

    async with client() as s:
        result = await s.call_tool("update_task", {"task_id": handover["task_id"], "hidden": "true"})

    payload = _payload(result)
    assert payload["success"] is False, f"an unread handover was hidden: {payload}"
    assert payload["error"] == "PENDING_HANDOVER_NOT_ARCHIVABLE", payload


async def test_a_handover_can_be_hidden_once_it_is_no_longer_pending(task_boundary):
    client, _tenant_key, product_id = task_boundary
    handover = await _create_handover(client, product_id)

    async with client() as s:
        completed = await s.call_tool("update_task", {"task_id": handover["task_id"], "status": "completed"})
        assert _payload(completed).get("success") is not False, _text(completed)
        result = await s.call_tool("update_task", {"task_id": handover["task_id"], "hidden": "true"})

    payload = _payload(result)
    assert payload.get("error") != "PENDING_HANDOVER_NOT_ARCHIVABLE", (
        f"a verified handover could not be archived: {payload}"
    )


async def test_a_pending_ordinary_task_can_still_be_hidden(task_boundary):
    client, _tenant_key, product_id = task_boundary
    async with client() as s:
        task = _payload(
            await s.call_tool(
                "create_task",
                {"title": "clutter", "description": "d", "product_id": product_id},
            )
        )
        result = await s.call_tool("update_task", {"task_id": task["task_id"], "hidden": "true"})

    payload = _payload(result)
    assert payload.get("error") != "PENDING_HANDOVER_NOT_ARCHIVABLE", payload




async def test_list_tasks_can_filter_to_handovers(task_boundary):
    client, _tenant_key, product_id = task_boundary
    handover = await _create_handover(client, product_id)
    async with client() as s:
        await s.call_tool("create_task", {"title": "noise", "description": "d", "product_id": product_id})
        result = await s.call_tool("list_tasks", {"task_type": "HND", "product_id": product_id})

    assert result.is_error is False, _text(result)
    body = json.dumps(_payload(result))
    assert handover["task_id"] in body, f"the HND filter did not return the handover: {body[:400]}"
    assert "noise" not in body, "the HND filter returned an ordinary task"
