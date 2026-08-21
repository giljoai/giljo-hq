# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
MissionRepository - Data access layer for agent mission operations.

BE-5022d: Extracted session operations from MissionService and
MissionOrchestrationService into repository methods.

All methods enforce tenant_key isolation. Session is passed by the caller.
"""

from __future__ import annotations

import logging

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload, selectinload

from giljo_mcp.models.agent_identity import TERMINAL_EXECUTION_STATUSES, AgentExecution, AgentJob
from giljo_mcp.models.projects import Project
from giljo_mcp.models.templates import AgentTemplate
from giljo_mcp.repositories.product_agent_selection import template_ids_for_product
from giljo_mcp.template_renderer import MAX_PACKAGED_TEMPLATES


logger = logging.getLogger(__name__)


class MissionRepository:
    """
    Repository for agent mission database operations.

    Covers: MissionService reads/writes, MissionOrchestrationService reads.
    All methods enforce tenant_key isolation.
    Session is passed in by the caller (service layer).
    """

    def __init__(self) -> None:
        self._logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")

    # ============================================================================
    # Core Reads — MissionService
    # ============================================================================

    async def get_job(
        self,
        session: AsyncSession,
        tenant_key: str,
        job_id: str,
    ) -> AgentJob | None:
        """Get an agent job by ID with tenant isolation."""
        result = await session.execute(
            select(AgentJob).where(
                and_(
                    AgentJob.job_id == job_id,
                    AgentJob.tenant_key == tenant_key,
                )
            )
        )
        return result.scalar_one_or_none()

    async def get_active_execution(
        self,
        session: AsyncSession,
        tenant_key: str,
        job_id: str,
    ) -> AgentExecution | None:
        """Get the latest active (non-terminal) execution for a job."""
        result = await session.execute(
            select(AgentExecution)
            .where(
                and_(
                    AgentExecution.job_id == job_id,
                    AgentExecution.tenant_key == tenant_key,
                    AgentExecution.status.not_in(TERMINAL_EXECUTION_STATUSES),
                )
            )
            .order_by(AgentExecution.started_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def get_project_by_id(
        self,
        session: AsyncSession,
        tenant_key: str,
        project_id: str,
    ) -> Project | None:
        """Get a project by ID with tenant isolation."""
        result = await session.execute(
            select(Project).where(Project.id == project_id, Project.tenant_key == tenant_key)
        )
        return result.scalar_one_or_none()

    async def get_project_executions_with_jobs(
        self,
        session: AsyncSession,
        tenant_key: str,
        project_id: str,
    ) -> list:
        """Get all executions with their jobs for a project."""
        result = await session.execute(
            select(AgentExecution, AgentJob)
            .join(AgentJob, AgentExecution.job_id == AgentJob.job_id)
            .where(
                and_(
                    AgentJob.project_id == project_id,
                    AgentExecution.tenant_key == tenant_key,
                )
            )
        )
        return result.all()

    async def get_template_by_id(
        self,
        session: AsyncSession,
        tenant_key: str,
        template_id: str,
    ) -> AgentTemplate | None:
        """Get a live agent template by ID with tenant isolation.

        BE-9325: ``deleted_at IS NULL`` is load-bearing here. ``AgentJob.template_id``
        is only nulled at the 30-day hard purge (``template_service.nullify_job_template_refs``),
        never at soft-delete, so a job bound to a since-trashed template would otherwise
        keep rendering that template's instructions as its live identity on every
        ``get_job_mission`` call for up to 30 days.
        """
        result = await session.execute(
            select(AgentTemplate).where(
                and_(
                    AgentTemplate.id == template_id,
                    AgentTemplate.tenant_key == tenant_key,
                    AgentTemplate.deleted_at.is_(None),
                )
            )
        )
        return result.scalar_one_or_none()

    async def get_template_by_role(
        self,
        session: AsyncSession,
        tenant_key: str,
        role: str,
    ) -> AgentTemplate | None:
        """Get an active agent template for a role.

        Resolution: tenant-specific -> role default.

        BE-9357: ``deleted_at IS NULL`` is load-bearing on both branches, for the same
        reason it is on :meth:`get_template_by_id` directly above. Soft-delete stamps
        ``deleted_at`` and leaves ``is_active``/``is_default`` set, so an ``is_active``
        predicate alone still matches a template the operator deleted -- and role
        resolution would hand its instructions back as a live agent identity.

        The ``tenant_key`` predicate on the default branch is defence in depth rather
        than a live leak fix: ``tenant_guard`` injects a tenant filter into every SELECT
        touching a tenant-scoped model, so no real caller read across tenants here. It is
        added because the house rule has no "something else also filters it" exception,
        and because it matches the shape of the live role-default read in
        ``thin_prompt_lifecycle``. Note the consequence: the default branch is now a
        strict subset of the tenant branch above, so it can no longer return a row the
        first branch would have missed. It is left in place rather than deleted -- the
        seeder writes every tenant its own ``is_default`` rows, and removing a resolution
        branch is a separate decision.
        """
        # 1. Tenant-specific
        stmt = select(AgentTemplate).where(
            AgentTemplate.tenant_key == tenant_key,
            AgentTemplate.role == role,
            AgentTemplate.is_active,
            AgentTemplate.deleted_at.is_(None),
        )
        result = await session.execute(stmt)
        template = result.scalar_one_or_none()
        if template:
            return template

        # 2. Role default
        stmt = (
            select(AgentTemplate)
            .where(
                AgentTemplate.tenant_key == tenant_key,
                AgentTemplate.role == role,
                AgentTemplate.is_default,
                AgentTemplate.is_active,
                AgentTemplate.deleted_at.is_(None),
            )
            .limit(1)
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def refresh(self, session: AsyncSession, entity) -> None:
        """Refresh an entity from the database."""
        await session.refresh(entity)

    # ============================================================================
    # Reads — MissionService update_agent_mission
    # ============================================================================

    async def count_non_orchestrator_agents(
        self,
        session: AsyncSession,
        tenant_key: str,
        project_id: str,
    ) -> int:
        """Count non-orchestrator, non-decommissioned agent executions for a project."""
        result = await session.execute(
            select(func.count())
            .select_from(AgentExecution)
            .join(AgentJob, AgentExecution.job_id == AgentJob.job_id)
            .where(
                AgentJob.project_id == project_id,
                AgentJob.tenant_key == tenant_key,
                AgentExecution.agent_display_name != "orchestrator",
                AgentExecution.status.not_in(["decommissioned"]),
            )
        )
        return result.scalar() or 0

    async def count_non_orchestrator_agents_by_liveness(
        self,
        session: AsyncSession,
        tenant_key: str,
        project_id: str,
    ) -> tuple[int, int]:
        """Count a project's specialist (non-orchestrator) executions as
        ``(total, in_flight)`` (BE-9165).

        ``in_flight`` counts executions whose status is NOT in
        :data:`~giljo_mcp.models.agent_identity.TERMINAL_EXECUTION_STATUSES`.
        ``total >= 1 and in_flight == 0`` is the "all deliverables already
        recorded" predicate shared by the force-close orchestrator-decommission
        guard and the staging-finale closeout reroute.
        """
        result = await session.execute(
            select(
                func.count(),
                func.count().filter(AgentExecution.status.not_in(TERMINAL_EXECUTION_STATUSES)),
            )
            .select_from(AgentExecution)
            .join(AgentJob, AgentExecution.job_id == AgentJob.job_id)
            .where(
                AgentJob.project_id == project_id,
                AgentJob.tenant_key == tenant_key,
                AgentExecution.agent_display_name != "orchestrator",
            )
        )
        total, in_flight = result.one()
        return int(total or 0), int(in_flight or 0)

    # ============================================================================
    # Reads — MissionOrchestrationService
    # ============================================================================

    async def get_execution_with_job(
        self,
        session: AsyncSession,
        tenant_key: str,
        job_id: str,
    ) -> AgentExecution | None:
        """Get execution with eagerly loaded job relationship."""
        result = await session.execute(
            select(AgentExecution)
            .options(joinedload(AgentExecution.job))
            .where(
                and_(
                    AgentExecution.job_id == job_id,
                    AgentExecution.tenant_key == tenant_key,
                )
            )
            .order_by(AgentExecution.started_at.desc())
        )
        return result.scalars().first()

    async def get_project_with_vision_docs(
        self,
        session: AsyncSession,
        tenant_key: str,
        product_id: str,
    ):
        """Get a product with eagerly loaded vision documents."""
        from giljo_mcp.models.products import Product

        result = await session.execute(
            select(Product)
            .where(and_(Product.id == product_id, Product.tenant_key == tenant_key))
            .options(selectinload(Product.vision_documents))
        )
        return result.scalar_one_or_none()

    async def get_product_name(
        self,
        session: AsyncSession,
        tenant_key: str,
        product_id: str,
    ) -> str | None:
        """Get just a product's name (FE-9408 provenance line), tenant-scoped.

        One scalar column rather than ``get_project_with_vision_docs`` above: the
        provenance line needs a label, and that method eagerly loads every vision
        document attached to the product -- multi-KB of text, dragged into the
        identity path to render a few words.
        """
        from giljo_mcp.models.products import Product

        result = await session.execute(
            select(Product.name).where(and_(Product.id == product_id, Product.tenant_key == tenant_key))
        )
        return result.scalar_one_or_none()

    async def get_active_templates(
        self,
        session: AsyncSession,
        tenant_key: str,
        limit: int = MAX_PACKAGED_TEMPLATES,
        *,
        product_id: str | None = None,
    ) -> list[AgentTemplate]:
        """Get the agent templates the orchestrator may spawn.

        BE-9325: soft-delete leaves ``is_active`` True, so without the ``deleted_at``
        filter a trashed agent stays on the roster the orchestrator is shown as
        available to spawn -- and spawning it then resolves nothing.

        BE-9385a, two changes:

        1. ``product_id`` narrows the roster to that product's junction. ``None``
           (no product in context) and a product with no junction rows both keep
           the tenant-wide set -- the tolerance rule, which lives in
           ``product_agent_selection``.
        2. The cap is now ``MAX_PACKAGED_TEMPLATES`` (16), shared with the export
           path, instead of a local literal 8. Those were two numbers for one
           concept: with more than 8 active agents the orchestrator was shown a
           roster it could spawn from that was strictly smaller than the set the
           export had already installed on disk -- so an agent could exist as a
           file and be unspawnable. The export cap was deliberately raised 8->16
           in BE-9208; the roster stayed at 8 by omission. Measured cost of the
           unification: nothing for a stock install (6 seeded agents, under both
           caps), ~+320 tokens of mission prompt in the cap-saturated worst case.

        The product filter is applied IN the query, not to its result: filtering
        after ``LIMIT`` would silently shrink the roster below the cap.
        """
        template_ids = await template_ids_for_product(session, product_id, tenant_key)

        stmt = select(AgentTemplate).where(
            and_(
                AgentTemplate.tenant_key == tenant_key,
                AgentTemplate.is_active,
                AgentTemplate.deleted_at.is_(None),
            )
        )
        if template_ids is not None:
            # An empty set is a real answer (every agent disabled for this
            # product), and ``in_(())`` correctly matches nothing.
            stmt = stmt.where(AgentTemplate.id.in_(template_ids))

        result = await session.execute(stmt.limit(limit))
        return list(result.scalars().all())

    async def get_category_metadata(
        self,
        session: AsyncSession,
        tenant_key: str,
        product_id: str,
    ) -> tuple[int, object]:
        """Get count and max created_at for product memory entries."""
        from giljo_mcp.models.product_memory_entry import ProductMemoryEntry

        result = await session.execute(
            select(
                func.count(ProductMemoryEntry.id),
                func.max(ProductMemoryEntry.created_at),
            ).where(
                and_(
                    ProductMemoryEntry.product_id == product_id,
                    ProductMemoryEntry.tenant_key == tenant_key,
                    ProductMemoryEntry.deleted_by_user.is_(False),
                )
            )
        )
        row = result.one()
        return row[0], row[1]
