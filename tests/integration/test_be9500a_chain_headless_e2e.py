# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy import select

from giljo_mcp.models.agent_identity import AgentExecution, AgentJob
from giljo_mcp.models.organizations import Organization
from giljo_mcp.models.products import Product
from giljo_mcp.models.projects import Project
from giljo_mcp.services.project_helpers import complete_chain_run_if_finished
from giljo_mcp.services.sequence_run_service import SequenceRunService
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


async def _seed_product_context(db_session, tenant_key: str) -> None:
    suffix = uuid.uuid4().hex[:8]
    org = Organization(name=f"Org {suffix}", slug=f"org-{suffix}", tenant_key=tenant_key, is_active=True)
    db_session.add(org)
    await db_session.flush()
    product = Product(
        id=str(uuid.uuid4()),
        name=f"Product {suffix}",
        description="be-9500a e2e",
        tenant_key=tenant_key,
        is_active=True,
    )
    db_session.add(product)
    await db_session.flush()


async def _seed_project(db_session, tenant_key: str) -> str:
    suffix = uuid.uuid4().hex[:8]
    owning_product = Product(
        id=str(uuid.uuid4()),
        tenant_key=tenant_key,
        name=f"Owning Product {uuid.uuid4().hex[:6]}",
        description="seeded",
        is_active=False,
    )
    db_session.add(owning_product)
    project = Project(
        id=str(uuid.uuid4()),
        tenant_key=tenant_key,
        product_id=owning_product.id,
        name=f"BE-9500a {suffix}",
        description="chain member",
        mission="build it",
        status="active",
        series_number=uuid.uuid4().int % 9000 + 1,
        execution_mode="claude_code_cli",
        created_at=datetime.now(UTC),
    )
    db_session.add(project)
    await db_session.flush()
    return project.id


async def _seed_staging_orchestrator(db_session, tenant_key: str, project_id: str) -> AgentJob:
    job = AgentJob(
        job_id=str(uuid.uuid4()),
        tenant_key=tenant_key,
        project_id=project_id,
        job_type="orchestrator",
        mission="BE-9500a chain sub-orchestrator",
        status="active",
        created_at=datetime.now(UTC),
    )
    db_session.add(job)
    await db_session.flush()

    execution = AgentExecution(
        id=str(uuid.uuid4()),
        agent_id=str(uuid.uuid4()),
        job_id=job.job_id,
        tenant_key=tenant_key,
        agent_display_name="orchestrator",
        status="working",
        started_at=datetime.now(UTC) - timedelta(minutes=1),
        project_phase="staging",
    )
    db_session.add(execution)
    await db_session.flush()
    return job


async def _seed_spawned_specialist(db_session, tenant_key: str, project_id: str) -> None:
    job_id = str(uuid.uuid4())
    job = AgentJob(
        job_id=job_id,
        tenant_key=tenant_key,
        project_id=project_id,
        job_type="implementer",
        mission="BE-9500a specialist",
        status="active",
        created_at=datetime.now(UTC),
    )
    db_session.add(job)
    await db_session.flush()

    execution = AgentExecution(
        id=str(uuid.uuid4()),
        agent_id=str(uuid.uuid4()),
        job_id=job_id,
        tenant_key=tenant_key,
        agent_display_name="implementer",
        status="working",
        started_at=datetime.now(UTC),
        project_phase="implementation",
    )
    db_session.add(execution)
    await db_session.flush()




@pytest_asyncio.fixture
async def primary_tenant_key() -> str:
    return TenantManager.generate_tenant_key()


class _TenantSwitch:
    def __init__(self, value: str):
        self.value = value


