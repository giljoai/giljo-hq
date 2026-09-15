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

from giljo_mcp.models import Project
from giljo_mcp.models.agent_identity import AgentJob
from giljo_mcp.models.product_agent_assignment import ProductAgentAssignment
from giljo_mcp.models.products import Product
from giljo_mcp.models.templates import AgentTemplate
from giljo_mcp.repositories.agent_completion_repository import AgentCompletionRepository
from giljo_mcp.repositories.mission_repository import MissionRepository
from giljo_mcp.system_roles import ORCHESTRATOR_AGENT_NAME
from giljo_mcp.template_renderer import MAX_PACKAGED_TEMPLATES
from giljo_mcp.tenant import TenantManager
from tests.helpers.mcp_session_fixture import create_connected_server_and_client_session


pytestmark = pytest.mark.asyncio


def _template(tenant_key: str, name: str) -> AgentTemplate:
    return AgentTemplate(
        id=str(uuid.uuid4()),
        tenant_key=tenant_key,
        name=name,
        role="custom",
        category="custom",
        system_instructions="sys",
        user_instructions="body",
        tool="claude",
        cli_tool="claude",
        is_active=True,
        version="1.0.0",
    )


def _product(tenant_key: str, name: str, *, is_active: bool = True) -> Product:
    return Product(id=str(uuid.uuid4()), tenant_key=tenant_key, name=name, is_active=is_active)


def _assignment(tenant_key: str, product_id: str, template_id: str, *, is_active: bool = True):
    return ProductAgentAssignment(
        id=str(uuid.uuid4()),
        product_id=product_id,
        template_id=template_id,
        tenant_key=tenant_key,
        is_active=is_active,
    )


def _project(tenant_key: str, product_id: str | None, name: str) -> Project:
    return Project(
        id=str(uuid.uuid4()),
        name=name,
        description="BE-9385a product-bound spawn.",
        mission="Spawn under a product-scoped allowlist.",
        status="active",
        tenant_key=tenant_key,
        product_id=product_id,
        series_number=1,
        execution_mode="multi_terminal",
        created_at=datetime.now(UTC),
    )




@pytest_asyncio.fixture
async def spawn_client(monkeypatch, db_manager, db_session):
    from api import app_state
    from api.endpoints import mcp_sdk_server
    from api.endpoints.mcp_tools import _base
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
    monkeypatch.setattr(_base, "_resolve_tenant", lambda ctx: tenant_key)
    monkeypatch.setattr(_base, "_resolve_user_id", lambda ctx: None)

    async def _noop(*_args, **_kwargs):
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


def _error_text(result) -> str:
    return "\n".join(getattr(b, "text", "") or "" for b in result.content)


def _payload(result) -> dict:
    if getattr(result, "structuredContent", None):
        return result.structured_content
    return json.loads(result.content[0].text)


async def test_spawn_allowlist_is_scoped_to_the_projects_product(spawn_client):
    new_client, tenant_key, session = spawn_client

    suffix = uuid.uuid4().hex[:8]
    enabled = _template(tenant_key, f"be9385a-enabled-{suffix}")
    disabled = _template(tenant_key, f"be9385a-disabled-{suffix}")
    product = _product(tenant_key, f"Product {suffix}")
    session.add_all([enabled, disabled, product])
    await session.flush()

    project = _project(tenant_key, product.id, f"BE-9385a spawn {suffix}")
    session.add(project)
    session.add_all(
        [
            _assignment(tenant_key, product.id, enabled.id, is_active=True),
            _assignment(tenant_key, product.id, disabled.id, is_active=False),
        ]
    )
    session.info["tenant_key"] = tenant_key
    await session.flush()

    async with new_client() as client:
        rejected = await client.call_tool(
            "spawn_job",
            {
                "agent_display_name": "worker-1",
                "agent_name": disabled.name,
                "project_id": project.id,
                "mission": "should never start",
            },
        )

    assert rejected.is_error, (
        "spawn_job accepted an agent that is disabled for this project's product. "
        "The orchestrator can spawn an agent the product does not use, and which its "
        "export never installed."
    )
    text = _error_text(rejected)
    assert disabled.name in text, f"rejection should name the refused agent; got: {text}"
    assert enabled.name in text, (
        "the rejection lists the valid choices, and that list must be the PRODUCT's "
        f"agents so the orchestrator can retry correctly; got: {text}"
    )

    async with new_client() as client:
        accepted = await client.call_tool(
            "spawn_job",
            {
                "agent_display_name": "worker-2",
                "agent_name": enabled.name,
                "project_id": project.id,
                "mission": "this one is enabled for the product",
            },
        )

    assert accepted.is_error is False, f"An agent ENABLED for the product must still spawn: {_error_text(accepted)}"
    assert _payload(accepted).get("job_id")


