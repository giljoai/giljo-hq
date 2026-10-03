# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from datetime import date

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.models import Project
from giljo_mcp.models.agent_identity import AgentExecution, AgentJob
from giljo_mcp.models.config import ApiMetrics
from giljo_mcp.models.mcp_tool_call_metrics import McpToolCallMetric


class JobStatisticsRepository:

    def __init__(self, db_manager):
        self.db = db_manager


    async def get_api_metrics(
        self,
        session: AsyncSession,
        tenant_key: str,
    ) -> ApiMetrics | None:
        stmt = select(ApiMetrics).where(ApiMetrics.tenant_key == tenant_key)
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_mcp_tool_call_counts(
        self,
        session: AsyncSession,
        tenant_key: str,
        since: date,
    ) -> list[tuple[str, int]]:
        total = func.sum(McpToolCallMetric.call_count).label("total")
        stmt = (
            select(McpToolCallMetric.tool_name, total)
            .where(
                McpToolCallMetric.tenant_key == tenant_key,
                McpToolCallMetric.day >= since,
            )
            .group_by(McpToolCallMetric.tool_name)
            .order_by(total.desc(), McpToolCallMetric.tool_name)
        )
        result = await session.execute(stmt)
        return [(name, int(count or 0)) for name, count in result.all()]


    async def get_agent_role_distribution(
        self,
        session: AsyncSession,
        tenant_key: str,
        product_id: str | None = None,
    ) -> list[dict]:
        from giljo_mcp.models.templates import AgentTemplate

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
        tmpl_names_by_len = sorted((t.name for t in templates), key=len, reverse=True)

        def _base_role(template_id: str | None, agent_name: str | None) -> str | None:
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

        counts_by_role: dict[str, int] = {}
        for template_id, agent_name, count in exec_result.all():
            role = _base_role(template_id, agent_name)
            if role is None:
                continue
            counts_by_role[role] = counts_by_role.get(role, 0) + count

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
