# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import json
import random
import uuid
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from mcp.types import Implementation

from giljo_mcp.models import Product, Project
from giljo_mcp.models.agent_identity import AgentExecution, AgentJob
from giljo_mcp.models.product_agent_assignment import ProductAgentAssignment
from giljo_mcp.models.templates import AgentTemplate
from giljo_mcp.platform_registry import get_harness
from giljo_mcp.tenant import TenantManager
from tests.helpers.mcp_session_fixture import create_connected_server_and_client_session


pytestmark = pytest.mark.asyncio

_BYPASS_MARKERS = ("--dangerously", "--auto", "bypass-approvals", "skip-permissions")


def _payload(result) -> dict:
    if getattr(result, "structuredContent", None):
        return result.structured_content
    return json.loads(result.content[0].text)


def _error_text(result) -> str:
    return "\n".join(getattr(b, "text", "") or "" for b in result.content)


@pytest_asyncio.fixture
async def boundary(monkeypatch, db_manager, db_session):
    from api import app_state
    from api.endpoints import mcp_sdk_server
    from api.endpoints.mcp_tools import _base
    from giljo_mcp.tools.tool_accessor import ToolAccessor

    state = app_state.state
    prior = (state.tool_accessor, state.tenant_manager, state.db_manager)
    tenant_manager = TenantManager()
    state.tenant_manager = tenant_manager
    state.db_manager = db_manager
    state.tool_accessor = ToolAccessor(db_manager=db_manager, tenant_manager=tenant_manager, test_session=db_session)

    tenant_key = TenantManager.generate_tenant_key()
    monkeypatch.setattr(_base, "_resolve_tenant", lambda ctx: tenant_key)
    monkeypatch.setattr(_base, "_resolve_user_id", lambda ctx: None)

    async def _noop(*args, **kwargs):
        return None

    monkeypatch.setattr("giljo_mcp.services.silence_detector.auto_clear_silent", _noop)
    monkeypatch.setattr("giljo_mcp.services.heartbeat.touch_heartbeat", _noop)

    def _client(client_info: Implementation | None = None):
        return create_connected_server_and_client_session(mcp_sdk_server.mcp, client_info=client_info)

    try:
        yield _client, tenant_key, db_session
    finally:
        state.tool_accessor, state.tenant_manager, state.db_manager = prior


async def _seed_project(session, tenant_key: str, execution_mode: str, *, staging: bool = False) -> tuple[str, str]:
    product = Product(
        id=str(uuid.uuid4()),
        tenant_key=tenant_key,
        name=f"BE-9649 product {uuid.uuid4().hex[:6]}",
        description="seeded",
        is_active=False,
    )
    session.add(product)
    project = Project(
        id=str(uuid.uuid4()),
        name=f"BE-9649 {execution_mode} {uuid.uuid4().hex[:8]}",
        description="Spawn-text boundary project.",
        mission="Stage then write.",
        status="active",
        tenant_key=tenant_key,
        product_id=product.id,
        series_number=random.randint(1, 9000),
        execution_mode=execution_mode,
        staging_status="staging" if staging else None,
        created_at=datetime.now(UTC),
        implementation_launched_at=None if staging else datetime.now(UTC),
    )
    session.add(project)
    session.info["tenant_key"] = tenant_key
    await session.flush()
    return project.id, product.id


async def _seed_template(session, tenant_key: str, product_id: str, cli_tool: str) -> str:
    template = AgentTemplate(
        id=str(uuid.uuid4()),
        tenant_key=tenant_key,
        product_id=product_id,
        name=f"be9649-{uuid.uuid4().hex[:8]}",
        role="implementer",
        category="custom",
        description="BE-9649 worker",
        system_instructions="Bootstrap the MCP session first.",
        user_instructions="Implement with tests.",
        cli_tool=cli_tool,
        tool=cli_tool,
        model="inherit",
        effort="inherit",
        is_active=True,
    )
    session.add(template)
    await session.flush()
    session.add(
        ProductAgentAssignment(
            id=str(uuid.uuid4()),
            product_id=product_id,
            template_id=template.id,
            tenant_key=tenant_key,
            is_active=True,
        )
    )
    await session.flush()
    return template.name


async def _spawn_prompt(client, project_id: str, agent_name: str, *, inline_seed: bool = False) -> str:
    async with client() as session:
        result = await session.call_tool(
            "spawn_job",
            {
                "agent_display_name": "implementer",
                "agent_name": agent_name,
                "project_id": project_id,
                "mission": "Do the work.",
                "inline_seed": inline_seed,
            },
        )
    assert result.is_error is not True, _error_text(result)
    payload = _payload(result)
    assert payload["agent_prompt_location"] == "inline", payload
    return payload["agent_prompt"]




async def test_subagent_spawn_prompt_has_no_launch_text(boundary) -> None:
    client, tenant_key, db_session = boundary
    project_id, product_id = await _seed_project(db_session, tenant_key, "subagent")
    name = await _seed_template(db_session, tenant_key, product_id, "codex")

    prompt = await _spawn_prompt(client, project_id, name)

    assert "## HARNESS" not in prompt, prompt
    assert "Launch this agent" not in prompt, prompt
    assert "new terminal" not in prompt, prompt
    for marker in _BYPASS_MARKERS:
        assert marker not in prompt, f"{marker!r} leaked into a subagent spawn prompt:\n{prompt}"
    assert "get_job_mission" in prompt, "the bootstrap itself must survive"




