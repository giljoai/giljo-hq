# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-8003f (D2 activation) — the harness param, proven LIVE at the MCP transport.

WO-8003f2 threaded a session ``harness`` preset from the ``get_job_mission`` +
``get_staging_instructions`` @mcp.tool wrappers all the way into the preset-ready
S1-S4 builders BE-8003f shipped. BE-8003f's own tests prove the builders render the
PREFERRED/FALLBACK/FLOOR ladder when handed a ``preset``; they do NOT prove a preset
ever REACHES them from a real tool call. That gap is exactly the BE-5042 class of bug
(green unit coverage, dead wrapper), so per CLAUDE.md's failing-layer mandate this
drives the REAL FastMCP transport (``create_connected_server_and_client_session``) —
the first live proof of the whole (d)->(e)->(f) stack:

  * ``get_job_mission(harness="chat")`` on a worker -> S4 chat render ([FLOOR] present,
    the shell env-detection aside GONE);
  * ``get_staging_instructions(harness="web_sandbox")`` on a chain conductor -> S1
    CH_CAPABILITY inline-conducting ladder ([FLOOR] + INLINE CONDUCTING, terminal-spawn
    markers gone);
  * the default (``harness=""``) and a GARBAGE harness both degrade to None -> the CLI
    render (byte-identity floor: the shell aside / non-inline capability comes back).

Parallel-safe: DB-touching tests use the db_session fixture (TransactionalTestContext,
rollback at teardown). No module-level mutable state. Edition Scope: Both.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime

import pytest
import pytest_asyncio

from giljo_mcp.models.agent_identity import AgentExecution, AgentJob
from giljo_mcp.models.organizations import Organization
from giljo_mcp.models.products import Product
from giljo_mcp.models.projects import Project
from giljo_mcp.tenant import TenantManager
from tests.helpers.mcp_session_fixture import create_connected_server_and_client_session


pytestmark = pytest.mark.asyncio

# Markers (kept in lock-step with tests/services/test_be8003f_render_ladder.py).
_FLOOR = "[FLOOR]"
_INLINE = "INLINE CONDUCTING"  # S1 capability, preset-active only
_WEB_SANDBOX_LABEL = "Web Sandbox"
_SHELL_ASIDE = "ENVIRONMENT DETECTION"  # S4 worker shell probe — gated OFF on a chat harness
_CHAT_ASIDE = "NO SHELL (chat session)"
# Terminal-launch markers the S1 preset render must NOT leak.
_S1_GATED = ("wt -w 0", "gnome-terminal", "osascript", "$DISPLAY", "$WAYLAND_DISPLAY")


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


# ---------------------------------------------------------------------------
# Transport fixture (mirrors test_be6221a_start_chain_run.chain_mcp_client)
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def tenant_key() -> str:
    return TenantManager.generate_tenant_key()


@pytest_asyncio.fixture
async def mcp_client(db_manager, db_session, tenant_key, monkeypatch):
    """Yield a factory for the in-memory FastMCP transport with the ToolAccessor bound
    to the rolled-back test session, so tool service construction + reads live inside
    the test transaction."""
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
    state.tool_accessor = ToolAccessor(
        db_manager=db_manager, tenant_manager=state.tenant_manager, test_session=db_session
    )

    monkeypatch.setattr(_base, "_resolve_tenant", lambda ctx: tenant_key)
    monkeypatch.setattr(_base, "_resolve_user_id", lambda ctx: None)

    def _client():
        return create_connected_server_and_client_session(mcp_sdk_server.mcp)

    try:
        yield _client
    finally:
        state.tool_accessor = prior_accessor
        state.tenant_manager = prior_tenant_manager
        state.db_manager = prior_db_manager


# ---------------------------------------------------------------------------
# Seed helpers
# ---------------------------------------------------------------------------


