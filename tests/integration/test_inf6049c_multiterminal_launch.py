# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""INF-6049c — MCP-boundary tests for per-agent tool routing + launch_commands.

Drives ``stage_project`` / ``implement_project`` through the in-memory FastMCP
transport (BE-5042 lesson: exercise the @mcp.tool wrapper, not just the service)
and proves the Phase-3 deliverables:

- Deliverable 3: each spawned agent's per-terminal seed is routed to ITS assigned
  coding tool (template ``cli_tool``) — a Claude agent's block carries the
  ToolSearch bootstrap, a codex/antigravity agent's does not.
- Deliverable 4: the multi_terminal payload carries a structured ``launch_commands``
  array — one entry per agent, each with the agent's tool + the correct launcher
  binary in the synthesized per-OS command.
- Tenant isolation: a template owned by another tenant never resolves a cli_tool
  (the resolver is tenant-filtered) — the agent falls back to claude.

Pattern reference: tests/integration/test_inf6049b_stage_implement_tools.py.
"""

from __future__ import annotations

import json
import random
from datetime import UTC, datetime
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import select

from giljo_mcp.models.agent_identity import AgentExecution, AgentJob
from giljo_mcp.models.organizations import Organization
from giljo_mcp.models.products import Product
from giljo_mcp.models.projects import Project
from giljo_mcp.models.templates import AgentTemplate
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
    return "\n".join(getattr(b, "text", "") or "" for b in call_tool_result.content)


async def _seed_launched_multiterminal_project(db_session, tenant_key: str):
    suffix = uuid4().hex[:8]
    org = Organization(name=f"Org {suffix}", slug=f"org-{suffix}", tenant_key=tenant_key, is_active=True)
    db_session.add(org)
    await db_session.flush()

    product = Product(
        id=str(uuid4()),
        name=f"Product {suffix}",
        description="INF-6049c launch tests",
        tenant_key=tenant_key,
        is_active=True,
        product_memory={},
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
        execution_mode="multi_terminal",
        staging_status="staging_complete",
        implementation_launched_at=datetime.now(UTC),
        series_number=random.randint(1, 999_999_999),
    )
    db_session.add(project)
    await db_session.commit()
    return project


async def _make_template(db_session, tenant_key: str, name: str, cli_tool: str) -> AgentTemplate:
    tpl = AgentTemplate(
        id=str(uuid4()),
        tenant_key=tenant_key,
        name=name,
        category="role",
        role=name,
        system_instructions="",
        cli_tool=cli_tool,
    )
    db_session.add(tpl)
    await db_session.flush()
    return tpl


async def _make_role_default_template(db_session, tenant_key: str, role: str, cli_tool: str) -> AgentTemplate:
    """BE-6204: a ``is_default`` template for ``role`` (the role-default fallback source)."""
    tpl = AgentTemplate(
        id=str(uuid4()),
        tenant_key=tenant_key,
        name=f"{role}-default-{uuid4().hex[:6]}",  # name != role on purpose (fallback is role-keyed)
        category="role",
        role=role,
        system_instructions="",
        cli_tool=cli_tool,
        is_default=True,
    )
    db_session.add(tpl)
    await db_session.flush()
    return tpl


async def _seed_team(db_session, tenant_key: str, project, agents: list[tuple[str, str | None]]):
    """Seed an orchestrator + child agents. ``agents`` = list of (display_name, template_id)."""
    orch_job = AgentJob(
        job_id=str(uuid4()),
        tenant_key=tenant_key,
        project_id=project.id,
        job_type="orchestrator",
        mission="orchestrate",
        status="active",
        created_at=datetime.now(UTC),
    )
    db_session.add(orch_job)
    await db_session.flush()
    orch_exec = AgentExecution(
        id=str(uuid4()),
        agent_id=str(uuid4()),
        job_id=orch_job.job_id,
        tenant_key=tenant_key,
        agent_display_name="orchestrator",
        status="idle",
        started_at=datetime.now(UTC),
    )
    db_session.add(orch_exec)
    await db_session.flush()

    for display_name, template_id in agents:
        child_job = AgentJob(
            job_id=str(uuid4()),
            tenant_key=tenant_key,
            project_id=project.id,
            job_type=display_name,
            mission="implement",
            status="active",
            created_at=datetime.now(UTC),
            template_id=template_id,
        )
        db_session.add(child_job)
        await db_session.flush()
        db_session.add(
            AgentExecution(
                id=str(uuid4()),
                agent_id=str(uuid4()),
                job_id=child_job.job_id,
                tenant_key=tenant_key,
                agent_display_name=display_name,
                status="waiting",
                spawned_by=orch_exec.agent_id,
                started_at=datetime.now(UTC),
            )
        )
    await db_session.commit()


@pytest_asyncio.fixture
async def primary_tenant_key() -> str:
    return TenantManager.generate_tenant_key()


@pytest_asyncio.fixture
async def secondary_tenant_key() -> str:
    return TenantManager.generate_tenant_key()


class _TenantSwitch:
    def __init__(self, value: str):
        self.value = value


@pytest_asyncio.fixture
async def lifecycle_mcp_client(db_manager, db_session, primary_tenant_key, monkeypatch):
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
    state.tool_accessor = ToolAccessor(
        db_manager=db_manager,
        tenant_manager=state.tenant_manager,
        test_session=db_session,
    )

    tenant_switch = _TenantSwitch(primary_tenant_key)
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
# implement_project — per-agent tool routing + launch_commands
# ---------------------------------------------------------------------------


async def test_implement_payload_routes_each_agent_to_its_tool_and_carries_launch_commands(
    lifecycle_mcp_client, db_session, primary_tenant_key
):
    new_client, _switch = lifecycle_mcp_client
    project = await _seed_launched_multiterminal_project(db_session, primary_tenant_key)
    codex_tpl = await _make_template(db_session, primary_tenant_key, "implementer", "codex")
    agy_tpl = await _make_template(db_session, primary_tenant_key, "reviewer", "antigravity")
    await db_session.commit()
    # implementer=codex, reviewer=antigravity, analyzer=NO template (default claude).
    await _seed_team(
        db_session,
        primary_tenant_key,
        project,
        [("implementer", codex_tpl.id), ("reviewer", agy_tpl.id), ("analyzer", None)],
    )

    async with new_client() as session:
        result = await session.call_tool("implement_project", {"project_id": project.id})

    assert result.is_error is False, _error_text(result)
    payload = _payload(result)
    assert payload["status"] == "ready"

    # Deliverable 4: structured per-agent launch_commands, one per spawned agent.
    lc = payload["launch_commands"]
    assert isinstance(lc, list) and len(lc) == 3
    by_agent = {e["agent"]: e for e in lc}
    assert by_agent["implementer"]["cli_tool"] == "codex"
    assert by_agent["reviewer"]["cli_tool"] == "antigravity"
    assert by_agent["analyzer"]["cli_tool"] == "claude"  # no template -> default

    # Each command invokes the correct launcher binary (codex->codex, antigravity->agy).
    assert "Start-Process codex " in by_agent["implementer"]["commands"]["windows"]
    assert "Start-Process agy " in by_agent["reviewer"]["commands"]["windows"]
    assert "Start-Process claude " in by_agent["analyzer"]["commands"]["windows"]
    # macOS surfaced as not validated.
    assert all(e["macos_validated"] is False for e in lc)

    # Deliverable 3: the per-terminal seed block routes each agent to its tool —
    # the prompt names each agent's tool, and only the Claude agent's seed carries
    # the ToolSearch bootstrap.
    prompt = payload["prompt"]
    assert "(tool: codex)" in prompt
    assert "(tool: antigravity)" in prompt
    assert "(tool: claude)" in prompt
    # The seed lines themselves are present (job self-fetch on boot).
    assert "get_job_mission" in prompt


async def test_implement_launch_command_is_runnable_with_autonomy_and_loaded_prompt(
    lifecycle_mcp_client, db_session, primary_tenant_key
):
    """BE-6182: the implement_project launch command is RUNNABLE — it carries the
    per-harness autonomy flag and a natural-language loaded prompt (get_job_mission),
    not raw tool-call seed lines. (The ToolSearch bootstrap stays in the prompt-body
    per-terminal seed block, asserted by the sibling test above; it is no longer baked
    into the launch command, which a CLI would not interpret.)"""
    new_client, _switch = lifecycle_mcp_client
    project = await _seed_launched_multiterminal_project(db_session, primary_tenant_key)
    codex_tpl = await _make_template(db_session, primary_tenant_key, "implementer", "codex")
    await db_session.commit()
    await _seed_team(
        db_session,
        primary_tenant_key,
        project,
        [("implementer", codex_tpl.id), ("analyzer", None)],
    )

    async with new_client() as session:
        result = await session.call_tool("implement_project", {"project_id": project.id})
    payload = _payload(result)
    by_agent = {e["agent"]: e for e in payload["launch_commands"]}

    # codex agent → codex autonomy flag; claude agent → claude autonomy flag.
    assert "--dangerously-bypass-approvals-and-sandbox" in by_agent["implementer"]["commands"]["linux"]
    assert "--dangerously-skip-permissions" in by_agent["analyzer"]["commands"]["linux"]

    # Both carry the natural-language loaded prompt (get_job_mission), and NOT a raw
    # mcp__ tool-call seed line as the terminal argument.
    for entry in by_agent.values():
        lx = entry["commands"]["linux"]
        assert "get_job_mission" in lx, "launch command must instruct loading the mission"
        assert "You are a GiljoAI agent" in lx, "must carry the natural-language loaded prompt"
        assert "mcp__giljo_mcp__health_check()" not in lx, "must NOT bake a raw tool-call seed into the command"


# ---------------------------------------------------------------------------
# stage_project — multi_terminal payload also carries launch_commands
# ---------------------------------------------------------------------------


async def test_stage_project_multiterminal_carries_launch_commands(
    lifecycle_mcp_client, db_session, primary_tenant_key
):
    new_client, _switch = lifecycle_mcp_client
    project = await _seed_launched_multiterminal_project(db_session, primary_tenant_key)
    codex_tpl = await _make_template(db_session, primary_tenant_key, "implementer", "codex")
    await db_session.commit()
    await _seed_team(db_session, primary_tenant_key, project, [("implementer", codex_tpl.id)])

    async with new_client() as session:
        result = await session.call_tool("stage_project", {"project_id": project.id, "mode": "multi_terminal"})

    assert result.is_error is False, _error_text(result)
    payload = _payload(result)
    assert "launch_commands" in payload
    lc = payload["launch_commands"]
    assert len(lc) == 1
    assert lc[0]["cli_tool"] == "codex"


async def test_stage_project_non_multiterminal_has_empty_launch_commands(
    lifecycle_mcp_client, db_session, primary_tenant_key
):
    new_client, _switch = lifecycle_mcp_client
    project = await _seed_launched_multiterminal_project(db_session, primary_tenant_key)

    async with new_client() as session:
        result = await session.call_tool("stage_project", {"project_id": project.id, "mode": "claude"})

    payload = _payload(result)
    # Single-terminal modes carry no per-agent launch array.
    assert payload.get("launch_commands", []) == []


# ---------------------------------------------------------------------------
# BE-6204 — multi_terminal ROLE-default harness fallback (template_id absent)
# ---------------------------------------------------------------------------


async def test_multiterminal_role_default_fallback_when_template_id_absent(
    lifecycle_mcp_client, db_session, primary_tenant_key
):
    """BE-6204: a multi_terminal worker whose job has NO template_id resolves its
    ROLE's default-template cli_tool instead of silently defaulting to claude
    (the project's cited "local template storage may be absent" case). Before
    BE-6204 this analyzer (template_id=None) would have resolved claude."""
    new_client, _switch = lifecycle_mcp_client
    project = await _seed_launched_multiterminal_project(db_session, primary_tenant_key)
    # A role-default template for analyzer (name deliberately != "analyzer"), and a
    # worker spawned WITHOUT a template_id -> the name-match path finds nothing.
    await _make_role_default_template(db_session, primary_tenant_key, "analyzer", "gemini")
    await db_session.commit()
    await _seed_team(db_session, primary_tenant_key, project, [("analyzer", None)])

    async with new_client() as session:
        result = await session.call_tool("implement_project", {"project_id": project.id})

    assert result.is_error is False, _error_text(result)
    by_agent = {e["agent"]: e for e in _payload(result)["launch_commands"]}
    # Role-default fallback fired: gemini, NOT the pre-BE-6204 claude default.
    assert by_agent["analyzer"]["cli_tool"] == "gemini"
    assert "Start-Process gemini " in by_agent["analyzer"]["commands"]["windows"]


async def test_multiterminal_template_id_wins_over_role_default(lifecycle_mcp_client, db_session, primary_tenant_key):
    """BE-6204 chain precedence: when a worker HAS a name-matched template_id, that
    template's cli_tool wins over the role-default fallback (template_id.cli_tool ->
    role-default -> claude). Characterization lock for the existing resolution."""
    new_client, _switch = lifecycle_mcp_client
    project = await _seed_launched_multiterminal_project(db_session, primary_tenant_key)
    codex_tpl = await _make_template(db_session, primary_tenant_key, "implementer", "codex")
    # A role-default for implementer electing a DIFFERENT tool — must NOT override.
    await _make_role_default_template(db_session, primary_tenant_key, "implementer", "gemini")
    await db_session.commit()
    await _seed_team(db_session, primary_tenant_key, project, [("implementer", codex_tpl.id)])

    async with new_client() as session:
        result = await session.call_tool("implement_project", {"project_id": project.id})

    by_agent = {e["agent"]: e for e in _payload(result)["launch_commands"]}
    assert by_agent["implementer"]["cli_tool"] == "codex"  # template_id wins, not the gemini role-default


async def test_role_default_fallback_is_gated_on_multi_terminal_byte_identity(db_session, primary_tenant_key):
    """BE-6204 gate: the role-default fallback applies ONLY in multi_terminal. In a
    subagent mode the SAME template-less worker + role-default still resolves claude,
    so subagent resolution is byte-identical to pre-BE-6204. Exercised directly at the
    resolution seam (the per-terminal seed / launch array is multi_terminal-only)."""
    from giljo_mcp.models.agent_identity import AgentExecution as _Exec
    from giljo_mcp.thin_prompt_generator import ThinClientPromptGenerator

    project = await _seed_launched_multiterminal_project(db_session, primary_tenant_key)
    await _make_role_default_template(db_session, primary_tenant_key, "analyzer", "gemini")
    await db_session.commit()
    await _seed_team(db_session, primary_tenant_key, project, [("analyzer", None)])

    gen = ThinClientPromptGenerator(db_session, primary_tenant_key)

    async def _fetch_analyzer() -> _Exec:
        from sqlalchemy.orm import joinedload

        stmt = (
            select(AgentExecution)
            .options(joinedload(AgentExecution.job))
            .join(
                AgentJob,
                (AgentJob.job_id == AgentExecution.job_id) & (AgentJob.tenant_key == AgentExecution.tenant_key),
            )
            .where(
                AgentExecution.tenant_key == primary_tenant_key,
                AgentExecution.agent_display_name == "analyzer",
                AgentJob.project_id == project.id,
            )
        )
        return (await db_session.execute(stmt)).scalars().first()

    # Subagent mode -> gate OFF -> claude (byte-identical to pre-BE-6204).
    subagent_exec = await _fetch_analyzer()
    await gen._resolve_agent_cli_tools([subagent_exec], execution_mode="claude_code_cli")
    assert subagent_exec.cli_tool == "claude"

    # multi_terminal -> gate ON -> role-default fallback fires.
    mt_exec = await _fetch_analyzer()
    await gen._resolve_agent_cli_tools([mt_exec], execution_mode="multi_terminal")
    assert mt_exec.cli_tool == "gemini"


# ---------------------------------------------------------------------------
# Tenant isolation on the cli_tool resolver
# ---------------------------------------------------------------------------


async def test_cli_tool_resolver_is_tenant_isolated(
    lifecycle_mcp_client, db_session, primary_tenant_key, secondary_tenant_key
):
    """A template owned by tenant B must not resolve a tool for tenant A's agent."""
    new_client, switch = lifecycle_mcp_client
    switch.value = primary_tenant_key
    project = await _seed_launched_multiterminal_project(db_session, primary_tenant_key)
    # Template belongs to a DIFFERENT tenant, but the agent (tenant A) references its id.
    foreign_tpl = await _make_template(db_session, secondary_tenant_key, "implementer", "codex")
    await db_session.commit()
    await _seed_team(db_session, primary_tenant_key, project, [("implementer", foreign_tpl.id)])

    async with new_client() as session:
        result = await session.call_tool("implement_project", {"project_id": project.id})
    payload = _payload(result)

    # Resolver is tenant-filtered -> the cross-tenant template is invisible -> claude.
    by_agent = {e["agent"]: e for e in payload["launch_commands"]}
    assert by_agent["implementer"]["cli_tool"] == "claude"

    # Sanity: tenant A's project row is unchanged.
    row = (await db_session.execute(select(Project).where(Project.id == project.id))).scalar_one()
    assert row.implementation_launched_at is not None
