# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""Transport-layer regression test for BE-5079 (Wave 1 deferred item 3).

Investigates the alleged stale TODO counts in ``get_workflow_status`` immediately
after ``report_progress``. Wave 1 static analysis found no obvious bug at the
service/repository layer:
- ``ProgressService.report_progress`` commits explicitly via
  ``self._repo.commit(session)`` before broadcasting.
- ``WorkflowStatusService.get_workflow_status`` opens a fresh session and runs
  ``AgentOperationsRepository.get_todo_counts_by_job`` (a plain SELECT GROUP BY,
  no caching, no identity-map carryover across sessions).
- PG18 default READ COMMITTED -- a session opened after the writer's commit
  must observe the new rows.

The hypothesis (per the orchestrator mission) is that the report is a
client-side caching artefact, not a server-side visibility race. This test
proves that hypothesis at the MCP transport boundary -- the same boundary the
dashboard hits -- by alternating ``report_progress`` and ``get_workflow_status``
calls in a tight loop with varying TODO mixes and asserting exact count
equality on every iteration.

Per CLAUDE.md "Regression test at the failing layer" rule, the test exercises
the ``@mcp.tool`` wrappers in ``api/endpoints/mcp_sdk_server.py`` (lines 994
and 1289) -- not the underlying services directly -- because the BE-5042
lesson showed that service-only coverage misses transport-wrapper bugs.

Note on file justification (bloat budget): no existing integration test
module covers the progress/workflow_status MCP boundary. The closest neighbour
is ``test_workflow_status_service.py`` in tests/unit/ but that operates at the
service layer and would not catch a transport-wrapper visibility bug.
"""

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
    parts = []
    for block in call_tool_result.content:
        text = getattr(block, "text", None)
        if text:
            parts.append(text)
    return "\n".join(parts)


async def _seed_progress_context(db_session, tenant_key: str) -> dict:
    """Create org + product + project + job + execution for a tenant.

    Mirrors the seeding pattern from test_request_approval_mcp_transport.py.
    Returns dict with keys: project, job, execution.
    """
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


# ---------------------------------------------------------------------------
# Fixtures: shared-session ToolAccessor + tenant-aware MCP client
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def primary_tenant_key() -> str:
    return TenantManager.generate_tenant_key()


class _TenantSwitch:
    def __init__(self, value: str):
        self.value = value


@pytest_asyncio.fixture
async def progress_mcp_client(db_manager, db_session, primary_tenant_key, monkeypatch):
    """Yield ``(new_client, tenant_switch)`` for in-memory FastMCP transport.

    Identical to the pattern in test_request_approval_mcp_transport.py and
    test_task_tools_mcp_transport.py: build a fresh ToolAccessor bound to the
    test session so every service (including the inner ProgressService and
    WorkflowStatusService held by OrchestrationService) reads/writes inside
    the rolled-back test transaction.

    ``test_session=db_session`` propagates through OrchestrationService into
    its sub-services (``_progress`` and ``_workflow_status``) -- both honour
    the injected session. This is critical: without shared-session binding,
    ProgressService would write to a session whose commit is invisible to
    the test fixture's session, and the test would assert against an empty DB.
    """
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

    # BE-6042d: _resolve_tenant/_resolve_user_id moved to mcp_tools._base (the
    # _call_tool call site reads them there). Patch _base, not mcp_sdk_server.
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


# ---------------------------------------------------------------------------
# The regression test: report_progress -> get_workflow_status visibility
# ---------------------------------------------------------------------------


def _todo_mix_for_iteration(i: int) -> tuple[list[dict], dict[str, int]]:
    """Generate a TODO mix that varies per iteration so successive calls
    produce different counts -- catches both initial-write bugs AND
    update-write bugs (e.g. a stale snapshot returned after a delete+insert).

    Returns (todo_items, expected_counts).

    The server enforces a regression guard (ProgressService) that rejects
    incoming todo_items lists with FEWER completed items than the DB already
    has. To stay valid agent behaviour, completed grows monotonically with
    ``i``; in_progress and pending vary freely so the read path still has to
    surface a fresh snapshot every iteration.

    Each iteration rebuilds the list from scratch with brand-new content, so the
    TOTAL count can shrink between iterations. Per BE-6209a that is a destructive
    full replacement, so the caller passes ``replace=True`` below to opt in.
    """
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
    """report_progress -> get_workflow_status (back-to-back, 10 iterations).

    Asserts that the TODO counts surfaced by ``get_workflow_status`` match
    the most recent ``report_progress`` call exactly, on every iteration.

    A failure here would prove the BE-5079 item 3 bug exists at the server
    boundary. A pass proves the server is consistent and the staleness must
    live in the dashboard / client cache.
    """
    new_client, _switch = progress_mcp_client
    seed = await _seed_progress_context(db_session, primary_tenant_key)
    job_id = seed["job"].job_id
    project_id = seed["project"].id

    async with new_client() as session:
        for i in range(10):
            todo_items, expected = _todo_mix_for_iteration(i)

            progress_result = await session.call_tool(
                "report_progress",
                # replace=True: each iteration is a full fresh-content list whose
                # total may shrink vs the prior one (BE-6209a shrink guard).
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


# ---------------------------------------------------------------------------
# BE-6182 (alpha AF5): worker happy-path lifecycle regression — a spawned agent
# runs get_job_mission -> report_progress(pending) -> report_progress(completed)
# -> complete_job cleanly through the MCP transport. Guards the baseline so the
# happy path cannot silently regress.
# ---------------------------------------------------------------------------


async def test_be6182_worker_lifecycle_mission_progress_complete(progress_mcp_client, db_session, primary_tenant_key):
    """get_job_mission -> report_progress(pending) -> report_progress(completed)
    -> complete_job runs clean for a spawned implementer agent (no error at any
    step). This is the AF5 happy-path baseline."""
    new_client, _switch = progress_mcp_client
    seed = await _seed_progress_context(db_session, primary_tenant_key)
    job_id = seed["job"].job_id

    async with new_client() as session:
        # 1. Load the mission (the agent's first action).
        mission_result = await session.call_tool("get_job_mission", {"job_id": job_id})
        assert mission_result.is_error is False, _error_text(mission_result)

        # 2. Report a pending TODO, then 3. flip it to completed.
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

        # 4. complete_job runs clean (deliverable TODO is completed; no gate trip).
        done = await session.call_tool(
            "complete_job",
            {"job_id": job_id, "result": {"summary": "Feature delivered"}},
        )
        assert done.is_error is False, _error_text(done)
