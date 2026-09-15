# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import json
import random
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import select

from giljo_mcp.models.agent_identity import AgentExecution, AgentJob, AgentTodoItem
from giljo_mcp.models.organizations import Organization
from giljo_mcp.models.products import Product
from giljo_mcp.models.projects import Project
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


async def _seed_staging_context(
    db_session,
    tenant_key: str,
    *,
    project_phase: str = "staging",
    staging_status: str = "staging",
) -> dict:
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
        description="CE-0026 MCP boundary test",
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
        description="CE-0026 MCP transport boundary",
        mission="x",
        status="active",
        staging_status=staging_status,
        series_number=random.randint(1, 9000),
    )
    db_session.add(project)
    await db_session.flush()

    job = AgentJob(
        job_id=str(uuid4()),
        tenant_key=tenant_key,
        project_id=project.id,
        job_type="orchestrator",
        mission="CE-0026 staging orchestrator",
        status="active",
        created_at=datetime.now(UTC),
    )
    db_session.add(job)
    await db_session.flush()

    now = datetime.now(UTC)
    execution = AgentExecution(
        id=str(uuid4()),
        agent_id=str(uuid4()),
        job_id=job.job_id,
        tenant_key=tenant_key,
        agent_display_name="orchestrator",
        status="working",
        started_at=now - timedelta(minutes=3),
        project_phase=project_phase,
    )
    db_session.add(execution)
    await db_session.commit()
    return {
        "org": org,
        "product": product,
        "project": project,
        "job": job,
        "execution": execution,
    }


async def _add_todo(
    db_session,
    tenant_key: str,
    job_id: str,
    content: str,
    *,
    status: str = "in_progress",
    sequence: int = 0,
) -> None:
    db_session.add(
        AgentTodoItem(
            job_id=job_id,
            tenant_key=tenant_key,
            content=content,
            status=status,
            sequence=sequence,
        )
    )
    await db_session.commit()


async def _seed_message_sender(
    db_session,
    tenant_key: str,
    project_id: str,
) -> AgentExecution:
    job_id = str(uuid4())
    job = AgentJob(
        job_id=job_id,
        tenant_key=tenant_key,
        project_id=project_id,
        job_type="implementer",
        mission="send_message sender",
        status="active",
        created_at=datetime.now(UTC),
    )
    db_session.add(job)
    await db_session.flush()

    execution = AgentExecution(
        id=str(uuid4()),
        agent_id=str(uuid4()),
        job_id=job_id,
        tenant_key=tenant_key,
        agent_display_name="implementer",
        status="working",
        started_at=datetime.now(UTC),
        project_phase="implementation",
    )
    db_session.add(execution)
    await db_session.commit()
    return execution




@pytest_asyncio.fixture
async def phase_mcp_client(db_manager, db_session, monkeypatch):
    from api import app_state
    from api.endpoints import mcp_sdk_server
    from giljo_mcp.services.job_completion_service import JobCompletionService
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
    accessor._job_completion_service = JobCompletionService(
        db_manager=db_manager,
        tenant_manager=state.tenant_manager,
        test_session=db_session,
    )

    state.tool_accessor = accessor

    from api.endpoints.mcp_tools import _base

    monkeypatch.setattr(_base, "_resolve_tenant", lambda ctx: tenant_key)
    monkeypatch.setattr(_base, "_resolve_user_id", lambda ctx: None)

    def _new_client():
        return create_connected_server_and_client_session(mcp_sdk_server.mcp)

    try:
        yield _new_client, tenant_key, db_session
    finally:
        state.tool_accessor = prior_tool_accessor
        state.tenant_manager = prior_tenant_manager
        state.db_manager = prior_db_manager




