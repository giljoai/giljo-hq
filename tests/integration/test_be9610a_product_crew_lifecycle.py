# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from sqlalchemy import select

from giljo_mcp.database import tenant_session_context
from giljo_mcp.models.product_agent_assignment import ProductAgentAssignment
from giljo_mcp.models.products import Product
from giljo_mcp.models.templates import AgentTemplate
from giljo_mcp.repositories.product_agent_selection import template_ids_for_product
from giljo_mcp.tenant import TenantManager


pytestmark = pytest.mark.asyncio

FACTORY_ROLES = {"implementer", "tester", "analyzer", "reviewer", "documenter"}


@pytest_asyncio.fixture
async def tenant_key() -> str:
    return TenantManager.generate_tenant_key()


def _product_service(db_manager, db_session, tenant_key: str):
    from giljo_mcp.services.product_service import ProductService

    return ProductService(db_manager=db_manager, tenant_key=tenant_key, test_session=db_session)


def _lifecycle_service(db_manager, db_session, tenant_key: str):
    from giljo_mcp.services.product_lifecycle_service import ProductLifecycleService

    return ProductLifecycleService(db_manager=db_manager, tenant_key=tenant_key, test_session=db_session)


async def _owned(db_session, tenant_key: str, product_id: str, *, deleted: bool | None = False):
    stmt = select(AgentTemplate).where(
        AgentTemplate.tenant_key == tenant_key,
        AgentTemplate.product_id == product_id,
    )
    if deleted is False:
        stmt = stmt.where(AgentTemplate.deleted_at.is_(None))
    elif deleted is True:
        stmt = stmt.where(AgentTemplate.deleted_at.isnot(None))
    with tenant_session_context(db_session, tenant_key):
        return list((await db_session.execute(stmt)).scalars().all())




async def test_a_new_product_arrives_with_a_working_crew(db_manager, db_session, tenant_key):
    service = _product_service(db_manager, db_session, tenant_key)

    product = await service.create_product(name=f"Fresh {uuid.uuid4().hex[:8]}")

    crew = await _owned(db_session, tenant_key, product.id)
    assert {t.role for t in crew} == FACTORY_ROLES, f"expected the factory crew, got {sorted(t.role for t in crew)}"

    served = await template_ids_for_product(db_session, product.id, tenant_key)
    assert served == {t.id for t in crew}, "a seeded crew arrives SWITCHED ON -- a product is handed a working team"


async def test_a_second_product_gets_its_own_copies_not_the_first_products(db_manager, db_session, tenant_key):
    service = _product_service(db_manager, db_session, tenant_key)

    first = await service.create_product(name=f"First {uuid.uuid4().hex[:8]}")
    second = await service.create_product(name=f"Second {uuid.uuid4().hex[:8]}")

    first_crew = await _owned(db_session, tenant_key, first.id)
    second_crew = await _owned(db_session, tenant_key, second.id)

    assert {t.id for t in first_crew}.isdisjoint({t.id for t in second_crew}), "the crews must be different ROWS"
    assert {t.name for t in first_crew}.isdisjoint({t.name for t in second_crew}), "names stay unique per account"
    assert {t.role for t in second_crew} == FACTORY_ROLES
    assert all(t.name.endswith("-2") for t in second_crew), (
        f"the second crew shares ONE suffix (ruling 6); got {sorted(t.name for t in second_crew)}"
    )


async def test_editing_one_products_agent_cannot_change_another(db_manager, db_session, tenant_key):
    service = _product_service(db_manager, db_session, tenant_key)
    first = await service.create_product(name=f"First {uuid.uuid4().hex[:8]}")
    second = await service.create_product(name=f"Second {uuid.uuid4().hex[:8]}")

    mine = next(t for t in await _owned(db_session, tenant_key, first.id) if t.role == "tester")
    theirs = next(t for t in await _owned(db_session, tenant_key, second.id) if t.role == "tester")
    before = theirs.user_instructions

    mine.user_instructions = "MY HOUSE TESTING RULES"
    await db_session.commit()
    await db_session.refresh(theirs)

    assert theirs.user_instructions == before, (
        "rewriting one product's tester changed the other product's tester -- they are still sharing a row"
    )
    assert theirs.id != mine.id


