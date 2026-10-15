# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import pytest
import pytest_asyncio
from sqlalchemy import select

from giljo_mcp.models.agent_identity import AgentExecution, AgentJob
from giljo_mcp.models.organizations import Organization
from giljo_mcp.models.products import Product
from giljo_mcp.models.projects import Project
from giljo_mcp.services.project_staging_service import ProjectStagingService
from giljo_mcp.services.sequence_chain_context import chain_member_phase, resolve_chain_launch_gate
from giljo_mcp.services.sequence_run_service import SequenceRunService
from giljo_mcp.tenant import TenantManager
from giljo_mcp.tools.project_closeout import close_project_and_update_memory
from tests.helpers.mcp_session_fixture import create_connected_server_and_client_session


pytestmark = pytest.mark.asyncio


def _payload(call_tool_result) -> dict:
    if getattr(call_tool_result, "structuredContent", None):
        return call_tool_result.structured_content
    return json.loads(call_tool_result.content[0].text)


def _error_text(call_tool_result) -> str:
    return "\n".join(getattr(block, "text", "") or "" for block in call_tool_result.content)


async def _seed_member(db_session, tenant_key: str) -> str:
    product = Product(
        id=str(uuid.uuid4()),
        tenant_key=tenant_key,
        name=f"BE-9761a product {uuid.uuid4().hex[:6]}",
        description="seeded",
        is_active=False,
    )
    db_session.add(product)
    project = Project(
        id=str(uuid.uuid4()),
        tenant_key=tenant_key,
        product_id=product.id,
        name=f"BE-9761a member {uuid.uuid4().hex[:6]}",
        description="chain member",
        mission="build it",
        status="inactive",
        staging_status="staged",
        series_number=uuid.uuid4().int % 9000 + 1,
        execution_mode="claude_code_cli",
        created_at=datetime.now(UTC),
    )
    db_session.add(project)
    await db_session.flush()
    return project.id


async def _seed_sub_orchestrator(db_session, tenant_key: str, project_id: str) -> AgentJob:
    job = AgentJob(
        job_id=str(uuid.uuid4()),
        tenant_key=tenant_key,
        project_id=project_id,
        job_type="orchestrator",
        mission="BE-9761a sub-orchestrator",
        status="active",
        created_at=datetime.now(UTC),
    )
    db_session.add(job)
    await db_session.flush()
    db_session.add(
        AgentExecution(
            id=str(uuid.uuid4()),
            agent_id=str(uuid.uuid4()),
            job_id=job.job_id,
            tenant_key=tenant_key,
            agent_display_name="orchestrator",
            status="working",
            started_at=datetime.now(UTC) - timedelta(minutes=1),
            project_phase="staging",
        )
    )
    await db_session.flush()
    return job


async def _spawn_specialist(db_session, tenant_key: str, project_id: str, *, status: str = "waiting") -> AgentExecution:
    job = AgentJob(
        job_id=str(uuid.uuid4()),
        tenant_key=tenant_key,
        project_id=project_id,
        job_type="implementer",
        mission="BE-9761a specialist",
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
        agent_display_name="implementer",
        status=status,
        started_at=datetime.now(UTC),
        project_phase="implementation",
    )
    db_session.add(execution)
    await db_session.flush()
    return execution


async def _project(db_session, tenant_key: str, project_id: str) -> Project:
    row = (
        await db_session.execute(select(Project).where(Project.id == project_id, Project.tenant_key == tenant_key))
    ).scalar_one()
    await db_session.refresh(row)
    return row


@pytest_asyncio.fixture
async def tenant_key() -> str:
    return TenantManager.generate_tenant_key()


