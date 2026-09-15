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
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.models import Product, Project
from giljo_mcp.models.templates import AgentTemplate
from giljo_mcp.tenant import TenantManager
from tests.helpers.mcp_session_fixture import create_connected_server_and_client_session
from tests.helpers.product_crew_helper import adopt_all_templates


pytestmark = pytest.mark.asyncio


_PERSONA_MARKER = "You implement backend changes with tests first."

_RULE_MARKER = "Never widen scope without a ruling."
_CRITERION_MARKER = "The regression test fails before the fix and passes after."

_SYSTEM_ONLY_MARKER = "Bootstrap the MCP session before doing anything else."


async def _seed_project(session: AsyncSession, tenant_key: str, execution_mode: str) -> str:
    suffix = uuid.uuid4().hex[:8]
    _owning_product_project = Product(
        id=str(uuid.uuid4()),
        tenant_key=tenant_key,
        name=f"Owning Product {uuid.uuid4().hex[:6]}",
        description="seeded",
        is_active=False,
    )
    session.add(_owning_product_project)
    project = Project(
        id=str(uuid.uuid4()),
        name=f"BE-9402 {execution_mode} {suffix}",
        description="MCP-boundary mode-elected-identity project.",
        mission="Stage then write.",
        status="active",
        tenant_key=tenant_key,
        product_id=_owning_product_project.id,
        series_number=1,
        execution_mode=execution_mode,
        created_at=datetime.now(UTC),
        implementation_launched_at=datetime.now(UTC),
    )
    session.add(project)
    session.info["tenant_key"] = tenant_key
    await session.flush()
    return project.id


async def _seed_live_template(session: AsyncSession, tenant_key: str) -> str:
    name = f"be9402-live-{uuid.uuid4().hex[:8]}"
    session.add(
        AgentTemplate(
            id=str(uuid.uuid4()),
            tenant_key=tenant_key,
            name=name,
            role="implementer",
            category="custom",
            system_instructions=_SYSTEM_ONLY_MARKER,
            user_instructions=_PERSONA_MARKER,
            behavioral_rules=[_RULE_MARKER],
            success_criteria=[_CRITERION_MARKER],
            is_active=True,
        )
    )
    await session.flush()

    for (_pid,) in (await session.execute(select(Product.id).where(Product.tenant_key == tenant_key))).all():
        await adopt_all_templates(session, tenant_key, _pid)
    return name


@pytest_asyncio.fixture
async def mission_boundary_client(monkeypatch, db_manager, db_session):
    from api import app_state
    from api.endpoints import mcp_sdk_server
    from giljo_mcp.tools.tool_accessor import ToolAccessor

    state = app_state.state
    prior_tool_accessor = state.tool_accessor
    prior_tenant_manager = state.tenant_manager
    prior_db_manager = state.db_manager

    tenant_manager = TenantManager()
    state.tenant_manager = tenant_manager
    state.db_manager = db_manager
    state.tool_accessor = ToolAccessor(
        db_manager=db_manager,
        tenant_manager=tenant_manager,
        test_session=db_session,
    )

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
        state.tool_accessor = prior_tool_accessor
        state.tenant_manager = prior_tenant_manager
        state.db_manager = prior_db_manager


def _payload(call_tool_result) -> dict:
    if getattr(call_tool_result, "structuredContent", None):
        return call_tool_result.structured_content
    return json.loads(call_tool_result.content[0].text)


def _error_text(call_tool_result) -> str:
    return "\n".join(getattr(b, "text", "") or "" for b in call_tool_result.content)


async def _spawn_specialist_and_read_mission(session_factory, project_id: str, agent_name: str) -> dict:
    async with session_factory() as session:
        spawn_result = await session.call_tool(
            "spawn_job",
            {
                "agent_display_name": "implementer",
                "agent_name": agent_name,
                "project_id": project_id,
                "mission": "Do the work.",
            },
        )
    assert spawn_result.is_error is not True, (
        f"Precondition: the spawn must succeed. Got: {_error_text(spawn_result)!r}"
    )
    job_id = _payload(spawn_result)["job_id"]

    async with session_factory() as session:
        mission = _payload(await session.call_tool("get_job_mission", {"job_id": job_id}))
    return mission


