# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import json
import random
import uuid
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import select

from giljo_mcp.models.agent_identity import AgentExecution, AgentJob
from giljo_mcp.models.products import Product
from giljo_mcp.models.projects import Project
from giljo_mcp.models.sequence_runs import SequenceRun
from giljo_mcp.tenant import TenantManager
from tests.helpers.mcp_session_fixture import create_connected_server_and_client_session
from tests.helpers.test_db_helper import purge_tenant_rows


pytestmark = pytest.mark.asyncio


def _payload(call_tool_result) -> dict:
    first_block = call_tool_result.content[0]
    text = getattr(first_block, "text", None)
    if text is None:
        raise AssertionError(f"unexpected content block: {first_block!r}")
    return json.loads(text)


def _content_text(call_tool_result) -> str:
    parts = []
    for block in call_tool_result.content or []:
        text = getattr(block, "text", None)
        if text:
            parts.append(text)
    return "\n".join(parts)


@pytest_asyncio.fixture
async def mcp_client(db_manager, monkeypatch):
    from api import app_state
    from api.endpoints import mcp_sdk_server
    from api.endpoints.mcp_tools import _base
    from giljo_mcp.tools.tool_accessor import ToolAccessor

    state = app_state.state
    prior_tool_accessor = state.tool_accessor
    prior_tenant_manager = state.tenant_manager
    prior_db_manager = state.db_manager

    if state.tenant_manager is None:
        state.tenant_manager = TenantManager()
    state.db_manager = db_manager

    tenant_key = TenantManager.generate_tenant_key()
    state.tool_accessor = ToolAccessor(db_manager=db_manager, tenant_manager=state.tenant_manager)

    monkeypatch.setattr(_base, "_resolve_tenant", lambda ctx: tenant_key)
    monkeypatch.setattr(_base, "_resolve_user_id", lambda ctx: None)

    def _client():
        return create_connected_server_and_client_session(mcp_sdk_server.mcp)

    try:
        yield _client, tenant_key
    finally:
        state.tool_accessor = prior_tool_accessor
        state.tenant_manager = prior_tenant_manager
        state.db_manager = prior_db_manager


async def _seed_project_with_completed_agent(
    db_manager,
    tenant_key: str,
    *,
    early_termination: bool = False,
    status: str = "active",
) -> tuple[str, str]:
    product_id = str(uuid.uuid4())
    project_id = str(uuid.uuid4())
    job_id = str(uuid.uuid4())
    execution_id = str(uuid.uuid4())

    async with db_manager.get_session_async(tenant_key=tenant_key) as session:
        session.add(
            Product(
                id=product_id,
                name=f"BE-9384 Product {uuid.uuid4().hex[:6]}",
                description="BE-9384 MCP archive completion path.",
                tenant_key=tenant_key,
                is_active=True,
                product_memory={},
            )
        )
        session.add(
            Project(
                id=project_id,
                tenant_key=tenant_key,
                product_id=product_id,
                name=f"BE-9384 {uuid.uuid4().hex[:6]}",
                description="Project the agent finishes over MCP.",
                mission="Prove MCP completion runs the whole archive lifecycle.",
                status=status,
                staging_status="staging_complete",
                early_termination=early_termination,
                series_number=random.randint(1, 9999),
            )
        )
        session.add(
            AgentJob(
                job_id=job_id,
                tenant_key=tenant_key,
                project_id=project_id,
                job_type="implementer",
                mission="BE-9384 fixture agent",
                status="active",
                created_at=datetime.now(UTC),
            )
        )
        session.add(
            AgentExecution(
                id=execution_id,
                agent_id=str(uuid.uuid4()),
                job_id=job_id,
                tenant_key=tenant_key,
                agent_display_name="implementer",
                agent_name="implementer",
                status="complete",
                started_at=datetime.now(UTC) - timedelta(minutes=5),
                completed_at=datetime.now(UTC) - timedelta(minutes=1),
            )
        )
        await session.commit()

    return project_id, execution_id


async def _read_back(db_manager, tenant_key: str, project_id: str, execution_id: str) -> tuple[Project, AgentExecution]:
    async with db_manager.get_session_async(tenant_key=tenant_key) as verify:
        project = (await verify.execute(select(Project).where(Project.id == project_id))).scalar_one()
        execution = (await verify.execute(select(AgentExecution).where(AgentExecution.id == execution_id))).scalar_one()
    return project, execution


async def _call_update_project(client, project_id: str, status: str, *, force: bool = False) -> object:
    async with client() as mcp_session:
        return await mcp_session.call_tool(
            "update_project", {"project_id": project_id, "status": status, "force": force}
        )


