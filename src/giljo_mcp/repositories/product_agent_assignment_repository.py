# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
ProductAgentAssignmentRepository - Data access for product-template assignments.

Manages the junction table that links products to tenant-wide agent templates.
Every query filters by tenant_key for multi-tenant isolation.
"""

from __future__ import annotations

import logging
from datetime import datetime

from sqlalchemy import and_, select
from sqlalchemy import delete as sql_delete
from sqlalchemy import update as sql_update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import contains_eager

from giljo_mcp.database import tenant_session_context
from giljo_mcp.models.product_agent_assignment import ProductAgentAssignment
from giljo_mcp.models.templates import AgentTemplate


logger = logging.getLogger(__name__)


class ProductAgentAssignmentRepository:
    """
    Repository for product-agent assignment operations.

    Methods accept an AsyncSession parameter (session-in pattern) so the
    calling service controls transaction boundaries.

    CRITICAL: Every query filters by tenant_key for tenant isolation.
    """

    def __init__(self) -> None:
        self._logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")

    async def get_assignments_for_product(
        self,
        session: AsyncSession,
        product_id: str,
        tenant_key: str,
        *,
        active_only: bool = False,
    ) -> list[ProductAgentAssignment]:
        """
        Get all assignments for a product with eager-loaded template info.

        Args:
            session: Active database session
            product_id: Product UUID
            tenant_key: Tenant key for isolation
            active_only: If True, only return active assignments

        Returns:
            List of ProductAgentAssignment ORM instances with template relationship loaded.
            Assignments whose template has been trashed are omitted.
        """
        # BE-9334: INNER join filtered on ``deleted_at IS NULL``. The write-path
        # predicates elsewhere in this class cannot cover the read, because a
        # template trashed AFTER it was assigned leaves a junction row that was
        # legitimate when it was written and is never revalidated. The old
        # ``joinedload`` was a LEFT OUTER JOIN with no predicate, so those stale
        # rows came back reported as ``template_is_active: True`` (soft-delete
        # stamps ``deleted_at`` and deliberately leaves ``is_active`` alone).
        #
        # Narrowing to an INNER join cannot drop a legitimate assignment:
        # ``template_id`` is ``nullable=False`` with an FK to ``agent_templates``,
        # so every row has a matching template. ``contains_eager`` populates the
        # relationship from this same join rather than adding a second one.
        stmt = (
            select(ProductAgentAssignment)
            .join(ProductAgentAssignment.template)
            .options(contains_eager(ProductAgentAssignment.template))
            .where(
                and_(
                    ProductAgentAssignment.product_id == product_id,
                    ProductAgentAssignment.tenant_key == tenant_key,
                    AgentTemplate.deleted_at.is_(None),
                )
            )
        )
        if active_only:
            stmt = stmt.where(ProductAgentAssignment.is_active.is_(True))

        with tenant_session_context(session, tenant_key):
            result = await session.execute(stmt)
        return list(result.unique().scalars().all())

    async def get_assignment(
        self,
        session: AsyncSession,
        product_id: str,
        template_id: str,
        tenant_key: str,
    ) -> ProductAgentAssignment | None:
        """
        Get a specific assignment by product+template pair.

        Args:
            session: Active database session
            product_id: Product UUID
            template_id: Template UUID
            tenant_key: Tenant key for isolation

        Returns:
            ProductAgentAssignment or None
        """
        stmt = select(ProductAgentAssignment).where(
            and_(
                ProductAgentAssignment.product_id == product_id,
                ProductAgentAssignment.template_id == template_id,
                ProductAgentAssignment.tenant_key == tenant_key,
            )
        )
        with tenant_session_context(session, tenant_key):
            result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def upsert_assignment(
        self,
        session: AsyncSession,
        product_id: str,
        template_id: str,
        tenant_key: str,
        is_active: bool,
    ) -> ProductAgentAssignment:
        """
        Create or update a product-template assignment.

        If the assignment exists, updates is_active. Otherwise creates it.

        Args:
            session: Active database session
            product_id: Product UUID
            template_id: Template UUID
            tenant_key: Tenant key for isolation
            is_active: Whether the template is active for this product

        Returns:
            The created or updated ProductAgentAssignment
        """
        existing = await self.get_assignment(session, product_id, template_id, tenant_key)

        if existing:
            existing.is_active = is_active
            await session.flush()
            return existing

        assignment = ProductAgentAssignment(
            product_id=product_id,
            template_id=template_id,
            tenant_key=tenant_key,
            is_active=is_active,
        )
        session.add(assignment)
        await session.flush()
        return assignment

    async def bulk_assign_all_templates(
        self,
        session: AsyncSession,
        product_id: str,
        tenant_key: str,
    ) -> list[ProductAgentAssignment]:
        """
        Assign all active tenant templates to a product (default: all active).

        Skips templates that already have an assignment for this product.

        Args:
            session: Active database session
            product_id: Product UUID
            tenant_key: Tenant key for isolation

        Returns:
            List of newly created ProductAgentAssignment instances
        """
        # Get all active templates for this tenant.
        # BE-9334: ``deleted_at IS NULL`` is what makes "active" mean what this
        # method's docstring says. Soft-delete stamps ``deleted_at`` and deliberately
        # leaves ``is_active`` True (``template_service.py:720``), so filtering
        # ``is_active`` alone auto-attached every TRASHED template to a product on
        # activation (``product_lifecycle_service.py:192``).
        templates_stmt = select(AgentTemplate).where(
            and_(
                AgentTemplate.tenant_key == tenant_key,
                AgentTemplate.is_active.is_(True),
                AgentTemplate.deleted_at.is_(None),
            )
        )
        with tenant_session_context(session, tenant_key):
            templates_result = await session.execute(templates_stmt)
            all_templates = list(templates_result.scalars().all())

        if not all_templates:
            return []

        # Get existing assignments for this product
        existing_stmt = select(ProductAgentAssignment.template_id).where(
            and_(
                ProductAgentAssignment.product_id == product_id,
                ProductAgentAssignment.tenant_key == tenant_key,
            )
        )
        with tenant_session_context(session, tenant_key):
            existing_result = await session.execute(existing_stmt)
        existing_template_ids = {row[0] for row in existing_result.all()}

        # Create assignments for templates not yet assigned
        new_assignments = []
        for template in all_templates:
            if template.id not in existing_template_ids:
                assignment = ProductAgentAssignment(
                    product_id=product_id,
                    template_id=template.id,
                    tenant_key=tenant_key,
                    is_active=True,
                )
                session.add(assignment)
                new_assignments.append(assignment)

        if new_assignments:
            await session.flush()

        return new_assignments

    async def remove_assignments_for_product(
        self,
        session: AsyncSession,
        product_id: str,
        tenant_key: str,
    ) -> int:
        """
        Remove all assignments for a product.

        Args:
            session: Active database session
            product_id: Product UUID
            tenant_key: Tenant key for isolation

        Returns:
            Number of assignments removed
        """
        stmt = sql_delete(ProductAgentAssignment).where(
            and_(
                ProductAgentAssignment.product_id == product_id,
                ProductAgentAssignment.tenant_key == tenant_key,
            )
        )
        with tenant_session_context(session, tenant_key):
            result = await session.execute(stmt)
        return result.rowcount

    async def record_export_for_product(
        self,
        session: AsyncSession,
        product_id: str,
        template_ids: list[str],
        tenant_key: str,
        export_timestamp: datetime,
    ) -> int:
        """Stamp ``last_exported_at`` on this product's rows for the exported agents.

        BE-9385e. The tenant-wide ``agent_templates.last_exported_at`` is still
        written by every export site (it remains the fallback), but only the
        EXPORTING product's junction rows are stamped here -- which is what stops
        one product's export from reading as another's.

        UPDATE-ONLY, deliberately: a product with no junction rows is a
        *tolerated* state, not a broken one (see ``product_agent_selection``), and
        inserting rows here would flip its tolerance off and curate it as a side
        effect of exporting. Selection semantics must not change because someone
        downloaded a ZIP. Such a product keeps reading the tenant-wide value
        through the fallback, exactly as it did before this project.

        Does NOT commit -- the caller owns the transaction, and every call site
        already commits the tenant-wide write in the same one, so the two stay
        atomic with each other.

        Args:
            session: Active database session
            product_id: The product that performed the export
            template_ids: Template UUIDs included in this export
            tenant_key: Tenant key for isolation
            export_timestamp: Timestamp to record

        Returns:
            Number of junction rows stamped.
        """
        if not template_ids:
            return 0

        stmt = (
            sql_update(ProductAgentAssignment)
            .where(
                and_(
                    ProductAgentAssignment.product_id == product_id,
                    ProductAgentAssignment.template_id.in_(template_ids),
                    ProductAgentAssignment.tenant_key == tenant_key,
                )
            )
            .values(last_exported_at=export_timestamp)
        )
        with tenant_session_context(session, tenant_key):
            result = await session.execute(stmt)
        return result.rowcount

    async def get_export_timestamps_for_product(
        self,
        session: AsyncSession,
        product_id: str,
        tenant_key: str,
    ) -> dict[str, datetime | None]:
        """Per-product ``last_exported_at`` by template id, for one product.

        BE-9385e. EVERY row for this product is returned, including rows whose
        value is still NULL -- and that is load-bearing, not laziness.

        The caller keys on MEMBERSHIP, not on the value, because "no row" and
        "row present but never stamped" are different answers and only one of
        them may fall back:

          * template id ABSENT  -> this product has no opinion; fall back to the
            template's tenant-wide value.
          * template id PRESENT with None -> this product has NOT exported this
            agent. That is an answer. Falling back here would hand the product
            whatever OTHER product last stamped the shared column, which is the
            precise defect BE-9385e exists to remove.

        Same existence-keyed shape BE-9385a used for selection, for the same
        reason: a value-keyed rule silently re-creates the bug it was meant to
        fix.

        Args:
            session: Active database session
            product_id: Product UUID
            tenant_key: Tenant key for isolation

        Returns:
            Mapping of template id -> this product's last export time (or None).
        """
        stmt = select(ProductAgentAssignment.template_id, ProductAgentAssignment.last_exported_at).where(
            and_(
                ProductAgentAssignment.product_id == product_id,
                ProductAgentAssignment.tenant_key == tenant_key,
            )
        )
        with tenant_session_context(session, tenant_key):
            result = await session.execute(stmt)
        return {row[0]: row[1] for row in result.all()}

    async def get_active_template_ids_for_product(
        self,
        session: AsyncSession,
        product_id: str,
        tenant_key: str,
    ) -> set[str]:
        """
        Get the set of active template IDs assigned to a product.

        Useful for filtering template lists by product context.

        An ACTIVE ASSIGNMENT is not the same thing as an ACTIVE TEMPLATE. This
        query previously checked only the assignment flag, so an assignment left
        pointing at a soft-deleted or deactivated template still named that
        template here. ``get_agent_templates`` narrows its live-template list to
        this set only when the set is non-empty, so one dead assignee was enough
        to engage the filter and remove every live-but-unassigned template --
        an empty agent roster on a product that plainly had agents. The join
        below makes the method honour its own name: a returned id always belongs
        to a template that is itself live.

        Args:
            session: Active database session
            product_id: Product UUID
            tenant_key: Tenant key for isolation

        Returns:
            Set of template IDs that are actively assigned AND still live
            (``is_active`` and not soft-deleted).
        """
        stmt = (
            select(ProductAgentAssignment.template_id)
            .join(AgentTemplate, AgentTemplate.id == ProductAgentAssignment.template_id)
            .where(
                and_(
                    ProductAgentAssignment.product_id == product_id,
                    ProductAgentAssignment.tenant_key == tenant_key,
                    ProductAgentAssignment.is_active.is_(True),
                    AgentTemplate.tenant_key == tenant_key,
                    AgentTemplate.is_active.is_(True),
                    AgentTemplate.deleted_at.is_(None),
                )
            )
        )
        with tenant_session_context(session, tenant_key):
            result = await session.execute(stmt)
        return {row[0] for row in result.all()}
