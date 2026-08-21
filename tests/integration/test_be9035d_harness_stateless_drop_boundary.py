# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-9035d -- persisted harness drives the render when the live clientInfo is dropped.

FINDING #4 (found LIVE on test.giljo.ai by a real Claude Code CLI): runtime harness
detection did NOT resolve on the ``get_staging_instructions`` render path. The server is
``FastMCP(stateless_http=True)``, which drops the ``initialize`` clientInfo on every
non-``initialize`` tools/call, so ``_detected_harness`` read empty ``client_params`` ->
``generic`` -> a claude-code CLI got the ``<your-harness>`` generic_mcp ladder instead of
the Claude-native ``Task(subagent_type=...)`` spawn prose.

This drives the REAL FastMCP transport (``create_connected_server_and_client_session``)
and EXPLICITLY reproduces the stateless drop: the live clientInfo is ABSENT on the call
(``client_info=None`` on the handshake), so ``_detected_harness``'s live axis resolves to
generic exactly as it does in prod. The harness the middleware would have stamped onto
scope state at initialize time is simulated by monkeypatching ``_persisted_harness`` (the
in-memory transport carries no HTTP request/scope; the fixture already monkeypatches
``_resolve_tenant`` for the same reason). The FULL end-to-end capture+stamp path is proven
separately at the ASGI middleware in ``tests/api/test_be9035d_harness_capture_and_stamp``.

The existing BE-9035b boundary test is green because the in-memory transport KEEPS
``client_params`` populated -- it never reproduces the stateless drop. That green-unit /
dead-seam gap is exactly the BE-5042 class, so per CLAUDE.md's failing-layer mandate this
regression pins the render at the transport with the live axis forced empty.