async def test_a_failed_crew_seed_fails_the_whole_create(db_manager, db_session, tenant_key, monkeypatch):
    from giljo_mcp import product_crew

    called = False

    async def _explode(*_args, **_kwargs):
        nonlocal called
        called = True
        raise RuntimeError("seed failed")

    monkeypatch.setattr(product_crew, "seed_product_crew", _explode)

    service = _product_service(db_manager, db_session, tenant_key)

    with pytest.raises(Exception, match=r"seed failed|Failed to create product"):
        await service.create_product(name=f"Doomed {uuid.uuid4().hex[:8]}")

    assert called, (
        "the crew seed was never reached, so this test proved nothing -- create_product "
        "has stopped seeding, or seeds through a different import"
    )




async def test_a_product_with_no_agents_serves_an_empty_set(db_session, tenant_key):
    product = Product(
        id=str(uuid.uuid4()),
        name=f"Empty {uuid.uuid4().hex[:8]}",
        description="no agents by choice",
        tenant_key=tenant_key,
        is_active=True,
        created_at=datetime.now(UTC),
    )
    db_session.add(product)
    await db_session.commit()

    assert await template_ids_for_product(db_session, product.id, tenant_key) == set()


async def test_get_job_mission_omits_agent_profile_entirely_when_nothing_is_bound(db_session, tenant_key):
    from giljo_mcp.schemas.responses.orchestration import MissionResponse

    response = MissionResponse(job_id=str(uuid.uuid4()), agent_profile=None)
    wire = response.model_dump()

    assert "agent_profile" not in wire, (
        "an unbound job must omit agent_profile entirely; a null here is a signal-less "
        "state the agent cannot distinguish from a server fault"
    )


async def test_compose_agent_profile_is_none_for_an_unbound_job():
    from giljo_mcp.services.mission_assembly import compose_agent_profile

    assert compose_agent_profile(None) is None




async def test_deleting_a_product_trashes_its_crew_and_frees_the_names(db_manager, db_session, tenant_key):
    service = _product_service(db_manager, db_session, tenant_key)
    lifecycle = _lifecycle_service(db_manager, db_session, tenant_key)

    product = await service.create_product(name=f"Doomed {uuid.uuid4().hex[:8]}")
    names_before = {t.name for t in await _owned(db_session, tenant_key, product.id)}
    assert names_before, "guard on the fixture"

    await lifecycle.delete_product(product.id)

    assert await _owned(db_session, tenant_key, product.id) == [], "the crew must be trashed with its product"
    assert len(await _owned(db_session, tenant_key, product.id, deleted=True)) == len(names_before)

    replacement = await service.create_product(name=f"Replacement {uuid.uuid4().hex[:8]}")
    replacement_names = {t.name for t in await _owned(db_session, tenant_key, replacement.id)}
    assert replacement_names == names_before, (
        f"a deleted crew must free its names. got {sorted(replacement_names)}, expected {sorted(names_before)}"
    )


async def test_restoring_a_product_renames_its_crew_when_the_names_were_taken(db_manager, db_session, tenant_key):
    service = _product_service(db_manager, db_session, tenant_key)
    lifecycle = _lifecycle_service(db_manager, db_session, tenant_key)

    original = await service.create_product(name=f"Original {uuid.uuid4().hex[:8]}")
    original_names = {t.name for t in await _owned(db_session, tenant_key, original.id)}

    await lifecycle.delete_product(original.id)
    squatter = await service.create_product(name=f"Squatter {uuid.uuid4().hex[:8]}")
    assert {t.name for t in await _owned(db_session, tenant_key, squatter.id)} == original_names

    await lifecycle.restore_product(original.id)

    restored = await _owned(db_session, tenant_key, original.id)
    restored_names = {t.name for t in restored}
    assert len(restored) == len(original_names), "every agent must come back"
    assert restored_names.isdisjoint(original_names), "the restored crew must not collide with the squatter"
    assert all(name.endswith("-2") for name in restored_names), (
        f"the crew moves together to one shared suffix; got {sorted(restored_names)}"
    )
    served = await template_ids_for_product(db_session, original.id, tenant_key)
    assert served == {t.id for t in restored}


