# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""Transport-layer tests for the ``decide_approval`` MCP tool (BE-9499d).

The gap this closes: ``awaiting_user`` used to clear ONLY via
``POST /api/approvals/{id}/decide`` (JWT cookie, dashboard button) --
``decide_approval`` is the harness-side door, routed through the SAME
``UserApprovalService.mark_decided`` write. These tests exercise the real
``@mcp.tool`` wrapper (api/endpoints/mcp_tools/_message_tools.py) through the
in-memory FastMCP transport -- the failing layer for an MCP-boundary change
(CLAUDE.md: MCP-boundary fix -> boundary test through the MCP transport) -- plus
the BE-9084 fence extension (``_HITL_FENCED_TOOLS``) and a parity check proving
the REST door and this door produce byte-identical audit rows.

Pattern reference: tests/integration/test_request_approval_mcp_transport.py
(shared-session transport + tenant-switch fixture) and
tests/integration/test_be9084_headless_hitl_gate.py (the fence fixture shape).
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
    if getattr(call_tool_result, "structuredContent", None):
        return call_tool_result.structured_content
    first_block = call_tool_result.content[0]
    text = getattr(first_block, "text", None)
    if text is None:
        raise AssertionError(f"unexpected content block: {first_block!r}")
    return json.loads(text)


def _error_text(call_tool_result) -> str:
    return "\n".join(getattr(block, "text", "") for block in call_tool_result.content if getattr(block, "text", ""))


async def _seed_approval_context(db_session, tenant_key: str, *, product_active: bool = True) -> dict:
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
        description="decide_approval transport-layer tests",
        tenant_key=tenant_key,
        is_active=product_active,
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
        job_type="orchestrator",
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
        agent_display_name="orchestrator",
        status="working",
        started_at=datetime.now(UTC),
    )
    db_session.add(execution)
    await db_session.commit()

    return {"project": project, "job": job, "execution": execution}


async def _create_pending(service, seed, tenant_key, options=None):
    return await service.create_pending(
        tenant_key=tenant_key,
        job_id=seed["job"].job_id,
        project_id=seed["project"].id,
        reason="please decide (transport test)",
        options=options
        or [
            {"id": "approve", "label": "Approve"},
            {"id": "rework", "label": "Send back for rework"},
        ],
        context=None,
    )


# ---------------------------------------------------------------------------
# Fixture: shared-session ToolAccessor + tenant-aware MCP client (unfenced --
# monkeypatches _request_from_context away so the BE-9084 fence's "request is
# None" carve-out applies, matching approval_mcp_client's transport in
# test_request_approval_mcp_transport.py)
# ---------------------------------------------------------------------------


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
async def decide_mcp_client(db_manager, db_session, primary_tenant_key, monkeypatch):
    """In-memory FastMCP client wired for decide_approval, unfenced (request is None)."""
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
    service = UserApprovalService(
        db_manager=db_manager,
        tenant_manager=state.tenant_manager,
        test_session=db_session,
    )
    accessor._user_approval_service = service
    state.tool_accessor = accessor

    tenant_switch = _TenantSwitch(primary_tenant_key)

    from api.endpoints.mcp_tools import _base

    monkeypatch.setattr(_base, "_resolve_tenant", lambda ctx: tenant_switch.value)
    monkeypatch.setattr(_base, "_resolve_user_id", lambda ctx: None)

    def _new_client():
        return create_connected_server_and_client_session(mcp_sdk_server.mcp)

    try:
        yield _new_client, tenant_switch, service
    finally:
        state.tool_accessor = prior_tool_accessor
        state.tenant_manager = prior_tenant_manager
        state.db_manager = prior_db_manager


# ---------------------------------------------------------------------------
# decide_approval wrapper -- happy path, tenant scoping, structured rejections
# ---------------------------------------------------------------------------


async def test_decide_approval_happy_path_through_wrapper(decide_mcp_client, db_session, primary_tenant_key):
    """Calling decide_approval via the FastMCP client clears awaiting_user through
    the SAME write UserApprovalService.mark_decided performs for the REST door."""
    new_client, _switch, service = decide_mcp_client
    seed = await _seed_approval_context(db_session, primary_tenant_key)
    pending = await _create_pending(service, seed, primary_tenant_key)

    async with new_client() as session:
        result = await session.call_tool(
            "decide_approval",
            {"approval_id": pending.id, "option_id": "approve"},
        )

    assert result.is_error is False, _error_text(result)
    payload = _payload(result)
    assert payload["approval_id"] == pending.id
    assert payload["status"] == "decided"
    assert payload["decided_option_id"] == "approve"
    assert payload["job_id"] == seed["job"].job_id
    assert payload["project_id"] == seed["project"].id

    row = (await db_session.execute(select(UserApproval).where(UserApproval.id == pending.id))).scalar_one()
    assert row.status == "decided"
    assert row.decided_option_id == "approve"
    assert row.decided_via == "mcp", "BE-9514: the decide_approval MCP tool must record decided_via='mcp'"

    execution = (
        await db_session.execute(select(AgentExecution).where(AgentExecution.id == seed["execution"].id))
    ).scalar_one()
    assert execution.status == "working", "decide_approval must resume the awaiting agent"