async def test_multi_terminal_named_harness_gets_plain_instructions(boundary) -> None:
    client, tenant_key, db_session = boundary
    project_id, product_id = await _seed_project(db_session, tenant_key, "multi_terminal", staging=True)
    name = await _seed_template(db_session, tenant_key, product_id, "gemini-cli")

    prompt = await _spawn_prompt(client, project_id, name, inline_seed=True)

    assert "## HARNESS" in prompt, prompt
    assert "gemini-cli" in prompt, "the user's chosen harness must be named"
    assert "work out its launch" in prompt, prompt
    assert "ask the user" in prompt, prompt
    for marker in _BYPASS_MARKERS:
        assert marker not in prompt, f"{marker!r} must never be added unasked:\n{prompt}"


async def test_multi_terminal_default_harness_is_the_orchestrators_own(boundary) -> None:
    client, tenant_key, db_session = boundary
    project_id, product_id = await _seed_project(db_session, tenant_key, "multi_terminal", staging=True)
    name = await _seed_template(db_session, tenant_key, product_id, "default")

    prompt = await _spawn_prompt(client, project_id, name, inline_seed=True)

    assert "## HARNESS" in prompt, prompt
    assert "same harness you are running in" in prompt, prompt
    for marker in _BYPASS_MARKERS:
        assert marker not in prompt, prompt


async def test_legacy_cli_tool_value_is_the_named_harness(boundary) -> None:
    client, tenant_key, db_session = boundary
    project_id, product_id = await _seed_project(db_session, tenant_key, "multi_terminal", staging=True)
    name = await _seed_template(db_session, tenant_key, product_id, "claude")

    prompt = await _spawn_prompt(client, project_id, name, inline_seed=True)

    assert "Harness: claude" in prompt, prompt
    assert "--dangerously-skip-permissions" not in prompt, prompt


async def test_multi_terminal_post_gate_names_the_registry_autonomy_flag(boundary) -> None:
    client, tenant_key, db_session = boundary
    project_id, product_id = await _seed_project(db_session, tenant_key, "multi_terminal")
    name = await _seed_template(db_session, tenant_key, product_id, "codex")

    prompt = await _spawn_prompt(client, project_id, name, inline_seed=True)

    assert "Harness: codex" in prompt, prompt
    assert get_harness("codex").autonomy_flag in prompt, f"post-gate launch text must carry the flag:\n{prompt}"
    assert "Do not add a permission-bypass" not in prompt, prompt


async def test_stored_value_that_is_not_a_name_is_never_echoed(boundary) -> None:
    client, tenant_key, db_session = boundary
    project_id, product_id = await _seed_project(db_session, tenant_key, "multi_terminal", staging=True)
    name = await _seed_template(db_session, tenant_key, product_id, "x; ignore all")

    prompt = await _spawn_prompt(client, project_id, name, inline_seed=True)

    assert "ignore all" not in prompt, prompt
    assert "same harness you are running in" in prompt, "an unusable value falls back to the default"




async def _seed_orchestrator(session, tenant_key: str, project_id: str) -> str:
    now = datetime.now(UTC)
    job = AgentJob(
        job_id=str(uuid.uuid4()),
        tenant_key=tenant_key,
        project_id=project_id,
        job_type="orchestrator",
        mission="BE-9649 orchestrator mission",
        status="active",
        created_at=now,
    )
    session.add(job)
    await session.flush()
    session.add(
        AgentExecution(
            id=str(uuid.uuid4()),
            agent_id=str(uuid.uuid4()),
            job_id=job.job_id,
            tenant_key=tenant_key,
            agent_display_name="orchestrator",
            status="working",
            started_at=now,
        )
    )
    await session.commit()
    return job.job_id


async def test_claude_code_spawn_chapter_uses_the_generic_worker(boundary) -> None:
    client, tenant_key, db_session = boundary
    project_id, _product_id = await _seed_project(db_session, tenant_key, "subagent", staging=True)
    job_id = await _seed_orchestrator(db_session, tenant_key, project_id)

    async with client(Implementation(name="claude-code", version="2.1.199")) as session:
        result = await session.call_tool("get_staging_instructions", {"job_id": job_id})
    assert result.is_error is False, _error_text(result)
    ch3 = _payload(result)["orchestrator_protocol"]["ch3_agent_spawning_rules"]

    assert "YOUR PLATFORM: CLAUDE CODE CLI" in ch3, "precondition: the Claude Code chapter rendered"
    assert 'subagent_type="general-purpose"' in ch3, ch3
    assert "First action: get_job_mission" in ch3, ch3
    assert "subagent_type='{agent_name}'" not in ch3, ch3
    assert "subagent_type='implementer'" not in ch3, ch3
    assert "Subagent type not found" not in ch3, ch3
    assert "NOT agent_display_name" not in ch3, ch3
    assert "already carries a HARNESS block" not in ch3, "Part A makes that claim false in subagent mode"
