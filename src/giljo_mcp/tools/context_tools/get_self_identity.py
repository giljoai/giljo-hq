# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import json
import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.database import DatabaseManager
from giljo_mcp.models import AgentTemplate


logger = logging.getLogger(__name__)


def estimate_tokens(data: dict[str, Any]) -> int:
    json_str = json.dumps(data, default=str)
    return len(json_str) // 4


async def get_self_identity(
    agent_name: str,
    tenant_key: str,
    db_manager: DatabaseManager | None = None,
    session: AsyncSession | None = None,
) -> dict[str, Any]:
    logger.info("fetching_self_identity agent_name=%s tenant_key=%s", agent_name, tenant_key)

    if db_manager is None and session is None:
        logger.error("db_manager or session is required operation=get_self_identity")
        raise ValueError("db_manager or session parameter is required")

    if session is not None:
        return await _get_self_identity_impl(session, agent_name, tenant_key)

    async with db_manager.get_session_async() as new_session:
        return await _get_self_identity_impl(new_session, agent_name, tenant_key)


async def _get_self_identity_impl(
    session: AsyncSession,
    agent_name: str,
    tenant_key: str,
) -> dict[str, Any]:
    stmt = select(AgentTemplate).where(
        AgentTemplate.name == agent_name,
        AgentTemplate.tenant_key == tenant_key,
        AgentTemplate.deleted_at.is_(None),
    )
    result = await session.execute(stmt)
    template = result.scalar_one_or_none()

    if not template:
        logger.warning(
            "template_not_found agent_name=%s tenant_key=%s operation=get_self_identity",
            agent_name,
            tenant_key,
        )
        return {
            "source": "self_identity",
            "data": {},
            "metadata": {"agent_name": agent_name, "tenant_key": tenant_key, "error": "template_not_found"},
        }

    data = {
        "name": template.name,
        "role": template.role or "",
        "description": template.description or "",
        "system_instructions": template.system_instructions or "",
        "user_instructions": template.user_instructions or "",
        "behavioral_rules": template.behavioral_rules or [],
        "success_criteria": template.success_criteria or [],
        "capabilities": template.meta_data.get("capabilities", []) if template.meta_data else [],
        "expertise": template.meta_data.get("expertise", []) if template.meta_data else [],
    }

    total_tokens = estimate_tokens(data)

    logger.info(
        "self_identity_fetched agent_name=%s tenant_key=%s has_system_instructions=%s has_user_instructions=%s num_behavioral_rules=%s num_success_criteria=%s estimated_tokens=%s",
        agent_name,
        tenant_key,
        bool(template.system_instructions),
        bool(template.user_instructions),
        len(data["behavioral_rules"]),
        len(data["success_criteria"]),
        total_tokens,
    )

    return {
        "source": "self_identity",
        "data": data,
        "metadata": {"agent_name": agent_name, "tenant_key": tenant_key, "estimated_tokens": total_tokens},
    }