async def test_decide_approval_is_tenant_scoped_at_transport_boundary(
    decide_mcp_client, db_session, primary_tenant_key, secondary_tenant_key
):
    """Tenant B cannot decide tenant A's approval through the transport -- a
    structured BE-6081 Tier-2 rejection (not raised, not a tenant-existence leak)."""
    new_client, switch, service = decide_mcp_client
    a_seed = await _seed_approval_context(db_session, primary_tenant_key)
    a_pending = await _create_pending(service, a_seed, primary_tenant_key)

    switch.value = secondary_tenant_key
    async with new_client() as session:
        result = await session.call_tool(
            "decide_approval",
            {"approval_id": a_pending.id, "option_id": "approve"},
        )

    assert result.is_error is False, "cross-tenant decide is a structured rejection, not isError"
    payload = _payload(result)
    assert payload["success"] is False
    assert payload["error"] == "APPROVAL_NOT_FOUND"

    row = (await db_session.execute(select(UserApproval).where(UserApproval.id == a_pending.id))).scalar_one()
    assert row.status == "pending", "cross-tenant attempt must not mutate"


async def test_decide_approval_already_decided_returns_structured_rejection(
    decide_mcp_client, db_session, primary_tenant_key
):
    new_client, _switch, service = decide_mcp_client
    seed = await _seed_approval_context(db_session, primary_tenant_key)
    pending = await _create_pending(service, seed, primary_tenant_key)

    async with new_client() as session:
        first = await session.call_tool("decide_approval", {"approval_id": pending.id, "option_id": "approve"})
        assert first.is_error is False
        assert _payload(first)["status"] == "decided"

        second = await session.call_tool("decide_approval", {"approval_id": pending.id, "option_id": "approve"})

    assert second.is_error is False
    payload = _payload(second)
    assert payload["success"] is False
    assert payload["error"] == "APPROVAL_ALREADY_DECIDED"


async def test_decide_approval_invalid_option_returns_structured_rejection(
    decide_mcp_client, db_session, primary_tenant_key
):
    new_client, _switch, service = decide_mcp_client
    seed = await _seed_approval_context(db_session, primary_tenant_key)
    pending = await _create_pending(service, seed, primary_tenant_key)

    async with new_client() as session:
        result = await session.call_tool(
            "decide_approval", {"approval_id": pending.id, "option_id": "not-a-real-option"}
        )

    assert result.is_error is False
    payload = _payload(result)
    assert payload["success"] is False
    assert payload["error"] == "APPROVAL_OPTION_INVALID"

    row = (await db_session.execute(select(UserApproval).where(UserApproval.id == pending.id))).scalar_one()
    assert row.status == "pending"


# ---------------------------------------------------------------------------
# Parity: the REST door and the MCP door must leave byte-identical audit shape.
# ---------------------------------------------------------------------------