async def test_a_deleted_agent_makes_an_in_flight_job_report_template_unresolved(db_session, tenant_key):
    from giljo_mcp.models.agent_identity import AgentExecution, AgentJob
    from giljo_mcp.services.mission_assembly import IDENTITY_TEMPLATE_UNRESOLVED, compose_unresolved_identity

    job = AgentJob(job_id=str(uuid.uuid4()), tenant_key=tenant_key, template_id=str(uuid.uuid4()))
    execution = AgentExecution(agent_display_name="tester-1", agent_name="tester")

    text, status = compose_unresolved_identity(job, execution)

    assert status == IDENTITY_TEMPLATE_UNRESOLVED
    assert "DELETED" in text, "the agent must be told WHICH of the two causes applies"
    assert "tester" in text


async def test_purging_a_product_leaves_no_agent_owned_by_a_product_that_does_not_exist(
    db_manager, db_session, tenant_key
):
    service = _product_service(db_manager, db_session, tenant_key)
    lifecycle = _lifecycle_service(db_manager, db_session, tenant_key)

    product = await service.create_product(name=f"Purged {uuid.uuid4().hex[:8]}")
    product_id = product.id
    assert await _owned(db_session, tenant_key, product_id), "guard on the fixture"

    await lifecycle.purge_product(product_id)

    assert await _owned(db_session, tenant_key, product_id) == [], (
        "live agents are still owned by a product that no longer exists"
    )
    rows = (
        (
            await db_session.execute(
                select(ProductAgentAssignment).where(ProductAgentAssignment.product_id == product_id)
            )
        )
        .scalars()
        .all()
    )
    assert rows == []




@pytest_asyncio.fixture
async def switched_on_but_retired(db_manager, db_session, tenant_key):
    service = _product_service(db_manager, db_session, tenant_key)
    product = await service.create_product(name=f"Retired-flag {uuid.uuid4().hex[:8]}")

    agent = next(t for t in await _owned(db_session, tenant_key, product.id) if t.role == "tester")
    agent.is_active = False
    await db_session.commit()

    served = await template_ids_for_product(db_session, product.id, tenant_key)
    assert agent.id in served, "guard on the fixture: the product must still have this agent switched on"
    return product, agent


async def test_self_identity_still_resolves_a_retired_flagged_agent(db_session, tenant_key, switched_on_but_retired):
    from giljo_mcp.tools.context_tools.get_self_identity import get_self_identity

    _product, agent = switched_on_but_retired

    result = await get_self_identity(agent_name=agent.name, tenant_key=tenant_key, session=db_session)

    assert result["metadata"].get("error") != "template_not_found", (
        f"an agent its product has switched ON was told its own template does not exist: {result['metadata']}"
    )
    assert result["data"].get("name") == agent.name, f"self-identity resolved nothing usable: {result}"


async def test_role_resolution_still_finds_a_retired_flagged_agent(db_session, tenant_key, switched_on_but_retired):
    from giljo_mcp.repositories.mission_repository import MissionRepository

    _product, agent = switched_on_but_retired

    resolved = await MissionRepository().get_template_by_role(db_session, tenant_key, "tester")

    assert resolved is not None, "the tester role resolved to nothing while the product has a tester switched on"
    assert resolved.id == agent.id




async def test_creating_an_agent_for_another_tenants_product_is_refused(db_manager, db_session, tenant_key):
    from api.endpoints.templates.models import TemplateCreate
    from giljo_mcp.exceptions import ValidationError
    from giljo_mcp.services.template_service import TemplateService

    other_tenant = TenantManager.generate_tenant_key()
    foreign = Product(
        id=str(uuid.uuid4()),
        name=f"Someone else's product {uuid.uuid4().hex[:6]}",
        description="another account entirely",
        tenant_key=other_tenant,
        is_active=True,
        created_at=datetime.now(UTC),
    )
    db_session.add(foreign)
    await db_session.commit()

    manager = TenantManager()
    manager.set_current_tenant(tenant_key)
    service = TemplateService(db_manager=db_manager, tenant_manager=manager, session=db_session)

    with pytest.raises(ValidationError, match="not found for this account"):
        await service.create_template_from_request(
            db_session,
            TemplateCreate(product_id=foreign.id, role="implementer", custom_suffix=f"x{uuid.uuid4().hex[:6]}"),
            tenant_key,
            "the-user",
        )

    assert await _owned(db_session, tenant_key, foreign.id) == []


