# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-9391 -- an agent you just created must be usable, immediately.

THE REGRESSION. ``ce_0091`` backfilled a junction row for every (product, active
template) pair, so every pre-existing product now HAS rows and is therefore
"curated" under BE-9385a's existence-keyed tolerance. Selection is then
authoritative: no row means excluded. But nothing on the template CREATE or
ACTIVATE path writes a junction row -- the writers are exactly
``toggle_assignment``, ``bulk_assign_all_templates`` (product activation) and the
one-time ``ce_0091``. A template that comes into existence after the backfill
therefore lands outside the curated set by construction, and the user who just
made it finds it silently unspawnable, absent from the orchestrator's roster, and
missing from the export.

Caught by the black-box QA harness (Suite B2) on the pre-production gate:

    Error: B1 the active template 'implementer-qab251022' is spawnable
    Expected value: "implementer-qab251022"
    Received array: ["documenter", "reviewer", "tester", "analyzer", "implementer"]

-- exactly the five agents ``ce_0091`` backfilled.

WHY THE FLOW BELOW IS CREATE-THEN-ACTIVATE, and not create-with-is_active
------------------------------------------------------------------------
``TemplateCreate.is_active`` defaults to ``False`` and the UI's create payload
(``TemplateManager.vue:458-473``) does not send the field at all, so a new agent
is born tenant-INACTIVE and is switched on afterwards through
``PUT /api/v1/templates/{id}``. ``bulk_assign_all_templates`` only ever assigns
tenant-ACTIVE templates, so a hook that fired at create time and nothing else
would be a no-op on the real path -- it would pass a hand-written service test
and still leave Suite B2 red. These tests drive both steps through the real
owning-service write paths for that reason.

Layer: MCP boundary, through the real transport, per the house bug-fix rule --
the failing surfaces are what an agent receives from ``spawn_job``,
``get_staging_instructions`` and ``giljo_setup``, so that is where the assertions
are made. Fixtures are lifted from the two BE-9385a integration files rather than
re-invented, so the chain under test is the shipped one.

