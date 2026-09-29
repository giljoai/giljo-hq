# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.models import Product, Project
from giljo_mcp.models.product_agent_assignment import ProductAgentAssignment
from giljo_mcp.models.templates import AgentTemplate
from giljo_mcp.tenant import TenantManager
from tests.helpers.mcp_session_fixture import create_connected_server_and_client_session


pytestmark = pytest.mark.asyncio

_PERSONA_MARKER = "You implement backend changes with tests first."
_RULE_MARKER = "Never widen scope without a ruling."
_CRITERION_MARKER = "The regression test fails before the fix and passes after."
_DESCRIPTION_MARKER = "Backend specialist for the BE-9605b boundary test."


async def _seed_project(session: AsyncSession, tenant_key: str, execution_mode: str) -> tuple[str, str]:
    product = Product(
        id=str(uuid.uuid4()),
        tenant_key=tenant_key,
        name=f"Owning Product {uuid.uuid4().hex[:6]}",
        description="seeded",
        is_active=False,
    )
    session.add(product)
    project = Project(
        id=str(uuid.uuid4()),
        name=f"BE-9605b {execution_mode} {uuid.uuid4().hex[:8]}",
        description="Mission-carries-profile boundary project.",
        mission="Stage then write.",
        status="active",
        tenant_key=tenant_key,
        product_id=product.id,
        series_number=1,
        execution_mode=execution_mode,
        created_at=datetime.now(UTC),
        implementation_launched_at=datetime.now(UTC),
    )
    session.add(project)
    session.info["tenant_key"] = tenant_key
    await session.flush()
    return project.id, product.id


async def _seed_template(
    session: AsyncSession,
    tenant_key: str,
    *,
    name: str | None = None,
    user_instructions: str = _PERSONA_MARKER,
    model: str | None = "inherit",
    effort: str | None = "inherit",
    cli_tool: str = "codex",
    enable_for: str | None = None,
) -> AgentTemplate:
    template = AgentTemplate(
        id=str(uuid.uuid4()),
        tenant_key=tenant_key,
        name=name or f"be9605b-{uuid.uuid4().hex[:8]}",
        role="implementer",
        category="custom",
        description=_DESCRIPTION_MARKER,
        system_instructions="Bootstrap the MCP session before doing anything else.",
        user_instructions=user_instructions,
        behavioral_rules=[_RULE_MARKER],
        success_criteria=[_CRITERION_MARKER],
        cli_tool=cli_tool,
        tool="claude",
        model=model,
        effort=effort,
        is_active=True,
    )
    session.add(template)
    await session.flush()
    if enable_for:
        template.product_id = enable_for
        session.add(
            ProductAgentAssignment(
                id=str(uuid.uuid4()),
                product_id=enable_for,
                template_id=template.id,
                tenant_key=tenant_key,
                is_active=True,
            )
        )
        await session.flush()
    return template


@pytest_asyncio.fixture
async def mission_boundary_client(monkeypatch, db_manager, db_session):
    from api import app_state
    from api.endpoints import mcp_sdk_server
    from giljo_mcp.tools.tool_accessor import ToolAccessor

    state = app_state.state
    prior = (state.tool_accessor, state.tenant_manager, state.db_manager)

    tenant_manager = TenantManager()
    state.tenant_manager = tenant_manager
    state.db_manager = db_manager
    state.tool_accessor = ToolAccessor(db_manager=db_manager, tenant_manager=tenant_manager, test_session=db_session)

    tenant_key = TenantManager.generate_tenant_key()
    from api.endpoints.mcp_tools import _base

    monkeypatch.setattr(_base, "_resolve_tenant", lambda ctx: tenant_key)
    monkeypatch.setattr(_base, "_resolve_user_id", lambda ctx: None)

    async def _noop(*args, **kwargs):
        return None

    monkeypatch.setattr("giljo_mcp.services.silence_detector.auto_clear_silent", _noop)
    monkeypatch.setattr("giljo_mcp.services.heartbeat.touch_heartbeat", _noop)

    def _new_client():
        return create_connected_server_and_client_session(mcp_sdk_server.mcp)

    try:
        yield _new_client, tenant_key, db_session
    finally:
        state.tool_accessor, state.tenant_manager, state.db_manager = prior


def _payload(result) -> dict:
    if getattr(result, "structuredContent", None):
        return result.structured_content
    return json.loads(result.content[0].text)


def _error_text(result) -> str:
    return "\n".join(getattr(b, "text", "") or "" for b in result.content)


async def _spawn(session_factory, project_id: str, agent_name: str) -> dict:
    async with session_factory() as session:
        result = await session.call_tool(
            "spawn_job",
            {
                "agent_display_name": "implementer",
                "agent_name": agent_name,
                "project_id": project_id,
                "mission": "Do the work.",
            },
        )
    assert result.is_error is not True, f"Precondition: spawn must succeed. Got: {_error_text(result)!r}"
    return _payload(result)


