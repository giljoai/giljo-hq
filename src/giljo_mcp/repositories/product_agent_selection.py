# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""Product-bound agent selection -- the one place that answers "which agents does
this product use?".

BE-9385a. Before this module, the product association had no representation on
any selection path: every export site, the orchestrator roster, and the spawn
allowlist queried ``WHERE tenant_key AND is_active AND deleted_at IS NULL`` with
no product term, so toggling the active product could not change what shipped or
what could spawn. The ``product_agent_assignments`` junction existed end-to-end
but was authoritative for nothing.

Six call sites now share the two functions below rather than each growing its own
product filter. That is deliberate: the tolerance rule is subtle, and a rule
re-implemented six times is a rule that will drift.

TOLERANCE (load-bearing -- read before changing anything here)
--------------------------------------------------------------
``None`` means "the junction has no opinion about this product; use the
tenant-active set unchanged". It is returned when there is no product in context
at all, and when the product has **no junction rows whatsoever**.

The predicate is ROW EXISTENCE, not "the active set is non-empty". Those are not
the same rule and the difference silently eats the feature:

    A product with no rows falls back to tenant-active, so the user sees every
    agent. They switch one OFF. The toggle writes a single ``is_active=False``
    row. Under an "active set is empty -> fall back" rule the active set is
    STILL empty, tolerance re-engages, and that agent stays exported and
    spawnable -- while the UI shows the toggle moved. A control that reports
    success and does nothing.

The counterpart obligation lives in ``ProductAgentAssignmentService.toggle_assignment``,
which materialises the product's full junction before flipping a single row. With
existence-keyed tolerance and a naive single-row write, the first toggle would
leave the product holding exactly one row, tolerance would switch off, and the
product's active set would collapse to zero -- every agent gone. The two halves
only work together.

Why tolerance is not a transitional nicety: activation-time assignment is
best-effort ``try/except`` (``product_lifecycle_service.py:202-207``), and
products created before the junction existed never got rows at all. Without the
fallback those installs would upgrade into an empty roster and 404ing exports.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from datetime import datetime

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.database import tenant_session_context
from giljo_mcp.models.product_agent_assignment import ProductAgentAssignment
from giljo_mcp.models.products import Product
from giljo_mcp.models.templates import AgentTemplate
from giljo_mcp.repositories.product_agent_assignment_repository import (
    ProductAgentAssignmentRepository,
)
from giljo_mcp.repositories.product_repository import ProductRepository


logger = logging.getLogger(__name__)


async def template_ids_for_product(
    session: AsyncSession,
    product_id: str | None,
    tenant_key: str,
) -> set[str] | None:
    """Template ids active for ``product_id``, or ``None`` for "no opinion".

    Args:
        session: Active database session.
        product_id: Product UUID. Falsy (a project with no product, a
            product-less context) yields ``None`` -- there is nothing to scope to.
        tenant_key: Tenant key for isolation.

    Returns:
        ``None`` when the junction has no opinion (see the module docstring's
        TOLERANCE section), otherwise the set of template ids active for this
        product. A non-empty row set with every row disabled correctly returns an
        EMPTY set: the user turned everything off for this product, which is an
        answer, not an absence of one.
    """
    if not product_id:
        return None

    # Existence probe, deliberately separate from the active-id query below.
    #
    # BE-9334 (do NOT simplify this join away -- it is a museum exhibit with an
    # incident attached, and ``test_agent_templates_assignment_liveness.py`` is
    # its guard). The probe counts only rows that point at a template which is
    # itself LIVE and tenant-active. A product whose only junction rows point at
    # soft-deleted or deactivated templates has no live opinion, so it falls back
    # -- exactly as it did before this project. Probing bare row existence
    # instead re-created the original defect: one dead assignee engaged the
    # filter and removed every live-but-unassigned template, leaving an EMPTY
    # roster on a product that plainly has agents. Found on a live CE box once
    # already; I reintroduced it here and the BE-9334 tests caught it.
    #
    # ``ProductAgentAssignment.is_active`` is deliberately NOT in this predicate.
    # That is what keeps the two rules from colliding: a user who switches every
    # agent OFF still has rows pointing at live templates, so the junction stays
    # authoritative and the empty active set is honoured as their choice (D1).
    # Dead assignees are stale data; disabled assignees are an instruction.
    exists_stmt = (
        select(ProductAgentAssignment.id)
        .join(AgentTemplate, AgentTemplate.id == ProductAgentAssignment.template_id)
        .where(
            and_(
                ProductAgentAssignment.product_id == product_id,
                ProductAgentAssignment.tenant_key == tenant_key,
                AgentTemplate.tenant_key == tenant_key,
                AgentTemplate.is_active.is_(True),
                AgentTemplate.deleted_at.is_(None),
            )
        )
        .limit(1)
    )
    with tenant_session_context(session, tenant_key):
        has_any_row = (await session.execute(exists_stmt)).first() is not None

    if not has_any_row:
        return None

    return await ProductAgentAssignmentRepository().get_active_template_ids_for_product(session, product_id, tenant_key)


