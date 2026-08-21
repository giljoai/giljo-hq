# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""Transport-layer regression tests for the BE-5059 Phase B close gates.

CLAUDE.md mandates a regression test at the failing layer for every bug-fix /
primitive project. The Phase B gates live inside the FastMCP ``@mcp.tool``
wrappers' downstream services -- this file exercises them through the MCP
transport (``create_connected_server_and_client_session``) so the wrapper +
``_call_tool`` dispatch + service-layer gate logic are all covered, not just
the service in isolation.

Two gates under test:

1. ``complete_job`` MUST refuse when the active execution is ``awaiting_user``
   and surface the pending ``approval_id`` in the error context.
2. ``write_project_closeout`` (force=False) MUST refuse when ANY
   team member is ``awaiting_user`` and surface a per-agent ``approval_id`` in
   the blockers list with ``issue_type="awaiting_user_approval"``.

Pattern reference: ``tests/integration/test_request_approval_mcp_transport.py``
(Phase A) and ``tests/integration/test_task_tools_mcp_transport.py`` (BE-5057).
Same in-memory transport, same ``_resolve_tenant`` monkeypatch, same shared-
session service rebinding so writes happen inside the rolled-back test
transaction.
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


async def _seed_full_context(db_session, tenant_key: str) -> dict:
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
        description="gate transport-layer tests",
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

    # BE-9054 (a): request_approval is orchestrator-only, so the awaiting_user
    # seed must be an orchestrator job (the gates under test are job-type-agnostic).
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
    return {"org": org, "product": product, "project": project, "job": job, "execution": execution}


@pytest_asyncio.fixture
async def gate_mcp_client(db_manager, db_session, monkeypatch):
    """Wire ToolAccessor's user_approval AND job_completion services to db_session.

    Same pattern as ``approval_mcp_client`` in
    ``tests/integration/test_request_approval_mcp_transport.py`` -- replace the
    accessor's services with shared-session instances so writes land inside the
    rolled-back test transaction. JobCompletionService also accepts a
    test_session, so the complete_job gate sees the same seed rows.
    """
    from api import app_state
    from api.endpoints import mcp_sdk_server
    from giljo_mcp.services.job_completion_service import JobCompletionService
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
    accessor._job_completion_service = JobCompletionService(
        db_manager=db_manager,
        tenant_manager=state.tenant_manager,
        test_session=db_session,
    )

    # write_project_closeout tool opens a new session via db_manager,
    # which won't see the test-transaction seed rows. Override the accessor's
    # method to forward the rolled-back db_session into the tool function.
    from giljo_mcp.tools.project_closeout import (
        close_project_and_update_memory as _close_tool,
    )

    async def _close_with_test_session(*, project_id, summary, key_outcomes, decisions_made, tenant_key, **kwargs):
        return await _close_tool(
            project_id=project_id,
            summary=summary,
            key_outcomes=key_outcomes,
            decisions_made=decisions_made,
            tenant_key=tenant_key,
            db_manager=db_manager,
            session=db_session,
            **kwargs,
        )

    accessor.write_project_closeout = _close_with_test_session

    state.tool_accessor = accessor

    # BE-6042d: _resolve_tenant/_resolve_user_id moved to mcp_tools._base (the
    # _call_tool call site reads them there). Patch _base, not mcp_sdk_server.
    from api.endpoints.mcp_tools import _base

    monkeypatch.setattr(_base, "_resolve_tenant", lambda ctx: tenant_key)
    monkeypatch.setattr(_base, "_resolve_user_id", lambda ctx: None)

    def _new_client():
        return create_connected_server_and_client_session(mcp_sdk_server.mcp)

    try:
        yield _new_client, tenant_key
    finally:
        state.tool_accessor = prior_tool_accessor
        state.tenant_manager = prior_tenant_manager
        state.db_manager = prior_db_manager


async def _request_approval_via_transport(new_client, seed):
    """Drive request_approval through the MCP wrapper to flip status atomically."""
    async with new_client() as session:
        result = await session.call_tool(
            "request_approval",
            {
                "job_id": seed["job"].job_id,
                "project_id": seed["project"].id,
                "reason": "Closeout: awaiting user review",
                "options": [
                    {"id": "approve", "label": "Approve and close"},
                    {"id": "rework", "label": "Send back for rework"},
                ],
                "context": {"deferred_findings": ["finding-1"]},
            },
        )
    assert result.is_error is False, _error_text(result)
    return _payload(result)["approval_id"]


# ---------------------------------------------------------------------------
# complete_job gate
# ---------------------------------------------------------------------------


async def test_complete_job_blocked_when_agent_is_awaiting_user(gate_mcp_client, db_session):
    """complete_job through the MCP transport must refuse on awaiting_user.

    The error must surface ``approval_id`` in its context so callers can route
    directly to the decide endpoint. Service-layer-only coverage would miss the
    @mcp.tool wrapper's exception serialization shape, which is the actual
    surface the orchestrator sees.
    """
    new_client, tenant_key = gate_mcp_client
    seed = await _seed_full_context(db_session, tenant_key)

    approval_id = await _request_approval_via_transport(new_client, seed)
    assert approval_id

    async with new_client() as session:
        result = await session.call_tool(
            "complete_job",
            {
                "job_id": seed["job"].job_id,
                "result": {"summary": "premature complete attempt"},
            },
        )

    assert result.is_error is True, "GATE LEAK: complete_job returned success while agent was awaiting_user"
    err = _error_text(result)
    assert "awaiting" in err.lower() or "AWAITING_USER_APPROVAL" in err or approval_id in err, (
        f"expected awaiting_user gate error, got: {err!r}"
    )


