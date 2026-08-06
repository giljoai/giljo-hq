# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""A dead agent assignment used to hide every live agent from get_context.

``get_agent_templates`` selects live templates (``is_active`` AND
``deleted_at IS NULL``), then narrows them to the ones assigned to the product
via ``get_active_template_ids_for_product``. That repository query filtered
only on ``ProductAgentAssignment.is_active`` -- it said nothing about whether
the template each assignment POINTS AT is still live, despite its name
promising "active template ids".

So a still-active assignment pointing at a soft-deleted or deactivated
template returned a non-empty ``active_ids``, which ENGAGED the caller's
filter, which then removed every live-but-unassigned template. Result: an
empty agent roster on a product that demonstrably has agents. Found on a live
CE box; reproduced here on real rows.

Real user path: assign an agent to a product, then delete or deactivate that
agent. Every remaining agent silently vanishes from ``get_context``.

The scenarios below are the whole contract, deliberately not just the two
failing ones:

* **A** zero assignments -> all live templates (the filter must stay OFF)
* **B** one assigned, all live -> exactly that one (the filter must stay ON)
* **C** assigned template SOFT-DELETED -> the other live templates survive
* **D** assigned template DEACTIVATED -> same
* **E** cross-tenant junction row -> this tenant's roster is untouched
  (end-to-end isolation; enforced by the tenant guard, see the test's own note)
* **F** the join's own ``AgentTemplate.tenant_key`` predicate, under an explicit
  ``tenant_isolation_bypass`` -- the one condition where that predicate, rather
  than the guard, is what excludes a foreign row

**A and B are the guard against the lazy fix.** Dropping the ``if active_ids:``
guard, or making the repository always return an empty set, would make C and D
pass while silently destroying B -- product-scoped agent assignment is a real
feature, not incidental behaviour. Any change that breaks B has not fixed this
defect, it has deleted a different one.

Real rows throughout: this is a predicate defect, and a mock cannot see a
predicate. Parallel-safe -- unique tenant per test via the rollback-isolated
``db_session``.
"""

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
    return row


@pytest_asyncio.fixture
async def templates(db_session, tenant_key, product):
    """Three live templates: implementer, tester, reviewer."""
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


async def test_a_no_assignments_returns_every_live_template(db_session, tenant_key, product, templates):
    """A -- with no assignments the filter must not engage."""
    assert await _names(db_session, tenant_key, product) == {t.name for t in templates}


async def test_b_one_assignment_narrows_to_that_template(db_session, tenant_key, product, templates):
    """B -- THE GUARD. Product-scoped assignment is a real feature; a fix that
    makes C and D pass by disabling the filter breaks this test."""
    await _assign(db_session, tenant_key, product, templates[0])
    assert await _names(db_session, tenant_key, product) == {templates[0].name}


async def test_c_soft_deleted_assignee_does_not_hide_the_live_templates(db_session, tenant_key, product, templates):
    """C -- THE DEFECT. Assign one template, soft-delete it, and the two live
    templates must not vanish with it."""
    await _assign(db_session, tenant_key, product, templates[0])
    templates[0].deleted_at = datetime.now(UTC)
    await db_session.commit()

    names = await _names(db_session, tenant_key, product)

    assert names, (
        "empty roster: a still-active assignment pointing at a SOFT-DELETED template "
        "engaged the filter and removed every live template"
    )
    assert names == {templates[1].name, templates[2].name}


async def test_d_deactivated_assignee_does_not_hide_the_live_templates(db_session, tenant_key, product, templates):
    """D -- same defect via is_active=False rather than soft delete."""
    await _assign(db_session, tenant_key, product, templates[0])
    templates[0].is_active = False
    await db_session.commit()

    names = await _names(db_session, tenant_key, product)

    assert names, (
        "empty roster: a still-active assignment pointing at a DEACTIVATED template "
        "engaged the filter and removed every live template"
    )
    assert names == {templates[1].name, templates[2].name}


async def test_e_foreign_tenant_assignment_cannot_narrow_this_tenants_roster(
    db_session, tenant_key, product, templates
):
    """E -- end-to-end: a cross-tenant junction row must not narrow this roster.

    The querying tenant has live templates of its own, so the filter IS reached
    (an earlier version of this test asked a FRESH tenant for its roster and
    asserted "nothing" -- vacuous, because a tenant with no templates
    short-circuits at ``if product_id and templates:`` and never invokes the
    repository at all).

    What excludes the foreign row here is the **tenant guard**, which
    auto-injects a ``tenant_key`` criterion for every tenant-scoped model in a
    SELECT (``tenant_guard._enforce_tenant_scope``). Measured, not assumed:
    deleting ``AgentTemplate.tenant_key == tenant_key`` from the repository join
    leaves this test green, because the guard re-adds it. So this test pins the
    end-to-end isolation PROPERTY; it does not cover that explicit predicate.
    ``test_f_...`` below is the one that covers it.
    """
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

    # Junction row filed under THIS tenant but pointing at the foreign template.
    await _assign(db_session, tenant_key, product, foreign_template)

    names = await _names(db_session, tenant_key, product)

    assert names == {t.name for t in templates}, (
        "a junction row pointing at another tenant's template narrowed this "
        f"tenant's roster -- tenant isolation is not being enforced. got={names}"
    )


async def test_f_join_carries_its_own_tenant_predicate_under_guard_bypass(db_session, tenant_key, product, templates):
    """F -- the join's own ``AgentTemplate.tenant_key`` predicate, given real coverage.

    In the normal path this predicate is invisible: the tenant guard auto-injects
    an equivalent criterion, so removing the explicit one changes nothing
    observable. That is why every scenario above stays green without it, and why
    "it has no coverage" and "it is redundant" look identical from the outside.

    They are not identical. ``tenant_isolation_bypass`` is a real, supported mode
    (``tenant_guard.tenant_isolation_bypass``) in which the guard deliberately
    stops injecting for the named models. Under it the explicit predicate is the
    ONLY thing standing between a cross-tenant junction row and this tenant's
    ``active_ids`` -- so that is where its coverage has to live.

    Verified by mutation: with ``AgentTemplate.tenant_key == tenant_key`` deleted
    from the join, this exact setup returns the foreign template's id instead of
    an empty set.
    """
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
    """The fix, asserted at the layer it lives in: the repository method promises
    'active template ids' and must not name a template that is not live."""
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

    assert active_ids == {templates[2].id}, (
        "get_active_template_ids_for_product returned ids of templates that are "
        f"soft-deleted or deactivated: {active_ids}"
    )