async def _resolve_default_product_id(session: AsyncSession, tenant_key: str) -> str | None:
    """The tenant's DEFAULT product id, or ``None`` (shared resolver, BE-9557).

    Delegates to :meth:`ProductRepository.get_default_product` -- the single
    query that reads ``is_default`` (not ``is_active``) and is still backed by
    a real per-tenant partial unique index (``idx_product_single_default_per_tenant``).

    BE-9557: the three callers below used to run their OWN ``.first()`` query
    on ``Product.is_active``, under a docstring claiming exactly one product
    per tenant can be active. That index (``idx_product_single_active_per_tenant``)
    was dropped in ce_0100 (BE-9525b/FE-9524) -- several products may be shown
    at once, so ``.first()`` returned whichever row the planner returned
    first: arbitrary, and silently wrong on any multi-shown tenant. Do NOT
    reintroduce a bare ``is_active`` query here; resolve through this one
    shared function so the rule cannot drift across its callers again.
    """
    with tenant_session_context(session, tenant_key):
        product = await ProductRepository().get_default_product(session, tenant_key, eager_load=False)
    return str(product.id) if product is not None else None


async def active_product_template_ids(
    session: AsyncSession,
    tenant_key: str,
) -> set[str] | None:
    """Template ids active for the tenant's DEFAULT product, or ``None``.

    The export paths (``giljo_setup``, the staged ZIPs, the REST bundle) carry a
    tenant but no product, so they resolve the DEFAULT product here (FE-9524:
    "default" is a single per-tenant column, independent of is_active/shown,
    and is what an unscoped read resolves to) -- see :func:`_resolve_default_product_id`.

    A tenant with no default product yields ``None`` (tenant-wide behaviour,
    unchanged), which is also what a brand-new tenant sees before it sets one.
    """
    product_id = await _resolve_default_product_id(session, tenant_key)

    if not product_id:
        return None

    return await template_ids_for_product(session, product_id, tenant_key)


async def build_export_context(session: AsyncSession, tenant_key: str, product_id: str | None = None):
    """The export identity for ``product_id``, or the DEFAULT product's (BE-9385b).

    Returns an ``ExportContext`` carrying the tenant and the resolved product's id
    and slug -- everything the assembler needs to produce product-qualified
    filenames and ownership markers. ``None`` when there is no product to
    resolve to, which keeps the export byte-identical to its pre-BE-9385b shape
    rather than inventing an owner.

    Args:
        session: Active database session.
        tenant_key: Tenant key for isolation.
        product_id: Explicit product to export as (BE-9557: giljo_setup's
            resolved binding). Falsy resolves the tenant's DEFAULT product
            instead (see :func:`_resolve_default_product_id`) -- the same
            fallback ``active_product_template_ids`` uses, so the two
            resolutions of "whose export is this" cannot disagree.

    Lives beside the selection helpers on purpose: the export sites already call
    into this module to answer "which agents", and "whose export is this" is the
    same question with the same product lookup. Splitting them would mean two
    resolutions of the product per export, which is how two answers start to
    disagree.

    Slug tolerance: a product created before ce_0092 (or by a path that bypassed
    ``ProductService``) can still carry ``slug IS NULL``. Rather than skip the
    marker or fail the export, the slug is derived from the name for that render.
    The derived value is NOT written back -- an export is a read path, and healing
    data from one is how a read path becomes a write path nobody expects.
    """
    from giljo_mcp.product_slug import slugify_product_name
    from giljo_mcp.tools.agent_template_assembler import ExportContext

    resolved_id = product_id or await _resolve_default_product_id(session, tenant_key)
    if not resolved_id:
        return None

    stmt = select(Product.id, Product.name, Product.slug).where(
        and_(
            Product.id == resolved_id,
            Product.tenant_key == tenant_key,
            Product.deleted_at.is_(None),
        )
    )
    with tenant_session_context(session, tenant_key):
        row = (await session.execute(stmt)).first()

    if row is None:
        return None

    row_product_id, product_name, product_slug = row

    return ExportContext(
        tenant_key=tenant_key,
        product_id=str(row_product_id),
        product_slug=product_slug or slugify_product_name(product_name),
    )


