# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import logging
from contextlib import asynccontextmanager
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.database import DatabaseManager
from giljo_mcp.models import AgentTemplate
from giljo_mcp.tools.context_tools._response_ceiling import estimate_tokens


logger = logging.getLogger(__name__)


@asynccontextmanager
async def _session_scope(db_manager: DatabaseManager | None, test_session: AsyncSession | None):
    if test_session is not None:
        yield test_session
    else:
        async with db_manager.get_session_async() as session:
            yield session


async def get_agent_templates(
    product_id: str,
    tenant_key: str,
    detail: str = "basic",
    offset: int = 0,
    limit: int = None,
    db_manager: DatabaseManager | None = None,
    _test_session: AsyncSession | None = None,
) -> dict[str, Any]:
    logger.info("fetching_agent_templates_context product_id=%s tenant_key=%s depth=%s", product_id, tenant_key, detail)

    if db_manager is None and _test_session is None:
        logger.error("db_manager is required operation=get_agent_templates")
        raise ValueError("db_manager parameter is required")

    async with _session_scope(db_manager, _test_session) as session:
        stmt = (
            select(AgentTemplate)
            .where(
                AgentTemplate.tenant_key == tenant_key,
                AgentTemplate.deleted_at.is_(None),
            )
            .order_by(AgentTemplate.name)
        )

        result = await session.execute(stmt)
        templates = list(result.scalars().all())

        if product_id and templates:
            from giljo_mcp.repositories.product_agent_selection import (
                filter_templates_by_ids,
                template_ids_for_product,
            )

            templates = filter_templates_by_ids(
                templates, await template_ids_for_product(session, product_id, tenant_key)
            )

        if not templates:
            logger.debug("no_agent_templates tenant_key=%s operation=get_agent_templates", tenant_key)
            return {
                "source": "agent_templates",
                "depth": detail,
                "data": [],
                "metadata": {"product_id": product_id, "tenant_key": tenant_key, "num_templates": 0},
            }

        template_list = []

        for template in templates:
            if detail == "basic":
                template_dict = {
                    "name": template.name,
                    "role": template.role or "Specialized agent",
                    "description": template.description or "",
                }

            else:
                template_dict = {
                    "name": template.name,
                    "role": template.role or "Specialized agent",
                    "description": template.description,
                    "system_instructions": template.system_instructions,
                    "user_instructions": template.user_instructions,
                    "behavioral_rules": template.behavioral_rules,
                    "success_criteria": template.success_criteria,
                    "harness": template.cli_tool or "claude",
                    "model": (template.model or "").strip() or "inherit",
                    "effort": (template.effort or "").strip() or "inherit",
                    "capabilities": template.meta_data.get("capabilities", []) if template.meta_data else [],
                    "expertise": template.meta_data.get("expertise", []) if template.meta_data else [],
                    "typical_tasks": template.meta_data.get("typical_tasks", []) if template.meta_data else [],
                    "tools": template.meta_data.get("tools", []) if template.meta_data else [],
                    "is_active": template.is_active,
                    "created_at": str(template.created_at) if template.created_at else None,
                    "updated_at": str(template.updated_at) if template.updated_at else None,
                }

            template_list.append(template_dict)

        total_tokens = estimate_tokens(template_list)

        logger.info(
            "agent_templates_fetched product_id=%s tenant_key=%s depth=%s num_templates=%s estimated_tokens=%s",
            product_id,
            tenant_key,
            detail,
            len(template_list),
            total_tokens,
        )

        return {
            "source": "agent_templates",
            "depth": detail,
            "data": template_list,
            "metadata": {
                "product_id": product_id,
                "tenant_key": tenant_key,
                "num_templates": len(template_list),
                "pagination_supported": False,
            },
        }
