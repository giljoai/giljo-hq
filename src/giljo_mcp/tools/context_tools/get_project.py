# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import logging
from typing import Any

from sqlalchemy import select

from giljo_mcp.database import DatabaseManager
from giljo_mcp.models.projects import Project
from giljo_mcp.services.next_action import project_next_action_for


logger = logging.getLogger(__name__)


def estimate_tokens(data: Any) -> int:
    import json

    text = json.dumps(data)
    return len(text) // 4


async def get_project(
    project_id: str, tenant_key: str, include_summary: bool = False, db_manager: DatabaseManager | None = None
) -> dict[str, Any]:
    logger.info(
        "fetching_project_description project_id=%s tenant_key=%s include_summary=%s",
        project_id,
        tenant_key,
        include_summary,
    )

    if db_manager is None:
        logger.error("db_manager is required operation=get_project")
        raise ValueError("db_manager parameter is required")

    async with db_manager.get_session_async() as session:
        stmt = select(Project).where(Project.id == project_id, Project.tenant_key == tenant_key)
        result = await session.execute(stmt)
        project = result.scalar_one_or_none()

        if not project:
            logger.warning(
                "project_not_found project_id=%s tenant_key=%s operation=get_project", project_id, tenant_key
            )
            return {
                "source": "project_description",
                "data": {},
                "metadata": {"project_id": project_id, "tenant_key": tenant_key, "error": "project_not_found"},
            }

        data: dict[str, Any] = {
            "project_name": project.name,
            "project_alias": project.alias,
            "taxonomy_alias": project.taxonomy_alias,
            "project_description": project.description,
            "orchestrator_mission": project.mission,
            "status": project.status,
            "staging_status": project.staging_status,
        }

        next_action = project_next_action_for(project)
        if next_action is not None:
            data["next_action"] = next_action

        if include_summary and project.orchestrator_summary:
            data["orchestrator_summary"] = project.orchestrator_summary

        total_tokens = estimate_tokens(data)

        logger.info(
            "project_description_fetched project_id=%s tenant_key=%s status=%s summary_included=%s estimated_tokens=%s",
            project_id,
            tenant_key,
            project.status,
            include_summary and bool(project.orchestrator_summary),
            total_tokens,
        )

        return {
            "source": "project_description",
            "data": data,
            "metadata": {"project_id": project_id, "tenant_key": tenant_key},
        }
