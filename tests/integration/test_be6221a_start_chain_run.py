# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-6221a: start_chain_run MCP tool + broadcast-on-create.

Two failing layers, two test groups (one file to respect the bloat budget; both
exercise BE-6221a):

1. MCP-BOUNDARY (through the in-memory FastMCP transport — the same boundary the
   CLI/headless connector hits, and the layer the @mcp.tool wrapper lives at):
     * happy path returns conductor_agent_id + conductor_job_id and a next_action
       that names the CORRECT bootstrap tool (get_staging_instructions — the
       conductor's FIRST drive call; get_job_mission is the LATER impl-phase drive);
     * structured {success: false, error: CODE} rejections (NOT raised errors,
       BE-6081 carve-out) for a non-existent project, a terminal project, an
       already-enrolled project, a 1-member list, and a non-permutation order.

2. SERVICE: SequenceRunService.create() now fires sequence:updated after commit
   (MUST-FIX #2) — asserted with a recording websocket_manager stub.

Parallel-safe: DB-touching tests use the db_session fixture
(TransactionalTestContext, rollback at teardown). No module-level mutable state.
Edition Scope: CE.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
import pytest_asyncio

from giljo_mcp.models.organizations import Organization
from giljo_mcp.models.products import Product
from giljo_mcp.models.projects import Project
from giljo_mcp.services.sequence_run_service import SequenceRunService
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


async def _seed_project(
    db_session,
    tenant_key: str,
    *,
    status: str = "active",
    staging_status: str | None = None,
    implementation_launched_at: datetime | None = None,
) -> str:
    """Create a single tenant-scoped Project; return its id."""
    suffix = uuid.uuid4().hex[:8]
    # BE-9437: a project belongs to a product. Its own, so an active
    # seed cannot collide under idx_project_single_active_per_product.
    _owning_product_project = Product(
        id=str(uuid.uuid4()),
        tenant_key=tenant_key,
        name=f"Owning Product {uuid.uuid4().hex[:6]}",
        description="seeded",
        is_active=False,
    )
    db_session.add(_owning_product_project)
    project = Project(
        id=str(uuid.uuid4()),
        tenant_key=tenant_key,
        product_id=_owning_product_project.id,
        name=f"BE-6221a {suffix}",
        description="chain member",
        mission="build it",
        status=status,
        series_number=uuid.uuid4().int % 9000 + 1,
        execution_mode="claude_code_cli",
        staging_status=staging_status,
        implementation_launched_at=implementation_launched_at,
        created_at=datetime.now(UTC),
    )
    db_session.add(project)
    db_session.info["tenant_key"] = tenant_key
    await db_session.flush()
    return project.id


async def _seed_product_context(db_session, tenant_key: str) -> None:
    """Org + Product so the tenant is shaped like a real account."""
    suffix = uuid.uuid4().hex[:8]
    org = Organization(name=f"Org {suffix}", slug=f"org-{suffix}", tenant_key=tenant_key, is_active=True)
    db_session.add(org)
    await db_session.flush()
    product = Product(
        id=str(uuid.uuid4()),
        name=f"Product {suffix}",
        description="be-6221a",
        tenant_key=tenant_key,
        is_active=True,
    )
    db_session.add(product)
    await db_session.flush()


# ---------------------------------------------------------------------------
# Recording websocket_manager stub (service broadcast test)
# ---------------------------------------------------------------------------


class _RecordingWS:
    """Records broadcast_event_to_tenant calls (the method SequenceRunService uses)."""

    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, Any]]] = []

    async def broadcast_event_to_tenant(self, tenant_key: str, event: dict[str, Any]) -> None:
        self.events.append((tenant_key, event))


# ---------------------------------------------------------------------------
# MCP transport fixture (mirrors test_progress_workflow_status_mcp_transport)
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def primary_tenant_key() -> str:
    return TenantManager.generate_tenant_key()


class _TenantSwitch:
    def __init__(self, value: str):
        self.value = value