async def test_staging_end_via_mcp_returns_stop_directive_and_flips_db(
    phase_mcp_client,
    db_session,
):
    new_client, tenant_key, session = phase_mcp_client
    seed = await _seed_staging_context(
        session,
        tenant_key,
        project_phase="staging",
        staging_status="staging",
    )
    await _seed_message_sender(session, tenant_key, seed["project"].id)

    async with new_client() as mcp_session:
        result = await mcp_session.call_tool(
            "complete_job",
            {
                "job_id": seed["job"].job_id,
                "result": {"summary": "CE-0026 staging session complete"},
            },
        )

    assert result.is_error is False, f"CE-0026: staging-end complete_job must succeed; got error: {_error_text(result)}"
    payload = _payload(result)

    assert "staging_directive" in payload, (
        f"CE-0026: response must contain 'staging_directive' key; keys: {list(payload)}"
    )
    directive = payload["staging_directive"]
    assert directive is not None, "CE-0026: staging_directive must not be null for staging-end"
    assert directive.get("action") == "STOP", (
        f"CE-0026: staging_directive.action must be 'STOP', got {directive.get('action')!r}"
    )
    assert directive.get("status") == "STAGING_SESSION_COMPLETE", (
        f"CE-0026: staging_directive.status must be 'STAGING_SESSION_COMPLETE', got {directive.get('status')!r}"
    )

    refreshed_project = (
        await session.execute(
            select(Project).where(
                Project.id == seed["project"].id,
                Project.tenant_key == tenant_key,
            )
        )
    ).scalar_one()
    assert refreshed_project.staging_status == "staging_complete", (
        f"CE-0026: project.staging_status must be 'staging_complete' after MCP staging-end, "
        f"got {refreshed_project.staging_status!r}"
    )


async def test_implementation_end_via_mcp_no_staging_directive(
    phase_mcp_client,
    db_session,
):
    new_client, tenant_key, session = phase_mcp_client
    seed = await _seed_staging_context(
        session,
        tenant_key,
        project_phase="implementation",
        staging_status="staging_complete",
    )

    async with new_client() as mcp_session:
        result = await mcp_session.call_tool(
            "complete_job",
            {
                "job_id": seed["job"].job_id,
                "result": {"summary": "CE-0026 implementation session complete"},
            },
        )

    assert result.is_error is False, (
        f"CE-0026: implementation-end complete_job must succeed; got: {_error_text(result)}"
    )
    payload = _payload(result)

    directive = payload.get("staging_directive")
    assert directive is None, (
        f"CE-0026: implementation-phase complete_job must NOT return a staging_directive; got {directive!r}"
    )






async def test_be6083_staging_end_response_self_explains(phase_mcp_client, db_session):
    new_client, tenant_key, session = phase_mcp_client
    seed = await _seed_staging_context(
        session,
        tenant_key,
        project_phase="staging",
        staging_status="staging",
    )
    await _seed_message_sender(session, tenant_key, seed["project"].id)

    async with new_client() as mcp_session:
        result = await mcp_session.call_tool(
            "complete_job",
            {
                "job_id": seed["job"].job_id,
                "result": {"summary": "BE-6083 staging done"},
            },
        )

    assert result.is_error is False, f"BE-6083 staging-end must succeed; got: {_error_text(result)}"
    payload = _payload(result)
    assert payload.get("phase") == "staging_end", f"expected phase='staging_end', got {payload.get('phase')!r}"
    assert "Staging marked complete" in payload.get("message", ""), f"unexpected message: {payload.get('message')!r}"
    next_action = payload.get("next_action") or {}
    assert "Implement" in next_action.get("why", ""), (
        f"staging_end next_action must point at the Implement gate; got {next_action!r}"
    )


async def test_be6083_closeout_response_self_explains(phase_mcp_client, db_session):
    new_client, tenant_key, session = phase_mcp_client
    seed = await _seed_staging_context(
        session,
        tenant_key,
        project_phase="implementation",
        staging_status="staging_complete",
    )

    async with new_client() as mcp_session:
        result = await mcp_session.call_tool(
            "complete_job",
            {
                "job_id": seed["job"].job_id,
                "result": {"summary": "BE-6083 closeout"},
            },
        )

    assert result.is_error is False, f"BE-6083 closeout must succeed; got: {_error_text(result)}"
    payload = _payload(result)
    assert payload.get("phase") == "closeout", f"expected phase='closeout', got {payload.get('phase')!r}"
    assert payload.get("staging_directive") is None, "closeout must not carry a staging_directive"
    next_action = payload.get("next_action") or {}
    assert next_action.get("tool") == "write_project_closeout", (
        f"closeout next_action must point at write_project_closeout; got {next_action!r}"
    )


