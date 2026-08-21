# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
Get agent self-identity (template) context tool.

Handover 0430: Internal tool for fetch_context() self_identity category.

Fetches the agent's own template from the database, providing behavioral guidance,
success criteria, and protocol instructions from the AgentTemplate stored in Admin Settings.
"""
# Read-only tool -- uses direct session.execute() for SELECT queries (no writes)

import json
import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.database import DatabaseManager
from giljo_mcp.models import AgentTemplate


logger = logging.getLogger(__name__)


def estimate_tokens(data: dict[str, Any]) -> int:
    """
    Estimate token count for response data.

    chars÷4 measured and found SAFE here, unlike
    get_tasks.py's identifier-dense rows. Agent-template content
    (system_instructions/user_instructions/behavioral_rules/success_criteria) is
    prose, not identifier-dense JSON -- measured on a realistic template payload
    against the real wire serializer (pydantic_core.to_json) and tiktoken
    o200k_base: 5.65 chars/token, i.e. ÷4 OVERestimates token cost here (the safe
    direction) rather than understating it. Left unchanged.

    Args:
        data: Dictionary to estimate tokens for

    Returns:
        Estimated token count
    """
    json_str = json.dumps(data, default=str)
    return len(json_str) // 4


async def get_self_identity(
    agent_name: str,
    tenant_key: str,
    db_manager: DatabaseManager | None = None,
    session: AsyncSession | None = None,  # For testing only
) -> dict[str, Any]:
    """
    Fetch agent template by name for self-identity context.

    Handover 0430: Internal tool for fetch_context() self_identity category.

    Returns the agent's template content including:
    - system_instructions: Protected MCP coordination instructions
    - user_instructions: User-customizable role-specific guidance
    - behavioral_rules: Role-specific behavioral constraints
    - success_criteria: Success metrics and completion criteria

    Args:
        agent_name: Template name (matches AgentTemplate.name, e.g., "orchestrator-coordinator")
        tenant_key: Tenant isolation key
        db_manager: Database manager instance

    Returns:
        Dict with agent identity info:
        {
            "source": "self_identity",
            "data": {
                "name": "orchestrator-coordinator",
                "role": "Orchestrator",
                "description": "...",
                "system_instructions": "...",
                "user_instructions": "...",
                "behavioral_rules": [...],
                "success_criteria": [...]
            },
            "metadata": {
                "agent_name": "orchestrator-coordinator",
                "tenant_key": "...",
                "estimated_tokens": 2000
            }
        }

    Multi-Tenant Isolation:
        All queries filter by tenant_key.

    Example:
        result = await get_self_identity(
            agent_name="orchestrator-coordinator",
            tenant_key="tenant_abc",
            db_manager=db_manager
        )
    """
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
    """Inner implementation for get_self_identity using a provided session."""
    # Query template by name with multi-tenant isolation.
    # BE-6137: exclude soft-deleted templates from self-identity reads.
    stmt = select(AgentTemplate).where(
        AgentTemplate.name == agent_name,
        AgentTemplate.tenant_key == tenant_key,
        AgentTemplate.is_active,
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

    # Build data dict with all identity fields
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

    # Calculate token estimate
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
