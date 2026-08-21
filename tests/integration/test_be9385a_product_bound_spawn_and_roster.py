# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-9385a -- the CALLING path must follow the product too, not just the export.

Companion to ``test_be9385a_product_bound_agent_selection_mcp_boundary.py``,
which covers the export side (the reported incident). This file covers the three
remaining consumers of "which agents are active" and the two lifecycle guarantees
that keep the junction honest over time:

* the spawn allowlist -- asserted through the real MCP transport, because that is
  where an orchestrator actually meets it;
* the orchestrator roster, including the 8 -> 16 cap unification;
* "deactivated stays deactivated" across a CE boot re-seed and a product
  re-activation (EM ruling R2);
* the first toggle on a row-less product must not blank it (EM ruling D1).

Parallel-safe: fresh tenant_key per test, rolled-back ``db_session``, no
module-level mutable state.
"""

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


# ---------------------------------------------------------------------------
# Spawn allowlist -- through the real MCP transport
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def spawn_client(monkeypatch, db_manager, db_session):
    """FastMCP client wired to a REAL ToolAccessor on the rolled-back test session.

    Pattern lifted from ``tests/integration/test_be6008_spawn_boundary.py`` rather
    than re-invented, so the spawn chain under test is the shipped one.
    """
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
    """An agent the active product disabled must not be spawnable into that product.

    Tenant-wide both templates are active, so pre-fix BOTH spawns succeeded: the
    orchestrator could spawn an agent the product had switched off, and the export
    for that product would not even have shipped it. Two views of "what is active",
    disagreeing.
    """
    new_client, tenant_key, session = spawn_client

    suffix = uuid.uuid4().hex[:8]
    enabled = _template(tenant_key, f"be9385a-enabled-{suffix}")
    disabled = _template(tenant_key, f"be9385a-disabled-{suffix}")
    product = _product(tenant_key, f"Product {suffix}")
    session.add_all([enabled, disabled, product])
    await session.flush()

    project = _project(tenant_key, product.id, f"BE-9385a spawn {suffix}")
    session.add(project)
    # Junction is explicit for BOTH templates -- this is a curated product, not a
    # tolerance case: one agent enabled, one deliberately disabled.
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


async def test_spawn_allowlist_tolerates_a_product_with_no_junction_rows(spawn_client):
    """Tolerance on the spawn path: a row-less product must keep the tenant-wide allowlist.

    Without this a pre-junction install upgrades into an orchestrator that can
    spawn nothing at all.
    """
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
    # Deliberately NO junction rows.

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

    assert result.is_error is False, (
        f"A product with no junction rows must fall back to the tenant-active allowlist. Got: {_error_text(result)}"
    )


# ---------------------------------------------------------------------------
# Orchestrator roster
# ---------------------------------------------------------------------------


async def test_roster_follows_the_product(db_session, test_tenant_key):
    """Two products, disjoint junctions -> two different spawnable rosters."""
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


async def test_roster_tolerates_a_product_with_no_junction_rows(db_session, test_tenant_key):
    """A row-less product keeps the tenant-wide roster -- the orchestrator is never blanked."""
    suffix = uuid.uuid4().hex[:8]
    template = _template(test_tenant_key, f"be9385a-roster-tol-{suffix}")
    product = _product(test_tenant_key, f"Roster tolerance {suffix}")
    db_session.add_all([template, product])
    await db_session.flush()

    roster = {
        t.name
        for t in await MissionRepository().get_active_templates(db_session, test_tenant_key, product_id=product.id)
    }

    assert template.name in roster, (
        "A product with no junction rows must keep the tenant-wide roster; an empty "
        "roster here means the orchestrator can spawn nothing."
    )


async def test_roster_cap_matches_the_export_cap(db_session, test_tenant_key):
    """R1: one number for "what is active".

    The roster cap was a local literal 8 while the export cap was 16 (raised
    deliberately in BE-9208). With 9-16 active agents the orchestrator was offered
    a strictly smaller set than the export had already written to disk, so an
    installed agent could be unspawnable. Both now read MAX_PACKAGED_TEMPLATES.
    """
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


# ---------------------------------------------------------------------------
# Lifecycle guarantees
# ---------------------------------------------------------------------------


async def test_deactivated_stays_deactivated_across_reseed_and_reactivation(db_session, test_tenant_key):
    """R2's guard. A CE boot re-seed plus a product re-activation must not resurrect an agent.

    CE reruns the seeder on every boot and re-activating a product bulk-assigns
    templates, so a self-hoster with no operator would otherwise find deliberately
    disabled agents switched back on after an upgrade.
    """
    from giljo_mcp.repositories.product_agent_assignment_repository import (
        ProductAgentAssignmentRepository,
    )
    from giljo_mcp.template_seeder import seed_tenant_templates

    suffix = uuid.uuid4().hex[:8]
    keep = _template(test_tenant_key, f"be9385a-keep-{suffix}")
    retired = _template(test_tenant_key, f"be9385a-retired-{suffix}")
    product = _product(test_tenant_key, f"Curated {suffix}")
    db_session.add_all([keep, retired, product])
    await db_session.flush()

    db_session.add_all(
        [
            _assignment(test_tenant_key, product.id, keep.id, is_active=True),
            # The user deliberately switched this one OFF for this product.
            _assignment(test_tenant_key, product.id, retired.id, is_active=False),
        ]
    )
    await db_session.flush()

    # 1. CE boot re-seed. The seeder must never touch the junction -- if it did,
    #    every upgrade would re-enable what the user turned off.
    await seed_tenant_templates(db_session, test_tenant_key)
    await db_session.flush()

    # 2. Product re-activation (the user toggling back to this product), which
    #    bulk-assigns missing templates. Skip-existing is what protects the OFF row.
    await ProductAgentAssignmentRepository().bulk_assign_all_templates(db_session, product.id, test_tenant_key)
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
        "A deliberately deactivated agent came back after a boot re-seed plus product "
        "re-activation. On CE this happens on every upgrade, and the self-hoster has no "
        "operator to clean it up."
    )

    names = await AgentCompletionRepository().get_active_template_names(
        db_session, test_tenant_key, product_id=product.id
    )
    assert retired.name not in names, f"Retired agent is spawnable again: {sorted(names)}"
    assert keep.name in names, "The agent the user kept must still be spawnable."


async def test_orchestrator_roster_is_product_scoped_at_the_mcp_boundary(spawn_client):
    """DoD 1's third surface, asserted on the wire rather than at the repository.

    ``get_staging_instructions`` is where an orchestrator is TOLD which agents it may
    spawn (``agent_templates``). The repository-level roster tests above pin the
    query; this pins what actually reaches the agent, which is the layer the house
    bug-fix rule cares about.
    """
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
    """Scope item 4: server-delivered identity needed NO change -- pinned, not assumed.

    ``spawn_job`` stores ``template_id`` and ``get_job_mission`` renders the profile
    from it at read time, so a multi_terminal agent gets its identity from the
    server rather than from an installed file. That path is product-bound for free
    once selection is, because the job's project already belongs to a product --
    but "for free" is a claim, and this is the test that makes it evidence.

    The regression it guards is specific: product-scoping ``get_template_by_name``
    (which this project also did) sits directly upstream of the ``template_id``
    that identity resolution reads. Get that wrong and the agent spawns with
    ``template_id=None`` and silently behaves generically -- no error, no clue.
    """
    new_client, tenant_key, session = spawn_client

    suffix = uuid.uuid4().hex[:8]
    template = _template(tenant_key, f"be9385a-profile-{suffix}")
    # The rendered identity is role + user_instructions (+ rules/criteria) --
    # compose_template_identity does not emit the template NAME -- so the marker
    # has to be profile CONTENT. That is the stronger assertion anyway: it proves
    # the agent received its instructions, not merely that something resolved.
    template.user_instructions = f"PROFILE-MARKER-{suffix}: you analyse things."
    template.behavioral_rules = [f"RULE-MARKER-{suffix}"]
    product = _product(tenant_key, f"Profile product {suffix}")
    session.add_all([template, product])
    await session.flush()

    project = _project(tenant_key, product.id, f"BE-9385a profile {suffix}")
    # Handover 0709's implementation gate short-circuits get_job_mission for a
    # project that has not been launched, returning the gate response instead of a
    # profile. That is correct behaviour, not a defect -- but it means an unlaunched
    # project cannot answer the question this test asks.
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


async def test_first_toggle_on_a_rowless_product_does_not_blank_it(db_manager, db_session, test_tenant_key):
    """D1's second half. Materialise-before-flip, proven at the service.

    Two failure modes are pinned here at once, and they pull in opposite directions:

    * Without materialisation the first toggle leaves ONE row, tolerance switches
      off (it keys on row existence), and every other agent silently vanishes from
      the product.
    * Under the old "fall back when the ACTIVE set is empty" rule, toggling the
      only-listed agent OFF would leave an empty active set, re-engage the
      fallback, and the agent would stay enabled -- a control that does nothing.
    """
    from giljo_mcp.services.product_agent_assignment_service import ProductAgentAssignmentService

    suffix = uuid.uuid4().hex[:8]
    first = _template(test_tenant_key, f"be9385a-tog-1-{suffix}")
    second = _template(test_tenant_key, f"be9385a-tog-2-{suffix}")
    third = _template(test_tenant_key, f"be9385a-tog-3-{suffix}")
    product = _product(test_tenant_key, f"Fresh {suffix}")
    db_session.add_all([first, second, third, product])
    await db_session.flush()
    # No junction rows: this product is in the tolerance state.

    service = ProductAgentAssignmentService(db_manager=db_manager, tenant_key=test_tenant_key, test_session=db_session)
    await service.toggle_assignment(product.id, first.id, False)

    names = await AgentCompletionRepository().get_active_template_names(
        db_session, test_tenant_key, product_id=product.id
    )

    assert first.name not in names, (
        "The toggle did nothing. Turning an agent OFF on a product that had no junction "
        "rows must actually disable it -- the UI showed the switch move."
    )
    assert {second.name, third.name} <= set(names), (
        "The first toggle blanked the product: the other agents disappeared because the "
        f"junction was left holding a single row. Remaining: {sorted(names)}"
    )