@pytest_asyncio.fixture
async def mcp_client(db_manager, db_session, tenant_key, monkeypatch):
    from api import app_state
    from api.endpoints import mcp_sdk_server
    from api.endpoints.mcp_tools import _base
    from giljo_mcp.tools.tool_accessor import ToolAccessor

    state = app_state.state
    prior = (state.tool_accessor, state.tenant_manager, state.db_manager)
    if state.tenant_manager is None:
        state.tenant_manager = TenantManager()
    state.db_manager = db_manager
    state.tool_accessor = ToolAccessor(
        db_manager=db_manager, tenant_manager=state.tenant_manager, test_session=db_session
    )
    monkeypatch.setattr(_base, "_resolve_tenant", lambda ctx: tenant_key)
    monkeypatch.setattr(_base, "_resolve_user_id", lambda ctx: None)

    org = Organization(name="BE-9761a", slug=f"be9761a-{uuid.uuid4().hex[:8]}", tenant_key=tenant_key, is_active=True)
    db_session.add(org)
    await db_session.flush()
    try:
        yield lambda: create_connected_server_and_client_session(mcp_sdk_server.mcp)
    finally:
        state.tool_accessor, state.tenant_manager, state.db_manager = prior


async def _call(new_client, tool: str, args: dict) -> dict:
    async with new_client() as session:
        result = await session.call_tool(tool, args)
    assert result.is_error is False, f"{tool} failed: {_error_text(result)}"
    payload = _payload(result)
    assert payload.get("success") is not False, f"{tool} refused: {payload}"
    return payload


async def _stage_like_the_sub_orchestrator(new_client, db_session, tenant_key: str, job: AgentJob) -> AgentExecution:
    worker = await _spawn_specialist(db_session, tenant_key, job.project_id)
    await db_session.commit()
    await _call(
        new_client,
        "report_progress",
        {
            "job_id": job.job_id,
            "todo_items": [
                {"content": "Spawn and brief the implementer", "status": "completed"},
                {"content": "Implementer delivers the change", "status": "pending"},
                {"content": "Review and close out", "status": "pending"},
            ],
        },
    )
    await _call(new_client, "update_job_mission", {"job_id": job.job_id, "mission": "Plan: one implementer."})
    return worker


async def _implement_and_finish(new_client, db_session, job: AgentJob, worker: AgentExecution) -> None:
    worker.status = "complete"
    await db_session.commit()
    await _call(
        new_client,
        "report_progress",
        {
            "job_id": job.job_id,
            "replace": True,
            "todo_items": [
                {"content": "Spawn and brief the implementer", "status": "completed"},
                {"content": "Implementer delivers the change", "status": "completed"},
                {"content": "Review and close out", "status": "completed"},
            ],
        },
    )
    payload = await _call(new_client, "complete_job", {"job_id": job.job_id, "result": {"summary": "delivered"}})
    assert payload.get("phase") != "staging_end"


def _launch_service(db_manager, db_session, tenant_key: str) -> ProjectStagingService:
    tm = MagicMock()
    tm.get_current_tenant.return_value = tenant_key
    return ProjectStagingService(db_manager=db_manager, tenant_manager=tm, test_session=db_session)


async def test_implement_chain_then_head_staging_end_succeeds(mcp_client, db_manager, db_session, tenant_key):
    new_client = mcp_client
    members = [await _seed_member(db_session, tenant_key) for _ in range(3)]
    await db_session.commit()
    await _call(new_client, "link_projects", {"project_ids": members, "execution_mode": "claude_code_cli"})
    head_job = await _seed_sub_orchestrator(db_session, tenant_key, members[0])
    await db_session.commit()

    await _launch_service(db_manager, db_session, tenant_key).launch_implementation(members[0], tenant_key=tenant_key)

    mission = await _call(new_client, "get_job_mission", {"job_id": head_job.job_id})
    assert mission["project_phase"] == "staging", "the head has not staged yet; its mission must say so"

    await _stage_like_the_sub_orchestrator(new_client, db_session, tenant_key, head_job)
    head = await _project(db_session, tenant_key, members[0])
    assert head.implementation_launched_at is not None and head.staging_status == "staging_complete", (
        "precondition: the live state (gate open, mission written) before the head's staging-end"
    )

    async with new_client() as session:
        result = await session.call_tool("complete_job", {"job_id": head_job.job_id, "result": {"summary": "staged"}})
    assert result.is_error is False, f"head staging-end refused: {_error_text(result)}"
    payload = _payload(result)
    assert payload.get("phase") == "staging_end", f"head staging-end was read as {payload.get('phase')!r}"
    assert payload["staging_directive"]["action"] == "CONTINUE"

    async with new_client() as session:
        result = await session.call_tool("complete_job", {"job_id": head_job.job_id, "result": {"summary": "done?"}})
    blocked = _payload(result)
    assert blocked.get("error") == "COMPLETION_BLOCKED", (
        f"the implementation-end complete_job must still block on unfinished TODOs, got {blocked}"
    )


