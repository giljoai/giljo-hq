# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import json
import random
from uuid import uuid4

import pytest
import pytest_asyncio

from giljo_mcp.models.organizations import Organization
from giljo_mcp.models.products import Product
from giljo_mcp.models.projects import Project
from giljo_mcp.models.templates import AgentTemplate
from giljo_mcp.services.protocol_sections.agent_lifecycle import _generate_orchestrator_protocol
from giljo_mcp.tenant import TenantManager
from tests.helpers.mcp_session_fixture import create_connected_server_and_client_session
from tests.helpers.product_crew_helper import adopt_all_templates


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


async def _seed_project(db_session, tenant_key: str, *, execution_mode: str) -> dict:
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
        description="BE-5103 footgun test",
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
        description="BE-5103 multi-terminal footgun guard",
        mission="x",
        status="active",
        staging_status="staging",
        execution_mode=execution_mode,
        series_number=random.randint(1, 9000),
    )
    db_session.add(project)
    await db_session.flush()

    template = AgentTemplate(
        tenant_key=tenant_key,
        name="implementer",
        role="implementer",
        description="BE-5103 test template",
        system_instructions="# implementer\nTest template body.",
        is_active=True,
    )
    db_session.add(template)
    await db_session.commit()

    await adopt_all_templates(db_session, tenant_key, product.id)
    return {"org": org, "product": product, "project": project}


@pytest_asyncio.fixture
async def spawn_mcp_client(db_manager, db_session, monkeypatch):
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

    tenant_key = TenantManager.generate_tenant_key()

    accessor = ToolAccessor(
        db_manager=db_manager,
        tenant_manager=state.tenant_manager,
        test_session=db_session,
    )
    state.tool_accessor = accessor

    from api.endpoints.mcp_tools import _base

    monkeypatch.setattr(_base, "_resolve_tenant", lambda ctx: tenant_key)
    monkeypatch.setattr(_base, "_resolve_user_id", lambda ctx: None)

    def _new_client():
        return create_connected_server_and_client_session(mcp_sdk_server.mcp)

    try:
        yield _new_client, tenant_key, db_session
    finally:
        state.tool_accessor = prior_tool_accessor
        state.tenant_manager = prior_tenant_manager
        state.db_manager = prior_db_manager




@pytest.mark.asyncio
async def test_spawn_job_multi_terminal_returns_pointer_not_bootstrap(
    spawn_mcp_client,
    db_session,
):
    new_client, tenant_key, session = spawn_mcp_client
    seed = await _seed_project(session, tenant_key, execution_mode="multi_terminal")

    async with new_client() as mcp_session:
        result = await mcp_session.call_tool(
            "spawn_job",
            {
                "agent_display_name": "ui-implementer",
                "agent_name": "implementer",
                "mission": "Implement the navbar redesign.",
                "project_id": seed["project"].id,
            },
        )

    assert result.is_error is False, f"BE-5103: spawn_job must succeed; got error: {_error_text(result)}"
    payload = _payload(result)

    assert "agent_prompt" in payload, f"BE-5103: response missing 'agent_prompt'; keys: {list(payload)}"
    agent_prompt = payload["agent_prompt"]
    assert "stored server-side" in agent_prompt, (
        f"BE-5103: multi_terminal agent_prompt must be a pointer mentioning 'stored server-side'; got: {agent_prompt!r}"
    )
    assert "## STARTUP (MANDATORY)" not in agent_prompt, (
        "BE-5103: multi_terminal agent_prompt MUST NOT contain the inline bootstrap "
        "header — a Claude Code orchestrator could paste it into Task() directly. "
        f"got: {agent_prompt!r}"
    )

    assert "agent_prompt_location" in payload, (
        f"BE-5103: response missing 'agent_prompt_location' discriminator; keys: {list(payload)}"
    )
    assert payload["agent_prompt_location"] == "dashboard", (
        f"BE-5103: agent_prompt_location must be 'dashboard' in multi_terminal mode; "
        f"got: {payload['agent_prompt_location']!r}"
    )




@pytest.mark.asyncio
async def test_spawn_job_multi_terminal_inline_seed_returns_bootstrap_inline(
    spawn_mcp_client,
    db_session,
):
    new_client, tenant_key, session = spawn_mcp_client
    seed = await _seed_project(session, tenant_key, execution_mode="multi_terminal")

    async with new_client() as mcp_session:
        result = await mcp_session.call_tool(
            "spawn_job",
            {
                "agent_display_name": "ui-implementer",
                "agent_name": "implementer",
                "mission": "Implement the navbar redesign.",
                "project_id": seed["project"].id,
                "inline_seed": True,
            },
        )

    assert result.is_error is False, f"BE-9499c: spawn_job must succeed; got error: {_error_text(result)}"
    payload = _payload(result)

    agent_prompt = payload["agent_prompt"]
    assert "stored server-side" not in agent_prompt, (
        f"BE-9499c: inline_seed=true must NOT return the dashboard pointer; got: {agent_prompt!r}"
    )
    assert "## STARTUP (MANDATORY)" in agent_prompt, (
        f"BE-9499c: inline_seed=true must return the real bootstrap seed; got: {agent_prompt!r}"
    )
    assert payload["agent_prompt_location"] == "inline", (
        f"BE-9499c: agent_prompt_location must be 'inline' when inline_seed=true; "
        f"got: {payload['agent_prompt_location']!r}"
    )