@pytest_asyncio.fixture
async def chain_mcp_client(db_manager, db_session, primary_tenant_key, monkeypatch):
    from api import app_state
    from api.endpoints import mcp_sdk_server
    from giljo_mcp.tools.tool_accessor import ToolAccessor

    state = app_state.state
    prior_tool_accessor = state.tool_accessor
    prior_tenant_manager = state.tenant_manager
    prior_db_manager = state.db_manager

    if state.tenant_manager is None:
        state.tenant_manager = TenantManager()
    state.db_manager = db_manager

    accessor = ToolAccessor(
        db_manager=db_manager,
        tenant_manager=state.tenant_manager,
        test_session=db_session,
    )
    state.tool_accessor = accessor

    tenant_switch = _TenantSwitch(primary_tenant_key)

    from api.endpoints.mcp_tools import _base

    monkeypatch.setattr(_base, "_resolve_tenant", lambda ctx: tenant_switch.value)
    monkeypatch.setattr(_base, "_resolve_user_id", lambda ctx: None)

    def _new_client():
        return create_connected_server_and_client_session(mcp_sdk_server.mcp)

    try:
        yield _new_client, tenant_switch
    finally:
        state.tool_accessor = prior_tool_accessor
        state.tenant_manager = prior_tenant_manager
        state.db_manager = prior_db_manager




async def test_headless_chain_drives_start_to_finish(chain_mcp_client, db_session, primary_tenant_key):
    new_client, _switch = chain_mcp_client
    tenant_key = primary_tenant_key
    await _seed_product_context(db_session, tenant_key)
    p1 = await _seed_project(db_session, tenant_key)
    p2 = await _seed_project(db_session, tenant_key)
    await db_session.commit()

    async with new_client() as session:
        result = await session.call_tool(
            "link_projects",
            {"project_ids": [p1, p2], "execution_mode": "claude_code_cli"},
        )
        assert result.is_error is False, _error_text(result)
        start_payload = _payload(result)

    assert start_payload["success"] is True
    run_id = start_payload["run_id"]
    conductor_agent_id = start_payload["conductor_agent_id"]
    assert start_payload["run"]["resolved_order"] == [p1, p2]

    job1 = await _seed_staging_orchestrator(db_session, tenant_key, p1)
    await _seed_spawned_specialist(db_session, tenant_key, p1)
    await db_session.commit()

    async with new_client() as session:
        result = await session.call_tool(
            "complete_job",
            {"job_id": job1.job_id, "result": {"summary": "member 1 staging complete"}},
        )
        assert result.is_error is False, _error_text(result)
        member1_payload = _payload(result)

    directive1 = member1_payload["staging_directive"]
    assert directive1["action"] == "CONTINUE", (
        f"a chain member's staging-end must poll-and-continue, not stop for a human Implement click; got {directive1}"
    )

    refreshed_p1 = (
        await db_session.execute(select(Project).where(Project.id == p1, Project.tenant_key == tenant_key))
    ).scalar_one()
    assert refreshed_p1.implementation_launched_at is not None, (
        "§14 gateless flow: member 1's OWN staging-end must stamp implementation_launched_at "
        "-- there is no per-project launch_implementation gate to cross"
    )

    run_svc = SequenceRunService(db_manager=None, tenant_manager=None, session=db_session)
    run_after_m1 = await run_svc.find_active_run_for_project(project_id=p1, tenant_key=tenant_key)
    assert run_after_m1["status"] == "running"
    assert run_after_m1["project_statuses"].get(p1) == "planning"
    assert run_after_m1["current_index"] == 0, "head project advance is index-0 -> stays 0"

    job2 = await _seed_staging_orchestrator(db_session, tenant_key, p2)
    await _seed_spawned_specialist(db_session, tenant_key, p2)
    await db_session.commit()

    async with new_client() as session:
        result = await session.call_tool(
            "complete_job",
            {"job_id": job2.job_id, "result": {"summary": "member 2 staging complete"}},
        )
        assert result.is_error is False, _error_text(result)

    run_held = await run_svc.find_active_run_for_project(project_id=p2, tenant_key=tenant_key)
    assert run_held["project_statuses"].get(p2) == "planning"
    assert run_held["current_index"] == 0, (
        "forward-only advance must HOLD at member 2 until member 1's closeout is recorded "
        "(project_helpers.advance_chain_member_to_implementing's commit-SHA gate)"
    )

    refreshed_p1.closeout_executed_at = datetime.now(UTC)
    refreshed_p1.status = "completed"
    await db_session.flush()
    await db_session.commit()

    from giljo_mcp.services.sequence_chain_context import SequenceChainContextResolver

    resolver = SequenceChainContextResolver(db_manager=None, tenant_manager=None, test_session=db_session)
    advanced = await resolver.advance_index_if_committed(
        run_id=run_id, project_id=p1, tenant_key=tenant_key, next_index=1
    )
    assert advanced is True, "current_index must advance to member 2 once member 1's closeout is recorded"

    run_after_advance = await run_svc.find_active_run_for_project(project_id=p2, tenant_key=tenant_key)
    assert run_after_advance["current_index"] == 1

    refreshed_p2 = (
        await db_session.execute(select(Project).where(Project.id == p2, Project.tenant_key == tenant_key))
    ).scalar_one()
    refreshed_p2.closeout_executed_at = datetime.now(UTC)
    refreshed_p2.status = "completed"
    await db_session.flush()
    await db_session.commit()

    purged = await complete_chain_run_if_finished(
        db_manager=None,
        tenant_manager=None,
        conductor_agent_id=conductor_agent_id,
        tenant_key=tenant_key,
        test_session=db_session,
    )
    assert purged is True, "the run must be purged once every member is terminal"

    surviving_run = await run_svc.find_active_run_for_project(project_id=p1, tenant_key=tenant_key)
    assert surviving_run is None, "a purged run must no longer resolve as active for either member"