@pytest_asyncio.fixture
async def chain_mcp_client(db_manager, db_session, primary_tenant_key, monkeypatch):
    """Yield (new_client, tenant_switch) for the in-memory FastMCP transport.

    The ToolAccessor is bound to the rolled-back test session so the new tool's
    service construction, validation reads, and conductor mint all live inside
    the test transaction.
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


# ---------------------------------------------------------------------------
# MCP-boundary: happy path
# ---------------------------------------------------------------------------


async def test_start_chain_run_happy_path_returns_conductor_and_staging_bootstrap(
    chain_mcp_client, db_session, primary_tenant_key
):
    new_client, _switch = chain_mcp_client
    await _seed_product_context(db_session, primary_tenant_key)
    p1 = await _seed_project(db_session, primary_tenant_key)
    p2 = await _seed_project(db_session, primary_tenant_key)
    await db_session.commit()

    async with new_client() as session:
        result = await session.call_tool(
            "start_chain_run",
            {"project_ids": [p1, p2], "execution_mode": "claude_code_cli"},
        )
        assert result.is_error is False, _error_text(result)
        payload = _payload(result)

    assert payload["success"] is True
    assert payload["conductor_agent_id"], "conductor_agent_id must be returned"
    assert payload["conductor_job_id"], "conductor_job_id must be returned (needed to bootstrap)"
    assert payload["run"]["project_ids"] == [p1, p2]

    # MUST-FIX #4: the next_action bootstraps the project-less conductor's DRIVE on the
    # current build via get_staging_instructions (the dashboard Run Sequential -> Stage
    # flow), NOT get_job_mission (which is the LATER implementation-phase drive).
    assert payload["bootstrap_tool"] == "get_staging_instructions"
    assert payload["bootstrap_tool"] != "get_job_mission"
    next_action = payload["next_action"]
    assert next_action["tool"] == "get_staging_instructions"
    assert next_action["args_hint"] == {"job_id": payload["conductor_job_id"]}
    # get_job_mission is only named as the follow-on impl-phase drive in `why`, never
    # as the bootstrap tool itself.
    assert next_action["tool"] != "get_job_mission"
    assert "get_job_mission" in next_action["why"]


async def test_start_chain_run_persists_chain_mission(chain_mcp_client, db_session, primary_tenant_key):
    new_client, _switch = chain_mcp_client
    await _seed_product_context(db_session, primary_tenant_key)
    p1 = await _seed_project(db_session, primary_tenant_key)
    p2 = await _seed_project(db_session, primary_tenant_key)
    await db_session.commit()

    async with new_client() as session:
        result = await session.call_tool(
            "start_chain_run",
            {
                "project_ids": [p1, p2],
                "execution_mode": "multi_terminal",
                "chain_mission": "Ship the linked feature across both projects.",
            },
        )
        assert result.is_error is False, _error_text(result)
        payload = _payload(result)

    assert payload["success"] is True
    assert payload["run"]["chain_mission"] == "Ship the linked feature across both projects."


# ---------------------------------------------------------------------------
# MCP-boundary: structured rejections (BE-6081 carve-out — success:false, not raised)
# ---------------------------------------------------------------------------


async def test_rejects_nonexistent_project(chain_mcp_client, db_session, primary_tenant_key):
    new_client, _switch = chain_mcp_client
    await _seed_product_context(db_session, primary_tenant_key)
    p1 = await _seed_project(db_session, primary_tenant_key)
    await db_session.commit()
    ghost = str(uuid.uuid4())

    async with new_client() as session:
        result = await session.call_tool(
            "start_chain_run",
            {"project_ids": [p1, ghost], "execution_mode": "claude_code_cli"},
        )
        assert result.is_error is False, _error_text(result)
        payload = _payload(result)

    assert payload["success"] is False
    assert payload["error"] == "PROJECT_NOT_FOUND"
    assert ghost in payload["project_ids"]


async def test_rejects_terminal_project(chain_mcp_client, db_session, primary_tenant_key):
    new_client, _switch = chain_mcp_client
    await _seed_product_context(db_session, primary_tenant_key)
    live = await _seed_project(db_session, primary_tenant_key)
    done = await _seed_project(db_session, primary_tenant_key, status="completed")
    await db_session.commit()

    async with new_client() as session:
        result = await session.call_tool(
            "start_chain_run",
            {"project_ids": [live, done], "execution_mode": "claude_code_cli"},
        )
        assert result.is_error is False, _error_text(result)
        payload = _payload(result)

    assert payload["success"] is False
    assert payload["error"] == "PROJECT_NOT_CHAINABLE"
    assert payload["reason"] == "terminal"
    assert done in payload["project_ids"]


async def test_rejects_already_enrolled_project(chain_mcp_client, db_session, primary_tenant_key):
    new_client, _switch = chain_mcp_client
    await _seed_product_context(db_session, primary_tenant_key)
    p1 = await _seed_project(db_session, primary_tenant_key)
    p2 = await _seed_project(db_session, primary_tenant_key)
    p3 = await _seed_project(db_session, primary_tenant_key)

    # Enroll p1 + p2 in a live run first (the owning service, same test session).
    await SequenceRunService(db_manager=None, tenant_manager=TenantManager(), session=db_session).create(
        project_ids=[p1, p2],
        resolved_order=[p1, p2],
        execution_mode="claude_code_cli",
        tenant_key=primary_tenant_key,
    )
    await db_session.commit()

    async with new_client() as session:
        result = await session.call_tool(
            "start_chain_run",
            {"project_ids": [p1, p3], "execution_mode": "claude_code_cli"},
        )
        assert result.is_error is False, _error_text(result)
        payload = _payload(result)

    assert payload["success"] is False
    assert payload["error"] == "PROJECT_NOT_CHAINABLE"
    assert payload["reason"] == "already_enrolled"
    assert p1 in payload["project_ids"]


async def test_rejects_member_awaiting_solo_implement(chain_mcp_client, db_session, primary_tenant_key):
    """BE-9069 (Defect A): a project parked at the SOLO human Implement gate
    (staging_status='staging_complete' with implementation_launched_at NULL) is refused
    enrollment — else start_chain_run would cross that project's sacred Implement gate as a
    side effect, with zero human GO (BE-6115a)."""
    new_client, _switch = chain_mcp_client
    await _seed_product_context(db_session, primary_tenant_key)
    live = await _seed_project(db_session, primary_tenant_key)
    parked = await _seed_project(db_session, primary_tenant_key, staging_status="staging_complete")
    await db_session.commit()

    async with new_client() as session:
        result = await session.call_tool(
            "start_chain_run",
            {"project_ids": [live, parked], "execution_mode": "claude_code_cli"},
        )
        assert result.is_error is False, _error_text(result)
        payload = _payload(result)

    assert payload["success"] is False
    assert payload["error"] == "PROJECT_NOT_CHAINABLE"
    assert payload["reason"] == "awaiting_implement"
    assert parked in payload["project_ids"]


async def test_rejects_launched_member(chain_mcp_client, db_session, primary_tenant_key):
    """BE-9069 (Defect B): a project already in implementation (implementation_launched_at
    set) is refused enrollment — enrolling it mid-flight forces a forbidden mixed-mode chain
    (the conductor re-stamp keeps its old execution_mode) and downgrades its live
    staging_status."""
    new_client, _switch = chain_mcp_client
    await _seed_product_context(db_session, primary_tenant_key)
    live = await _seed_project(db_session, primary_tenant_key)
    launched = await _seed_project(
        db_session,
        primary_tenant_key,
        staging_status="staging_complete",
        implementation_launched_at=datetime.now(UTC),
    )
    await db_session.commit()

    async with new_client() as session:
        result = await session.call_tool(
            "start_chain_run",
            {"project_ids": [live, launched], "execution_mode": "claude_code_cli"},
        )
        assert result.is_error is False, _error_text(result)
        payload = _payload(result)

    assert payload["success"] is False
    assert payload["error"] == "PROJECT_NOT_CHAINABLE"
    assert payload["reason"] == "already_launched"
    assert launched in payload["project_ids"]


async def test_rejects_one_member_chain(chain_mcp_client, db_session, primary_tenant_key):
    new_client, _switch = chain_mcp_client
    await _seed_product_context(db_session, primary_tenant_key)
    p1 = await _seed_project(db_session, primary_tenant_key)
    await db_session.commit()

    async with new_client() as session:
        result = await session.call_tool(
            "start_chain_run",
            {"project_ids": [p1], "execution_mode": "claude_code_cli"},
        )
        assert result.is_error is False, _error_text(result)
        payload = _payload(result)

    assert payload["success"] is False
    assert payload["error"] == "CHAIN_TOO_SMALL"


async def test_rejects_non_permutation_resolved_order(chain_mcp_client, db_session, primary_tenant_key):
    new_client, _switch = chain_mcp_client
    await _seed_product_context(db_session, primary_tenant_key)
    p1 = await _seed_project(db_session, primary_tenant_key)
    p2 = await _seed_project(db_session, primary_tenant_key)
    await db_session.commit()
    stranger = str(uuid.uuid4())

    async with new_client() as session:
        result = await session.call_tool(
            "start_chain_run",
            {"project_ids": [p1, p2], "resolved_order": [p1, stranger], "execution_mode": "claude_code_cli"},
        )
        assert result.is_error is False, _error_text(result)
        payload = _payload(result)

    assert payload["success"] is False
    assert payload["error"] == "RESOLVED_ORDER_MISMATCH"


# ---------------------------------------------------------------------------
# SERVICE: create() broadcasts sequence:updated after commit (MUST-FIX #2)
# ---------------------------------------------------------------------------


async def test_create_broadcasts_sequence_updated(db_session, primary_tenant_key):
    p1 = await _seed_project(db_session, primary_tenant_key)
    p2 = await _seed_project(db_session, primary_tenant_key)

    ws = _RecordingWS()
    svc = SequenceRunService(
        db_manager=None,
        tenant_manager=TenantManager(),
        session=db_session,
        websocket_manager=ws,
    )
    run = await svc.create(
        project_ids=[p1, p2],
        resolved_order=[p1, p2],
        execution_mode="claude_code_cli",
        tenant_key=primary_tenant_key,
    )

    assert len(ws.events) == 1, "create() must fire exactly one sequence:updated broadcast"
    tenant_arg, event = ws.events[0]
    assert tenant_arg == primary_tenant_key
    assert event["type"] == "sequence:updated"
    assert event["data"]["run_id"] == run["id"]