async def _seed_product(db_session, tenant_key: str) -> str:
    suffix = uuid.uuid4().hex[:8]
    org = Organization(name=f"Org {suffix}", slug=f"org-{suffix}", tenant_key=tenant_key, is_active=True)
    db_session.add(org)
    await db_session.flush()
    product = Product(
        id=str(uuid.uuid4()), name=f"Product {suffix}", description="be-8003f2", tenant_key=tenant_key, is_active=True
    )
    db_session.add(product)
    await db_session.flush()
    return product.id


async def _seed_chain_project(db_session, tenant_key: str) -> str:
    """A chainable (active, non-terminal) project in claude_code_cli mode.

    product_id is left NULL: the partial unique index idx_project_single_active_per_product
    forbids two ACTIVE projects sharing one product, and a chain needs two active members.
    """
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
        name=f"BE-8003f2 {uuid.uuid4().hex[:8]}",
        description="chain member",
        mission="build it",
        status="active",
        series_number=uuid.uuid4().int % 9000 + 1,
        execution_mode="claude_code_cli",
        created_at=datetime.now(UTC),
    )
    db_session.add(project)
    db_session.info["tenant_key"] = tenant_key
    await db_session.flush()
    return project.id


async def _seed_impl_worker(db_session, tenant_key: str, product_id: str) -> str:
    """A launched-implementation worker job whose execution is 'waiting' so
    get_job_mission renders the full S4 worker protocol (past the impl gate)."""
    now = datetime.now(UTC)
    project = Project(
        id=str(uuid.uuid4()),
        tenant_key=tenant_key,
        product_id=product_id,
        name=f"BE-8003f2 worker {uuid.uuid4().hex[:8]}",
        description="worker host",
        mission="ship it",
        status="active",
        series_number=uuid.uuid4().int % 9000 + 1,
        execution_mode="multi_terminal",
        staging_status="staging_complete",
        implementation_launched_at=now,
        created_at=now,
    )
    db_session.add(project)
    db_session.info["tenant_key"] = tenant_key
    await db_session.flush()

    job = AgentJob(
        job_id=str(uuid.uuid4()),
        tenant_key=tenant_key,
        project_id=project.id,
        job_type="implementer",
        mission="BE-8003f2 worker mission",
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
        agent_display_name="implementer",
        status="waiting",
        started_at=now,
    )
    db_session.add(execution)
    await db_session.commit()
    return job.job_id


# ---------------------------------------------------------------------------
# get_job_mission — the runtime worker path (S4)
# ---------------------------------------------------------------------------


async def test_get_job_mission_chat_harness_renders_shell_less_worker(mcp_client, db_session, tenant_key):
    """harness='chat' must reach the S4 worker render: the [FLOOR] line is present and
    the shell env-detection aside is gone. This is the whole (d)->(e)->(f) stack, live."""
    product_id = await _seed_product(db_session, tenant_key)
    job_id = await _seed_impl_worker(db_session, tenant_key, product_id)

    async with mcp_client() as session:
        result = await session.call_tool("get_job_mission", {"job_id": job_id, "harness": "chat"})
        assert result.is_error is False, _error_text(result)
        payload = _payload(result)

    protocol = payload["full_protocol"]
    assert protocol, "worker mission must carry a full_protocol"
    assert _FLOOR in protocol, "chat render must carry the [FLOOR] fallback line"
    assert _CHAT_ASIDE in protocol, "chat render must carry the shell-less worker banner"
    # DoD: the gated CLI-ism (the shell env-detection probe) is absent on a chat harness.
    assert _SHELL_ASIDE not in protocol, "chat render leaked the shell env-detection aside"


