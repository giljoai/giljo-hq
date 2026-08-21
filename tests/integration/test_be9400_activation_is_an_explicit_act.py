# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-9400 -- activation is an explicit user act, never a side effect of creation.

THE OPERATOR'S RULING. A user who has renamed the seeded agents and rewritten
their instructions later wants more agents. What they are asking for is RAW
MATERIAL TO CONFIGURE, not working agents: "these should not load in activated,
only existing and activated agents stay activated." So everything new -- newly
created templates and everything from "Add Default Agents" -- arrives switched
OFF in the current product. Auto-activating drops generic, unconfigured agents
into a live product, which is the opposite of what a user rebuilding their own
set wants.

TWO SWITCHES, AND THE DISTINCTION IS THE WHOLE PROJECT
------------------------------------------------------
* "Available in all products" -- tenant ``is_active``, the Edit dialog switch.
  The agent EXISTS, is visible in the list, and is editable. **Stays ON at birth.**
* "Active here" -- the per-product junction row, the table column. The agent is
  live in the product I am in. **OFF at birth.**

The ruling applies to "Active here" ONLY. If both were off at birth the agent
would be invisible in two places at once -- which is exactly how BE-9391's
"created agents unusable" defect presented to QA at the pre-production gate. The
preservation tests below exist so that cannot be reintroduced: a new agent must
still be available, visible, editable, and spawnable ONCE THE USER SWITCHES IT ON.

Layer: the MCP boundary for spawnability (the surface QA and the orchestrator
actually hit) plus a direct junction read for the switch state, which is the
thing the ruling is about. Fixtures follow ``test_be9391_created_template_is_usable``
so the chain under test is the shipped one.

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
from giljo_mcp.models.product_agent_assignment import ProductAgentAssignment
from giljo_mcp.models.products import Product
from giljo_mcp.models.templates import AgentTemplate
from giljo_mcp.tenant import TenantManager
from tests.helpers.mcp_session_fixture import create_connected_server_and_client_session


pytestmark = pytest.mark.asyncio


def _template(tenant_key: str, name: str) -> AgentTemplate:
    """A pre-existing, tenant-active agent -- one of the rows ``ce_0091`` backfilled."""
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
        description="BE-9400 activation is an explicit act.",
        mission="Spawn an agent the user switched on.",
        status="active",
        tenant_key=tenant_key,
        product_id=product_id,
        series_number=1,
        execution_mode="multi_terminal",
        created_at=datetime.now(UTC),
    )