async def test_spawn_allowlist_is_empty_for_a_product_that_enabled_nothing(spawn_client):
    new_client, tenant_key, session = spawn_client

    suffix = uuid.uuid4().hex[:8]
    template = _template(tenant_key, f"be9385a-tol-spawn-{suffix}")
    product = _product(tenant_key, f"Untouched {suffix}")
    session.add_all([template, product])
    await session.flush()

    project = _project(tenant_key, product.id, f"BE-9385a tolerance {suffix}")
    session.add(project)
    session.info["tenant_key"] = tenant_key
    await session.flush()

    async with new_client() as client:
        result = await client.call_tool(
            "spawn_job",
            {
                "agent_display_name": "worker-1",
                "agent_name": template.name,
                "project_id": project.id,
                "mission": "tolerance path",
            },
        )

    assert result.is_error is True, "a product that has enabled nothing must not spawn an agent"
    assert "no agents assigned for this product" in _error_text(result).lower(), (
        "ruling 4: the refusal names the harness default instead of reading as a server "
        f"fault. got={_error_text(result)!r}"
    )




async def test_roster_follows_the_product(db_session, test_tenant_key):
    suffix = uuid.uuid4().hex[:8]
    t_a = _template(test_tenant_key, f"be9385a-roster-a-{suffix}")
    t_b = _template(test_tenant_key, f"be9385a-roster-b-{suffix}")
    product_a = _product(test_tenant_key, f"Roster A {suffix}")
    product_b = _product(test_tenant_key, f"Roster B {suffix}", is_active=False)
    db_session.add_all([t_a, t_b, product_a, product_b])
    await db_session.flush()

    db_session.add_all(
        [
            _assignment(test_tenant_key, product_a.id, t_a.id),
            _assignment(test_tenant_key, product_b.id, t_b.id),
        ]
    )
    await db_session.flush()

    repo = MissionRepository()
    roster_a = {t.name for t in await repo.get_active_templates(db_session, test_tenant_key, product_id=product_a.id)}
    roster_b = {t.name for t in await repo.get_active_templates(db_session, test_tenant_key, product_id=product_b.id)}

    assert t_a.name in roster_a and t_b.name not in roster_a, f"Product A roster wrong: {sorted(roster_a)}"
    assert t_b.name in roster_b and t_a.name not in roster_b, f"Product B roster wrong: {sorted(roster_b)}"


async def test_roster_is_empty_for_a_product_that_enabled_nothing(db_session, test_tenant_key):
    suffix = uuid.uuid4().hex[:8]
    template = _template(test_tenant_key, f"be9385a-roster-tol-{suffix}")
    product = _product(test_tenant_key, f"Roster tolerance {suffix}")
    db_session.add_all([template, product])
    await db_session.flush()

    roster = {
        t.name
        for t in await MissionRepository().get_active_templates(db_session, test_tenant_key, product_id=product.id)
    }

    assert roster == set(), (
        "a product that has enabled nothing must have an empty roster; serving it another "
        f"product's agents is the sharing BE-9610a removes. got={sorted(roster)}"
    )


