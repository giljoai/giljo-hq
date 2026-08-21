# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
Transport-layer smoke tests for the new task MCP tools (BE-5057).

Closes the BE-5042 lesson gap: ``tests/services/test_task_taxonomy_mcp_tools.py``
covers the service layer with 24 tests, but the FastMCP ``@mcp.tool`` wrappers
at ``api/endpoints/mcp_sdk_server.py:584-702`` are themselves untested. CLAUDE.md
mandates a regression test at the failing layer for every bug-fix project; this
file is defense-in-depth for that layer before a real bug ever lives there.

What this file does NOT do:

- Re-test service logic (taxonomy resolution, status transitions, audit-trail
  appending). Those have ~24 dedicated tests in tests/services/.
- Cover wrappers other than create_task / update_task / list_tasks (the task
  wrappers; BE-6225a retired complete_task by folding it into update_task via
  the completion_notes param).

Pattern reference: ``tests/integration/test_mcp_protocol_harness.py`` — same
in-memory ``create_connected_server_and_client_session`` transport.

Tenant injection: in production, ``MCPAuthMiddleware`` puts ``tenant_key`` into
the ASGI scope and the wrappers read it via ``_resolve_tenant``. The in-memory
transport has no HTTP scope, so we monkeypatch ``_resolve_tenant`` /
``_resolve_user_id`` to return the test tenant. That is the boundary we want
to hold steady — the wrappers' own kwarg-unpacking + ``_call_tool`` dispatch.
"""

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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _payload(call_tool_result) -> dict:
    """Decode a CallToolResult into a dict (mirrors the harness helper)."""
    if getattr(call_tool_result, "structuredContent", None):
        return call_tool_result.structured_content
    first_block = call_tool_result.content[0]
    text = getattr(first_block, "text", None)
    if text is None:
        raise AssertionError(f"unexpected content block: {first_block!r}")
    return json.loads(text)


def _error_text(call_tool_result) -> str:
    """Concatenate error text blocks from an error CallToolResult."""
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


# ---------------------------------------------------------------------------
# Fixtures: shared-session ToolAccessor + tenant-aware MCP client
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def primary_tenant_key() -> str:
    return TenantManager.generate_tenant_key()


@pytest_asyncio.fixture
async def secondary_tenant_key() -> str:
    return TenantManager.generate_tenant_key()


class _TenantSwitch:
    """Mutable holder so tests can flip the resolved tenant_key per call."""

    def __init__(self, value: str):
        self.value = value


@pytest_asyncio.fixture
async def task_mcp_client(db_manager, db_session, primary_tenant_key, monkeypatch):
    """
    Yield a tuple ``(new_client, tenant_switch)``.

    ``new_client()`` returns a fresh single-use async context manager that
    produces an initialized ``ClientSession`` against the live FastMCP server
    (the SDK's in-memory ``create_connected_server_and_client_session`` is
    one-shot — call ``new_client()`` once per ``async with`` block).
    ``tenant_switch``
    lets a test mutate the tenant_key the wrappers see (used for cross-tenant
    list_tasks scoping).

    Built on top of the ``mcp_client`` pattern but with three deltas:
    1. Replaces ``ToolAccessor._task_service`` with a ``TaskService`` bound to
       the test ``db_session`` so writes/reads happen inside the same
       rolled-back transaction (otherwise wrapper-spawned sessions would see
       no taxonomy/products and would commit live rows past the test).
    2. Monkeypatches ``_resolve_tenant`` / ``_resolve_user_id`` to read from
       a closure (no auth middleware in the in-memory transport).
    3. Monkeypatches ``_call_tool``'s post-call ``auto_clear_silent`` /
       ``touch_heartbeat`` paths to no-ops — they only fire when ``job_id``
       is in kwargs (which it isn't here), but importing app_state.db_manager
       would crash if state were unset, so we belt-and-brace the import path.
    """
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

    # BE-6042d: _resolve_tenant/_resolve_user_id moved to mcp_tools._base (the
    # _call_tool call site reads them there). Patch _base, not mcp_sdk_server.
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


# ---------------------------------------------------------------------------
# create_task wrapper (mcp_sdk_server.py:584-603)
# ---------------------------------------------------------------------------


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
                "task_type": "BE",
            },
        )

    assert result.is_error is False, _error_text(result)
    payload = _payload(result)
    assert payload["task_id"]
    # BE-6049c: tasks are TSK-only — an explicit task_type ("BE") is
    # accepted-but-ignored; the task is always created as the reserved TSK tag.
    assert payload.get("task_type") == "TSK"


async def test_create_task_ignores_task_type_param_and_forces_tsk(task_mcp_client, db_session, primary_tenant_key):
    """BE-6049c: a bogus task_type no longer errors — it is ignored and the
    task is created as TSK (the param is accepted-but-ignored, not validated)."""
    new_client, _switch = task_mcp_client
    await _seed_product(db_session, primary_tenant_key)
    await _seed_taxonomy(db_session, primary_tenant_key)

    async with new_client() as session:
        result = await session.call_tool(
            "create_task",
            {
                "title": "bogus type is ignored",
                "description": "unknown task_type no longer errors",
                "task_type": "MADEUP",
            },
        )

    assert result.is_error is False, _error_text(result)
    payload = _payload(result)
    assert payload["task_id"]
    assert payload.get("task_type") == "TSK"


# ---------------------------------------------------------------------------
# update_task wrapper (mcp_sdk_server.py:606-643)
# ---------------------------------------------------------------------------


async def _create_seed_task(new_client, db_session, tenant_key) -> str:
    await _seed_product(db_session, tenant_key)
    await _seed_taxonomy(db_session, tenant_key)
    async with new_client() as session:
        result = await session.call_tool(
            "create_task",
            {
                "title": "seed",
                "description": "seed for update/complete",
                "task_type": "BE",
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
    """BE-6049c: the TSK tag is immutable — update_task ignores an inbound
    task_type (no error) instead of validating/rejecting it."""
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

    assert result.is_error is True
    assert "not_a_real_status" in _error_text(result) or "status" in _error_text(result).lower()


# ---------------------------------------------------------------------------
# BE-6225a: update_task completion_notes fold (regression at the @mcp.tool
# boundary). The standalone complete_task tool was RETIRED and folded into
# update_task via the completion_notes param — completing a task is now
# update_task(status="completed", completion_notes=...). These tests prove the
# folded contract THROUGH the MCP transport (the layer the fold changed), not
# just the service layer.
# ---------------------------------------------------------------------------


async def test_update_task_completed_with_notes_appends_and_stamps(task_mcp_client, db_session, primary_tenant_key):
    """update_task(status="completed", completion_notes=...) stamps completed_at
    AND appends the note to the description as an audit-trail entry — the parity
    contract that retired complete_task depends on."""
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

    # The note must have been appended to the task description (audit trail).
    async with new_client() as session:
        full = await session.call_tool("list_tasks", {"mode": "full"})
    row = next(r for r in _payload(full)["tasks"] if r["task_id"] == task_id)
    assert row["status"] == "completed"
    assert row["completed_at"]
    # Round-trip the timestamp to confirm it's a real ISO datetime.
    parsed = datetime.fromisoformat(row["completed_at"])
    assert parsed.tzinfo is not None or parsed <= datetime.now()  # noqa: DTZ005 — stored as naive in DB
    assert "all green via transport" in row["description"]


async def test_update_task_completion_notes_without_completed_is_noop(task_mcp_client, db_session, primary_tenant_key):
    """A completion_notes value with a non-completing status must NOT append the
    note — the audit entry only makes sense on completion (BE-6225a contract)."""
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


# ---------------------------------------------------------------------------
# TSK-9163: due_date through the transport. The wrapper's due_date param is
# typed str, so the service ALWAYS receives a string on this path; before the
# _parse_due_date fix the raw str reached the DateTime(timezone=True) column
# and asyncpg rejected it at commit — every MCP due_date write 500'd with the
# generic internal-error envelope (REST was unaffected: Pydantic parses).
# ---------------------------------------------------------------------------


async def test_update_task_due_date_string_via_transport(task_mcp_client, db_session, primary_tenant_key):
    """The exact TSK-9163 repro call: update_task(task_id, due_date='2026-07-15')."""
    new_client, _switch = task_mcp_client
    task_id = await _create_seed_task(new_client, db_session, primary_tenant_key)

    async with new_client() as session:
        result = await session.call_tool(
            "update_task",
            {"task_id": task_id, "due_date": "2026-07-15"},
        )

    assert result.is_error is False, _error_text(result)
    payload = _payload(result)
    assert payload["task_id"] == task_id
    assert "due_date" in payload["updated_fields"]

    # Round-trip: the stored value must read back as the requested date.
    async with new_client() as session:
        full = await session.call_tool("list_tasks", {"mode": "full"})
    row = next(r for r in _payload(full)["tasks"] if r["task_id"] == task_id)
    assert row["due_date"] is not None
    parsed = datetime.fromisoformat(row["due_date"])
    assert (parsed.year, parsed.month, parsed.day) == (2026, 7, 15)


async def test_update_task_due_date_garbage_is_actionable_error_via_transport(
    task_mcp_client, db_session, primary_tenant_key
):
    """An unparseable due_date must surface as an actionable validation error
    naming the field, not the generic internal-error envelope."""
    new_client, _switch = task_mcp_client
    task_id = await _create_seed_task(new_client, db_session, primary_tenant_key)

    async with new_client() as session:
        result = await session.call_tool(
            "update_task",
            {"task_id": task_id, "due_date": "next tuesday"},
        )

    assert result.is_error is True
    assert "due_date" in _error_text(result)


# ---------------------------------------------------------------------------
# list_tasks wrapper (mcp_sdk_server.py:665-702)
# ---------------------------------------------------------------------------


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
    expected = {"task_id", "title", "status", "priority", "task_type", "due_date", "created_at"}
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
    """Two tenants, each with one task. list_tasks called as tenant A must
    not return tenant B's task. This is the regression that proves the
    wrapper passes tenant_key through to the service correctly.
    """
    new_client, switch = task_mcp_client

    # Tenant A: create product + taxonomy + task via the wrapper as tenant A.
    switch.value = primary_tenant_key
    a_task_id = await _create_seed_task(new_client, db_session, primary_tenant_key)

    # Tenant B: seed product + taxonomy directly, then create task via wrapper
    # while monkeypatched tenant is B.
    await _seed_product(db_session, secondary_tenant_key)
    await _seed_taxonomy(db_session, secondary_tenant_key)
    switch.value = secondary_tenant_key
    async with new_client() as session:
        b_result = await session.call_tool(
            "create_task",
            {"title": "tenant_b task", "description": "x", "task_type": "BE"},
        )
    assert b_result.is_error is False, _error_text(b_result)
    b_task_id = _payload(b_result)["task_id"]
    assert b_task_id != a_task_id

    # Now call list_tasks as tenant A; tenant B's task must not appear.
    switch.value = primary_tenant_key
    async with new_client() as session:
        list_result = await session.call_tool("list_tasks", {"mode": "summary"})

    assert list_result.is_error is False, _error_text(list_result)
    ids = {row["task_id"] for row in _payload(list_result)["tasks"]}
    assert a_task_id in ids
    assert b_task_id not in ids, (
        "TENANT LEAK: tenant A's list_tasks returned tenant B's task — wrapper is not propagating tenant_key correctly."
    )


# ---------------------------------------------------------------------------
# FE-5046: Task UI parity -- hidden + taxonomy fields via the wrapper
# ---------------------------------------------------------------------------


async def test_list_tasks_summary_includes_taxonomy_and_hidden_fields(task_mcp_client, db_session, primary_tenant_key):
    """Wrapper-level shape check for FE-5046 parity contract."""
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
    # BE-6049c: tasks are TSK-only, so the seeded task's type is the reserved TSK tag.
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
            {"title": "hidden task", "description": "x", "task_type": "BE"},
        )
    assert h_create.is_error is False, _error_text(h_create)
    hidden_id = _payload(h_create)["task_id"]

    async with new_client() as session:
        await session.call_tool("update_task", {"task_id": hidden_id, "hidden": "true"})

    # No filter -> both visible (default contract)
    async with new_client() as session:
        both = await session.call_tool("list_tasks", {"mode": "summary"})
    ids_both = {r["task_id"] for r in _payload(both)["tasks"]}
    assert visible_id in ids_both
    assert hidden_id in ids_both

    # hidden=true -> only hidden
    async with new_client() as session:
        only_hidden = await session.call_tool("list_tasks", {"mode": "summary", "hidden": "true"})
    ids_h = {r["task_id"] for r in _payload(only_hidden)["tasks"]}
    assert hidden_id in ids_h
    assert visible_id not in ids_h

    # hidden=false -> only visible
    async with new_client() as session:
        only_visible = await session.call_tool("list_tasks", {"mode": "summary", "hidden": "false"})
    ids_v = {r["task_id"] for r in _payload(only_visible)["tasks"]}
    assert visible_id in ids_v
    assert hidden_id not in ids_v


# ---------------------------------------------------------------------------
# TSK-9177: due_before through the transport. Same class as TSK-9163: the
# wrapper's due_before param is typed str and was forwarded raw into
# ``Task.due_date < due_before``, so asyncpg rejected the str-vs-timestamptz
# comparison and every MCP list_tasks(due_before=...) call failed with the
# generic internal-error envelope.
# ---------------------------------------------------------------------------


async def test_list_tasks_due_before_string_via_transport(task_mcp_client, db_session, primary_tenant_key):
    """The exact TSK-9177 repro call: list_tasks(due_before='2026-07-15')."""
    new_client, _switch = task_mcp_client
    task_id = await _create_seed_task(new_client, db_session, primary_tenant_key)

    async with new_client() as session:
        set_due = await session.call_tool(
            "update_task",
            {"task_id": task_id, "due_date": "2026-07-10T00:00:00+00:00"},
        )
    assert set_due.is_error is False, _error_text(set_due)

    async with new_client() as session:
        result = await session.call_tool("list_tasks", {"due_before": "2026-07-15"})

    assert result.is_error is False, _error_text(result)
    ids = {row["task_id"] for row in _payload(result)["tasks"]}
    assert task_id in ids

    # The parsed bound must actually filter: a cutoff before the due date
    # excludes the task.
    async with new_client() as session:
        earlier = await session.call_tool("list_tasks", {"due_before": "2026-07-01"})
    assert earlier.is_error is False, _error_text(earlier)
    ids_earlier = {row["task_id"] for row in _payload(earlier)["tasks"]}
    assert task_id not in ids_earlier


async def test_list_tasks_due_before_garbage_is_actionable_error_via_transport(
    task_mcp_client, db_session, primary_tenant_key
):
    """An unparseable due_before must surface as an actionable validation error
    naming the field, not the generic internal-error envelope."""
    new_client, _switch = task_mcp_client
    await _create_seed_task(new_client, db_session, primary_tenant_key)

    async with new_client() as session:
        result = await session.call_tool("list_tasks", {"due_before": "next tuesday"})

    assert result.is_error is True
    assert "due_before" in _error_text(result)


# Suppress unused-import warning: random/datetime are kept for future
# parameterization; keep them imported so contributors don't re-add them.
_ = random
