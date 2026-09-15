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

from giljo_mcp.models import Project
from giljo_mcp.models.product_agent_assignment import ProductAgentAssignment
from giljo_mcp.models.products import Product
from giljo_mcp.models.templates import AgentTemplate
from giljo_mcp.system_roles import ORCHESTRATOR_AGENT_NAME
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
        description="BE-9391 created-agent usability.",
        mission="Spawn an agent that was just created.",
        status="active",
        tenant_key=tenant_key,
        product_id=product_id,
        series_number=1,
        execution_mode="multi_terminal",
        created_at=datetime.now(UTC),
    )


@pytest_asyncio.fixture
async def agents_client(monkeypatch, db_manager, db_session):
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
        yield _new_client, tenant_key, db_session, tenant_manager
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


async def _create_and_activate_agent(
    session, db_manager, tenant_manager, tenant_key: str, suffix: str, product_id: str
) -> str:
    from api.endpoints.templates.models import TemplateCreate
    from giljo_mcp.services.template_service import TemplateService

    service = TemplateService(db_manager=db_manager, tenant_manager=tenant_manager, session=session)

    created = await service.create_template_from_request(
        session,
        TemplateCreate(product_id=product_id, role="implementer", custom_suffix=f"be9391{suffix}"),
        tenant_key,
        "qa-harness",
    )
    assert created.product_id == product_id, (
        "Guard on this test's own premise: a new agent belongs to the product it was "
        "created in (ruling 2). If this changes, the switch-on step below is toggling "
        "an agent the product does not own and the test stops reproducing the flow."
    )

    from giljo_mcp.services.product_agent_assignment_service import ProductAgentAssignmentService

    assignments = ProductAgentAssignmentService(db_manager, tenant_key, test_session=session)
    await assignments.toggle_assignment(product_id, created.id, is_active=True)

    return created.name


async def _curated_product_with_project(session, tenant_key: str, suffix: str):
    existing_one = _template(tenant_key, f"be9391-seeded-a-{suffix}")
    existing_two = _template(tenant_key, f"be9391-seeded-b-{suffix}")
    product = _product(tenant_key, f"Curated Product {suffix}")
    session.add_all([existing_one, existing_two, product])
    await session.flush()

    project = _project(tenant_key, product.id, f"BE-9391 {suffix}")
    session.add(project)
    session.add_all(
        [
            _assignment(tenant_key, product.id, existing_one.id),
            _assignment(tenant_key, product.id, existing_two.id),
        ]
    )
    session.info["tenant_key"] = tenant_key
    await session.flush()

    return product, project, {existing_one.name, existing_two.name}


async def test_a_newly_created_agent_is_spawnable_in_a_curated_product(agents_client, db_manager):
    new_client, tenant_key, session, tenant_manager = agents_client

    suffix = uuid.uuid4().hex[:8]
    product, project, existing_names = await _curated_product_with_project(session, tenant_key, suffix)
    new_agent = await _create_and_activate_agent(session, db_manager, tenant_manager, tenant_key, suffix, product.id)

    async with new_client() as client:
        result = await client.call_tool(
            "spawn_job",
            {
                "agent_display_name": "worker-1",
                "agent_name": new_agent,
                "project_id": project.id,
                "mission": "Do the work the user just created this agent for.",
            },
        )

    assert result.is_error is False, (
        f"An agent the user just created and activated cannot be spawned into the "
        f"active product.\n"
        f"  created + activated: {new_agent}\n"
        f"  the product's backfilled agents: {sorted(existing_names)}\n"
        f"  rejection: {_error_text(result)}\n"
        "This is BE-9391: ce_0091 made every product curated, and no create/activate "
        "path writes a junction row, so a new agent is excluded by construction."
    )
    assert _payload(result).get("job_id"), "spawn_job reported success without a job_id."


async def test_a_newly_created_agent_is_on_the_orchestrator_roster(agents_client, db_manager):
    new_client, tenant_key, session, tenant_manager = agents_client

    suffix = uuid.uuid4().hex[:8]
    product, project, existing_names = await _curated_product_with_project(session, tenant_key, suffix)
    new_agent = await _create_and_activate_agent(session, db_manager, tenant_manager, tenant_key, suffix, product.id)

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

    assert new_agent in rendered, (
        f"The orchestrator's roster omits {new_agent}, which the user just created and "
        f"activated. It shows only the backfilled set {sorted(existing_names)}, so the "
        "orchestrator cannot delegate to an agent that plainly exists in the UI."
    )