async def test_roster_cap_matches_the_export_cap(db_session, test_tenant_key):
    assert MAX_PACKAGED_TEMPLATES == 16, "R1 unified both caps on the operator-chosen 16."

    suffix = uuid.uuid4().hex[:8]
    templates = [_template(test_tenant_key, f"be9385a-cap-{i:02d}-{suffix}") for i in range(12)]
    db_session.add_all(templates)
    await db_session.flush()

    roster = await MissionRepository().get_active_templates(db_session, test_tenant_key)

    assert len(roster) == 12, (
        f"With 12 active agents the roster must show all 12 (cap {MAX_PACKAGED_TEMPLATES}); "
        f"got {len(roster)}. A cap of 8 here is the pre-BE-9385a behaviour."
    )




async def test_switched_off_stays_switched_off_across_a_reseed(db_session, test_tenant_key):
    from giljo_mcp.repositories.product_agent_assignment_repository import (
        ProductAgentAssignmentRepository,
    )

    suffix = uuid.uuid4().hex[:8]
    keep = _template(test_tenant_key, f"be9385a-keep-{suffix}")
    retired = _template(test_tenant_key, f"be9385a-retired-{suffix}")
    product = _product(test_tenant_key, f"Curated {suffix}")
    db_session.add_all([keep, retired, product])
    await db_session.flush()

    db_session.add_all(
        [
            _assignment(test_tenant_key, product.id, keep.id, is_active=True),
            _assignment(test_tenant_key, product.id, retired.id, is_active=False),
        ]
    )
    await db_session.flush()

    await ProductAgentAssignmentRepository().enable_templates_for_product(
        db_session, product.id, test_tenant_key, [keep.id, retired.id]
    )
    await db_session.flush()

    row = (
        await db_session.execute(
            select(ProductAgentAssignment).where(
                ProductAgentAssignment.product_id == product.id,
                ProductAgentAssignment.template_id == retired.id,
                ProductAgentAssignment.tenant_key == test_tenant_key,
            )
        )
    ).scalar_one()

    assert row.is_active is False, (
        "An agent the user deliberately switched off came back after a bulk enable. On CE "
        "an upgrade runs unattended, and the self-hoster has no operator to clean it up."
    )

    names = await AgentCompletionRepository().get_active_template_names(
        db_session, test_tenant_key, product_id=product.id
    )
    assert retired.name not in names, f"Retired agent is spawnable again: {sorted(names)}"
    assert keep.name in names, "The agent the user kept must still be spawnable."


async def test_orchestrator_roster_is_product_scoped_at_the_mcp_boundary(spawn_client):
    new_client, tenant_key, session = spawn_client

    suffix = uuid.uuid4().hex[:8]
    enabled = _template(tenant_key, f"be9385a-roster-on-{suffix}")
    disabled = _template(tenant_key, f"be9385a-roster-off-{suffix}")
    product = _product(tenant_key, f"Roster boundary {suffix}")
    session.add_all([enabled, disabled, product])
    await session.flush()

    project = _project(tenant_key, product.id, f"BE-9385a roster {suffix}")
    session.add(project)
    session.add_all(
        [
            _assignment(tenant_key, product.id, enabled.id, is_active=True),
            _assignment(tenant_key, product.id, disabled.id, is_active=False),
        ]
    )
    session.info["tenant_key"] = tenant_key
    await session.flush()

    async with new_client() as client:
        spawned = await client.call_tool(
            "spawn_job",
            {
                "agent_display_name": "orchestrator",
                "agent_name": ORCHESTRATOR_AGENT_NAME,
                "project_id": project.id,
                "mission": "Coordinate.",
            },
        )
    assert spawned.is_error is False, _error_text(spawned)

    async with new_client() as client:
        staging = await client.call_tool("get_staging_instructions", {"job_id": _payload(spawned)["job_id"]})

    assert staging.is_error is False, _error_text(staging)
    rendered = json.dumps(_payload(staging))

    assert enabled.name in rendered, (
        f"The orchestrator's roster omits an agent this product has enabled: {enabled.name}"
    )
    assert disabled.name not in rendered, (
        f"The orchestrator is offered {disabled.name}, which this product disabled. It would "
        "spawn an agent the product does not use and whose files the export never installed."
    )


