# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""MCP-transport boundary tests for BE-6049d taxonomy advertising.

CLAUDE.md mandates a regression test at the layer the behavior lives. The
agent-facing taxonomy contract changed by the BE-6049 chain lives at the
FastMCP ``@mcp.tool`` wrapper layer (``api/endpoints/mcp_tools/_task_tools.py``
and ``_project_tools.py``): create_task is auto-tagged ``TSK`` and create_project
must never accept or advertise ``TSK``. The service-layer behavior is covered by
``tests/services/test_task_taxonomy_mcp_tools.py`` and
``tests/services/test_be6049c_tsk_namespace.py``; this file closes the gap by
exercising the actual MCP transport so the wrapper + ``_call_tool`` dispatch are
covered, not just the service in isolation.

Behaviors under test (through ``create_connected_server_and_client_session``):

1. create_task via MCP yields a TSK task with a TSK-nnnn alias (no type to pick).
2. create_project via MCP rejects ``project_type="TSK"`` -- a project can never be
   created as TSK.
3. create_project via MCP (no type) succeeds, its ``valid_types`` hint excludes
   TSK, and it advertises auto-numbering via the ``numbering`` field.

Pattern reference: ``tests/integration/test_complete_job_mcp_boundary.py``
(same in-memory transport, same ``_resolve_tenant`` monkeypatch, same
shared-session service rebinding so writes land in the rolled-back transaction).
"""

from __future__ import annotations

import json
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import delete

from giljo_mcp.models.organizations import Organization
from giljo_mcp.models.products import Product
from giljo_mcp.models.projects import TaxonomyType
from giljo_mcp.tenant import TenantManager
from tests.helpers.mcp_session_fixture import create_connected_server_and_client_session


pytestmark = pytest.mark.asyncio


# ============================================================================
# Helpers
# ============================================================================


def _payload(call_tool_result) -> dict:
    """Extract structured payload from an MCP CallToolResult."""
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


# ============================================================================
# Fixture: MCP client wired to the rolled-back test session, with an active product
# ============================================================================


@pytest_asyncio.fixture
async def taxonomy_mcp_client(db_manager, db_session, monkeypatch):
    """Yield ``(new_client, tenant_key)`` for FastMCP transport tests.

    Installs:
    - A monkeypatched ``_resolve_tenant`` so the in-memory transport has a
      synthetic tenant_key (no auth middleware in the in-process MCP fixture).
    - A ToolAccessor whose ProjectService AND TaskService share ``db_session``
      (the rolled-back transaction) so create writes never leak. ToolAccessor
      passes ``test_session`` to ProjectService but not TaskService, so the task
      service is rebound explicitly.
    - A real, active Product committed via ``db_session`` so the create paths'
      active-product resolution succeeds inside the same transaction.

    Default-type seeding inside ``_get_valid_project_types`` opens its own
    committing session (it is not the test transaction), so the seeded
    ``taxonomy_types`` rows are removed for the synthetic tenant on teardown.
    """
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

    # An active product for this tenant, committed inside the rolled-back
    # transaction so the create paths' ProductService (which now receives the
    # shared test_session) can resolve it.
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
        name=f"Product {suffix}",
        description="BE-6049d MCP boundary test",
        tenant_key=tenant_key,
        is_active=True,
    )
    db_session.add(product)
    await db_session.commit()

    accessor = ToolAccessor(
        db_manager=db_manager,
        tenant_manager=state.tenant_manager,
        test_session=db_session,
    )
    # ToolAccessor does not pass the session to TaskService; rebind so task
    # writes (and its ProductService active-product lookup) share the txn.
    accessor._task_service = TaskService(
        db_manager=db_manager,
        tenant_manager=state.tenant_manager,
        session=db_session,
    )
    state.tool_accessor = accessor

    monkeypatch.setattr(_base, "_resolve_tenant", lambda ctx: tenant_key)
    monkeypatch.setattr(_base, "_resolve_user_id", lambda ctx: None)

    def _new_client():
        return create_connected_server_and_client_session(mcp_sdk_server.mcp)

    try:
        yield _new_client, tenant_key
    finally:
        # Remove default taxonomy rows seeded via the non-transactional session.
        async with db_manager.get_session_async() as cleanup:
            await cleanup.execute(delete(TaxonomyType).where(TaxonomyType.tenant_key == tenant_key))
            await cleanup.commit()
        state.tool_accessor = prior_tool_accessor
        state.tenant_manager = prior_tenant_manager
        state.db_manager = prior_db_manager


# ============================================================================
# Tests
# ============================================================================


async def test_create_task_via_mcp_yields_tsk(taxonomy_mcp_client):
    """(1) create_task through the transport auto-tags TSK with a TSK-nnnn alias.

    The task_type argument is accepted-but-ignored; supplying 'BE' must NOT make
    the task a BE task. This guards the wrapper + service forcing TSK at the
    boundary an agent actually calls.
    """
    new_client, _tenant_key = taxonomy_mcp_client

    async with new_client() as mcp_session:
        result = await mcp_session.call_tool(
            "create_task",
            {
                "title": "Investigate flaky websocket test",
                "description": "Repro and fix",
                "priority": "high",
                "task_type": "BE",  # ignored -- every task is TSK
            },
        )

    assert result.is_error is False, f"BE-6049d: create_task must succeed; got: {_error_text(result)}"
    payload = _payload(result)
    assert payload.get("success") is True
    assert payload.get("task_type") == "TSK", (
        f"BE-6049d: every task must be auto-tagged TSK regardless of task_type; got {payload.get('task_type')!r}"
    )
    assert str(payload.get("taxonomy_alias", "")).startswith("TSK-"), (
        f"BE-6049d: task alias must render TSK-nnnn; got {payload.get('taxonomy_alias')!r}"
    )


async def test_create_project_via_mcp_rejects_tsk(taxonomy_mcp_client):
    """(2) create_project through the transport refuses project_type='TSK'.

    TSK is task-only; a project can never be created as TSK. The wrapper must
    surface a rejection, not silently create a TSK-typed project.
    """
    new_client, _tenant_key = taxonomy_mcp_client

    async with new_client() as mcp_session:
        result = await mcp_session.call_tool(
            "create_project",
            {
                "name": "Should never be TSK",
                "description": "BE-6049d boundary: TSK is not a valid project type",
                "project_type": "TSK",
            },
        )

    assert result.is_error is True, (
        "BE-6049d: create_project with project_type='TSK' must be rejected "
        f"(TSK is task-only); got success payload: {_error_text(result)}"
    )
    err = _error_text(result)
    assert "TSK" in err and "Valid types" in err, (
        f"BE-6049d: rejection must explain TSK is not a valid project type; got: {err!r}"
    )


async def test_create_project_via_mcp_valid_types_excludes_tsk_and_advertises_numbering(taxonomy_mcp_client):
    """(3) create_project (no type) succeeds; valid_types excludes TSK and the
    response advertises auto-numbering.

    Omitting project_type returns the valid_types hint -- TSK must not appear in
    it. The response also advertises that numbering is automatic so agents stop
    supplying series_number.
    """
    new_client, _tenant_key = taxonomy_mcp_client

    async with new_client() as mcp_session:
        result = await mcp_session.call_tool(
            "create_project",
            {
                "name": "Auto-numbered project",
                "description": "BE-6049d boundary: omit type -> valid_types hint excludes TSK",
            },
        )

    assert result.is_error is False, f"BE-6049d: create_project (no type) must succeed; got: {_error_text(result)}"
    payload = _payload(result)
    assert payload.get("success") is True

    valid_types = payload.get("valid_types")
    assert isinstance(valid_types, list) and valid_types, (
        f"BE-6049d: omitting project_type must surface a non-empty valid_types hint; got {valid_types!r}"
    )
    abbreviations = {t.get("abbreviation") for t in valid_types}
    assert "TSK" not in abbreviations, (
        f"BE-6049d: the reserved TSK tag must NEVER appear in project valid_types; got {sorted(abbreviations)}"
    )

    numbering = str(payload.get("numbering", ""))
    assert "auto-assigned" in numbering.lower(), (
        f"BE-6049d: create_project success must advertise auto-numbering; got numbering={numbering!r}"
    )