@pytest.mark.asyncio
async def test_spawn_job_multi_terminal_default_still_returns_pointer(
    spawn_mcp_client,
    db_session,
):
    new_client, tenant_key, session = spawn_mcp_client
    seed = await _seed_project(session, tenant_key, execution_mode="multi_terminal")

    async with new_client() as mcp_session:
        result = await mcp_session.call_tool(
            "spawn_job",
            {
                "agent_display_name": "ui-implementer",
                "agent_name": "implementer",
                "mission": "Implement the navbar redesign.",
                "project_id": seed["project"].id,
            },
        )

    assert result.is_error is False, _error_text(result)
    payload = _payload(result)
    assert "stored server-side" in payload["agent_prompt"]
    assert payload["agent_prompt_location"] == "dashboard"




_BANNER_DEFAULTS = {
    "job_id": "job-be5103",
    "tenant_key": "tk_test",
    "executor_id": "exec-be5103",
    "execution_mode": "multi_terminal",
}


@pytest.mark.parametrize(
    ("tool", "expected_substrings"),
    [
        ("claude-code", ("FORBIDDEN", "Task(", "Agent(", "✗")),
        ("codex", ("FORBIDDEN", "spawn_agent(", "✗")),
        (
            "multi_terminal",
            ("FORBIDDEN", "Task(", "spawn_agent(", "✗"),
        ),
    ],
)
def test_forbidden_banner_renders_at_top_of_protocol(tool, expected_substrings):
    protocol = _generate_orchestrator_protocol(**{**_BANNER_DEFAULTS, "tool": tool})
    head = protocol[:500]
    for needle in expected_substrings:
        assert needle in head, (
            f"BE-5103 tool={tool!r}: expected {needle!r} in first 500 chars of protocol; head was:\n{head!r}"
        )


def test_forbidden_banner_omits_other_tools_forbidden_lines():
    protocol = _generate_orchestrator_protocol(**{**_BANNER_DEFAULTS, "tool": "claude-code"})
    head = protocol[:500]
    assert "spawn_agent(" not in head, "BE-5103: claude-code banner leaked codex forbidden syntax"
    assert "@agent-name" not in head, "BE-5103: claude-code banner leaked gemini @-syntax"




@pytest.mark.parametrize("subagent_mode", ["claude-code", "codex"])
def test_forbidden_banner_not_injected_for_subagent_modes(subagent_mode):
    protocol = _generate_orchestrator_protocol(
        job_id="job-be5103",
        tenant_key="tk_test",
        executor_id="exec-be5103",
        execution_mode=subagent_mode,
        tool=subagent_mode,
    )
    assert "FORBIDDEN in this mode" not in protocol, (
        f"BE-5103: FORBIDDEN banner MUST NOT be injected for execution_mode={subagent_mode!r} "
        f"(in-process subagents are legitimate in that mode)"
    )
    assert protocol.startswith("These are your coordination operating procedures."), (
        f"BE-5103: subagent-mode protocol must open with the unmodified coordination framing; "
        f"got opening: {protocol[:120]!r}"
    )


@pytest.mark.asyncio
async def test_spawn_job_subagent_mode_returns_inline_bootstrap(
    spawn_mcp_client,
    db_session,
):
    new_client, tenant_key, session = spawn_mcp_client
    seed = await _seed_project(session, tenant_key, execution_mode="claude_code_cli")

    async with new_client() as mcp_session:
        result = await mcp_session.call_tool(
            "spawn_job",
            {
                "agent_display_name": "ui-implementer",
                "agent_name": "implementer",
                "mission": "Implement the navbar redesign.",
                "project_id": seed["project"].id,
            },
        )

    assert result.is_error is False, f"BE-5103: subagent-mode spawn_job must succeed; got: {_error_text(result)}"
    payload = _payload(result)

    agent_prompt = payload["agent_prompt"]
    assert "## STARTUP (MANDATORY)" in agent_prompt, (
        "BE-5103: subagent-mode spawn_job must keep the inline bootstrap "
        "(orchestrator legitimately spawns via Task()/spawn_agent()/@-syntax)"
    )
    assert payload["agent_prompt_location"] == "inline", (
        f"BE-5103: subagent-mode agent_prompt_location must be 'inline'; got: {payload['agent_prompt_location']!r}"
    )