@pytest_asyncio.fixture
async def agents_client(monkeypatch, db_manager, db_session):
    """FastMCP client on a REAL ToolAccessor bound to the rolled-back test session.

    Yields ``(client_factory, tenant_key, session, tenant_manager)``.
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
    state.tool_accessor = ToolAccessor(db_manager=db_manager, tenant_manager=tenant_manager, test_session=db_session)

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


async def _curated_product_with_project(session, tenant_key: str, suffix: str):
    """An ACTIVE product that already has junction rows -- the post-``ce_0091`` world."""
    existing_one = _template(tenant_key, f"be9400-seeded-a-{suffix}")
    existing_two = _template(tenant_key, f"be9400-seeded-b-{suffix}")
    product = _product(tenant_key, f"Curated Product {suffix}")
    session.add_all([existing_one, existing_two, product])
    await session.flush()

    project = _project(tenant_key, product.id, f"BE-9400 {suffix}")
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


async def _create_agent(session, db_manager, tenant_manager, tenant_key: str, suffix: str):
    """Create an agent the way the shipped UI does: tenant-ACTIVE in one shot.

    ``TemplateManager.vue:410`` sends ``is_active: true`` on create, so this is
    the production path -- not the REST default (``TemplateCreate.is_active``
    defaults False) and not the create-then-activate flow BE-9391 drives.
    """
    from api.endpoints.templates.models import TemplateCreate
    from giljo_mcp.services.template_service import TemplateService

    service = TemplateService(db_manager=db_manager, tenant_manager=tenant_manager, session=session)
    created = await service.create_template_from_request(
        session,
        TemplateCreate(role="implementer", custom_suffix=f"be9400{suffix}", is_active=True),
        tenant_key,
        "the-user",
    )
    assert created.is_active is True, (
        "Guard on this test's own premise: the agent must be born TENANT-ACTIVE "
        "('Available in all products' stays ON at birth). If this flips, the test "
        "is no longer exercising the ruling."
    )
    return created


async def _junction_row(session, tenant_key: str, product_id: str, template_id: str):
    """The (product, template) junction row, or None when no row exists."""
    return (
        await session.execute(
            select(ProductAgentAssignment).where(
                ProductAgentAssignment.product_id == product_id,
                ProductAgentAssignment.template_id == template_id,
                ProductAgentAssignment.tenant_key == tenant_key,
            )
        )
    ).scalar_one_or_none()


async def test_a_newly_created_agent_is_not_active_in_the_current_product(agents_client, db_manager):
    """THE RULING, pinned. Fail-first against master, where creation activates.

    Pre-fix ``create_from_request`` calls ``include_in_active_product``, which
    materialises the junction with this agent ``is_active=True`` -- the agent goes
    live in the product the moment it is created, with no user act.
    """
    _new_client, tenant_key, session, tenant_manager = agents_client

    suffix = uuid.uuid4().hex[:8]
    product, _project_row, _existing = await _curated_product_with_project(session, tenant_key, suffix)
    created = await _create_agent(session, db_manager, tenant_manager, tenant_key, suffix)

    row = await _junction_row(session, tenant_key, product.id, created.id)

    assert row is None or row.is_active is False, (
        "A newly created agent arrived ACTIVE in the current product. Activation "
        "must be an explicit user act, never a side effect of creation: the user "
        "asked for raw material to configure, and an unconfigured agent just went "
        "live in the product they are working in."
    )


async def test_a_newly_created_agent_is_not_spawnable_until_the_user_switches_it_on(agents_client, db_manager):
    """The same ruling at the surface it matters on -- what the product can spawn.

    A junction flag nobody reads would be a switch that reports success and does
    nothing, so the state is asserted through the MCP boundary as well.
    """
    new_client, tenant_key, session, tenant_manager = agents_client

    suffix = uuid.uuid4().hex[:8]
    _product_row, project, _existing = await _curated_product_with_project(session, tenant_key, suffix)
    created = await _create_agent(session, db_manager, tenant_manager, tenant_key, suffix)

    async with new_client() as client:
        result = await client.call_tool(
            "spawn_job",
            {
                "agent_display_name": "worker-1",
                "agent_name": created.name,
                "project_id": project.id,
                "mission": "Should not be spawnable before the user switches it on.",
            },
        )

    assert result.is_error is True, (
        f"An agent the user created but never switched on for this product was "
        f"spawnable anyway: {created.name}. Creation activated it in the product."
    )


async def test_a_newly_created_agent_is_available_visible_and_editable(agents_client, db_manager):
    """BE-9391's guarantee, PRESERVED. The agent must not be invisible twice over.

    'Off in this product' must never become 'gone'. Both-switches-off is precisely
    how BE-9391's defect presented to QA, so this pins the tenant switch ON, the
    agent present in the tenant's live list, and the agent editable.
    """
    _new_client, tenant_key, session, tenant_manager = agents_client

    suffix = uuid.uuid4().hex[:8]
    await _curated_product_with_project(session, tenant_key, suffix)
    created = await _create_agent(session, db_manager, tenant_manager, tenant_key, suffix)

    from api.endpoints.templates.models import TemplateUpdate
    from giljo_mcp.services.template_service import TemplateService

    service = TemplateService(db_manager=db_manager, tenant_manager=tenant_manager, session=session)

    # AVAILABLE: the tenant-wide switch is ON.
    assert created.is_active is True, "'Available in all products' must stay ON at birth."
    assert created.deleted_at is None, "A newly created agent must not be soft-deleted."

    # VISIBLE: it is in the tenant's live template list, not hidden.
    live = await service.list_templates_with_filters(session, tenant_key)
    assert created.name in {t.name for t in live}, (
        f"{created.name} is missing from the agent list. An agent switched off in a "
        "product must still be VISIBLE -- invisible in two places at once is the "
        "BE-9391 defect this ruling must not reintroduce."
    )

    # EDITABLE: the user can configure it, which is the whole point of creating it.
    edited, _fields = await service.update_template_from_request(
        session,
        created.id,
        TemplateUpdate(user_instructions="configured by the user"),
        tenant_key,
        "the-user",
    )
    assert edited.user_instructions == "configured by the user", (
        "A newly created agent could not be edited. It arrives as raw material to "
        "configure, so editing it is the primary thing the user does next."
    )


async def test_a_newly_created_agent_becomes_spawnable_once_switched_on(agents_client, db_manager):
    """The other half of preservation: the switch WORKS, and one act is enough.

    Off-at-birth is only acceptable because switching it on is immediate and
    sufficient. If this reddens, the agent is stranded rather than waiting.
    """
    new_client, tenant_key, session, tenant_manager = agents_client
    from giljo_mcp.services.product_agent_assignment_service import ProductAgentAssignmentService

    suffix = uuid.uuid4().hex[:8]
    product, project, _existing = await _curated_product_with_project(session, tenant_key, suffix)
    created = await _create_agent(session, db_manager, tenant_manager, tenant_key, suffix)

    # THE EXPLICIT USER ACT -- the "Active here" toggle in the table.
    svc = ProductAgentAssignmentService(db_manager, tenant_key, test_session=session)
    await svc.toggle_assignment(product.id, created.id, True)

    async with new_client() as client:
        result = await client.call_tool(
            "spawn_job",
            {
                "agent_display_name": "worker-1",
                "agent_name": created.name,
                "project_id": project.id,
                "mission": "Switched on by the user, now do the work.",
            },
        )

    assert result.is_error is False, (
        f"The user switched {created.name} on for this product and it is still not "
        f"spawnable: {_error_text(result)}. The agent is stranded, not waiting."
    )
    assert _payload(result).get("job_id"), "spawn_job reported success without a job_id."


async def test_add_default_agents_arrives_available_but_switched_off(agents_client, db_manager):
    """ "Add Default Agents" -- ALREADY CORRECT. Confirmed by test, changed by nothing.

    ``template_import.py`` defaults tenant ``is_active`` True and writes no
    junction row, so imported defaults already arrive available and switched off.
    This test exists so that stays true: it is the only thing standing between the
    ruling and a future change that wires a junction writer into the import path.
    """
    _new_client, tenant_key, session, _tenant_manager = agents_client
    from giljo_mcp.template_import import import_default_templates

    suffix = uuid.uuid4().hex[:8]
    product, _project_row, _existing = await _curated_product_with_project(session, tenant_key, suffix)

    await import_default_templates(session, tenant_key)
    await session.flush()

    imported = (
        (
            await session.execute(
                select(AgentTemplate).where(
                    AgentTemplate.tenant_key == tenant_key,
                    AgentTemplate.name.not_in([f"be9400-seeded-a-{suffix}", f"be9400-seeded-b-{suffix}"]),
                )
            )
        )
        .scalars()
        .all()
    )
    assert imported, "Add Default Agents imported nothing -- this test's premise is gone."

    for template in imported:
        assert template.is_active is True, (
            f"Imported default {template.name!r} arrived tenant-INACTIVE. Both switches "
            "off makes it invisible twice over -- the BE-9391 defect."
        )
        row = await _junction_row(session, tenant_key, product.id, template.id)
        assert row is None or row.is_active is False, (
            f"Imported default {template.name!r} arrived ACTIVE in the current product. "
            "Add Default Agents is a request for raw material to configure, not for "
            "generic unconfigured agents to go live."
        )