async def test_ui_chain_lock_and_prompt_flow_untouched_by_headless(chain_mcp_client, db_session, primary_tenant_key):
    new_client, _switch = chain_mcp_client
    tenant_key = primary_tenant_key
    await _seed_product_context(db_session, tenant_key)
    p1 = await _seed_project(db_session, tenant_key)
    p2 = await _seed_project(db_session, tenant_key)
    await db_session.commit()

    async with new_client() as session:
        result = await session.call_tool(
            "link_projects",
            {"project_ids": [p1, p2], "execution_mode": "multi_terminal"},
        )
        assert result.is_error is False, _error_text(result)
        run_id = _payload(result)["run_id"]

    run_svc = SequenceRunService(db_manager=None, tenant_manager=None, session=db_session)
    locked = await run_svc.update(run_id=run_id, tenant_key=tenant_key, locked=True)
    assert locked["locked"] is True, "a headless-created run must be lockable via the same owning service the UI uses"

    unlocked = await run_svc.update(run_id=run_id, tenant_key=tenant_key, locked=False)
    assert unlocked["locked"] is False


async def test_create_broadcasts_regardless_of_door(db_session, primary_tenant_key):
    tenant_key = primary_tenant_key

    class _RecordingWS:
        def __init__(self) -> None:
            self.events: list[tuple[str, dict[str, Any]]] = []

        async def broadcast_event_to_tenant(self, tenant_key: str, event: dict[str, Any]) -> None:
            self.events.append((tenant_key, event))

    await _seed_product_context(db_session, tenant_key)
    p1 = await _seed_project(db_session, tenant_key)
    p2 = await _seed_project(db_session, tenant_key)
    await db_session.commit()

    ws = _RecordingWS()
    svc = SequenceRunService(db_manager=None, tenant_manager=None, session=db_session, websocket_manager=ws)
    await svc.create(
        project_ids=[p1, p2],
        resolved_order=[p1, p2],
        execution_mode="claude_code_cli",
        tenant_key=tenant_key,
    )

    assert any(evt["type"] == "sequence:updated" for _tk, evt in ws.events), (
        "SequenceRunService.create must broadcast sequence:updated for EVERY caller "
        "(MCP start_chain_run and the REST create endpoint both construct this same service)"
    )




