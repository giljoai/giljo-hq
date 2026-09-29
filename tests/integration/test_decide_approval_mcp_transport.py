# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


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




async def test_decide_approval_happy_path_through_wrapper(decide_mcp_client, db_session, primary_tenant_key):
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




async def test_rest_and_mcp_decide_doors_produce_identical_audit_shape(
    decide_mcp_client, db_manager, db_session, primary_tenant_key
):
    from unittest.mock import AsyncMock, MagicMock

    from giljo_mcp.services.user_approval_service import UserApprovalService

    new_client, _switch, mcp_service = decide_mcp_client
    seed_a = await _seed_approval_context(db_session, primary_tenant_key)
    seed_b = await _seed_approval_context(db_session, primary_tenant_key, product_active=False)
    pending_a = await _create_pending(mcp_service, seed_a, primary_tenant_key)
    pending_b = await _create_pending(mcp_service, seed_b, primary_tenant_key)

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
    assert rest_row.decided_via == "ui"
    assert mcp_row.decided_via == "mcp"
    exec_a = (
        await db_session.execute(select(AgentExecution).where(AgentExecution.id == seed_a["execution"].id))
    ).scalar_one()
    exec_b = (
        await db_session.execute(select(AgentExecution).where(AgentExecution.id == seed_b["execution"].id))
    ).scalar_one()
    assert exec_a.status == exec_b.status == "working"




class _FakeRequest:
    def __init__(self, state: dict):
        self.scope = {"state": state}


async def _seed_headless_setting(db_manager, tenant_key: str, allow: bool) -> None:
    from giljo_mcp.services.settings_service import SettingsService

    async with db_manager.get_session_async() as db:
        svc = SettingsService(db, tenant_key)
        await svc.update_settings("security", {"allow_headless_launch": allow})


def _jwt_orchestrator_state(tenant_key: str) -> dict:
    return {
        "auth_method": "jwt",
        "scopes": ["mcp:read", "mcp:write", "mcp:agent"],
        "tenant_key": tenant_key,
    }


@pytest_asyncio.fixture
async def fenced_gate_client(db_manager, db_session, monkeypatch):
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
    async def test_no_row_hides_decide_approval_from_tools_list(self, fenced_gate_client):
        new_client, holder, _service = fenced_gate_client
        holder.state = _jwt_orchestrator_state(holder.tenant_key)

        async with new_client() as session:
            result = await session.list_tools()

        advertised = {t.name for t in result.tools}
        assert "decide_approval" not in advertised, "unset tenant must default to HITL (hidden)"
        assert "request_approval" in advertised
        assert "spawn_job" in advertised

    async def test_no_row_blocks_decide_approval_call(self, fenced_gate_client, db_session):
        new_client, holder, service = fenced_gate_client
        seed = await _seed_approval_context(db_session, holder.tenant_key)
        pending = await _create_pending(service, seed, holder.tenant_key)
        holder.state = _jwt_orchestrator_state(holder.tenant_key)

        async with new_client() as session:
            result = await session.call_tool("decide_approval", {"approval_id": pending.id, "option_id": "approve"})

        joined = _error_text(result)
        assert "HITL mode" in joined, f"unset tenant must be HITL-fenced, got: {joined!r}"

    async def test_explicit_false_still_hides_decide_approval_from_tools_list(self, fenced_gate_client, db_manager):
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
