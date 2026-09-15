# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
import pytest_asyncio

from giljo_mcp.models.product_agent_assignment import ProductAgentAssignment
from giljo_mcp.models.products import Product
from giljo_mcp.models.templates import AgentTemplate
from giljo_mcp.tenant import TenantManager
from giljo_mcp.tools.context_tools.get_agent_templates import get_agent_templates
from tests.helpers.product_crew_helper import adopt_all_templates


pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def tenant_key() -> str:
    return TenantManager.generate_tenant_key()


@pytest_asyncio.fixture
async def product(db_session, tenant_key):
    row = Product(
        id=str(uuid4()),
        name=f"Liveness Product {uuid4().hex[:6]}",
        description="agent-template liveness fixture",
        tenant_key=tenant_key,
        is_active=True,
        created_at=datetime.now(UTC),
    )
    db_session.add(row)
    await db_session.commit()
    await adopt_all_templates(db_session, tenant_key, row.id)
    return row


@pytest_asyncio.fixture
async def templates(db_session, tenant_key, product):
    rows = []
    for name in ("implementer", "tester", "reviewer"):
        row = AgentTemplate(
            id=str(uuid4()),
            tenant_key=tenant_key,
            product_id=product.id,
            name=f"{name}_{uuid4().hex[:6]}",
            role=name.title(),
            description=f"{name} description",
            is_active=True,
        )
        db_session.add(row)
        rows.append(row)
    await db_session.commit()
    return rows


async def _assign(db_session, tenant_key, product, template, *, is_active=True):
    row = ProductAgentAssignment(
        id=str(uuid4()),
        tenant_key=tenant_key,
        product_id=product.id,
        template_id=template.id,
        is_active=is_active,
    )
    db_session.add(row)
    await db_session.commit()
    return row


async def _names(db_session, tenant_key, product) -> set[str]:
    result = await get_agent_templates(
        product_id=product.id,
        tenant_key=tenant_key,
        detail="basic",
        _test_session=db_session,
    )
    return {entry["name"] for entry in result["data"]}


async def test_a_no_assignments_serves_nothing(db_session, tenant_key, product, templates):
    assert await _names(db_session, tenant_key, product) == set()


async def test_b_one_assignment_narrows_to_that_template(db_session, tenant_key, product, templates):
    await _assign(db_session, tenant_key, product, templates[0])
    assert await _names(db_session, tenant_key, product) == {templates[0].name}


async def test_c_soft_deleted_assignee_does_not_hide_the_others(db_session, tenant_key, product, templates):
    for template in templates:
        await _assign(db_session, tenant_key, product, template)
    templates[0].deleted_at = datetime.now(UTC)
    await db_session.commit()

    names = await _names(db_session, tenant_key, product)

    assert names, (
        "empty roster: a still-active assignment pointing at a SOFT-DELETED template "
        "engaged the filter and removed every live template"
    )
    assert names == {templates[1].name, templates[2].name}


async def test_d_the_retire_flag_no_longer_vetoes_an_enabled_agent(db_session, tenant_key, product, templates):
    for template in templates:
        await _assign(db_session, tenant_key, product, template)
    templates[0].is_active = False
    await db_session.commit()

    names = await _names(db_session, tenant_key, product)

    assert names == {t.name for t in templates}, (
        "the account-wide retire flag vetoed an agent this product has switched ON -- "
        f"that is the stuck-seven defect ruling 7 removes. got={names}"
    )


async def test_e_foreign_tenant_assignment_cannot_narrow_this_tenants_roster(
    db_session, tenant_key, product, templates
):
    foreign_tenant = TenantManager.generate_tenant_key()
    foreign_template = AgentTemplate(
        id=str(uuid4()),
        tenant_key=foreign_tenant,
        product_id=product.id,
        name=f"foreign_{uuid4().hex[:6]}",
        role="Foreign",
        description="owned by another tenant",
        is_active=True,
    )
    db_session.add(foreign_template)
    await db_session.commit()

    await _assign(db_session, tenant_key, product, foreign_template)

    for template in templates:
        await _assign(db_session, tenant_key, product, template)

    names = await _names(db_session, tenant_key, product)

    assert names == {t.name for t in templates}, (
        "a junction row pointing at another tenant's template narrowed this "
        f"tenant's roster -- tenant isolation is not being enforced. got={names}"
    )


async def test_f_join_carries_its_own_tenant_predicate_under_guard_bypass(db_session, tenant_key, product, templates):
    from giljo_mcp.repositories.product_agent_assignment_repository import (
        ProductAgentAssignmentRepository,
    )
    from giljo_mcp.tenant_guard import tenant_isolation_bypass

    foreign_tenant = TenantManager.generate_tenant_key()
    foreign_template = AgentTemplate(
        id=str(uuid4()),
        tenant_key=foreign_tenant,
        product_id=product.id,
        name=f"foreign_{uuid4().hex[:6]}",
        role="Foreign",
        description="owned by another tenant",
        is_active=True,
    )
    db_session.add(foreign_template)
    await db_session.commit()
    await _assign(db_session, tenant_key, product, foreign_template)

    repo = ProductAgentAssignmentRepository()
    with tenant_isolation_bypass(
        db_session,
        reason="BE agent-template liveness: prove the join's own tenant predicate",
        models=(AgentTemplate, ProductAgentAssignment),
    ):
        active_ids = await repo.get_active_template_ids_for_product(db_session, product.id, tenant_key)

    assert foreign_template.id not in active_ids, (
        "another tenant's template id leaked into active_ids with the guard bypassed -- "
        "the join is relying on the guard instead of carrying its own tenant predicate"
    )
    assert active_ids == set()


async def test_repository_excludes_dead_templates_from_active_ids(db_session, tenant_key, product, templates):
    from giljo_mcp.repositories.product_agent_assignment_repository import (
        ProductAgentAssignmentRepository,
    )

    for template in templates:
        await _assign(db_session, tenant_key, product, template)
    templates[0].deleted_at = datetime.now(UTC)
    templates[1].is_active = False
    await db_session.commit()

    repo = ProductAgentAssignmentRepository()
    active_ids = await repo.get_active_template_ids_for_product(db_session, product.id, tenant_key)

    assert active_ids == {templates[1].id, templates[2].id}, (
        "the repository must exclude the SOFT-DELETED template and only that one -- "
        f"the retire flag is inert since ruling 7. got={active_ids}"
    )
