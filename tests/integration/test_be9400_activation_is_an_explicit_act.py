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
from giljo_mcp.models.product_agent_assignment import ProductAgentAssignment
from giljo_mcp.models.products import Product
from giljo_mcp.models.templates import AgentTemplate
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


async def _create_agent(session, db_manager, tenant_manager, tenant_key: str, suffix: str, product_id: str):
    from api.endpoints.templates.models import TemplateCreate
    from giljo_mcp.services.template_service import TemplateService

    service = TemplateService(db_manager=db_manager, tenant_manager=tenant_manager, session=session)
    created = await service.create_template_from_request(
        session,
        TemplateCreate(
            product_id=product_id,
            role="implementer",
            custom_suffix=f"be9400{suffix}",
            is_active=True,
        ),
        tenant_key,
        "the-user",
    )
    assert created.is_active is True, (
        "Guard on this test's own premise: the agent must be born with the tenant "
        "column set (it is inert since ruling 7, but it must still be ON at birth). "
        "If this flips, the test is no longer exercising the ruling."
    )
    return created


async def _junction_row(session, tenant_key: str, product_id: str, template_id: str):
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
    _new_client, tenant_key, session, tenant_manager = agents_client

    suffix = uuid.uuid4().hex[:8]
    product, _project_row, _existing = await _curated_product_with_project(session, tenant_key, suffix)
    created = await _create_agent(session, db_manager, tenant_manager, tenant_key, suffix, product.id)

    row = await _junction_row(session, tenant_key, product.id, created.id)

    assert row is None or row.is_active is False, (
        "A newly created agent arrived ACTIVE in the current product. Activation "
        "must be an explicit user act, never a side effect of creation: the user "
        "asked for raw material to configure, and an unconfigured agent just went "
        "live in the product they are working in."
    )


async def test_a_newly_created_agent_is_not_spawnable_until_the_user_switches_it_on(agents_client, db_manager):
    new_client, tenant_key, session, tenant_manager = agents_client

    suffix = uuid.uuid4().hex[:8]
    product, project, _existing = await _curated_product_with_project(session, tenant_key, suffix)
    created = await _create_agent(session, db_manager, tenant_manager, tenant_key, suffix, product.id)

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
    _new_client, tenant_key, session, tenant_manager = agents_client

    suffix = uuid.uuid4().hex[:8]
    product, _project_row, _existing = await _curated_product_with_project(session, tenant_key, suffix)
    created = await _create_agent(session, db_manager, tenant_manager, tenant_key, suffix, product.id)

    from api.endpoints.templates.models import TemplateUpdate
    from giljo_mcp.services.template_service import TemplateService

    service = TemplateService(db_manager=db_manager, tenant_manager=tenant_manager, session=session)

    assert created.is_active is True, "the tenant-wide column must stay ON at birth."
    assert created.deleted_at is None, "A newly created agent must not be soft-deleted."

    live = await service.list_templates_with_filters(session, tenant_key)
    assert created.name in {t.name for t in live}, (
        f"{created.name} is missing from the agent list. An agent switched off in a "
        "product must still be VISIBLE -- invisible in two places at once is the "
        "BE-9391 defect this ruling must not reintroduce."
    )

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
    new_client, tenant_key, session, tenant_manager = agents_client
    from giljo_mcp.services.product_agent_assignment_service import ProductAgentAssignmentService

    suffix = uuid.uuid4().hex[:8]
    product, project, _existing = await _curated_product_with_project(session, tenant_key, suffix)
    created = await _create_agent(session, db_manager, tenant_manager, tenant_key, suffix, product.id)

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
    _new_client, tenant_key, session, _tenant_manager = agents_client
    from giljo_mcp.template_import import import_default_templates

    suffix = uuid.uuid4().hex[:8]
    product, _project_row, _existing = await _curated_product_with_project(session, tenant_key, suffix)

    await import_default_templates(session, tenant_key, product.id)
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
        assert template.product_id == product.id, (
            f"Imported default {template.name!r} is owned by {template.product_id!r}, not the "
            "product it was imported into. An agent owned by another product is on the wrong tab."
        )
        row = await _junction_row(session, tenant_key, product.id, template.id)
        assert row is not None and row.is_active is True, (
            f"Imported default {template.name!r} did not arrive switched on. The button hands "
            "the user a working crew; one they must enable agent by agent is not that."
        )


async def test_a_newly_created_agent_is_live_in_no_product_at_all(agents_client, db_manager):
    from giljo_mcp.repositories.product_agent_selection import template_ids_for_product

    _new_client, tenant_key, session, tenant_manager = agents_client

    suffix = uuid.uuid4().hex[:8]
    product, _project_row, _existing = await _curated_product_with_project(session, tenant_key, suffix)
    other, _other_project, _other_existing = await _curated_product_with_project(session, tenant_key, f"{suffix}b")

    created = await _create_agent(session, db_manager, tenant_manager, tenant_key, suffix, product.id)

    for candidate in (product, other):
        served = await template_ids_for_product(session, candidate.id, tenant_key)
        assert created.id not in served, (
            f"A newly created agent is live in product {candidate.name!r}. Activation is an "
            "explicit user act, never a side effect of creation (BE-9400)."
        )

    assert created.product_id == product.id, "a new agent belongs to the product it was created in (ruling 2)"