@pytest.mark.parametrize("harness", ["", "not_a_real_harness"])
async def test_get_job_mission_default_and_garbage_harness_degrade_to_cli(mcp_client, db_session, tenant_key, harness):
    """harness='' (every existing caller) AND a garbage token both degrade to None ->
    the CLI render: the shell aside comes back, the chat banner never appears. This is
    the byte-identity floor + the select_effective_preset tier degrade, proven live."""
    product_id = await _seed_product(db_session, tenant_key)
    job_id = await _seed_impl_worker(db_session, tenant_key, product_id)

    async with mcp_client() as session:
        result = await session.call_tool("get_job_mission", {"job_id": job_id, "harness": harness})
        assert result.is_error is False, _error_text(result)
        payload = _payload(result)

    protocol = payload["full_protocol"]
    assert _SHELL_ASIDE in protocol, f"CLI render (harness={harness!r}) must keep the shell env-detection aside"
    assert _CHAT_ASIDE not in protocol, f"CLI render (harness={harness!r}) must NOT carry the chat banner"


# ---------------------------------------------------------------------------
# get_staging_instructions — the chain-conductor staging path (S1)
# ---------------------------------------------------------------------------


async def _start_chain_and_get_conductor(session, p1: str, p2: str) -> str:
    """Mint a project-less chain conductor via start_chain_run; return its job_id."""
    result = await session.call_tool("start_chain_run", {"project_ids": [p1, p2], "execution_mode": "claude_code_cli"})
    assert result.is_error is False, _error_text(result)
    payload = _payload(result)
    assert payload["success"] is True
    return payload["conductor_job_id"]


async def test_get_staging_instructions_web_sandbox_renders_inline_conducting(mcp_client, db_session, tenant_key):
    """harness='web_sandbox' on a chain conductor must reach S1 CH_CAPABILITY: the
    inline-conducting ladder ([FLOOR] + INLINE CONDUCTING + the preset label), with the
    terminal-spawn markers gated OFF."""
    await _seed_product(db_session, tenant_key)  # shape the tenant (org+product), projects stay unlinked
    p1 = await _seed_chain_project(db_session, tenant_key)
    p2 = await _seed_chain_project(db_session, tenant_key)
    await db_session.commit()

    async with mcp_client() as session:
        conductor_job_id = await _start_chain_and_get_conductor(session, p1, p2)
        result = await session.call_tool(
            "get_staging_instructions", {"job_id": conductor_job_id, "harness": "web_sandbox"}
        )
        assert result.is_error is False, _error_text(result)
        payload = _payload(result)

    assert payload["status"] == "CHAIN_CONDUCTOR_STAGING"
    capability = payload["orchestrator_protocol"]["ch_capability"]
    assert _INLINE in capability, "web_sandbox conductor must render the inline-conducting capability"
    assert _FLOOR in capability, "web_sandbox conductor capability must carry the [FLOOR] line"
    assert _WEB_SANDBOX_LABEL in capability
    for marker in _S1_GATED:
        assert marker not in capability, f"web_sandbox conductor capability leaked terminal marker {marker!r}"


@pytest.mark.parametrize("harness", ["", "not_a_real_harness"])
async def test_get_staging_instructions_default_and_garbage_degrade_to_cli(mcp_client, db_session, tenant_key, harness):
    """harness='' AND a garbage token degrade to None -> the CLI conductor render:
    the inline-conducting marker never appears (it is preset-active only)."""
    await _seed_product(db_session, tenant_key)  # shape the tenant (org+product), projects stay unlinked
    p1 = await _seed_chain_project(db_session, tenant_key)
    p2 = await _seed_chain_project(db_session, tenant_key)
    await db_session.commit()

    async with mcp_client() as session:
        conductor_job_id = await _start_chain_and_get_conductor(session, p1, p2)
        result = await session.call_tool("get_staging_instructions", {"job_id": conductor_job_id, "harness": harness})
        assert result.is_error is False, _error_text(result)
        payload = _payload(result)

    assert payload["status"] == "CHAIN_CONDUCTOR_STAGING"
    capability = payload["orchestrator_protocol"]["ch_capability"]
    assert _INLINE not in capability, (
        f"CLI conductor render (harness={harness!r}) must NOT carry the inline-conducting marker"
    )