class TestSoloCompletionRunsTheArchiveLifecycle:
    async def test_completing_a_solo_project_over_mcp_closes_its_agents(self, mcp_client, db_manager):
        client, tenant_key = mcp_client
        project_id, execution_id = await _seed_project_with_completed_agent(db_manager, tenant_key)

        try:
            result = await _call_update_project(client, project_id, "completed", force=True)

            assert not result.is_error, f"completion must not error. content: {_content_text(result)!r}"
            payload = _payload(result)
            assert payload.get("success") is True, f"expected success, got: {payload!r}"

            project, execution = await _read_back(db_manager, tenant_key, project_id, execution_id)

            assert project.status == "completed"
            assert project.completed_at is not None, "the terminal transition must stamp the completion date"

            assert execution.status == "closed", (
                "a spawned agent left at 'complete' must be transitioned to 'closed' by the "
                "completion -- reaching only the status write strands it there forever"
            )

            assert "archive lifecycle" in payload.get("message", ""), (
                f"the response must name what actually ran, got: {payload.get('message')!r}"
            )
        finally:
            await purge_tenant_rows(db_manager, tenant_key)

    async def test_an_early_terminated_project_lands_on_terminated_not_completed(self, mcp_client, db_manager):
        client, tenant_key = mcp_client
        project_id, execution_id = await _seed_project_with_completed_agent(
            db_manager, tenant_key, early_termination=True
        )

        try:
            result = await _call_update_project(client, project_id, "completed", force=True)
            assert not result.is_error, _content_text(result)

            project, execution = await _read_back(db_manager, tenant_key, project_id, execution_id)
            assert project.status == "terminated", (
                "early_termination=True must yield 'terminated', not the literal status asked for"
            )
            assert project.completed_at is not None
            assert execution.status == "closed"
        finally:
            await purge_tenant_rows(db_manager, tenant_key)

    async def test_an_already_inactive_project_completes_without_a_deactivate_error(self, mcp_client, db_manager):
        client, tenant_key = mcp_client
        project_id, execution_id = await _seed_project_with_completed_agent(db_manager, tenant_key, status="inactive")

        try:
            result = await _call_update_project(client, project_id, "completed", force=True)
            assert not result.is_error, f"an inactive project must complete cleanly: {_content_text(result)!r}"

            project, execution = await _read_back(db_manager, tenant_key, project_id, execution_id)
            assert project.status == "completed"
            assert execution.status == "closed"
        finally:
            await purge_tenant_rows(db_manager, tenant_key)


class TestPathsThatMustStayUnchanged:
    async def test_a_chain_member_keeps_the_bare_status_write(self, mcp_client, db_manager):
        client, tenant_key = mcp_client
        project_id, execution_id = await _seed_project_with_completed_agent(db_manager, tenant_key)

        async with db_manager.get_session_async(tenant_key=tenant_key) as session:
            session.add(
                SequenceRun(
                    id=str(uuid.uuid4()),
                    tenant_key=tenant_key,
                    project_ids=[project_id],
                    resolved_order=[project_id],
                    current_index=0,
                    execution_mode="claude_code_cli",
                    status="running",
                    locked=True,
                    project_statuses={project_id: "implementing"},
                )
            )
            await session.commit()

        try:
            result = await _call_update_project(client, project_id, "completed")
            assert not result.is_error, _content_text(result)

            project, execution = await _read_back(db_manager, tenant_key, project_id, execution_id)
            assert project.status == "completed", "the plain status write still applies"
            assert execution.status == "complete", (
                "a chain member must NOT run the archive lifecycle -- its conductor owns "
                "member completion, and a second terminal transition would race it"
            )
        finally:
            await purge_tenant_rows(db_manager, tenant_key)

    async def test_cancelled_stays_a_plain_status_write(self, mcp_client, db_manager):
        client, tenant_key = mcp_client
        project_id, execution_id = await _seed_project_with_completed_agent(db_manager, tenant_key)

        try:
            result = await _call_update_project(client, project_id, "cancelled")
            assert not result.is_error, _content_text(result)

            project, execution = await _read_back(db_manager, tenant_key, project_id, execution_id)
            assert project.status == "cancelled"
            assert execution.status == "complete", "cancelling must not run the completion lifecycle"
        finally:
            await purge_tenant_rows(db_manager, tenant_key)

    async def test_a_non_status_update_is_untouched(self, mcp_client, db_manager):
        client, tenant_key = mcp_client
        project_id, execution_id = await _seed_project_with_completed_agent(db_manager, tenant_key)

        try:
            async with client() as mcp_session:
                result = await mcp_session.call_tool(
                    "update_project", {"project_id": project_id, "name": "BE-9384 renamed"}
                )
            assert not result.is_error, _content_text(result)

            project, execution = await _read_back(db_manager, tenant_key, project_id, execution_id)
            assert project.name == "BE-9384 renamed"
            assert project.status == "active", "a rename must not move the project's status"
            assert execution.status == "complete"
        finally:
            await purge_tenant_rows(db_manager, tenant_key)
