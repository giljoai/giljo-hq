# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""Service-layer tests for roadmap reference resolution (BE-9474).

The MCP-boundary suite
(``tests/integration/test_be9474_roadmap_ergonomics_mcp_transport.py``) proves
an agent can rank by alias. This file covers what that one cannot reach:

- the id-vs-alias classification, which decides whether a lookup happens at all;
- the ``remove`` list, resolved by the same call as ``items``;
- the duplicate guard, which the ``uq_*_taxonomy_active`` UNIQUE indexes make
  unreachable through the database and which therefore has to be driven
  directly if it is to be tested at all.

Parallel-safe: each test owns its fixture data, uses the rolled-back
``db_session`` (TransactionalTestContext), and shares no module-level state.

Edition Scope: CE.
"""

from __future__ import annotations

import uuid

import pytest

from giljo_mcp.database import tenant_session_context
from giljo_mcp.exceptions import ValidationError
from giljo_mcp.models import Product, Project, Task
from giljo_mcp.models.organizations import Organization
from giljo_mcp.models.projects import TaxonomyType
from giljo_mcp.services.roadmap_references import _alias_to_id, _is_uuid_shaped, resolve_refs
from giljo_mcp.tenant import TenantManager


pytestmark = pytest.mark.asyncio


async def _seed_aliased(db_session, *, project_series: int = 7, task_series: int = 86) -> dict:
    """Org + active product + one aliased project + one aliased task, fresh tenant."""
    suffix = uuid.uuid4().hex[:8]
    tenant_key = TenantManager.generate_tenant_key()

    org = Organization(name=f"Org {suffix}", slug=f"org-{suffix}", tenant_key=tenant_key, is_active=True)
    db_session.add(org)
    await db_session.flush()

    product = Product(
        id=str(uuid.uuid4()),
        name=f"Product {suffix}",
        description="roadmap reference test product",
        tenant_key=tenant_key,
        is_active=True,
    )
    proj_type = TaxonomyType(
        id=str(uuid.uuid4()), tenant_key=tenant_key, abbreviation="BE", label="Backend", color="#607D8B"
    )
    task_type = TaxonomyType(
        id=str(uuid.uuid4()), tenant_key=tenant_key, abbreviation="IMP", label="Implementation", color="#607D8B"
    )
    db_session.add_all([product, proj_type, task_type])
    await db_session.flush()

    project = Project(
        id=str(uuid.uuid4()),
        tenant_key=tenant_key,
        product_id=product.id,
        name=f"Project {suffix}",
        description="desc",
        mission="mission",
        project_type_id=proj_type.id,
        series_number=project_series,
    )
    task = Task(
        id=str(uuid.uuid4()),
        tenant_key=tenant_key,
        product_id=product.id,
        title=f"Task {suffix}",
        description="desc",
        status="pending",
        priority="medium",
        task_type_id=task_type.id,
        series_number=task_series,
    )
    db_session.add_all([project, task])
    await db_session.commit()

    return {
        "tenant_key": tenant_key,
        "product_id": product.id,
        "project_id": project.id,
        "project_alias": f"BE-{project_series:04d}",
        "task_id": task.id,
        "task_alias": f"IMP-{task_series:04d}",
    }


async def test_only_non_uuid_references_are_treated_as_aliases():
    """The classifier decides whether an existing caller pays for a lookup.

    Everything an existing caller sends is UUID-shaped, so it must classify as
    an id; everything the alias builder can emit must classify as an alias.
    """
    assert _is_uuid_shaped(str(uuid.uuid4())) is True
    assert _is_uuid_shaped(uuid.uuid4().hex) is True  # dashless form of the same id
    assert _is_uuid_shaped("BE-0007") is False
    assert _is_uuid_shaped("IMP-0086") is False
    assert _is_uuid_shaped("BE-0001a") is False  # subseries suffix
    assert _is_uuid_shaped("0017") is False  # untyped project: serial only
    assert _is_uuid_shaped("5RRBTM") is False  # type-less project's random alias
    assert _is_uuid_shaped("") is False


async def test_resolve_refs_rewrites_aliases_in_items_and_remove(db_session):
    """One call resolves BOTH lists, so a row can be named the same way in either."""
    seed = await _seed_aliased(db_session)

    items = [
        {"item_type": "project", "project_id": seed["project_alias"], "task_id": None},
        {"item_type": "task", "project_id": None, "task_id": seed["task_alias"]},
    ]
    remove = [{"item_type": "task", "project_id": None, "task_id": seed["task_alias"]}]

    with tenant_session_context(db_session, seed["tenant_key"]):
        await resolve_refs(db_session, seed["tenant_key"], seed["product_id"], items, remove)

    assert items[0]["project_id"] == seed["project_id"]
    assert items[1]["task_id"] == seed["task_id"]
    assert remove[0]["task_id"] == seed["task_id"]


async def test_resolve_refs_leaves_ids_and_unresolvable_aliases_exactly_as_sent(db_session):
    """An id is passed through untouched; an alias that names nothing is NOT invented.

    Leaving the unresolved value in place is what routes it into the existing
    "do not exist in this workspace" refusal instead of a second vocabulary.
    """
    seed = await _seed_aliased(db_session)
    stranger = str(uuid.uuid4())

    items = [
        {"item_type": "project", "project_id": seed["project_id"], "task_id": None},
        {"item_type": "project", "project_id": stranger, "task_id": None},
        {"item_type": "project", "project_id": "BE-9999", "task_id": None},
    ]

    with tenant_session_context(db_session, seed["tenant_key"]):
        await resolve_refs(db_session, seed["tenant_key"], seed["product_id"], items, [])

    assert items[0]["project_id"] == seed["project_id"]
    assert items[1]["project_id"] == stranger
    assert items[2]["project_id"] == "BE-9999"


async def test_resolve_refs_will_not_reach_across_a_tenant_or_a_product(db_session):
    """Resolution is scoped, so a neighbour's alias simply does not resolve."""
    # Distinct serials: if both tenants minted BE-0007 the neighbour's alias
    # would resolve to MY row and the test would pass for the wrong reason.
    mine = await _seed_aliased(db_session, project_series=7, task_series=86)
    theirs = await _seed_aliased(db_session, project_series=50, task_series=51)

    items = [{"item_type": "project", "project_id": theirs["project_alias"], "task_id": None}]

    # Same alias text, my tenant + my product: nothing to resolve it to.
    with tenant_session_context(db_session, mine["tenant_key"]):
        await resolve_refs(db_session, mine["tenant_key"], mine["product_id"], items, [])
    assert items[0]["project_id"] == theirs["project_alias"]

    # And it is a real row -- resolvable from its own tenant + product.
    with tenant_session_context(db_session, theirs["tenant_key"]):
        await resolve_refs(db_session, theirs["tenant_key"], theirs["product_id"], items, [])
    assert items[0]["project_id"] == theirs["project_id"]


async def test_an_alias_matching_two_rows_is_refused_rather_than_guessed():
    """The guard the UNIQUE indexes make unreachable, driven directly.

    ``uq_project_taxonomy_active`` is UNIQUE over exactly the tuple an alias is
    built from, so no seedable database state reaches this branch -- which is
    the point: the guard exists so that relaxing that constraint fails loudly
    instead of silently picking a row on the user's behalf. Driving it needs a
    stand-in for the one call it makes.
    """

    class _TwoRowSession:
        """Minimal AsyncSession stand-in: answers ``execute`` and nothing else."""

        async def execute(self, _stmt):
            return [("BE-0007", "id-one"), ("BE-0007", "id-two")]

    with pytest.raises(ValidationError) as excinfo:
        await _alias_to_id(_TwoRowSession(), "tk_whatever", "product-1", Project, {"BE-0007"})

    assert "BE-0007" in str(excinfo.value)
    assert excinfo.value.context["ambiguous_aliases"] == ["BE-0007"]
