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

from giljo_mcp.models.agent_identity import AgentExecution, AgentJob
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


async def _seed_progress_context(db_session, tenant_key: str) -> dict:
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
        description="progress/workflow_status transport tests",
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
        job_type="implementer",
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
        agent_display_name="implementer",
        status="working",
        started_at=datetime.now(UTC),
    )
    db_session.add(execution)
    await db_session.commit()

    return {"project": project, "job": job, "execution": execution}




@pytest_asyncio.fixture
async def primary_tenant_key() -> str:
    return TenantManager.generate_tenant_key()


class _TenantSwitch:
    def __init__(self, value: str):
        self.value = value


@pytest_asyncio.fixture
async def progress_mcp_client(db_manager, db_session, primary_tenant_key, monkeypatch):
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




def _todo_mix_for_iteration(i: int) -> tuple[list[dict], dict[str, int]]:
    completed = i + 1
    in_progress = (i % 3) + 1
    pending = (i % 5) + 1

    items: list[dict] = []
    items += [{"content": f"done-{i}-{n}", "status": "completed"} for n in range(completed)]
    items += [{"content": f"wip-{i}-{n}", "status": "in_progress"} for n in range(in_progress)]
    items += [{"content": f"todo-{i}-{n}", "status": "pending"} for n in range(pending)]

    expected = {
        "completed": completed,
        "in_progress": in_progress,
        "pending": pending,
    }
    return items, expected


async def test_workflow_status_observes_report_progress_immediately(
    progress_mcp_client, db_session, primary_tenant_key
):
    new_client, _switch = progress_mcp_client
    seed = await _seed_progress_context(db_session, primary_tenant_key)
    job_id = seed["job"].job_id
    project_id = seed["project"].id

    async with new_client() as session:
        for i in range(10):
            todo_items, expected = _todo_mix_for_iteration(i)

            progress_result = await session.call_tool(
                "report_progress",
                {"job_id": job_id, "todo_items": todo_items, "replace": True},
            )
            assert progress_result.is_error is False, _error_text(progress_result)

            status_result = await session.call_tool(
                "get_workflow_status",
                {"project_id": project_id},
            )
            assert status_result.is_error is False, _error_text(status_result)

            payload = _payload(status_result)
            agents = payload.get("agents") or []
            this_agent = next((a for a in agents if a.get("job_id") == job_id), None)
            assert this_agent is not None, f"iteration {i}: job_id {job_id} missing from agents list: {agents!r}"

            todos = this_agent.get("todos") or {}
            actual = {
                "completed": todos.get("completed", 0),
                "in_progress": todos.get("in_progress", 0),
                "pending": todos.get("pending", 0),
            }
            assert actual == expected, (
                f"iteration {i}: stale counts after report_progress. "
                f"expected={expected!r} actual={actual!r}. "
                f"This indicates a server-side visibility race in the "
                f"report_progress -> get_workflow_status path."
            )




async def test_be6182_worker_lifecycle_mission_progress_complete(progress_mcp_client, db_session, primary_tenant_key):
    new_client, _switch = progress_mcp_client
    seed = await _seed_progress_context(db_session, primary_tenant_key)
    job_id = seed["job"].job_id

    async with new_client() as session:
        mission_result = await session.call_tool("get_job_mission", {"job_id": job_id})
        assert mission_result.is_error is False, _error_text(mission_result)

        pending = await session.call_tool(
            "report_progress",
            {"job_id": job_id, "todo_items": [{"content": "Deliver the feature", "status": "pending"}]},
        )
        assert pending.is_error is False, _error_text(pending)

        completed = await session.call_tool(
            "report_progress",
            {"job_id": job_id, "todo_items": [{"content": "Deliver the feature", "status": "completed"}]},
        )
        assert completed.is_error is False, _error_text(completed)

        done = await session.call_tool(
            "complete_job",
            {"job_id": job_id, "result": {"summary": "Feature delivered"}},
        )
        assert done.is_error is False, _error_text(done)