async def _read_mission(session_factory, job_id: str) -> dict:
    async with session_factory() as session:
        return _payload(await session.call_tool("get_job_mission", {"job_id": job_id}))


async def test_subagent_mission_carries_the_full_profile(mission_boundary_client) -> None:
    new_client, tenant_key, db_session = mission_boundary_client
    project_id, product_id = await _seed_project(db_session, tenant_key, "subagent")
    template = await _seed_template(db_session, tenant_key, model="opus", effort="high", enable_for=product_id)

    spawned = await _spawn(new_client, project_id, template.name)
    mission = await _read_mission(new_client, spawned["job_id"])

    profile = mission.get("agent_profile")
    assert profile, f"agent_profile missing from the mission payload: {sorted(mission)}"
    assert profile["name"] == template.name
    assert profile["role"] == "implementer"
    assert profile["description"] == _DESCRIPTION_MARKER
    assert profile["harness"] == "codex"
    assert profile["model"] == "opus"
    assert profile["effort"] == "high"
    assert _PERSONA_MARKER in profile["instructions"]
    assert profile["behavioral_rules"] == [_RULE_MARKER]
    assert profile["success_criteria"] == [_CRITERION_MARKER]
    assert mission.get("agent_identity"), "identity block withheld -- the ruling requires it served in every mode"
    assert _PERSONA_MARKER in mission["agent_identity"]


async def test_profile_defaults_to_inherit_when_unset(mission_boundary_client) -> None:
    new_client, tenant_key, db_session = mission_boundary_client
    project_id, product_id = await _seed_project(db_session, tenant_key, "multi_terminal")
    template = await _seed_template(db_session, tenant_key, model=None, effort=None, enable_for=product_id)

    spawned = await _spawn(new_client, project_id, template.name)
    profile = (await _read_mission(new_client, spawned["job_id"]))["agent_profile"]

    assert profile["model"] == "inherit"
    assert profile["effort"] == "inherit"


async def test_product_scoped_template_binds_and_the_disabled_sibling_is_refused(mission_boundary_client) -> None:
    new_client, tenant_key, db_session = mission_boundary_client
    project_id, product_id = await _seed_project(db_session, tenant_key, "subagent")
    disabled_row = await _seed_template(db_session, tenant_key, user_instructions="NOT ENABLED FOR THIS PRODUCT.")
    enabled_row = await _seed_template(
        db_session, tenant_key, user_instructions="PRODUCT-SCOPED BODY.", enable_for=product_id
    )

    spawned = await _spawn(new_client, project_id, enabled_row.name)
    profile = (await _read_mission(new_client, spawned["job_id"]))["agent_profile"]
    assert profile["instructions"] == "PRODUCT-SCOPED BODY."
    assert profile["template_id"] == enabled_row.id

    async with new_client() as session:
        refused = await session.call_tool(
            "spawn_job",
            {
                "agent_display_name": "implementer",
                "agent_name": disabled_row.name,
                "project_id": project_id,
                "mission": "Do the work.",
            },
        )
    assert refused.is_error or not _payload(refused).get("job_id"), (
        "a template the product disabled must not bind: " + _error_text(refused)
    )


async def test_a_product_that_enabled_nothing_serves_nothing(mission_boundary_client) -> None:
    new_client, tenant_key, db_session = mission_boundary_client
    project_id, _ = await _seed_project(db_session, tenant_key, "subagent")
    template = await _seed_template(db_session, tenant_key, user_instructions="TENANT FALLBACK BODY.")

    async with new_client() as session:
        refused = await session.call_tool(
            "spawn_job",
            {
                "agent_display_name": "implementer",
                "agent_name": template.name,
                "project_id": project_id,
                "mission": "Do the work.",
            },
        )

    assert refused.is_error or not _payload(refused).get("job_id"), (
        "an agent no product has enabled must not be spawnable: " + _error_text(refused)
    )
    assert "no agents assigned for this product" in _error_text(refused).lower(), (
        "ruling 4: the refusal must say the product has no agents and name the harness "
        f"default, not read as a server fault. got={_error_text(refused)!r}"
    )


async def test_thin_prompt_carries_the_hints_but_no_launch_line_in_subagent_mode(mission_boundary_client) -> None:
    new_client, tenant_key, db_session = mission_boundary_client
    project_id, product_id = await _seed_project(db_session, tenant_key, "subagent")
    template = await _seed_template(
        db_session, tenant_key, cli_tool="codex", model="gpt-5", effort="high", enable_for=product_id
    )

    spawned = await _spawn(new_client, project_id, template.name)
    prompt = spawned["agent_prompt"]

    assert "## HARNESS" not in prompt
    assert "--dangerously-bypass-approvals-and-sandbox" not in prompt
    assert "Model hint: gpt-5" in prompt
    assert "Effort hint: high" in prompt
