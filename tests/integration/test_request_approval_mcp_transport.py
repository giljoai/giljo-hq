# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""Transport-layer tests for the ``request_approval`` MCP tool (BE-5029).

Closes the regression-test-at-the-failing-layer gap flagged by the tester:
``tests/tools/test_request_approval.py`` covers ``ToolAccessor.request_approval``
directly, but the ``@mcp.tool`` wrapper at ``api/endpoints/mcp_sdk_server.py:705``
is itself untested. The wrapper invokes ``_resolve_tenant(ctx)`` (reading
``tenant_key`` from the ASGI session set by ``MCPAuthMiddleware``) and dispatches
through ``_call_tool`` -- that whole boundary is what these tests exercise.

Pattern reference: ``tests/integration/test_task_tools_mcp_transport.py`` -- same
in-memory ``create_connected_server_and_client_session`` transport, same
``_resolve_tenant`` / ``_resolve_user_id`` monkeypatch trick, same shared-session
service rebinding so DB writes/reads happen inside the rolled-back test
transaction.
"""

from __future__ import annotations

import json
import random
from datetime import UTC, datetime
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import select

from giljo_mcp.models.agent_identity import AgentExecution, AgentJob
from giljo_mcp.models.organizations import Organization
from giljo_mcp.models.products import Product
from giljo_mcp.models.projects import Project
from giljo_mcp.models.user_approval import UserApproval
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


async def _seed_approval_context(db_session, tenant_key: str, job_type: str = "orchestrator") -> dict:
    """Create org + product + project + agent_job + agent_execution for tenant.

    Returns dict with keys: project, job, execution -- mirrors the seed fixture
    in tests/tools/test_request_approval.py but creates everything for an
    arbitrary tenant_key so cross-tenant isolation can be tested.

    BE-9054 (a): request_approval is orchestrator-only, so the default seed is
    an orchestrator job; pass job_type="implementer" to exercise the worker
    rejection.
    """
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
        description="approval transport-layer tests",
        tenant_key=tenant_key,
        is_active=True,
    )
    db_session.add(product)
    await db_session.flush()

    project = Project(
        id=str(uuid4()),
        tenant_key=tenant_key,
        product_id=product.id,
        name=f"Project {suffix}",
        description="x",
        mission="x",
        status="active",
        series_number=random.randint(1, 9000),
    )
    db_session.add(project)
    await db_session.flush()

    job = AgentJob(
        job_id=str(uuid4()),
        tenant_key=tenant_key,
        project_id=project.id,
        job_type=job_type,
        mission="x",
        status="active",
        created_at=datetime.now(UTC),
    )
    db_session.add(job)
    await db_session.flush()

    execution = AgentExecution(
        id=str(uuid4()),
        agent_id=str(uuid4()),
        job_id=job.job_id,
        tenant_key=tenant_key,
        agent_display_name=job_type,
        status="working",
        started_at=datetime.now(UTC),
    )
    db_session.add(execution)
    await db_session.commit()

    return {"project": project, "job": job, "execution": execution}


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
async def approval_mcp_client(db_manager, db_session, primary_tenant_key, monkeypatch):
    """Yield ``(new_client, tenant_switch)`` for in-memory FastMCP transport tests.

    ``new_client()`` returns a one-shot async context manager around an
    initialized ``ClientSession``. ``tenant_switch.value`` is the tenant_key the
    monkeypatched ``_resolve_tenant`` returns -- mutating it between calls lets
    a single test flip the active tenant without spinning up a second fixture.

    Three deltas vs production wiring:
    1. Replace ``ToolAccessor._user_approval_service`` with a service bound to
       the test ``db_session`` so writes happen inside the rolled-back test
       transaction (otherwise a fresh session would see no
       project/job/execution rows and would commit live rows past teardown).
    2. Monkeypatch ``_resolve_tenant`` / ``_resolve_user_id`` to read from the
       tenant_switch closure (no auth middleware in the in-memory transport).
    3. Belt-and-brace ``app_state.db_manager`` so the post-call
       ``auto_clear_silent`` / ``touch_heartbeat`` paths in ``_call_tool`` find
       a live db_manager when ``job_id`` is in kwargs (which it always is for
       request_approval).
    """
    from api import app_state
    from api.endpoints import mcp_sdk_server
    from giljo_mcp.services.user_approval_service import UserApprovalService
    from giljo_mcp.tools.tool_accessor import ToolAccessor

    state = app_state.state

    prior_tool_accessor = state.tool_accessor
    prior_tenant_manager = state.tenant_manager
    prior_db_manager = state.db_manager

    if state.tenant_manager is None:
        state.tenant_manager = TenantManager()
    state.db_manager = db_manager

    accessor = ToolAccessor(db_manager=db_manager, tenant_manager=state.tenant_manager)
    accessor._user_approval_service = UserApprovalService(
        db_manager=db_manager,
        tenant_manager=state.tenant_manager,
        test_session=db_session,
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
# request_approval wrapper (mcp_sdk_server.py:705-737)
# ---------------------------------------------------------------------------


async def test_request_approval_happy_path_through_wrapper(approval_mcp_client, db_session, primary_tenant_key):
    """Call request_approval via the FastMCP client and assert:

    1. Response shape matches ``{"approval_id": "<uuid>", "status": "pending"}``.
    2. The persisted row's tenant_key is the one resolved from the ASGI session
       (the monkeypatched ``_resolve_tenant``), proving the wrapper is using the
       session-derived tenant_key and NOT trusting client kwargs.
    """
    new_client, _switch = approval_mcp_client
    seed = await _seed_approval_context(db_session, primary_tenant_key)

    async with new_client() as session:
        result = await session.call_tool(
            "request_approval",
            {
                "job_id": seed["job"].job_id,
                "project_id": seed["project"].id,
                "reason": "transport-layer happy path",
                "options": [
                    {"id": "approve", "label": "Approve"},
                    {"id": "rework", "label": "Rework"},
                ],
                "context": {"deferred": ["x"]},
            },
        )

    assert result.is_error is False, _error_text(result)
    payload = _payload(result)
    # IMP-6038: the FastMCP server echoes `_meta:{skills_version}` on every MCP
    # response (per-device skills nudge), so require the contract keys as a subset
    # while still rejecting any extra key other than `_meta`.
    assert {"approval_id", "status"} <= set(payload.keys()), f"unexpected response keys: {payload!r}"
    assert set(payload.keys()) - {"approval_id", "status"} <= {"_meta"}, f"unexpected extra keys: {payload!r}"
    assert payload["status"] == "pending"
    approval_id = payload["approval_id"]
    assert approval_id

    row = (await db_session.execute(select(UserApproval).where(UserApproval.id == approval_id))).scalar_one()
    assert row.tenant_key == primary_tenant_key, (
        "wrapper must persist tenant_key resolved from the ASGI session, not whatever was supplied in kwargs"
    )
    assert row.job_id == seed["job"].job_id
    assert row.project_id == seed["project"].id
    assert row.status == "pending"


async def test_request_approval_is_tenant_scoped_at_transport_boundary(
    approval_mcp_client,
    db_session,
    primary_tenant_key,
    secondary_tenant_key,
):
    """Tenant A creates an approval through the transport. Switch the
    monkeypatched ``_resolve_tenant`` to tenant B and try to interact with
    tenant A's job through the same transport: the wrapper must reject because
    tenant B's scope cannot see tenant A's AgentJob row.

    This is the regression that proves the ``@mcp.tool`` wrapper passes the
    session-derived tenant_key through to the service correctly. If the wrapper
    ever started trusting a client-supplied tenant_key kwarg, this test would
    flip green for the wrong reason -- so we also assert the persisted tenant_A
    row is invisible from tenant B's view.
    """
    new_client, switch = approval_mcp_client

    # Tenant A: full seed + create approval via the wrapper.
    switch.value = primary_tenant_key
    a_seed = await _seed_approval_context(db_session, primary_tenant_key)

    async with new_client() as session:
        a_result = await session.call_tool(
            "request_approval",
            {
                "job_id": a_seed["job"].job_id,
                "project_id": a_seed["project"].id,
                "reason": "tenant-A approval",
                "options": [{"id": "approve", "label": "Approve"}],
                "context": None,
            },
        )
    assert a_result.is_error is False, _error_text(a_result)
    a_approval_id = _payload(a_result)["approval_id"]

    # Tenant B: seed independent context so tenant B has its own job/project.
    await _seed_approval_context(db_session, secondary_tenant_key)

    # Tenant B switches active session and tries to request approval against
    # tenant A's job_id + project_id. Service must reject because the
    # AgentJob lookup filters by (tenant_key, job_id) and tenant B cannot
    # see tenant A's job.
    switch.value = secondary_tenant_key
    async with new_client() as session:
        cross_tenant_result = await session.call_tool(
            "request_approval",
            {
                "job_id": a_seed["job"].job_id,
                "project_id": a_seed["project"].id,
                "reason": "tenant-B trying to touch tenant-A job",
                "options": [{"id": "approve", "label": "Approve"}],
                "context": None,
            },
        )

    assert cross_tenant_result.is_error is True, (
        "TENANT LEAK: tenant B must not be able to create an approval against tenant A's job_id through the transport"
    )
    err = _error_text(cross_tenant_result)
    assert a_seed["job"].job_id in err or "AgentJob" in err or "not found" in err.lower(), (
        f"expected ResourceNotFoundError-style message, got: {err!r}"
    )

    # And the persisted tenant-A approval still belongs to tenant A only --
    # confirm by direct DB read scoped to tenant B finds nothing.
    rows_for_b = (
        (
            await db_session.execute(
                select(UserApproval).where(
                    UserApproval.id == a_approval_id,
                    UserApproval.tenant_key == secondary_tenant_key,
                )
            )
        )
        .scalars()
        .all()
    )
    assert rows_for_b == [], "TENANT LEAK: tenant A's approval row is visible under tenant B's tenant_key"


async def test_request_approval_worker_rejected_at_mcp_boundary(approval_mcp_client, db_session, primary_tenant_key):
    """BE-9054 (a) regression AT THE FAILING LAYER (the MCP transport):

    A worker job calling request_approval through the FastMCP transport gets the
    BE-6081 structured domain rejection as NORMAL tool content (isError False,
    success False, error=ORCHESTRATOR_ONLY_APPROVAL) — not an exception — and
    the worker is NOT parked in awaiting_user (no unreachable dead end: the
    dashboard's Approve/Reject card binds only to the orchestrator's job).
    """
    new_client, _switch = approval_mcp_client
    seed = await _seed_approval_context(db_session, primary_tenant_key, job_type="implementer")

    async with new_client() as session:
        result = await session.call_tool(
            "request_approval",
            {
                "job_id": seed["job"].job_id,
                "project_id": seed["project"].id,
                "reason": "worker asking through the transport",
                "options": [{"id": "approve", "label": "Approve"}],
                "context": None,
            },
        )

    assert result.is_error is False, (
        "BE-6081 Tier-2 contract: the worker rejection is a structured RESPONSE, not isError. " + _error_text(result)
    )
    payload = _payload(result)
    assert payload["success"] is False
    assert payload["error"] == "ORCHESTRATOR_ONLY_APPROVAL"
    assert payload["calling_agent_role"] == "implementer"
    assert "post_to_thread" in payload["message"]

    # No approval row persisted; the worker's status is untouched.
    rows = (
        (await db_session.execute(select(UserApproval).where(UserApproval.job_id == seed["job"].job_id)))
        .scalars()
        .all()
    )
    assert rows == [], "a rejected worker request must not persist a user_approvals row"

    execution = (
        await db_session.execute(select(AgentExecution).where(AgentExecution.id == seed["execution"].id))
    ).scalar_one()
    assert execution.status == "working", "rejected worker must not be flipped to awaiting_user"


# Suppress unused-import warning: random/datetime are kept for future
# parameterization; keep them imported so contributors don't re-add them.
_ = random