async def test_subagent_election_now_serves_the_identity_block(mission_boundary_client) -> None:
    new_client, tenant_key, db_session = mission_boundary_client
    project_id = await _seed_project(db_session, tenant_key, "subagent")
    agent_name = await _seed_live_template(db_session, tenant_key)

    mission = await _spawn_specialist_and_read_mission(new_client, project_id, agent_name)

    assert mission.get("agent_identity"), (
        "get_job_mission withheld the identity block from a SUBAGENT-mode agent. Since BE-9605b "
        "the server is the only source of truth for the agent profile; a worker with no local "
        "agent file must be able to act from this payload alone."
    )
    assert _PERSONA_MARKER in mission["agent_identity"]
    assert _RULE_MARKER in mission["agent_identity"]
    assert _CRITERION_MARKER in mission["agent_identity"]
    assert _SYSTEM_ONLY_MARKER not in mission["agent_identity"]
    assert "identity_status" not in mission, f"Got: {mission.get('identity_status')!r}"
    assert mission.get("mission")
    assert mission.get("full_protocol")


async def test_multi_terminal_election_still_serves_the_identity_block(mission_boundary_client) -> None:
    new_client, tenant_key, db_session = mission_boundary_client
    project_id = await _seed_project(db_session, tenant_key, "multi_terminal")
    agent_name = await _seed_live_template(db_session, tenant_key)

    mission = await _spawn_specialist_and_read_mission(new_client, project_id, agent_name)

    assert mission.get("agent_identity"), (
        "A multi_terminal agent received NO identity block. Its terminal booted on a ~50-token "
        "prompt, so the server is its only identity channel -- it is now running with no role framing."
    )
    assert _PERSONA_MARKER in mission["agent_identity"], (
        f"The served identity must carry the bound template's own instructions. Got: {mission['agent_identity']!r:.300}"
    )
    assert _RULE_MARKER in mission["agent_identity"], (
        "The served identity dropped the template's behavioral_rules. A multi_terminal agent "
        f"boots on a ~50-token prompt, so it now has no behavioral constraints at all. "
        f"Got: {mission['agent_identity']!r:.300}"
    )
    assert _CRITERION_MARKER in mission["agent_identity"], (
        "The served identity dropped the template's success_criteria -- the agent does not know "
        f"what finished looks like. Got: {mission['agent_identity']!r:.300}"
    )
    assert _SYSTEM_ONLY_MARKER not in mission["agent_identity"], (
        "system_instructions reached the served identity. That field is excluded by design; "
        f"its presence is a separate defect from any of the above. Got: {mission['agent_identity']!r:.300}"
    )


async def test_unrecognised_election_falls_back_to_serving_the_identity_block(mission_boundary_client) -> None:
    new_client, tenant_key, db_session = mission_boundary_client
    project_id = await _seed_project(db_session, tenant_key, "multi_terminal")
    agent_name = await _seed_live_template(db_session, tenant_key)

    async with new_client() as session:
        spawn_result = await session.call_tool(
            "spawn_job",
            {
                "agent_display_name": "implementer",
                "agent_name": agent_name,
                "project_id": project_id,
                "mission": "Do the work.",
            },
        )
    assert spawn_result.is_error is not True, (
        f"Precondition: the spawn must succeed. Got: {_error_text(spawn_result)!r}"
    )
    job_id = _payload(spawn_result)["job_id"]

    project_row = (
        await db_session.execute(select(Project).where(Project.id == project_id, Project.tenant_key == tenant_key))
    ).scalar_one()
    project_row.execution_mode = "headless"
    await db_session.flush()

    async with new_client() as session:
        mission = _payload(await session.call_tool("get_job_mission", {"job_id": job_id}))

    assert mission.get("blocked") is not True, (
        "Precondition: an unknown-but-non-empty mode must reach the render layer, not hard-block "
        f"(execution_mode_gate.py:101-109). Got: {mission.get('user_instruction')!r}"
    )
    assert mission.get("agent_identity"), (
        "A project whose election the server could not recognise received no identity block. Only an "
        "EXPLICIT subagent election may withhold it -- an unrecognised mode must fail SAFE and serve."
    )
    assert _PERSONA_MARKER in mission["agent_identity"], (
        f"The fail-safe serve must carry the real persona. Got: {mission['agent_identity']!r:.300}"
    )


async def test_subagent_election_still_serves_the_composed_orchestrator_identity(mission_boundary_client) -> None:
    new_client, tenant_key, db_session = mission_boundary_client
    project_id = await _seed_project(db_session, tenant_key, "subagent")

    async with new_client() as session:
        spawned = await session.call_tool(
            "spawn_job",
            {
                "agent_display_name": "orchestrator",
                "agent_name": "orchestrator",
                "project_id": project_id,
                "mission": "Drive this project.",
            },
        )
    assert spawned.is_error is not True, f"Precondition: the sentinel spawn must succeed. {_error_text(spawned)!r}"
    job_id = _payload(spawned)["job_id"]

    async with new_client() as session:
        mission = _payload(await session.call_tool("get_job_mission", {"job_id": job_id}))

    assert mission.get("agent_identity"), (
        "A SUBAGENT-mode orchestrator received no identity block. Nothing else can give it one: "
        "it is the root session, so no installed file feeds it, and its identity is composed from "
        "server-side tenant data that no file could carry. It is now running with no role framing."
    )
    assert "Orchestrator Agent" in mission["agent_identity"], (
        f"The composed orchestrator identity must survive the mode gate. Got: {mission['agent_identity']!r:.300}"
    )
    assert "identity_status" not in mission, (
        f"The composed default is healthy by design and must carry no degradation key. "
        f"Got: {mission.get('identity_status')!r}"
    )