async def test_an_over_long_product_id_is_refused_at_both_layers(db_manager, db_session, tenant_key):
    import pydantic

    from api.endpoints.templates.models import TemplateCreate
    from giljo_mcp.exceptions import ValidationError
    from giljo_mcp.services.template_service import TemplateService

    with pytest.raises(pydantic.ValidationError, match="product_id"):
        TemplateCreate(product_id="x" * 200, role="implementer", custom_suffix="y")

    manager = TenantManager()
    manager.set_current_tenant(tenant_key)
    service = TemplateService(db_manager=db_manager, tenant_manager=manager, session=db_session)

    class _DuckTypedCreate:
        product_id = "x" * 200
        role = "implementer"
        name = None
        custom_suffix = f"y{uuid.uuid4().hex[:6]}"
        cli_tool = "claude"
        background_color = None
        description = None
        user_instructions = None
        model = "inherit"
        effort = "inherit"
        behavioral_rules: list = []  # noqa: RUF012
        success_criteria: list = []  # noqa: RUF012
        tags: list = []  # noqa: RUF012
        is_default = False
        is_active = False
        category = None

    with pytest.raises(ValidationError, match="maximum length"):
        await service.create_template_from_request(db_session, _DuckTypedCreate(), tenant_key, "the-user")


async def test_creating_an_agent_for_a_deleted_product_is_refused(db_manager, db_session, tenant_key):
    from api.endpoints.templates.models import TemplateCreate
    from giljo_mcp.exceptions import ValidationError
    from giljo_mcp.services.template_service import TemplateService

    product_service = _product_service(db_manager, db_session, tenant_key)
    lifecycle = _lifecycle_service(db_manager, db_session, tenant_key)
    product = await product_service.create_product(name=f"Doomed {uuid.uuid4().hex[:8]}")
    await lifecycle.delete_product(product.id)

    manager = TenantManager()
    manager.set_current_tenant(tenant_key)
    service = TemplateService(db_manager=db_manager, tenant_manager=manager, session=db_session)

    with pytest.raises(ValidationError, match="not found for this account"):
        await service.create_template_from_request(
            db_session,
            TemplateCreate(product_id=product.id, role="implementer", custom_suffix=f"z{uuid.uuid4().hex[:6]}"),
            tenant_key,
            "the-user",
        )


async def test_importing_defaults_for_another_tenants_product_is_refused(db_manager, db_session, tenant_key):
    from giljo_mcp.exceptions import ValidationError
    from giljo_mcp.template_import import import_default_templates

    other_tenant = TenantManager.generate_tenant_key()
    foreign = Product(
        id=str(uuid.uuid4()),
        name=f"Someone else's product {uuid.uuid4().hex[:6]}",
        description="another account entirely",
        tenant_key=other_tenant,
        is_active=True,
        created_at=datetime.now(UTC),
    )
    db_session.add(foreign)
    await db_session.commit()

    with pytest.raises(ValidationError, match="not found for this account"):
        await import_default_templates(db_session, tenant_key, foreign.id)

    assert await _owned(db_session, tenant_key, foreign.id) == []


async def test_an_agent_cannot_be_moved_to_another_product_by_editing_it(db_manager, db_session, tenant_key):
    from giljo_mcp.services.template_service import _ALLOWED_TEMPLATE_UPDATE_FIELDS, TemplateService

    assert "product_id" not in _ALLOWED_TEMPLATE_UPDATE_FIELDS, (
        "product_id became settable via update -- one edit can now move an agent to another product's tab"
    )

    product_service = _product_service(db_manager, db_session, tenant_key)
    home = await product_service.create_product(name=f"Home {uuid.uuid4().hex[:8]}")
    neighbour = await product_service.create_product(name=f"Neighbour {uuid.uuid4().hex[:8]}")
    agent = next(t for t in await _owned(db_session, tenant_key, home.id) if t.role == "tester")

    manager = TenantManager()
    manager.set_current_tenant(tenant_key)
    service = TemplateService(db_manager=db_manager, tenant_manager=manager, session=db_session)

    class _CraftedUpdate:
        @staticmethod
        def model_dump(exclude_unset: bool = True) -> dict:  # noqa: ARG004
            return {"description": "still mine", "product_id": neighbour.id}

    updated, _fields = await service.update_template_from_request(
        db_session, agent.id, _CraftedUpdate(), tenant_key, "the-user"
    )

    assert updated.product_id == home.id, "an edit moved the agent to another product"
    assert updated.description == "still mine", "guard: the legitimate field must still apply"