async def test_re_activating_an_agent_does_not_resurrect_it_for_a_product_that_disabled_it(agents_client, db_manager):
    from sqlalchemy import select

    from api.endpoints.templates.models import TemplateUpdate
    from giljo_mcp.services.template_service import TemplateService

    _new_client, tenant_key, session, tenant_manager = agents_client

    suffix = uuid.uuid4().hex[:8]
    agent = _template(tenant_key, f"be9391-retired-{suffix}")
    product = _product(tenant_key, f"Curated {suffix}")
    session.add_all([agent, product])
    await session.flush()
    session.add(_assignment(tenant_key, product.id, agent.id, is_active=False))
    session.info["tenant_key"] = tenant_key
    await session.flush()

    service = TemplateService(db_manager=db_manager, tenant_manager=tenant_manager, session=session)
    await service.update_template_from_request(session, agent.id, TemplateUpdate(is_active=False), tenant_key, "u")
    await service.update_template_from_request(session, agent.id, TemplateUpdate(is_active=True), tenant_key, "u")

    row_is_active = (
        await session.execute(
            select(ProductAgentAssignment.is_active).where(
                ProductAgentAssignment.product_id == product.id,
                ProductAgentAssignment.template_id == agent.id,
                ProductAgentAssignment.tenant_key == tenant_key,
            )
        )
    ).scalar_one()

    assert row_is_active is False, (
        "Re-activating the agent tenant-wide switched it back ON for a product where the "
        "user had disabled it. The tenant flag must not overwrite the per-product choice."
    )


async def test_a_new_agent_is_usable_in_a_hidden_product(agents_client, db_manager):
    from sqlalchemy import func, select

    new_client, tenant_key, session, tenant_manager = agents_client

    suffix = uuid.uuid4().hex[:8]
    hidden = _product(tenant_key, f"Hidden Product {suffix}", is_active=False)
    untouched = _product(tenant_key, f"Untouched Product {suffix}", is_active=True)
    session.add_all([hidden, untouched])
    await session.flush()

    project = _project(tenant_key, hidden.id, f"BE-9391 hidden-product {suffix}")
    session.add(project)
    session.info["tenant_key"] = tenant_key
    await session.flush()

    new_agent = await _create_and_activate_agent(session, db_manager, tenant_manager, tenant_key, suffix, hidden.id)

    async with new_client() as client:
        spawned = await client.call_tool(
            "spawn_job",
            {
                "agent_display_name": "worker-1",
                "agent_name": new_agent,
                "project_id": project.id,
                "mission": "Usable in a hidden product.",
            },
        )
    assert spawned.is_error is False, (
        "An agent created and switched on in a HIDDEN product is not usable there. "
        f"Hidden means 'tab not shown', not 'paused': {_error_text(spawned)}"
    )

    untouched_rows = (
        await session.execute(
            select(func.count(ProductAgentAssignment.id)).where(
                ProductAgentAssignment.tenant_key == tenant_key,
                ProductAgentAssignment.product_id == untouched.id,
            )
        )
    ).scalar_one()
    assert untouched_rows == 0, (
        f"{untouched_rows} junction row(s) were written into a product the user never "
        "touched. Creating an agent in one product must not reach into another -- that "
        "is the cross-product write this project exists to remove."
    )


async def test_creating_an_agent_never_writes_into_another_product(agents_client, db_manager):
    from sqlalchemy import select

    _new_client, tenant_key, session, tenant_manager = agents_client

    suffix = uuid.uuid4().hex[:8]
    home, _project_row, _existing = await _curated_product_with_project(session, tenant_key, suffix)
    neighbour, _neighbour_project, neighbour_names = await _curated_product_with_project(
        session, tenant_key, f"{suffix}n"
    )

    before = {
        row[0]
        for row in (
            await session.execute(
                select(ProductAgentAssignment.template_id).where(
                    ProductAgentAssignment.product_id == neighbour.id,
                    ProductAgentAssignment.tenant_key == tenant_key,
                )
            )
        ).all()
    }

    await _create_and_activate_agent(session, db_manager, tenant_manager, tenant_key, suffix, home.id)

    after = {
        row[0]
        for row in (
            await session.execute(
                select(ProductAgentAssignment.template_id).where(
                    ProductAgentAssignment.product_id == neighbour.id,
                    ProductAgentAssignment.tenant_key == tenant_key,
                )
            )
        ).all()
    }

    assert after == before, (
        f"Creating and enabling an agent in {home.name!r} changed the junction of "
        f"{neighbour.name!r}. Editing an agent in one product must not touch another. "
        f"added={sorted(after - before)} removed={sorted(before - after)}"
    )
    assert neighbour_names, "guard on the fixture: the neighbour must actually have agents"
