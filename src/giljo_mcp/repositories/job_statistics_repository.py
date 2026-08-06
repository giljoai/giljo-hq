# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""Job and agent statistics repository — agent executions, jobs, API metrics, health checks."""

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.models import Project
from giljo_mcp.models.agent_identity import AgentExecution, AgentJob
from giljo_mcp.models.config import ApiMetrics


class JobStatisticsRepository:
    """
    Repository for job and agent statistics queries.

    Covers API metrics, agent execution counts, per-agent message stats,
    job lookups, database health checks, and agent role distribution.
    All methods enforce tenant isolation via tenant_key.
    """

    def __init__(self, db_manager):
        """
        Initialize job statistics repository.

        Args:
            db_manager: Database manager instance
        """
        self.db = db_manager

    # ============================================================================
    # API METRICS DOMAIN
    # ============================================================================

    async def get_api_metrics(
        self,
        session: AsyncSession,
        tenant_key: str,
    ) -> ApiMetrics | None:
        """
        Get API call metrics for tenant.

        Args:
            session: Async database session
            tenant_key: Tenant key for isolation

        Returns:
            ApiMetrics instance or None if not found
        """
        stmt = select(ApiMetrics).where(ApiMetrics.tenant_key == tenant_key)
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    # ============================================================================
    # AGENT STATISTICS DOMAIN
    # ============================================================================

    async def count_total_agents(
        self,
        session: AsyncSession,
        tenant_key: str,
    ) -> int:
        """
        Count total agents (AgentExecution instances) for tenant.

        Args:
            session: Async database session
            tenant_key: Tenant key for isolation

        Returns:
            Total agent execution count
        """
        result = await session.scalar(
            select(func.count(AgentExecution.agent_id)).where(AgentExecution.tenant_key == tenant_key)
        )
        return result or 0

    async def count_active_agents(
        self,
        session: AsyncSession,
        tenant_key: str,
    ) -> int:
        """
        Count active agents (status in ['waiting', 'working']).

        Args:
            session: Async database session
            tenant_key: Tenant key for isolation

        Returns:
            Active agent count
        """
        result = await session.scalar(
            select(func.count(AgentExecution.agent_id)).where(
                AgentExecution.tenant_key == tenant_key, AgentExecution.status.in_(["waiting", "working"])
            )
        )
        return result or 0

    async def count_completed_agents(
        self,
        session: AsyncSession,
        tenant_key: str,
    ) -> int:
        """
        Count completed agents (status='complete').

        Args:
            session: Async database session
            tenant_key: Tenant key for isolation

        Returns:
            Completed agent count
        """
        result = await session.scalar(
            select(func.count(AgentExecution.agent_id)).where(
                AgentExecution.tenant_key == tenant_key, AgentExecution.status == "complete"
            )
        )
        return result or 0

    # ============================================================================
    # DASHBOARD ANALYTICS DOMAIN
    # ============================================================================

    async def get_agent_role_distribution(
        self,
        session: AsyncSession,
        tenant_key: str,
        product_id: str | None = None,
    ) -> list[dict]:
        """
        Count agents an orchestrator spawned, categorized by role.

        Powers the Dashboard "Agent Roles / N spawned" ticker + categorization
        bar. The ticker is the sum of the returned segment counts; the bar is
        the segments themselves.

        Counting rules:
        1. Every AgentExecution is a spawned agent EXCEPT the orchestrator /
           conductor itself -- it does the assigning, it is not an agent it
           spawned -- so orchestrator executions are excluded.
        2. Each execution folds into a base role for its bar segment:
           - job.template_id -> that template's name (the activated template);
           - else agent_name that exactly matches a template name;
           - else agent_name that starts with "<template>-"/"_" folds into that
             base template (e.g. implementer-backend / implementer-frontend ->
             implementer);
           - else the agent_name stands as its own segment (a spawned agent that
             maps to no configured template still counts toward the ticker).
        Configured templates that were never spawned are still returned (count
        0) so the roster stays stable across polls.

        BE-9334 -- the template query below deliberately does NOT filter
        ``deleted_at``, and that is not an oversight. This is the third audit to
        flag it; it is being recorded here so it is the last.

        The query is neither an existence check nor an authorization check. It is
        the label/colour lookup table that ``_base_role`` folds historical
        executions onto, and history outlives the template it was produced by
        (``AgentJob.template_id`` survives soft-delete until the 30-day purge).
        Excluding a trashed row does not remove its executions from the chart --
        it removes their *fold target*, so ``implementer-backend`` and
        ``implementer-frontend`` stop collapsing onto a since-deleted
        ``implementer`` and split one historical segment into several.

        The symptom that makes this look like the BE-9325 defect class -- a
        deleted agent lingering in the Dashboard roster -- is not rendered. Both
        the bar and the legend are built from ``buildSegments``, which drops every
        zero-count entry (``DashboardView.vue:346``), so a trashed template that
        was never spawned emits count 0 and never reaches the screen. Filtering
        here would cost real fidelity on the spawned case and buy nothing on the
        unspawned one.

        Pinned by
        ``tests/services/test_be9334_trashed_template_assignment_paths.py::test_role_distribution_deliberately_keeps_trashed_templates_as_fold_targets``
        -- adding the filter turns that test red on purpose.

        Args:
            session: Async database session
            tenant_key: Tenant key for isolation
            product_id: Optional product filter

        Returns:
            List of AgentRoleDistItem-shaped dicts, sorted by count descending.
        """
        from giljo_mcp.models.templates import AgentTemplate

        # 1. Get all configured templates (scoped by product when filtered).
        #    These provide the label/colour + base-role folding targets.
        tmpl_stmt = select(
            AgentTemplate.id,
            AgentTemplate.name,
            AgentTemplate.background_color,
            AgentTemplate.is_active,
        ).where(AgentTemplate.tenant_key == tenant_key)
        if product_id:
            tmpl_stmt = tmpl_stmt.where(
                or_(
                    AgentTemplate.product_id == product_id,
                    AgentTemplate.product_id.is_(None),
                )
            )
        tmpl_result = await session.execute(tmpl_stmt)
        templates = tmpl_result.all()

        tmpl_by_id = {t.id: t for t in templates}
        # Longest template names first so a prefix fold prefers the most
        # specific base (e.g. "code-reviewer" wins over a hypothetical "code").
        tmpl_names_by_len = sorted((t.name for t in templates), key=len, reverse=True)

        def _base_role(template_id: str | None, agent_name: str | None) -> str | None:
            """Fold one execution into its base-role bucket (see docstring rule 2)."""
            if template_id and template_id in tmpl_by_id:
                return tmpl_by_id[template_id].name
            if not agent_name:
                return None
            name = agent_name.strip()
            low = name.lower()
            for tname in tmpl_names_by_len:
                if low == tname.lower():
                    return tname
            for tname in tmpl_names_by_len:
                tl = tname.lower()
                if low.startswith((tl + "-", tl + "_")):
                    return tname
            return name

        # 2. Count EVERY spawned worker execution, excluding the orchestrator /
        #    conductor (created with agent_display_name "orchestrator").
        exec_stmt = (
            select(
                AgentJob.template_id,
                AgentExecution.agent_name,
                func.count(AgentExecution.id).label("cnt"),
            )
            .join(
                AgentJob,
                and_(
                    AgentExecution.job_id == AgentJob.job_id,
                    AgentJob.tenant_key == tenant_key,
                ),
            )
            .where(
                AgentExecution.tenant_key == tenant_key,
                func.lower(func.coalesce(AgentExecution.agent_display_name, "")) != "orchestrator",
            )
            .group_by(AgentJob.template_id, AgentExecution.agent_name)
        )
        if product_id:
            exec_stmt = exec_stmt.join(
                Project,
                and_(
                    AgentJob.project_id == Project.id,
                    Project.tenant_key == tenant_key,
                ),
            ).where(Project.product_id == product_id)
        exec_result = await session.execute(exec_stmt)

        # 3. Fold counts into base roles.
        counts_by_role: dict[str, int] = {}
        for template_id, agent_name, count in exec_result.all():
            role = _base_role(template_id, agent_name)
            if role is None:
                continue
            counts_by_role[role] = counts_by_role.get(role, 0) + count

        # 4. Build segments: every configured template (even count 0) + any
        #    spawned role that maps to no template.
        result = []
        emitted: set[str] = set()
        for tmpl in templates:
            if tmpl.name in emitted:
                continue
            emitted.add(tmpl.name)
            result.append(
                {
                    "label": tmpl.name.replace("-", " ").replace("_", " ").title(),
                    "count": counts_by_role.get(tmpl.name, 0),
                    "color": tmpl.background_color or "#9e9e9e",
                    "is_active": tmpl.is_active,
                }
            )
        for role, count in counts_by_role.items():
            if role in emitted:
                continue
            emitted.add(role)
            result.append(
                {
                    "label": role.replace("-", " ").replace("_", " ").title(),
                    "count": count,
                    "color": "#9e9e9e",
                    "is_active": True,
                }
            )

        result.sort(key=lambda x: x["count"], reverse=True)
        return result