async def test_terminate_remaining_ends_run_via_mcp(chain_mcp_client, db_session, primary_tenant_key):
    new_client, _switch = chain_mcp_client
    tenant_key = primary_tenant_key
    await _seed_product_context(db_session, tenant_key)
    p1 = await _seed_project(db_session, tenant_key)
    p2 = await _seed_project(db_session, tenant_key)
    await db_session.commit()

    async with new_client() as session:
        result = await session.call_tool(
            "link_projects",
            {"project_ids": [p1, p2], "execution_mode": "claude_code_cli"},
        )
        assert result.is_error is False, _error_text(result)
        run_id = _payload(result)["run_id"]

    async with new_client() as session:
        result = await session.call_tool(
            "unlink_projects",
            {"run_id": run_id},
        )
        assert result.is_error is False, _error_text(result)
        payload = _payload(result)

    assert payload["success"] is True
    assert payload["action"] == "terminate_remaining"
    assert payload["run"]["status"] == "cancelled"

    run_svc = SequenceRunService(db_manager=None, tenant_manager=None, session=db_session)
    surviving = await run_svc.find_active_run_for_project(project_id=p1, tenant_key=tenant_key)
    assert surviving is None, "a cancelled run must no longer resolve as active for its members"


async def test_mark_reviewed_is_non_gating(db_session, primary_tenant_key):
    tenant_key = primary_tenant_key
    await _seed_product_context(db_session, tenant_key)
    p1 = await _seed_project(db_session, tenant_key)
    p2 = await _seed_project(db_session, tenant_key)
    await db_session.commit()

    svc = SequenceRunService(db_manager=None, tenant_manager=None, session=db_session)
    run = await svc.create(
        project_ids=[p1, p2],
        resolved_order=[p1, p2],
        execution_mode="claude_code_cli",
        tenant_key=tenant_key,
    )
    run_id = run["id"]
    current_index_before = run["current_index"]
    statuses_before = dict(run["project_statuses"])

    marked = await svc.mark_member_reviewed(run_id=run_id, project_id=p1, tenant_key=tenant_key)

    assert marked["reviewed_project_ids"] == [p1]
    assert marked["current_index"] == current_index_before, "mark_reviewed must never advance the run"
    assert marked["project_statuses"] == statuses_before, "mark_reviewed must never touch project_statuses"

    again = await svc.mark_member_reviewed(run_id=run_id, project_id=p1, tenant_key=tenant_key)
    assert again["reviewed_project_ids"] == [p1], "marking the same member twice must not duplicate the entry"


async def test_unlink_projects_requires_a_run_id(chain_mcp_client, db_session, primary_tenant_key):
    new_client, _switch = chain_mcp_client
    await _seed_product_context(db_session, primary_tenant_key)
    await db_session.commit()

    async with new_client() as session:
        result = await session.call_tool("unlink_projects", {})
        assert result.is_error is False and "VALIDATION_ERROR" in _error_text(result)




async def test_mark_reviewed_broadcasts_sequence_updated(db_session, primary_tenant_key):
    tenant_key = primary_tenant_key

    class _RecordingWS:
        def __init__(self) -> None:
            self.events: list[tuple[str, dict[str, Any]]] = []

        async def broadcast_event_to_tenant(self, tenant_key: str, event: dict[str, Any]) -> None:
            self.events.append((tenant_key, event))

    await _seed_product_context(db_session, tenant_key)
    p1 = await _seed_project(db_session, tenant_key)
    p2 = await _seed_project(db_session, tenant_key)
    await db_session.commit()

    ws = _RecordingWS()
    svc = SequenceRunService(db_manager=None, tenant_manager=None, session=db_session, websocket_manager=ws)
    run = await svc.create(
        project_ids=[p1, p2],
        resolved_order=[p1, p2],
        execution_mode="claude_code_cli",
        tenant_key=tenant_key,
    )
    ws.events.clear()

    await svc.mark_member_reviewed(run_id=run["id"], project_id=p1, tenant_key=tenant_key)

    assert any(evt["type"] == "sequence:updated" for _tk, evt in ws.events), (
        "mark_member_reviewed must broadcast sequence:updated so the cockpit tracks a "
        "headless-driven review exactly as it tracks a UI-driven one"
    )
