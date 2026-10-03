# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio

from giljo_mcp.models import AgentExecution, AgentJob, Product, Project
from giljo_mcp.tenant import TenantManager
from tests.helpers.mcp_session_fixture import create_connected_server_and_client_session
from tests.helpers.test_db_helper import purge_tenant_rows


pytestmark = pytest.mark.asyncio


def _payload(result) -> dict:
    if getattr(result, "structuredContent", None):
        return result.structured_content
    return json.loads(result.content[0].text)


def _error_text(result) -> str:
    return "\n".join(getattr(b, "text", "") or "" for b in result.content)


async def _seed_project(db_manager, tenant_key: str, *, orchestrator_status: str, quiet_minutes: int) -> dict:
    now = datetime.now(UTC)
    async with db_manager.get_session_async(tenant_key=tenant_key) as session:
        product = Product(
            id=str(uuid.uuid4()),
            tenant_key=tenant_key,
            name=f"BE-9717 product {uuid.uuid4().hex[:6]}",
            description="seeded",
            is_active=True,
        )
        session.add(product)
        await session.flush()
        project = Project(
            id=str(uuid.uuid4()),
            tenant_key=tenant_key,
            product_id=product.id,
            name=f"BE-9717 {uuid.uuid4().hex[:6]}",
            description="x",
            mission="x",
            status="active",
            staging_status="staging_complete",
            execution_mode="claude_code_cli",
            series_number=1,
            implementation_launched_at=now - timedelta(minutes=90),
        )
        session.add(project)
        await session.flush()
        ids = {"project_id": project.id, "product_id": product.id}
        for job_type, status, quiet in (
            ("orchestrator", orchestrator_status, quiet_minutes),
            ("implementer", "working", 1),
            ("tester", "working", 2),
        ):
            job = AgentJob(
                job_id=str(uuid.uuid4()),
                tenant_key=tenant_key,
                project_id=project.id,
                job_type=job_type,
                mission="x",
                status="active",
                created_at=now - timedelta(minutes=80),
            )
            session.add(job)
            await session.flush()
            session.add(
                AgentExecution(
                    id=str(uuid.uuid4()),
                    agent_id=str(uuid.uuid4()),
                    job_id=job.job_id,
                    tenant_key=tenant_key,
                    agent_display_name=job_type,
                    agent_name=job_type,
                    status=status,
                    started_at=now - timedelta(minutes=70),
                    last_progress_at=now - timedelta(minutes=quiet),
                )
            )
            ids[f"{job_type}_job_id"] = job.job_id
        await session.commit()
    return ids


@pytest_asyncio.fixture
async def board_client(db_manager, monkeypatch):
    from api import app_state
    from api.endpoints import mcp_sdk_server
    from api.endpoints.mcp_tools import _base
    from giljo_mcp.tools.tool_accessor import ToolAccessor

    state = app_state.state
    prior = (state.tool_accessor, state.tenant_manager, state.db_manager)
    if state.tenant_manager is None:
        state.tenant_manager = TenantManager()
    state.db_manager = db_manager
    state.tool_accessor = ToolAccessor(db_manager=db_manager, tenant_manager=state.tenant_manager)
    tenant_key = TenantManager.generate_tenant_key()
    monkeypatch.setattr(_base, "_resolve_tenant", lambda ctx: tenant_key)
    monkeypatch.setattr(_base, "_resolve_user_id", lambda ctx: None)
    try:
        yield (lambda: create_connected_server_and_client_session(mcp_sdk_server.mcp)), tenant_key
    finally:
        await purge_tenant_rows(db_manager, tenant_key)
        state.tool_accessor, state.tenant_manager, state.db_manager = prior


async def test_call_on_a_project_with_a_stale_orchestrator_carries_the_board_line(board_client, db_manager):
    new_client, tenant_key = board_client
    ids = await _seed_project(db_manager, tenant_key, orchestrator_status="silent", quiet_minutes=14)

    async with new_client() as session:
        result = await session.call_tool("get_workflow_status", {"project_id": ids["project_id"]})

    assert result.is_error is False, _error_text(result)
    board = _payload(result)["_meta"]["board"]
    assert "orchestrator of this project" in board
    assert "stale 14 min" in board
    assert "Monitoring (2 agents running)" in board
    assert "report_progress" in board
    assert "you" not in board.lower().split()


async def test_call_carrying_a_job_id_of_that_project_carries_the_line_too(board_client, db_manager):
    new_client, tenant_key = board_client
    ids = await _seed_project(db_manager, tenant_key, orchestrator_status="silent", quiet_minutes=14)

    async with new_client() as session:
        result = await session.call_tool("get_agent_result", {"job_id": ids["implementer_job_id"]})

    assert result.is_error is False, _error_text(result)
    assert "Monitoring (2 agents running)" in _payload(result)["_meta"]["board"]


async def test_call_on_a_project_with_a_fresh_orchestrator_carries_none(board_client, db_manager):
    new_client, tenant_key = board_client
    ids = await _seed_project(db_manager, tenant_key, orchestrator_status="working", quiet_minutes=2)

    async with new_client() as session:
        result = await session.call_tool("get_workflow_status", {"project_id": ids["project_id"]})

    assert result.is_error is False, _error_text(result)
    meta = _payload(result)["_meta"]
    assert "board" not in meta
    assert "skills_version" in meta


async def test_call_with_no_project_or_job_carries_none(board_client, db_manager):
    new_client, tenant_key = board_client
    await _seed_project(db_manager, tenant_key, orchestrator_status="silent", quiet_minutes=14)

    async with new_client() as session:
        result = await session.call_tool("health_check", {})

    assert result.is_error is False, _error_text(result)
    assert "board" not in (_payload(result).get("_meta") or {})
