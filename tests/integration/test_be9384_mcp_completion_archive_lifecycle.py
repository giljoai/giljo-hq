# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-9384 — MCP-transport boundary regression test for solo-project completion.

Symptom: ``POST /api/v1/projects/{id}/archive`` is the supported completion path
and runs four steps -- deactivate, terminal-status selection from
``early_termination``, the status write with ``completed_at`` stamped (BE-9343),
and ``close_completed_agents_with_commit`` moving spawned agents from 'complete'
to 'closed' (BE-9246). No MCP tool reached that endpoint, so an agent finishing a
project over MCP had ``update_project(status="completed")`` and nothing else, which
reached the status write ALONE. The end state looked right (status and completion
date both present) while spawned agents stayed stranded at 'complete', and nothing
surfaced the skipped steps. A mechanism gap, not an agent-discipline gap: the
closeout tool's own response text warned callers off the only path they had.

Fix: the four steps moved into ``ProjectService.archive_project`` (single writer);
the REST endpoint and the MCP terminal transition are its two callers.

FAIL-FIRST: on pre-fix master ``test_completing_a_solo_project_over_mcp_closes_its_agents``
fails on the agent-closure assertion -- the agent is still 'complete'. The status and
``completed_at`` assertions in that same test PASS pre-fix (BE-9343 already stamped
the date through the bare write), which is precisely why the gap went unnoticed: the
observable end state was plausible.

Transport: drives the REAL ``@mcp.tool`` transport via
``create_connected_server_and_client_session`` (BE-5042 precedent, mirroring
``tests/integration/test_be9016_another_project_active_mcp_boundary.py``) against the
real Postgres test DB.

Parallel-safe: each test generates a fresh tenant_key and purges its own rows in a
``finally`` block -- these MCP-adapter calls commit for real via ``db_manager``, so
there is no rollback isolation to lean on. No module-level mutable state, no ordering
dependencies. Edition Scope: Both.
"""

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
    """Wire a real ToolAccessor into the in-memory MCP transport.

    No injected test session: every tool call opens its own real session, exactly
    as it does in production. Yields ``(client_factory, tenant_key)``.
    """
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
    """Commit an active product + one project + one spawned agent left at 'complete'.

    The agent is a SUBAGENT (``agent_display_name="implementer"``), which also keeps
    deactivation's never-run-orchestrator cleanup (BE-6085/BE-6123) out of the way:
    that path requires zero non-orchestrator executions, so it is a no-op here and
    cannot be mistaken for the agent closure this test measures.

    Returns ``(project_id, execution_id)``.
    """
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
    """Re-read project + agent through a FRESH session (the tool committed its own)."""
    async with db_manager.get_session_async(tenant_key=tenant_key) as verify:
        project = (await verify.execute(select(Project).where(Project.id == project_id))).scalar_one()
        execution = (await verify.execute(select(AgentExecution).where(AgentExecution.id == execution_id))).scalar_one()
    return project, execution


async def _call_update_project(client, project_id: str, status: str, *, force: bool = False) -> object:
    """Invoke the agent-facing ``update_project`` @mcp.tool over the real transport.

    ``force=True`` (BE-9539) skips the closeout-required gate -- these seeded
    projects never ran ``write_project_closeout``, and most of these tests pin
    the archive-lifecycle mechanics (deactivate/terminal-status/agent-closure),
    orthogonal to that gate.
    """
    async with client() as mcp_session:
        return await mcp_session.call_tool(
            "update_project", {"project_id": project_id, "status": status, "force": force}
        )


class TestSoloCompletionRunsTheArchiveLifecycle:
    async def test_completing_a_solo_project_over_mcp_closes_its_agents(self, mcp_client, db_manager):
        """THE regression. The agent-closure assertion is the one that fails pre-fix.

        This is the whole defect in one call: an agent finishes its project the only
        way MCP lets it, and every visible signal says the project closed cleanly
        while a spawned agent is left sitting at 'complete' forever.
        """
        client, tenant_key = mcp_client
        project_id, execution_id = await _seed_project_with_completed_agent(db_manager, tenant_key)

        try:
            result = await _call_update_project(client, project_id, "completed", force=True)

            assert not result.is_error, f"completion must not error. content: {_content_text(result)!r}"
            payload = _payload(result)
            assert payload.get("success") is True, f"expected success, got: {payload!r}"

            project, execution = await _read_back(db_manager, tenant_key, project_id, execution_id)

            # Steps 2-3 -- these already PASSED pre-fix, which is why the gap hid.
            assert project.status == "completed"
            assert project.completed_at is not None, "the terminal transition must stamp the completion date"

            # Step 4 -- FAIL-FIRST: pre-fix this agent is still 'complete'.
            assert execution.status == "closed", (
                "a spawned agent left at 'complete' must be transitioned to 'closed' by the "
                "completion -- reaching only the status write strands it there forever"
            )

            # The response must SAY the lifecycle ran; the old message ("updated
            # successfully") is exactly what let a caller believe a bare status write
            # had completed the project.
            assert "archive lifecycle" in payload.get("message", ""), (
                f"the response must name what actually ran, got: {payload.get('message')!r}"
            )
        finally:
            await purge_tenant_rows(db_manager, tenant_key)

    async def test_an_early_terminated_project_lands_on_terminated_not_completed(self, mcp_client, db_manager):
        """The terminal status is DERIVED from early_termination, never taken literally.

        This is why ``terminated`` is not an MCP-writable status: the flag decides, and
        an agent asking for 'completed' on a project the user terminated early must
        still land on 'terminated' -- the same answer the dashboard's Archive button
        gives. Pre-fix the bare write recorded 'completed' and lost that distinction.
        """
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
        """The deactivate-skip gate is load-bearing, not decoration.

        ``deactivate_project`` raises ProjectStateError on anything but ACTIVE, so
        completing an already-inactive project -- the ordinary shape after a closeout
        -- would blow up if the lifecycle deactivated unconditionally.
        """
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
        """Chain-run semantics are out of scope and must not be rerouted.

        A member of a live chain has its lifecycle driven by the run's conductor
        (``_closeout_finalize`` flips the row and marks the run entry). Running the
        archive lifecycle here would fire a second, competing terminal transition, so
        the member keeps today's plain status write -- observable by the agent NOT
        being closed.
        """
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
        """'cancelled' is abandonment, not completion. Archive never writes it."""
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
        """The overwhelmingly common call shape -- a rename -- must not archive anything."""
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