async def test_subagent_election_still_serves_a_degraded_identity_block(mission_boundary_client) -> None:
    new_client, tenant_key, db_session = mission_boundary_client
    project_id = await _seed_project(db_session, tenant_key, "subagent")
    agent_name = await _seed_live_template(db_session, tenant_key)

    async with new_client() as session:
        spawned = await session.call_tool(
            "spawn_job",
            {
                "agent_display_name": "implementer",
                "agent_name": agent_name,
                "project_id": project_id,
                "mission": "Do the work.",
            },
        )
    job_id = _payload(spawned)["job_id"]

    template_row = (
        await db_session.execute(
            select(AgentTemplate).where(
                AgentTemplate.tenant_key == tenant_key,
                AgentTemplate.name == agent_name,
            )
        )
    ).scalar_one()
    template_row.deleted_at = datetime.now(UTC)
    await db_session.flush()

    async with new_client() as session:
        degraded = _payload(await session.call_tool("get_job_mission", {"job_id": job_id}))

    assert degraded.get("agent_identity"), (
        "The BE-9333 degradation block was withheld in subagent mode. That is not de-duplication -- "
        "no installed file carries this report -- it is a silent null, the exact state BE-9333 removed."
    )
    assert "deleted" in degraded["agent_identity"].lower(), (
        f"The served block must still name the cause. Got: {degraded['agent_identity']!r:.300}"
    )
    assert degraded.get("identity_status") == "template_unresolved", (
        f"The typed degradation signal must survive the mode gate. Got: {degraded.get('identity_status')!r}"
    )


async def test_legacy_generic_mcp_election_still_serves_the_identity_block(mission_boundary_client) -> None:
    new_client, tenant_key, db_session = mission_boundary_client
    project_id = await _seed_project(db_session, tenant_key, "multi_terminal")
    agent_name = await _seed_live_template(db_session, tenant_key)

    async with new_client() as session:
        spawned = await session.call_tool(
            "spawn_job",
            {
                "agent_display_name": "implementer",
                "agent_name": agent_name,
                "project_id": project_id,
                "mission": "Do the work.",
            },
        )
    job_id = _payload(spawned)["job_id"]

    project_row = (
        await db_session.execute(select(Project).where(Project.id == project_id, Project.tenant_key == tenant_key))
    ).scalar_one()
    project_row.execution_mode = "generic_mcp"
    await db_session.flush()

    async with new_client() as session:
        mission = _payload(await session.call_tool("get_job_mission", {"job_id": job_id}))

    assert mission.get("agent_identity"), (
        "A legacy generic_mcp agent received no identity block. That mode has no CLI and no "
        "installed agent files -- its own protocol prose says templates are served by the MCP "
        "server, not local files -- so the server is its only identity channel, exactly as for "
        "multi_terminal. It is now running with no role framing."
    )
    assert _PERSONA_MARKER in mission["agent_identity"], (
        f"The served identity must carry the bound template's own prose. Got: {mission['agent_identity']!r:.300}"
    )


async def test_a_null_election_is_blocked_before_identity_is_ever_composed(mission_boundary_client) -> None:
    new_client, tenant_key, db_session = mission_boundary_client
    project_id = await _seed_project(db_session, tenant_key, "multi_terminal")
    agent_name = await _seed_live_template(db_session, tenant_key)

    async with new_client() as session:
        spawn_result = await session.call_tool(
            "spawn_job",
            {
                "agent_display_name": "implementer",
                "agent_name": agent_name,
                "project_id": project_id,
                "mission": "Do the work.",
            },
        )
    job_id = _payload(spawn_result)["job_id"]

    project_row = (
        await db_session.execute(select(Project).where(Project.id == project_id, Project.tenant_key == tenant_key))
    ).scalar_one()
    project_row.execution_mode = None
    await db_session.flush()

    async with new_client() as session:
        mission = _payload(await session.call_tool("get_job_mission", {"job_id": job_id}))

    assert mission.get("blocked") is True, (
        "A NULL election must be blocked by the implementation gate before any identity is composed. "
        f"Got: {mission!r:.300}"
    )
    assert "execution mode" in (mission.get("user_instruction") or "").lower(), (
        f"The block must tell the user to pick a mode. Got: {mission.get('user_instruction')!r}"
    )