async def record_product_export(
    session: AsyncSession,
    product_id: str | None,
    tenant_key: str,
    template_ids: list[str],
    export_timestamp: datetime,
) -> int:
    """Record that ``product_id`` exported these agents, at this time (BE-9385e).

    The one junction-side export writer, shared by every export path for the same
    reason the selection helpers above are shared: the export sites already call
    into this module to answer "which agents" and "whose export is this", and a
    rule re-implemented at four sites is a rule that will drift.

    ``agent_templates.last_exported_at`` is still written by each site exactly as
    before -- it stays as the fallback and as pre-existing information. What is
    new is that the EXPORTING product's own rows are stamped, which is what stops
    product A's export from reading as product B's.

    Tolerant on both ends, and deliberately so:
      * ``product_id`` falsy (no active product) -> nothing to record, return 0.
        The tenant-wide write still happened, so behaviour is unchanged from
        before this project.
      * A product with no junction rows updates nothing. It is a *tolerated*
        state, not a broken one, and inserting rows here would switch its
        selection tolerance off as a side effect of downloading a ZIP. Its
        display keeps falling back to the tenant-wide value.

    Does NOT commit: every caller already commits the tenant-wide stamp, and
    sharing that transaction is what keeps the two records from disagreeing.

    Args:
        session: Active database session (caller owns the transaction).
        product_id: The product that performed the export, or None.
        tenant_key: Tenant key for isolation.
        template_ids: Template UUIDs included in this export.
        export_timestamp: Timestamp to record.

    Returns:
        Number of junction rows stamped.
    """
    if not product_id or not template_ids:
        return 0

    return await ProductAgentAssignmentRepository().record_export_for_product(
        session,
        product_id,
        template_ids,
        tenant_key,
        export_timestamp,
    )


async def active_product_export_timestamps(session: AsyncSession, tenant_key: str) -> dict[str, datetime | None]:
    """The ACTIVE product's per-agent export times, keyed by template id (BE-9385e).

    The read half of :func:`record_product_export`, and the one the Agents screen
    needs: the staleness badge is asking "when did *the product I am in* last
    export this agent?". Resolves the DEFAULT product the same way
    :func:`active_product_template_ids` does -- see
    :func:`_resolve_default_product_id`.

    Keyed on MEMBERSHIP: a template ABSENT from the mapping has no junction row
    and falls back to the tenant-wide value, while a template PRESENT with a
    ``None`` value has not been exported by this product and must NOT fall back.
    See ``models.templates.effective_last_exported_at`` for why that distinction
    is the whole fix. A tenant with no default product yields an empty mapping, so
    every lookup falls back and the display is exactly what it was before this
    project.

    Args:
        session: Active database session.
        tenant_key: Tenant key for isolation.

    Returns:
        Mapping of template id -> the default product's last export time.
    """
    product_id = await _resolve_default_product_id(session, tenant_key)

    if not product_id:
        return {}

    return await ProductAgentAssignmentRepository().get_export_timestamps_for_product(session, product_id, tenant_key)


def filter_templates_by_ids[T](templates: Iterable[T], template_ids: set[str] | None) -> list[T]:
    """Narrow ``templates`` to ``template_ids``; a ``None`` id set passes them through.

    Kept as a function rather than inlined at six call sites so the ``None``
    branch cannot be forgotten at one of them -- forgetting it is precisely the
    "product goes dark" failure this feature has to avoid.
    """
    if template_ids is None:
        return list(templates)
    return [t for t in templates if t.id in template_ids]