async def test_skipped_staging_end_still_closes_out(mcp_client, db_manager, db_session, tenant_key):
    new_client = mcp_client
    members = [await _seed_member(db_session, tenant_key) for _ in range(2)]
    await db_session.commit()
    await _call(new_client, "link_projects", {"project_ids": members, "execution_mode": "claude_code_cli"})
    head_job = await _seed_sub_orchestrator(db_session, tenant_key, members[0])
    await db_session.commit()
    await _launch_service(db_manager, db_session, tenant_key).launch_implementation(members[0], tenant_key=tenant_key)
    await _spawn_specialist(db_session, tenant_key, members[0], status="complete")
    await db_session.commit()
    await _call(new_client, "update_job_mission", {"job_id": head_job.job_id, "mission": "Plan: one implementer."})

    payload = await _call(new_client, "complete_job", {"job_id": head_job.job_id, "result": {"summary": "all done"}})

    assert payload.get("phase") != "staging_end", (
        "every worker already finished: this complete_job is the project's real closeout"
    )


async def test_member_closeout_advances_chain_and_opens_next_gate(mcp_client, db_manager, db_session, tenant_key):
    new_client = mcp_client
    members = [await _seed_member(db_session, tenant_key) for _ in range(3)]
    await db_session.commit()
    run_id = (await _call(new_client, "link_projects", {"project_ids": members, "execution_mode": "claude_code_cli"}))[
        "run_id"
    ]
    head_job = await _seed_sub_orchestrator(db_session, tenant_key, members[0])
    second_job = await _seed_sub_orchestrator(db_session, tenant_key, members[1])
    await db_session.commit()
    await _launch_service(db_manager, db_session, tenant_key).launch_implementation(members[0], tenant_key=tenant_key)
    head_worker = await _stage_like_the_sub_orchestrator(new_client, db_session, tenant_key, head_job)
    await _call(new_client, "complete_job", {"job_id": head_job.job_id, "result": {"summary": "staged"}})
    await _implement_and_finish(new_client, db_session, head_job, head_worker)

    await close_project_and_update_memory(
        project_id=members[0],
        summary="Member 1 shipped.",
        key_outcomes=["shipped"],
        decisions_made=["kept it small"],
        tenant_key=tenant_key,
        db_manager=db_manager,
        session=db_session,
    )

    run = await SequenceRunService(db_manager=None, tenant_manager=None, session=db_session).get(
        run_id=run_id, tenant_key=tenant_key
    )
    assert run["current_index"] == 1, f"the run must advance to member 2 on member 1's closeout, got {run}"
    second = await _project(db_session, tenant_key, members[1])
    third = await _project(db_session, tenant_key, members[2])
    assert second.implementation_launched_at is not None, "member 2's gate must open so its play button shows"
    assert third.implementation_launched_at is None, "only the NEXT member opens; the tail stays closed"
    assert chain_member_phase(second) == "staging", "member 2's prompt must still start at staging"
    _is_member, blocker = await resolve_chain_launch_gate(db_session, project_id=members[1], tenant_key=tenant_key)
    assert blocker is None

    await _stage_like_the_sub_orchestrator(new_client, db_session, tenant_key, second_job)
    payload = await _call(new_client, "complete_job", {"job_id": second_job.job_id, "result": {"summary": "staged"}})
    assert payload.get("phase") == "staging_end"