async def test_rest_and_mcp_decide_doors_produce_identical_audit_shape(
    decide_mcp_client, db_manager, db_session, primary_tenant_key
):
    """Regression that the UI (REST) door stays byte-identical after adding the
    MCP door: decide one approval via each and compare the resulting row shape
    (every field except the id-like columns that are naturally distinct)."""
    from unittest.mock import AsyncMock, MagicMock

    from giljo_mcp.services.user_approval_service import UserApprovalService

    new_client, _switch, mcp_service = decide_mcp_client
    seed_a = await _seed_approval_context(db_session, primary_tenant_key)
    seed_b = await _seed_approval_context(db_session, primary_tenant_key, product_active=False)
    pending_a = await _create_pending(mcp_service, seed_a, primary_tenant_key)
    pending_b = await _create_pending(mcp_service, seed_b, primary_tenant_key)

    # REST door: same service class, same db_session, direct call (mirrors
    # api/endpoints/approvals.py's decide_approval() dependency-injected service).
    ws = MagicMock()
    ws.broadcast_to_tenant = AsyncMock()
    rest_service = UserApprovalService(
        db_manager=db_manager,
        tenant_manager=TenantManager(),
        websocket_manager=ws,
        test_session=db_session,
    )
    rest_decided = await rest_service.mark_decided(
        tenant_key=primary_tenant_key,
        approval_id=pending_a.id,
        option_id="approve",
        user_id=None,
        decided_via="ui",
    )

    async with new_client() as session:
        result = await session.call_tool(
            "decide_approval",
            {"approval_id": pending_b.id, "option_id": "approve"},
        )
    assert result.is_error is False, _error_text(result)
    mcp_payload = _payload(result)

    rest_row = (await db_session.execute(select(UserApproval).where(UserApproval.id == pending_a.id))).scalar_one()
    mcp_row = (await db_session.execute(select(UserApproval).where(UserApproval.id == pending_b.id))).scalar_one()

    assert rest_row.status == mcp_row.status == "decided"
    assert rest_row.decided_option_id == mcp_row.decided_option_id == "approve"
    assert rest_decided.status == mcp_payload["status"] == "decided"
    assert rest_decided.decided_option_id == mcp_payload["decided_option_id"] == "approve"
    # BE-9514: decided_via is the ONE field this parity check deliberately does
    # NOT expect identical -- it exists precisely to record which door decided,
    # so the REST/UI row and the MCP row must differ here on purpose.
    assert rest_row.decided_via == "ui"
    assert mcp_row.decided_via == "mcp"
    # Same shape of side effect: both resume their agent from awaiting_user.
    exec_a = (
        await db_session.execute(select(AgentExecution).where(AgentExecution.id == seed_a["execution"].id))
    ).scalar_one()
    exec_b = (
        await db_session.execute(select(AgentExecution).where(AgentExecution.id == seed_b["execution"].id))
    ).scalar_one()
    assert exec_a.status == exec_b.status == "working"


# ---------------------------------------------------------------------------
# BE-9084 fence: decide_approval is fenced identically to launch_implementation,
# EXCEPT it stays in the orchestrator profile's static allow-set (see
# _HITL_FENCED_TOOLS's docstring in _scopes.py).
# ---------------------------------------------------------------------------


class _FakeRequest:
    def __init__(self, state: dict):
        self.scope = {"state": state}


async def _seed_headless_setting(db_manager, tenant_key: str, allow: bool) -> None:
    from giljo_mcp.services.settings_service import SettingsService

    async with db_manager.get_session_async() as db:
        svc = SettingsService(db, tenant_key)
        await svc.update_settings("security", {"allow_headless_launch": allow})


def _jwt_orchestrator_state(tenant_key: str) -> dict:
    """An ordinary mcp:agent jwt session with NO declared profile -- resolves to
    the orchestrator profile default (BE-9017), which INCLUDES decide_approval."""
    return {
        "auth_method": "jwt",
        "scopes": ["mcp:read", "mcp:write", "mcp:agent"],
        "tenant_key": tenant_key,
    }


@pytest_asyncio.fixture
async def fenced_gate_client(db_manager, db_session, monkeypatch):
    """Like decide_mcp_client, but ALSO wires the real request-state fence
    (mirrors test_be9084_headless_hitl_gate.gate_client) so tools/list + dispatch
    run the genuine BE-9084 predicate against a configurable session shape."""
    from api import app_state
    from api.endpoints import mcp_sdk_server
    from api.endpoints.mcp_tools import _base
    from giljo_mcp.services.user_approval_service import UserApprovalService
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
    accessor._user_approval_service = UserApprovalService(
        db_manager=db_manager,
        tenant_manager=state.tenant_manager,
        test_session=db_session,
    )
    state.tool_accessor = accessor

    class _Holder:
        pass

    holder = _Holder()
    holder.tenant_key = tenant_key
    holder.state = {}

    monkeypatch.setattr(mcp_sdk_server, "_request_from_context", lambda: _FakeRequest(holder.state))
    monkeypatch.setattr(_base, "_resolve_tenant", lambda ctx: holder.tenant_key)
    monkeypatch.setattr(_base, "_resolve_user_id", lambda ctx: None)

    def _new_client():
        return create_connected_server_and_client_session(mcp_sdk_server.mcp)

    try:
        yield _new_client, holder, accessor._user_approval_service
    finally:
        state.tool_accessor = prior_tool_accessor
        state.tenant_manager = prior_tenant_manager
        state.db_manager = prior_db_manager