Parallel-safe: fresh tenant_key per test, rolled-back ``db_session``, no
module-level mutable state.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Any

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
    """FastMCP client on a REAL ToolAccessor bound to the rolled-back test session.

    ``ToolAccessor.get_session_async`` honours ``test_session`` (``__init__.py:145-159``),
    so this one fixture serves all three surfaces -- ``spawn_job``,
    ``get_staging_instructions`` and ``giljo_setup``.

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


async def _create_and_activate_agent(session, db_manager, tenant_manager, tenant_key: str, suffix: str) -> str:
    """Drive the REAL create + tenant-wide activate path; return the generated name.

    This is the user's action and the QA harness's action, through the owning
    service that the thin REST endpoints delegate to (``crud.py:141-151`` for
    create, ``:172-179`` for update -- both are pass-throughs since BE-8000j).
    ``is_active`` is deliberately NOT passed to the create call: the UI does not
    send it either, so the agent is born inactive exactly as in production.
    """
    from api.endpoints.templates.models import TemplateCreate, TemplateUpdate
    from giljo_mcp.services.template_service import TemplateService

    service = TemplateService(db_manager=db_manager, tenant_manager=tenant_manager, session=session)

    created = await service.create_template_from_request(
        session,
        TemplateCreate(role="implementer", custom_suffix=f"be9391{suffix}"),
        tenant_key,
        "qa-harness",
    )
    assert created.is_active is False, (
        "Guard on this test's own premise: the create path is expected to produce a "
        "tenant-INACTIVE agent (TemplateCreate.is_active defaults False and the UI "
        "omits the field). If this ever changes, the activate step below stops "
        "reproducing the user's flow and this test must be revisited."
    )

    # The user flips the agent on / the harness activates it tenant-wide.
    activated, _fields = await service.update_template_from_request(
        session,
        created.id,
        TemplateUpdate(is_active=True),
        tenant_key,
        "qa-harness",
    )
    assert activated.is_active is True, "The activate step did not make the agent tenant-active."

    return created.name


async def _curated_product_with_project(session, tenant_key: str, suffix: str):
    """An ACTIVE product that already has junction rows -- the post-``ce_0091`` world.

    Returns ``(product, project, existing_template_names)``.
    """
    existing_one = _template(tenant_key, f"be9391-seeded-a-{suffix}")
    existing_two = _template(tenant_key, f"be9391-seeded-b-{suffix}")
    product = _product(tenant_key, f"Curated Product {suffix}")
    session.add_all([existing_one, existing_two, product])
    await session.flush()

    project = _project(tenant_key, product.id, f"BE-9391 {suffix}")
    session.add(project)
    # This is what ce_0091 wrote: a row per (product, active template) pair.
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
    """THE REPORTED DEFECT, at the surface QA hit. Fail-first against master.

    Pre-fix the rejection lists only the backfilled agents and the brand-new one
    is absent -- byte-for-byte the Suite B2 failure.
    """
    new_client, tenant_key, session, tenant_manager = agents_client

    suffix = uuid.uuid4().hex[:8]
    _product_row, project, existing_names = await _curated_product_with_project(session, tenant_key, suffix)
    new_agent = await _create_and_activate_agent(session, db_manager, tenant_manager, tenant_key, suffix)

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
    """Second surface: the roster the orchestrator is actually TOLD it may spawn from.

    ``get_staging_instructions`` is where that list reaches the agent, so it is
    asserted on the wire rather than at the repository.
    """
    new_client, tenant_key, session, tenant_manager = agents_client

    suffix = uuid.uuid4().hex[:8]
    _product_row, project, existing_names = await _curated_product_with_project(session, tenant_key, suffix)
    new_agent = await _create_and_activate_agent(session, db_manager, tenant_manager, tenant_key, suffix)

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


async def test_a_newly_created_agent_is_exported(agents_client, db_manager):
    """Third surface: the export. An agent that never ships is an agent that never runs.

    ``web_sandbox`` takes ``giljo_setup``'s no-filesystem branch, which returns the
    selected templates inline instead of a staged ZIP, so the shipped set is
    directly assertable on the wire.
    """
    new_client, tenant_key, session, tenant_manager = agents_client

    suffix = uuid.uuid4().hex[:8]
    await _curated_product_with_project(session, tenant_key, suffix)
    new_agent = await _create_and_activate_agent(session, db_manager, tenant_manager, tenant_key, suffix)

    async with new_client() as client:
        result = await client.call_tool(
            "giljo_setup",
            {"platform": "claude_code", "harness": "web_sandbox"},
        )

    assert not result.is_error, f"giljo_setup errored on the wire: {result.content}"
    payload: dict[str, Any] = result.structured_content or {}
    assert payload.get("mode") == "inline", f"Expected giljo_setup's inline branch; got mode={payload.get('mode')!r}."
    shipped = {a["filename"] for a in payload.get("agents", [])}

    # BE-9385b: the filename is now product-qualified. Match on the agent-name
    # stem rather than the whole name so this test keeps asserting what it is about
    # -- that the newly created agent SHIPS -- instead of re-pinning a naming
    # scheme that BE-9385b's own tests already own.
    assert any(f.startswith(f"{new_agent}") and f.endswith(".md") for f in shipped), (
        f"The export omits {new_agent}.md -- the agent the user just created is never "
        f"installed on disk, so it cannot run even if something tried to spawn it. "
        f"Shipped: {sorted(shipped)}"
    )


# REPEALED BY BE-9400: ``test_an_agent_created_already_active_is_spawnable``.
#
# It created a template with ``is_active=True`` in one shot and asserted the agent
# was immediately spawnable in the curated product -- i.e. that CREATION had made it
# active in that product. The operator's 2026-08-10 ruling repeals exactly that:
# activation is always an explicit user act, never a side effect of creation, so a
# new agent now arrives available but switched OFF in the current product.
#
# Removed rather than rewritten: its stated purpose was to exercise the create-side
# junction write, and BE-9400 removes that write. Its replacement is
# ``tests/integration/test_be9400_activation_is_an_explicit_act.py``, which asserts
# the inverse on the same setup AND keeps this file's real guarantee -- that the
# agent is not stranded -- by proving it stays available, visible and editable, and
# becomes spawnable after one explicit toggle.
#
# The other six tests below and above are untouched: they drive create-THEN-activate,
# where the junction row comes from the tenant-wide switch-on hook, which BE-9400
# deliberately leaves alone.


async def test_re_activating_an_agent_does_not_resurrect_it_for_a_product_that_disabled_it(agents_client, db_manager):
    """R2's guarantee, against the NEW write this fix introduces.

    The fix fires on every tenant-wide False -> True transition, so it now runs in a
    situation R2 cares about: the user has switched this agent OFF **for this
    product**, then retires and un-retires it tenant-wide. ``assign_all_templates``
    is skip-existing, so the explicit ``is_active=False`` row must survive. If this
    ever reddens, the fix has started overriding a per-product choice from the
    tenant-wide switch -- exactly what BE-9385a separated.
    """
    from sqlalchemy import select

    from api.endpoints.templates.models import TemplateUpdate
    from giljo_mcp.services.template_service import TemplateService

    _new_client, tenant_key, session, tenant_manager = agents_client

    suffix = uuid.uuid4().hex[:8]
    agent = _template(tenant_key, f"be9391-retired-{suffix}")
    product = _product(tenant_key, f"Curated {suffix}")
    session.add_all([agent, product])
    await session.flush()
    # The user deliberately switched this agent OFF for this product.
    session.add(_assignment(tenant_key, product.id, agent.id, is_active=False))
    session.info["tenant_key"] = tenant_key
    await session.flush()

    service = TemplateService(db_manager=db_manager, tenant_manager=tenant_manager, session=session)
    # Retire tenant-wide, then un-retire -- the transition the fix hooks.
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


async def test_a_new_agent_is_usable_when_no_product_is_active(agents_client, db_manager):
    """THE EM RULING, pinned. With no active product the fix writes NOTHING -- and must not need to.

    A CE fresh install and a tenant between products both land here. Both selection
    helpers return ``None`` when no product is in play, so tolerance engages and the
    tenant-active set passes through untouched: the agent is spawnable and exported
    without a single junction row existing.

    The rejected alternative was to assign the new agent to the tenant's INACTIVE
    products. That would curate products the user never touched -- switching
    tolerance off for them as a side effect of creating an agent, which is the
    "product goes dark" failure the feature exists to avoid. The row-count assertion
    below is what stops a future change from quietly doing that.
    """
    from sqlalchemy import func, select

    new_client, tenant_key, session, tenant_manager = agents_client

    suffix = uuid.uuid4().hex[:8]
    # A product exists but is NOT active, and has no junction rows: "between products".
    dormant = _product(tenant_key, f"Dormant Product {suffix}", is_active=False)
    session.add(dormant)
    await session.flush()

    project = _project(tenant_key, dormant.id, f"BE-9391 no-active-product {suffix}")
    session.add(project)
    session.info["tenant_key"] = tenant_key
    await session.flush()

    new_agent = await _create_and_activate_agent(session, db_manager, tenant_manager, tenant_key, suffix)

    async with new_client() as client:
        spawned = await client.call_tool(
            "spawn_job",
            {
                "agent_display_name": "worker-1",
                "agent_name": new_agent,
                "project_id": project.id,
                "mission": "Usable with no active product.",
            },
        )
    assert spawned.is_error is False, (
        "With no active product, tolerance must carry the tenant-active set through. "
        f"A newly created agent was stranded instead: {_error_text(spawned)}"
    )

    async with new_client() as client:
        exported = await client.call_tool("giljo_setup", {"platform": "claude_code", "harness": "web_sandbox"})
    assert not exported.is_error, f"giljo_setup errored on the wire: {exported.content}"
    shipped = {a["filename"] for a in (exported.structured_content or {}).get("agents", [])}
    assert f"{new_agent}.md" in shipped, f"The export dropped {new_agent}.md. Shipped: {sorted(shipped)}"

    row_count = (
        await session.execute(
            select(func.count(ProductAgentAssignment.id)).where(
                ProductAgentAssignment.tenant_key == tenant_key,
            )
        )
    ).scalar_one()
    assert row_count == 0, (
        f"{row_count} junction row(s) were written with no active product. The fix must "
        "write NOTHING here: curating a dormant product turns its tolerance off, and the "
        "next agent added while it is still dormant would then be excluded from it."
    )


async def test_the_no_active_product_gap_self_heals_on_the_next_activation(agents_client, db_manager):
    """The other half of the ruling: doing nothing is safe BECAUSE activation heals it.

    Accepting the no-op means accepting that a dormant product has no row for this
    agent. That is only acceptable because activation runs the same skip-existing
    pass and picks it up -- so this pins the healing path rather than trusting it.
    """
    from sqlalchemy import select

    from giljo_mcp.repositories.product_agent_assignment_repository import (
        ProductAgentAssignmentRepository,
    )

    _new_client, tenant_key, session, tenant_manager = agents_client

    suffix = uuid.uuid4().hex[:8]
    dormant = _product(tenant_key, f"Dormant Product {suffix}", is_active=False)
    session.add(dormant)
    await session.flush()
    session.info["tenant_key"] = tenant_key

    new_agent = await _create_and_activate_agent(session, db_manager, tenant_manager, tenant_key, suffix)

    # Exactly what product activation does (product_lifecycle_service.py:186-208).
    await ProductAgentAssignmentRepository().bulk_assign_all_templates(session, dormant.id, tenant_key)
    await session.flush()

    healed = (
        await session.execute(
            select(ProductAgentAssignment.is_active)
            .join(AgentTemplate, AgentTemplate.id == ProductAgentAssignment.template_id)
            .where(
                ProductAgentAssignment.product_id == dormant.id,
                ProductAgentAssignment.tenant_key == tenant_key,
                AgentTemplate.name == new_agent,
            )
        )
    ).scalar_one_or_none()

    assert healed is True, (
        f"Activating the product did not pick up {new_agent}. The no-active-product "
        "no-op is only safe because this heals; if it stops healing, the ruling has to "
        "be revisited rather than the test relaxed."
    )
