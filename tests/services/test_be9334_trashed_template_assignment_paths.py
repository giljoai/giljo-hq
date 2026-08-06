# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
BE-9334 — the tail of the BE-9325 ``deleted_at`` audit.

Two of the three remaining live sites let a TRASHED ``AgentTemplate`` back into a
product-agent-assignment write path, because both filtered ``is_active`` (or nothing)
and soft-delete deliberately leaves ``is_active`` True (``template_service.py:720``):

* ``ProductAgentAssignmentService.toggle_assignment`` — the tenant existence check,
  so ``PUT /api/products/{id}/agent-assignments/{template_id}`` did not 404 on a
  trashed template and happily created a junction row pointing at it.
* ``ProductAgentAssignmentRepository.bulk_assign_all_templates`` — the activation-time
  bulk assign, which auto-attached every trashed template to a newly activated product
  while its own docstring promised "all *active* tenant templates".

Every assertion below runs against REAL database rows on purpose. Both defects live in
a WHERE clause, and a mocked result set cannot see a WHERE clause — a mock would have
passed against the broken code.

The third class member, ``JobStatisticsRepository.get_agent_role_distribution``, is
NOT a defect. Its missing ``deleted_at`` filter is deliberate, and the last test in
this file pins that intent so the next audit does not re-file it.
"""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
import pytest_asyncio

from giljo_mcp.database import tenant_session_context
from giljo_mcp.exceptions import ResourceNotFoundError
from giljo_mcp.models import AgentExecution, AgentJob, Product, Project
from giljo_mcp.models.product_agent_assignment import ProductAgentAssignment
from giljo_mcp.models.templates import AgentTemplate
from giljo_mcp.repositories.job_statistics_repository import JobStatisticsRepository
from giljo_mcp.repositories.product_agent_assignment_repository import (
    ProductAgentAssignmentRepository,
)
from giljo_mcp.services.product_agent_assignment_service import (
    ProductAgentAssignmentService,
)
from giljo_mcp.tenant import TenantManager


# ============================================================================
# Fixtures — real rows, one isolated tenant per test run
# ============================================================================


@pytest_asyncio.fixture
async def tenant_key():
    return TenantManager.generate_tenant_key()


@pytest_asyncio.fixture
async def product(db_session, tenant_key):
    row = Product(
        id=str(uuid4()),
        name=f"BE-9334 Product {uuid4().hex[:6]}",
        description="product for the trashed-template assignment tests",
        tenant_key=tenant_key,
        is_active=True,
        created_at=datetime.now(UTC),
    )
    db_session.add(row)
    await db_session.flush()
    return row


def _template(tenant_key, name, *, deleted: bool) -> AgentTemplate:
    """A template that is ``is_active`` either way — soft-delete does not clear it.

    That is the whole point of the defect: filtering ``is_active`` alone lets every
    trashed row through, so the fixture must mirror production and leave it True.
    """
    return AgentTemplate(
        id=str(uuid4()),
        tenant_key=tenant_key,
        name=f"{name}-{uuid4().hex[:4]}",
        role=name,
        description=f"BE-9334 {name} template",
        system_instructions=f"You are a {name} agent.",
        is_active=True,
        deleted_at=datetime.now(UTC) if deleted else None,
    )


@pytest_asyncio.fixture
async def trashed_template(db_session, tenant_key):
    row = _template(tenant_key, "trashed", deleted=True)
    db_session.add(row)
    await db_session.flush()
    return row


@pytest_asyncio.fixture
async def live_template(db_session, tenant_key):
    row = _template(tenant_key, "live", deleted=False)
    db_session.add(row)
    await db_session.flush()
    return row


@pytest_asyncio.fixture
def service(db_manager, tenant_key, db_session):
    return ProductAgentAssignmentService(
        db_manager=db_manager,
        tenant_key=tenant_key,
        test_session=db_session,
    )


# ============================================================================
# Item 1 — the service existence check (PUT /agent-assignments/{template_id})
# ============================================================================


@pytest.mark.asyncio
async def test_toggle_assignment_404s_on_trashed_template(service, product, trashed_template):
    """A trashed template must not be assignable to a product.

    Before the fix the existence check matched on ``id + tenant_key`` only, so the
    trashed row satisfied it, no ``ResourceNotFoundError`` was raised, and the upsert
    created a ``ProductAgentAssignment`` referencing a deleted agent.
    """
    with pytest.raises(ResourceNotFoundError):
        await service.toggle_assignment(product.id, trashed_template.id, True)


@pytest.mark.asyncio
async def test_toggle_assignment_writes_no_row_for_a_trashed_template(
    db_session, service, product, trashed_template, tenant_key
):
    """The rejection must happen *before* the write, not merely be reported after it."""
    with pytest.raises(ResourceNotFoundError):
        await service.toggle_assignment(product.id, trashed_template.id, True)

    repo = ProductAgentAssignmentRepository()
    assignment = await repo.get_assignment(db_session, product.id, trashed_template.id, tenant_key)
    assert assignment is None


@pytest.mark.asyncio
async def test_toggle_assignment_still_accepts_a_live_template(service, product, live_template):
    """Control: the new predicate must not be over-broad and reject healthy rows."""
    result = await service.toggle_assignment(product.id, live_template.id, True)

    assert result["template_id"] == live_template.id
    assert result["product_id"] == product.id
    assert result["is_active"] is True


# ============================================================================
# Item 4 — the activation-time bulk assign (repository layer, distinct from Item 1)
# ============================================================================


@pytest.mark.asyncio
async def test_bulk_assign_skips_trashed_templates(db_session, product, tenant_key, trashed_template, live_template):
    """Activating a product must not auto-assign agents the user already deleted.

    ``bulk_assign_all_templates`` runs from ``product_lifecycle_service.py:192`` on
    product activation. It filtered ``is_active`` only, so every trashed template was
    attached to the freshly activated product — contradicting its own docstring, which
    promises "all *active* tenant templates".
    """
    repo = ProductAgentAssignmentRepository()
    new_assignments = await repo.bulk_assign_all_templates(db_session, product.id, tenant_key)

    assigned_template_ids = {a.template_id for a in new_assignments}
    assert live_template.id in assigned_template_ids
    assert trashed_template.id not in assigned_template_ids


@pytest.mark.asyncio
async def test_bulk_assign_persists_no_row_for_a_trashed_template(
    db_session, product, tenant_key, trashed_template, live_template
):
    """Same check read back from the table, not from the returned list."""
    repo = ProductAgentAssignmentRepository()
    await repo.bulk_assign_all_templates(db_session, product.id, tenant_key)
    await db_session.flush()

    stored = await repo.get_assignments_for_product(db_session, product.id, tenant_key)
    stored_template_ids = {a.template_id for a in stored}
    assert live_template.id in stored_template_ids
    assert trashed_template.id not in stored_template_ids


@pytest.mark.asyncio
async def test_bulk_assign_leaves_an_existing_assignment_alone(db_session, product, tenant_key, live_template):
    """Control: the added predicate must not disturb the skip-what-exists path."""
    db_session.add(
        ProductAgentAssignment(
            id=str(uuid4()),
            product_id=product.id,
            template_id=live_template.id,
            tenant_key=tenant_key,
            is_active=False,
        )
    )
    await db_session.flush()

    repo = ProductAgentAssignmentRepository()
    new_assignments = await repo.bulk_assign_all_templates(db_session, product.id, tenant_key)

    assert live_template.id not in {a.template_id for a in new_assignments}


# ============================================================================
# Item 5 — the READ path (GET /api/products/{id}/agent-assignments)
#
# Distinct from Items 1 and 4, and NOT covered by either. Both of those guard a
# WRITE: they stop a junction row being created against an already-trashed
# template. This item is the case where the junction row was created while the
# template was perfectly healthy and the template was trashed AFTERWARDS — so no
# write-path predicate is ever consulted again and the row is permanently stale.
# ``get_assignments_for_product`` eager-loaded the template with ``joinedload``
# (a LEFT OUTER JOIN) and no ``deleted_at`` predicate, so it kept returning the
# assignment, and the service reported ``template_is_active: True`` for it
# because soft-delete leaves ``is_active`` alone.
#
# The fix is an INNER join filtered on ``deleted_at IS NULL``. That is only safe
# because ``ProductAgentAssignment.template_id`` is ``nullable=False``
# (``models/product_agent_assignment.py:49-53``), so no legitimate assignment can
# have a NULL template to be dropped by the stricter join. The live-template
# tests below are the load-bearing half of the proof.
# ============================================================================


async def _assign_then_trash(db_session, product, tenant_key, template):
    """Reproduce the real sequence: assign while healthy, trash afterwards.

    Written in this order deliberately. Creating the junction row against an
    already-trashed template would be testing Items 1/4 again; the whole point
    here is that the row is created legitimately and goes stale later.
    """
    db_session.add(
        ProductAgentAssignment(
            id=str(uuid4()),
            product_id=product.id,
            template_id=template.id,
            tenant_key=tenant_key,
            is_active=True,
        )
    )
    await db_session.flush()

    template.deleted_at = datetime.now(UTC)
    await db_session.flush()


@pytest.mark.asyncio
async def test_list_assignments_drops_a_template_trashed_after_it_was_assigned(
    db_session, product, tenant_key, live_template
):
    """The defect: a template trashed after assignment kept being returned.

    Real rows on purpose — the bug lives in a JOIN predicate, and a mocked result
    set cannot see a JOIN predicate. A mock-based version of this test passes
    against the broken code.
    """
    await _assign_then_trash(db_session, product, tenant_key, live_template)

    repo = ProductAgentAssignmentRepository()
    assignments = await repo.get_assignments_for_product(db_session, product.id, tenant_key)

    assert live_template.id not in {a.template_id for a in assignments}


@pytest.mark.asyncio
async def test_list_assignments_still_returns_a_live_assigned_template(db_session, product, tenant_key, live_template):
    """LOAD-BEARING CONTROL: the inner join must not drop healthy assignments.

    An inner join is the risky half of this fix. If the join predicate were wrong
    — or if ``template_id`` were ever nullable — this is the test that catches it,
    and the test above would still pass while the endpoint returned nothing at all.
    """
    db_session.add(
        ProductAgentAssignment(
            id=str(uuid4()),
            product_id=product.id,
            template_id=live_template.id,
            tenant_key=tenant_key,
            is_active=True,
        )
    )
    await db_session.flush()

    repo = ProductAgentAssignmentRepository()
    assignments = await repo.get_assignments_for_product(db_session, product.id, tenant_key)

    assert live_template.id in {a.template_id for a in assignments}
    # The template must still arrive eager-loaded; the service dereferences it.
    returned = next(a for a in assignments if a.template_id == live_template.id)
    assert returned.template is not None
    assert returned.template.name == live_template.name


@pytest.mark.asyncio
async def test_list_assignments_returns_the_live_one_and_only_the_live_one(
    db_session, product, tenant_key, live_template
):
    """Both sides in a single query, which is what production actually looks like."""
    survivor = _template(tenant_key, "survivor", deleted=False)
    db_session.add(survivor)
    await db_session.flush()

    db_session.add(
        ProductAgentAssignment(
            id=str(uuid4()),
            product_id=product.id,
            template_id=survivor.id,
            tenant_key=tenant_key,
            is_active=True,
        )
    )
    await _assign_then_trash(db_session, product, tenant_key, live_template)

    repo = ProductAgentAssignmentRepository()
    assignments = await repo.get_assignments_for_product(db_session, product.id, tenant_key)

    assert {a.template_id for a in assignments} == {survivor.id}


@pytest.mark.asyncio
async def test_list_assignments_active_only_still_composes_with_the_join(
    db_session, product, tenant_key, live_template
):
    """``active_only=True`` filters the ASSIGNMENT flag and must still see the join.

    Guards against the added predicate being appended in a way that breaks the
    existing optional filter — the two ``where`` clauses target different tables.
    """
    survivor = _template(tenant_key, "survivor", deleted=False)
    db_session.add(survivor)
    await db_session.flush()

    db_session.add(
        ProductAgentAssignment(
            id=str(uuid4()),
            product_id=product.id,
            template_id=survivor.id,
            tenant_key=tenant_key,
            is_active=True,
        )
    )
    await _assign_then_trash(db_session, product, tenant_key, live_template)

    repo = ProductAgentAssignmentRepository()
    assignments = await repo.get_assignments_for_product(db_session, product.id, tenant_key, active_only=True)

    assert {a.template_id for a in assignments} == {survivor.id}


@pytest.mark.asyncio
async def test_service_list_assignments_no_longer_reports_a_trashed_template_as_active(
    db_session, service, product, tenant_key, live_template
):
    """The reported symptom, at the surface that reported it.

    The audit probe saw ``template_is_active: True`` for a trashed template here,
    because soft-delete stamps ``deleted_at`` and leaves ``is_active`` True. This
    pins the user-visible shape, not just the repository return value.
    """
    await _assign_then_trash(db_session, product, tenant_key, live_template)

    payload = await service.list_assignments(product.id)

    assert live_template.id not in {row["template_id"] for row in payload}


# ============================================================================
# Item 2 — INTENT PIN, not a bug fix.
# ============================================================================


@pytest.mark.asyncio
async def test_role_distribution_deliberately_keeps_trashed_templates_as_fold_targets(db_session):
    """``get_agent_role_distribution`` omits ``deleted_at`` ON PURPOSE. Do not "fix" it.

    This test exists to make that decision fail loudly rather than be re-filed by the
    next audit. Adding ``AgentTemplate.deleted_at.is_(None)`` to the template query in
    ``job_statistics_repository.py`` turns this test RED, which is the point.

    The query is not an existence check and not an authorization check. It is the
    label/colour lookup table that ``_base_role`` folds historical executions onto.
    Delete the trashed row from it and the *history* does not disappear — the fold
    target does: ``implementer-backend`` and ``implementer-frontend`` stop collapsing
    onto ``implementer`` and split the one historical segment into two.

    The symptom that looks alarming — a deleted agent lingering in the Dashboard
    roster — is not actually rendered. ``DashboardView.vue`` builds both the bar and
    the legend from ``buildSegments``, which does ``.filter(e => e.count > 0)``
    (``DashboardView.vue:346``), so a trashed template that was never spawned emits
    count 0 and never reaches the screen. Filtering here would therefore cost real
    fidelity on the spawned case and buy nothing on the unspawned one.
    """
    tenant = TenantManager.generate_tenant_key()

    with tenant_session_context(db_session, tenant):
        # The base template is TRASHED, and was spawned twice under variant names
        # before it was deleted. Its name is the only thing that can fold them.
        base = AgentTemplate(
            tenant_key=tenant,
            name="implementer",
            background_color="#aabbcc",
            is_active=True,
            deleted_at=datetime.now(UTC),
        )
        # A trashed template that was NEVER spawned — the case that looks like a leak.
        never_spawned = AgentTemplate(
            tenant_key=tenant,
            name="retired-analyst",
            background_color="#ddeeff",
            is_active=True,
            deleted_at=datetime.now(UTC),
        )
        db_session.add_all([base, never_spawned])
        await db_session.flush()

        project = Project(
            tenant_key=tenant,
            name="BE-9334 intent pin",
            description="seeded for the role-distribution intent pin",
            mission="seeded mission",
            status="active",
            series_number=9334,
        )
        db_session.add(project)
        await db_session.flush()

        for agent_name in ("implementer-backend", "implementer-frontend"):
            job = AgentJob(
                job_id=str(uuid4()),
                tenant_key=tenant,
                project_id=project.id,
                mission="m",
                job_type=agent_name,
                status="active",
                created_at=datetime.now(UTC),
            )
            db_session.add(job)
            db_session.add(
                AgentExecution(
                    job_id=job.job_id,
                    agent_id=str(uuid4()),
                    tenant_key=tenant,
                    agent_display_name=agent_name,
                    agent_name=agent_name,
                    status="working",
                    started_at=datetime.now(UTC),
                )
            )
        await db_session.flush()

        dist = await JobStatisticsRepository(None).get_agent_role_distribution(db_session, tenant)

    by_label = {seg["label"]: seg["count"] for seg in dist}

    # THE INTENT: both executions still fold onto the deleted base template's name.
    assert by_label["Implementer"] == 2, (
        "The trashed template stopped acting as a fold target. If a deleted_at filter "
        "was just added to job_statistics_repository.get_agent_role_distribution, that "
        "is the deliberate behaviour documented there being removed -- read the "
        "docstring before changing this assertion."
    )
    assert "Implementer Backend" not in by_label
    assert "Implementer Frontend" not in by_label

    # The never-spawned trashed template is returned at count 0 -- harmless, because
    # the Dashboard drops every zero-count segment before rendering.
    assert by_label["Retired Analyst"] == 0