async def test_be6083_deliverable_response_self_explains(phase_mcp_client, db_session):
    new_client, tenant_key, session = phase_mcp_client
    seed = await _seed_staging_context(
        session,
        tenant_key,
        project_phase="staging",
        staging_status="staging",
    )
    worker = await _seed_message_sender(session, tenant_key, seed["project"].id)

    async with new_client() as mcp_session:
        result = await mcp_session.call_tool(
            "complete_job",
            {
                "job_id": worker.job_id,
                "result": {"summary": "BE-6083 deliverable done"},
            },
        )

    assert result.is_error is False, f"BE-6083 deliverable must succeed; got: {_error_text(result)}"
    payload = _payload(result)
    assert payload.get("phase") == "deliverable", f"expected phase='deliverable', got {payload.get('phase')!r}"
    assert payload.get("staging_directive") is None, "deliverable must not carry a staging_directive"
    assert "Deliverable recorded" in payload.get("message", ""), f"unexpected message: {payload.get('message')!r}"


async def test_be6083_closeout_auto_acks_without_flag(phase_mcp_client, db_session):
    new_client, tenant_key, session = phase_mcp_client
    seed = await _seed_staging_context(
        session,
        tenant_key,
        project_phase="implementation",
        staging_status="staging_complete",
    )
    await _add_todo(
        session,
        tenant_key,
        seed["job"].job_id,
        "Closeout: call complete_job for orchestrator job",
        status="in_progress",
    )

    async with new_client() as mcp_session:
        result = await mcp_session.call_tool(
            "complete_job",
            {
                "job_id": seed["job"].job_id,
                "result": {"summary": "BE-6083 closeout no-flag"},
            },
        )

    assert result.is_error is False, (
        f"BE-6083 closeout must auto-ack and succeed without the flag; got: {_error_text(result)}"
    )
    payload = _payload(result)
    assert payload.get("phase") == "closeout"

    todo = (
        await session.execute(
            select(AgentTodoItem).where(
                AgentTodoItem.job_id == seed["job"].job_id,
                AgentTodoItem.tenant_key == tenant_key,
            )
        )
    ).scalar_one()
    assert todo.status == "completed", (
        f"BE-6083: closeout TODO must auto-complete in closeout phase; got status {todo.status!r}"
    )


async def test_be6083_closeout_back_compat_with_flag(phase_mcp_client, db_session):
    new_client, tenant_key, session = phase_mcp_client
    seed = await _seed_staging_context(
        session,
        tenant_key,
        project_phase="implementation",
        staging_status="staging_complete",
    )
    await _add_todo(
        session,
        tenant_key,
        seed["job"].job_id,
        "Closeout: complete_job + close_project_and_update_memory",
        status="in_progress",
    )

    async with new_client() as mcp_session:
        result = await mcp_session.call_tool(
            "complete_job",
            {
                "job_id": seed["job"].job_id,
                "result": {"summary": "BE-6083 closeout with flag"},
                "acknowledge_closeout_todo": True,
            },
        )

    assert result.is_error is False, (
        f"BE-6083 back-compat: complete_job with acknowledge_closeout_todo=True must still succeed; "
        f"got: {_error_text(result)}"
    )
    payload = _payload(result)
    assert payload.get("phase") == "closeout"

    todo = (
        await session.execute(
            select(AgentTodoItem).where(
                AgentTodoItem.job_id == seed["job"].job_id,
                AgentTodoItem.tenant_key == tenant_key,
            )
        )
    ).scalar_one()
    assert todo.status == "completed"