Parallel-safe: DB-touching tests use the db_session fixture (TransactionalTestContext,
rollback at teardown). No module-level mutable state. Edition Scope: Both.
"""

from __future__ import annotations

import json
import random
import uuid
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from mcp.types import Implementation

from giljo_mcp.models.agent_identity import AgentExecution, AgentJob
from giljo_mcp.models.organizations import Organization
from giljo_mcp.models.products import Product
from giljo_mcp.models.projects import Project
from giljo_mcp.tenant import TenantManager
from tests.helpers.mcp_session_fixture import create_connected_server_and_client_session


pytestmark = pytest.mark.asyncio


# Render markers (lock-step with chapters_reference: the CLAUDE block header + the
# Claude-native spawn syntax vs the generic_mcp ladder header + its <your-harness> token).
_CLAUDE_BLOCK = "YOUR PLATFORM: CLAUDE CODE CLI"
_CLAUDE_SPAWN = "Task(subagent_type="
_GENERIC_MCP_BLOCK = "ANY MCP-CONNECTED AGENT (generic_mcp)"
_GENERIC_PLACEHOLDER = "<your-harness>"

_CLAUDE_CODE_INFO = Implementation(name="claude-code", version="2.1.199")


def _payload(result) -> dict:
    if getattr(result, "structuredContent", None):
        return result.structured_content
    first = result.content[0]
    text = getattr(first, "text", None)
    if text is None:  # pragma: no cover - defensive
        raise AssertionError(f"unexpected content block: {first!r}")
    return json.loads(text)


def _error_text(result) -> str:
    return "\n".join(b.text for b in result.content if getattr(b, "text", None))


@pytest_asyncio.fixture
async def mcp_client(db_manager, db_session, monkeypatch):
    from api import app_state
    from api.endpoints import mcp_sdk_server
    from api.endpoints.mcp_tools import _base
    from giljo_mcp.tools.tool_accessor import ToolAccessor

    state = app_state.state
    prior_accessor = state.tool_accessor
    prior_tenant_manager = state.tenant_manager
    prior_db_manager = state.db_manager

    if state.tenant_manager is None:
        state.tenant_manager = TenantManager()
    state.db_manager = db_manager

    tenant_key = TenantManager.generate_tenant_key()
    state.tool_accessor = ToolAccessor(
        db_manager=db_manager, tenant_manager=state.tenant_manager, test_session=db_session
    )

    monkeypatch.setattr(_base, "_resolve_tenant", lambda ctx: tenant_key)
    monkeypatch.setattr(_base, "_resolve_user_id", lambda ctx: None)

    def _client(client_info: Implementation | None = None):
        return create_connected_server_and_client_session(mcp_sdk_server.mcp, client_info=client_info)

    try:
        yield _client, tenant_key, db_session, monkeypatch
    finally:
        state.tool_accessor = prior_accessor
        state.tenant_manager = prior_tenant_manager
        state.db_manager = prior_db_manager


async def _seed_org_product(db_session, tenant_key: str) -> str:
    suffix = uuid.uuid4().hex[:8]
    org = Organization(name=f"Org {suffix}", slug=f"org-{suffix}", tenant_key=tenant_key, is_active=True)
    db_session.add(org)
    await db_session.flush()
    product = Product(
        id=str(uuid.uuid4()), name=f"Product {suffix}", description="be-9035d", tenant_key=tenant_key, is_active=True
    )
    db_session.add(product)
    await db_session.flush()
    return product.id


async def _seed_orchestrator(db_session, tenant_key: str, product_id: str, execution_mode: str) -> str:
    """An orchestrator job in staging for a project of ``execution_mode``, so
    get_staging_instructions renders the orchestrator protocol (incl. CH3)."""
    now = datetime.now(UTC)
    project = Project(
        id=str(uuid.uuid4()),
        tenant_key=tenant_key,
        product_id=product_id,
        name=f"BE-9035d orch {uuid.uuid4().hex[:8]}",
        description=f"{execution_mode} orchestrator",
        mission="build it",
        status="active",
        staging_status="staging",
        series_number=random.randint(1, 9000),
        execution_mode=execution_mode,
        created_at=now,
    )
    db_session.add(project)
    db_session.info["tenant_key"] = tenant_key
    await db_session.flush()

    job = AgentJob(
        job_id=str(uuid.uuid4()),
        tenant_key=tenant_key,
        project_id=project.id,
        job_type="orchestrator",
        mission="BE-9035d orchestrator mission",
        status="active",
        created_at=now,
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
        started_at=now,
    )
    db_session.add(execution)
    await db_session.commit()
    return job.job_id


async def _ch3_for(client, client_info, job_id) -> str:
    async with client(client_info) as session:
        result = await session.call_tool("get_staging_instructions", {"job_id": job_id})
        assert result.is_error is False, _error_text(result)
        payload = _payload(result)
    return payload["orchestrator_protocol"]["ch3_agent_spawning_rules"]


def _force_persisted(monkeypatch, harness: str) -> None:
    """Simulate the middleware having stamped ``resolved_harness`` onto scope state.

    ``_detected_harness`` reads the persisted value via ``_persisted_harness`` (both live
    in ``_harness``); the in-memory transport carries no HTTP scope, so we substitute the
    read (mirrors the fixture's ``_resolve_tenant`` monkeypatch)."""
    from api.endpoints.mcp_tools import _harness

    monkeypatch.setattr(_harness, "_persisted_harness", lambda ctx: harness)


async def test_persisted_harness_drives_claude_render_when_live_dropped(mcp_client):
    """The stateless drop (no live clientInfo) + a persisted claude-code token ->
    CH3 renders the Claude Code CLI block with Task(subagent_type=...), NOT the
    generic_mcp <your-harness> ladder. This is FINDING #4's exact failing path."""
    client, tenant_key, db_session, monkeypatch = mcp_client
    product_id = await _seed_org_product(db_session, tenant_key)
    job_id = await _seed_orchestrator(db_session, tenant_key, product_id, "generic_mcp")

    _force_persisted(monkeypatch, "claude-code")
    # client_info=None -> the live clientInfo axis resolves to generic (the stateless drop).
    ch3 = await _ch3_for(client, None, job_id)

    assert _CLAUDE_BLOCK in ch3, "persisted claude-code must render the Claude Code CLI spawn block"
    assert _CLAUDE_SPAWN in ch3, "the claude render must carry the Task(subagent_type=...) spawn syntax"
    assert _GENERIC_MCP_BLOCK not in ch3, "the persisted harness must replace the generic_mcp ladder"
    assert _GENERIC_PLACEHOLDER not in ch3, "no <your-harness> placeholder once the harness is recovered"


async def test_no_persisted_harness_is_generic_floor(mcp_client):
    """Live dropped AND nothing persisted -> the generic_mcp ladder renders (the fallback
    fabricates nothing; the byte-identity floor holds)."""
    client, tenant_key, db_session, monkeypatch = mcp_client
    product_id = await _seed_org_product(db_session, tenant_key)
    job_id = await _seed_orchestrator(db_session, tenant_key, product_id, "generic_mcp")

    _force_persisted(monkeypatch, "generic")  # stamp skips generic in prod; simulate "nothing recovered"
    ch3 = await _ch3_for(client, None, job_id)

    assert _GENERIC_MCP_BLOCK in ch3, "no recovered harness -> the generic_mcp ladder must render"
    assert _CLAUDE_BLOCK not in ch3, "the fallback must never fabricate a claude render"


async def test_live_client_info_wins_over_persisted(mcp_client):
    """A concrete LIVE clientInfo (initialize path, where client_params survives) wins
    outright -- the persisted value is never consulted. Proves live stays primary."""
    client, tenant_key, db_session, monkeypatch = mcp_client
    product_id = await _seed_org_product(db_session, tenant_key)
    job_id = await _seed_orchestrator(db_session, tenant_key, product_id, "generic_mcp")

    # Persisted says codex, but the live handshake declares claude-code -> live wins.
    _force_persisted(monkeypatch, "codex")
    ch3 = await _ch3_for(client, _CLAUDE_CODE_INFO, job_id)

    assert _CLAUDE_BLOCK in ch3, "a live claude-code clientInfo must win over the persisted token"
    assert _GENERIC_MCP_BLOCK not in ch3