# ---------------------------------------------------------------------------
# write_project_closeout gate (was close_project_and_update_memory, renamed INF-6052a)
# ---------------------------------------------------------------------------


async def test_close_project_blocked_when_any_team_member_awaiting_user(gate_mcp_client, db_session):
    """close_project (force=False) must refuse when any agent is awaiting_user.

    BE-9016 (Sentry GILJOAI-BACKEND-5): CLOSEOUT_BLOCKED is an EXPECTED,
    agent-actionable domain rejection (BE-6081 Tier 2) -- it must be RETURNED
    as structured content, NOT raised as isError (was: isError is True; the
    raise reached Sentry as an error-level event for a routine, resolvable
    workspace state, not an internal failure).

    Asserts:
    1. The transport result is NOT an error (Tier 2: normal content).
    2. The payload carries success=False, error="CLOSEOUT_BLOCKED", and a
       blocker with ``issue_type="awaiting_user_approval"`` plus the resolved
       ``approval_id`` (so the UI can deep-link to the decide route).
    """
    new_client, tenant_key = gate_mcp_client
    seed = await _seed_full_context(db_session, tenant_key)

    approval_id = await _request_approval_via_transport(new_client, seed)
    assert approval_id

    async with new_client() as session:
        result = await session.call_tool(
            "write_project_closeout",
            {
                "project_id": seed["project"].id,
                "summary": "premature close attempt",
                "key_outcomes": ["x"],
                "decisions_made": ["x"],
                "tags": ["chore", "backend"],
            },
        )

    assert not result.is_error, (
        f"CLOSEOUT_BLOCKED must be a Tier-2 structured rejection, not isError. got: {_error_text(result)!r}"
    )
    payload = _payload(result)
    assert payload.get("success") is False
    assert payload.get("error") == "CLOSEOUT_BLOCKED"
    blockers = [b for b in payload.get("blockers", []) if "_summary" not in b]
    assert any(b.get("issue_type") == "awaiting_user_approval" for b in blockers), (
        f"expected an awaiting_user_approval blocker, got: {blockers!r}"
    )
    assert any(b.get("approval_id") == approval_id for b in blockers), (
        f"expected blocker to carry approval_id={approval_id!r}, got: {blockers!r}"
    )


# ---------------------------------------------------------------------------
# BE-9153: signal-gated closeout_mode enforcement THROUGH the MCP boundary.
# The gate auto-creates the approval (the agent does NOT call request_approval
# first). BE-5042 lesson: the failing layer (the @mcp.tool complete_job wrapper +
# _call_tool dispatch) must be exercised through the transport, not just the
# service in isolation.
# ---------------------------------------------------------------------------


async def _make_closeout_phase(db_session, project) -> None:
    """Flip the seeded project past staging so complete_job classifies the
    orchestrator call as the CLOSEOUT phase (where the BE-9153 gate lives)."""
    project.staging_status = "staging_complete"
    project.implementation_launched_at = datetime.now(UTC)
    await db_session.commit()


async def test_complete_job_gate_blocks_signal_bearing_closeout_under_hitl(gate_mcp_client, db_session):
    """Through the MCP transport: closeout_mode='hitl' + a signal-bearing closeout
    result auto-creates a blocking user_approval and complete_job refuses."""
    from giljo_mcp.services.settings_service import SettingsService

    new_client, tenant_key = gate_mcp_client
    seed = await _seed_full_context(db_session, tenant_key)
    await _make_closeout_phase(db_session, seed["project"])
    await SettingsService(db_session, tenant_key).update_settings("general", {"closeout_mode": "hitl"})

    async with new_client() as session:
        result = await session.call_tool(
            "complete_job",
            {
                "job_id": seed["job"].job_id,
                "result": {"summary": "done", "deferred_findings": ["needs a call on the retry policy"]},
            },
        )

    assert result.is_error is True, "GATE LEAK: signal-bearing closeout completed under hitl without approval"
    err = _error_text(result)
    assert "CLOSEOUT_APPROVAL_REQUIRED" in err or "approval" in err.lower(), f"unexpected error: {err!r}"


async def test_complete_job_gate_allows_clean_closeout_under_hitl(gate_mcp_client, db_session):
    """Through the MCP transport: a CLEAN closeout completes under hitl (the gate
    blocks ONLY on signal — this is the fix for the April 'blocked EVERY closeout')."""
    from giljo_mcp.services.settings_service import SettingsService

    new_client, tenant_key = gate_mcp_client
    seed = await _seed_full_context(db_session, tenant_key)
    await _make_closeout_phase(db_session, seed["project"])
    await SettingsService(db_session, tenant_key).update_settings("general", {"closeout_mode": "hitl"})

    async with new_client() as session:
        result = await session.call_tool(
            "complete_job",
            {"job_id": seed["job"].job_id, "result": {"summary": "straightforward, all green"}},
        )

    assert result.is_error is False, f"clean closeout must complete under hitl; got error: {_error_text(result)!r}"
    payload = _payload(result)
    assert payload.get("status") == "success"
