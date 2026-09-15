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
    parts = []
    for block in call_tool_result.content:
        text = getattr(block, "text", None)
        if text:
            parts.append(text)
    return "\n".join(parts)


async def _seed_approval_context(db_session, tenant_key: str, job_type: str = "orchestrator") -> dict:
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
async def approval_mcp_client(db_manager, db_session, primary_tenant_key, monkeypatch):
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




async def test_request_approval_happy_path_through_wrapper(approval_mcp_client, db_session, primary_tenant_key):
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
    new_client, switch = approval_mcp_client

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

    await _seed_approval_context(db_session, secondary_tenant_key)

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


_ = random