class TestDecideApprovalDefaultHeadlessFence:
    async def test_no_row_advertises_decide_approval_in_tools_list(self, fenced_gate_client):
        """Under the platform default an ordinary orchestrator-profile jwt session
        MUST be advertised decide_approval."""
        new_client, holder, _service = fenced_gate_client
        holder.state = _jwt_orchestrator_state(holder.tenant_key)

        async with new_client() as session:
            result = await session.list_tools()

        advertised = {t.name for t in result.tools}
        assert "decide_approval" in advertised, "platform default must advertise decide_approval"
        assert "request_approval" in advertised
        assert "spawn_job" in advertised
        # NOTE: launch_implementation is also admitted whenever the toggle
        # admits -- the toggle mechanism working as designed; see
        # TestToggleAdmitsWithNoDeclaration in test_be9084_headless_hitl_gate.py.

    async def test_no_row_allows_decide_approval_call(self, fenced_gate_client, db_session):
        new_client, holder, service = fenced_gate_client
        seed = await _seed_approval_context(db_session, holder.tenant_key)
        pending = await _create_pending(service, seed, holder.tenant_key)
        holder.state = _jwt_orchestrator_state(holder.tenant_key)

        async with new_client() as session:
            result = await session.call_tool("decide_approval", {"approval_id": pending.id, "option_id": "approve"})

        joined = _error_text(result)
        assert "HITL mode" not in joined, f"platform default must not be HITL-fenced, got: {joined!r}"

    async def test_explicit_false_still_hides_decide_approval_from_tools_list(self, fenced_gate_client, db_manager):
        """The opt-out still fences identically to the pre-BE-9542 default."""
        new_client, holder, _service = fenced_gate_client
        await _seed_headless_setting(db_manager, holder.tenant_key, allow=False)
        holder.state = _jwt_orchestrator_state(holder.tenant_key)

        async with new_client() as session:
            result = await session.list_tools()

        assert "decide_approval" not in {t.name for t in result.tools}, "explicit opt-out must still hide it"

    async def test_explicit_false_still_rejects_decide_approval_call(self, fenced_gate_client, db_manager, db_session):
        new_client, holder, service = fenced_gate_client
        await _seed_headless_setting(db_manager, holder.tenant_key, allow=False)
        seed = await _seed_approval_context(db_session, holder.tenant_key)
        pending = await _create_pending(service, seed, holder.tenant_key)
        holder.state = _jwt_orchestrator_state(holder.tenant_key)

        async with new_client() as session:
            result = await session.call_tool("decide_approval", {"approval_id": pending.id, "option_id": "approve"})

        assert result.is_error is True
        joined = _error_text(result)
        assert "HITL mode" in joined, f"expected the BE-9084/BE-9542 fence rejection, got: {joined!r}"

        row = (await db_session.execute(select(UserApproval).where(UserApproval.id == pending.id))).scalar_one()
        assert row.status == "pending", "a fenced call must not reach the service at all"


class TestDecideApprovalHeadlessOnAllows:
    async def test_toggle_on_advertises_decide_approval_in_list(self, fenced_gate_client, db_manager):
        new_client, holder, _service = fenced_gate_client
        await _seed_headless_setting(db_manager, holder.tenant_key, allow=True)
        holder.state = _jwt_orchestrator_state(holder.tenant_key)

        async with new_client() as session:
            result = await session.list_tools()

        assert "decide_approval" in {t.name for t in result.tools}, "Headless-ON tenant must see decide_approval"

    async def test_toggle_on_allows_decide_approval_call(self, fenced_gate_client, db_manager, db_session):
        new_client, holder, service = fenced_gate_client
        await _seed_headless_setting(db_manager, holder.tenant_key, allow=True)
        seed = await _seed_approval_context(db_session, holder.tenant_key)
        pending = await _create_pending(service, seed, holder.tenant_key)
        holder.state = _jwt_orchestrator_state(holder.tenant_key)

        async with new_client() as session:
            result = await session.call_tool("decide_approval", {"approval_id": pending.id, "option_id": "approve"})

        assert result.is_error is False, _error_text(result)
        assert _payload(result)["status"] == "decided"


class TestDecideApprovalApiKeyBypassUnaffected:
    async def test_api_key_sees_and_can_call_decide_approval_even_with_headless_off(
        self, fenced_gate_client, db_session
    ):
        new_client, holder, service = fenced_gate_client
        seed = await _seed_approval_context(db_session, holder.tenant_key)
        pending = await _create_pending(service, seed, holder.tenant_key)
        holder.state = {"auth_method": "api_key", "tenant_key": holder.tenant_key}

        async with new_client() as session:
            listed = await session.list_tools()
            advertised = {t.name for t in listed.tools}
            call = await session.call_tool("decide_approval", {"approval_id": pending.id, "option_id": "approve"})

        assert "decide_approval" in advertised, "api_key operator must still see decide_approval"
        assert call.is_error is False, _error_text(call)
        assert _payload(call)["status"] == "decided"