async def test_multi_terminal_agent_still_receives_its_full_profile(spawn_client):
    new_client, tenant_key, session = spawn_client

    suffix = uuid.uuid4().hex[:8]
    template = _template(tenant_key, f"be9385a-profile-{suffix}")
    template.user_instructions = f"PROFILE-MARKER-{suffix}: you analyse things."
    template.behavioral_rules = [f"RULE-MARKER-{suffix}"]
    product = _product(tenant_key, f"Profile product {suffix}")
    session.add_all([template, product])
    await session.flush()

    project = _project(tenant_key, product.id, f"BE-9385a profile {suffix}")
    project.implementation_launched_at = datetime.now(UTC)
    session.add(project)
    session.add(_assignment(tenant_key, product.id, template.id, is_active=True))
    session.info["tenant_key"] = tenant_key
    await session.flush()

    async with new_client() as client:
        spawned = await client.call_tool(
            "spawn_job",
            {
                "agent_display_name": "worker-1",
                "agent_name": template.name,
                "project_id": project.id,
                "mission": "Do the work.",
            },
        )
    assert spawned.is_error is False, _error_text(spawned)
    job_id = _payload(spawned)["job_id"]

    job = (
        await session.execute(select(AgentJob).where(AgentJob.tenant_key == tenant_key, AgentJob.job_id == job_id))
    ).scalar_one()

    assert job.template_id == template.id, (
        "The spawn bound no template (or the wrong one), so get_job_mission will render "
        "no identity and the agent will behave generically with nothing to explain it."
    )

    async with new_client() as client:
        mission = await client.call_tool("get_job_mission", {"job_id": job_id})

    assert mission.is_error is False, _error_text(mission)
    rendered = json.dumps(_payload(mission))
    assert f"PROFILE-MARKER-{suffix}" in rendered, (
        "A multi_terminal agent must still receive its full server-delivered profile; "
        "its role prose is absent from the mission response."
    )
    assert f"RULE-MARKER-{suffix}" in rendered, "The behavioural rules half of the profile did not reach the agent."


async def test_a_toggle_moves_exactly_one_agent(db_manager, db_session, test_tenant_key):
    from giljo_mcp.services.product_agent_assignment_service import ProductAgentAssignmentService

    suffix = uuid.uuid4().hex[:8]
    first = _template(test_tenant_key, f"be9385a-tog-1-{suffix}")
    second = _template(test_tenant_key, f"be9385a-tog-2-{suffix}")
    third = _template(test_tenant_key, f"be9385a-tog-3-{suffix}")
    product = _product(test_tenant_key, f"Fresh {suffix}")
    db_session.add_all([first, second, third, product])
    await db_session.flush()
    for template in (first, second, third):
        template.product_id = product.id
    db_session.add_all(
        [
            _assignment(test_tenant_key, product.id, first.id, is_active=True),
            _assignment(test_tenant_key, product.id, second.id, is_active=True),
            _assignment(test_tenant_key, product.id, third.id, is_active=True),
        ]
    )
    await db_session.flush()

    service = ProductAgentAssignmentService(db_manager=db_manager, tenant_key=test_tenant_key, test_session=db_session)
    await service.toggle_assignment(product.id, first.id, False)

    names = await AgentCompletionRepository().get_active_template_names(
        db_session, test_tenant_key, product_id=product.id
    )

    assert first.name not in names, (
        "The toggle did nothing. Turning an agent OFF must actually disable it -- the UI showed the switch move."
    )
    assert {second.name, third.name} == set(names), (
        f"Toggling one agent moved another: the switch must change exactly what it names. Remaining: {sorted(names)}"
    )
