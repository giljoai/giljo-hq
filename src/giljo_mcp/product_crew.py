# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import logging
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.database import tenant_session_context
from giljo_mcp.exceptions import CrewNamingExhaustedError
from giljo_mcp.models import AgentTemplate
from giljo_mcp.system_roles import SYSTEM_MANAGED_ROLES
from giljo_mcp.template_seeder import (
    _get_default_templates_v103,
    _get_mcp_bootstrap_section,
    _seeded_user_instructions,
)
from giljo_mcp.utils.log_sanitizer import sanitize


logger = logging.getLogger(__name__)


async def seed_product_crew(session: AsyncSession, tenant_key: str, product_id: str) -> list[str]:
    if not tenant_key:
        logger.error("Cannot seed product crew: tenant_key is empty or None")
        raise ValueError("tenant_key must be non-empty string")
    if not product_id:
        logger.error("Cannot seed product crew: product_id is empty or None")
        raise ValueError("product_id must be non-empty string")

    with tenant_session_context(session, tenant_key):
        return await _seed_product_crew(session, tenant_key, product_id)


async def _seed_product_crew(session: AsyncSession, tenant_key: str, product_id: str) -> list[str]:
    from giljo_mcp.services.product_agent_assignment_service import ProductAgentAssignmentService
    from giljo_mcp.services.template_service import TemplateService
    from giljo_mcp.services.template_write_paths import (
        AGENT_NAME_RACE_ATTEMPTS,
        is_agent_name_conflict,
        resolve_crew_suffix,
    )

    already_owned = await session.execute(
        select(func.count(AgentTemplate.id)).where(
            AgentTemplate.tenant_key == tenant_key,
            AgentTemplate.product_id == product_id,
            AgentTemplate.deleted_at.is_(None),
        )
    )
    if (already_owned.scalar() or 0) > 0:
        logger.info("Product '%s' already owns templates, skipping crew seed", sanitize(product_id))
        return []

    service = TemplateService(db_manager=None, tenant_manager=None, session=session)  # type: ignore[arg-type]

    crew = [t for t in _get_default_templates_v103() if t["role"] not in SYSTEM_MANAGED_ROLES]
    base_names = [t["name"] for t in crew]
    bootstrap = _get_mcp_bootstrap_section()
    seeded_ids: list[str] = []
    seeded_names: list[str] = []

    for attempt in range(1, AGENT_NAME_RACE_ATTEMPTS + 1):
        names = await resolve_crew_suffix(service, session, tenant_key, base_names)
        current_time = datetime.now(UTC)
        seeded_ids = []
        seeded_names = []
        try:
            async with session.begin_nested():
                for template_def, name in zip(crew, names, strict=True):
                    template = AgentTemplate(
                        id=str(uuid4()),
                        tenant_key=tenant_key,
                        product_id=product_id,
                        name=name,
                        category="role",
                        role=template_def["role"],
                        cli_tool=template_def["cli_tool"],
                        background_color=template_def["background_color"],
                        description=template_def["description"],
                        system_instructions=bootstrap,
                        user_instructions=_seeded_user_instructions(template_def),
                        model=template_def.get("model", "inherit"),
                        effort=template_def.get("effort", "inherit"),
                        tools=template_def.get("tools"),
                        variables=[],
                        behavioral_rules=template_def.get("behavioral_rules", []),
                        success_criteria=template_def.get("success_criteria", []),
                        tool=template_def["cli_tool"],
                        version=template_def.get("version", "1.0.0"),
                        is_active=template_def.get("is_active", True),
                        is_default=False,
                        tags=["default", "product"],
                        created_at=current_time,
                    )
                    session.add(template)
                    seeded_ids.append(template.id)
                    seeded_names.append(name)
                await session.flush()
            break
        except IntegrityError as exc:
            if not is_agent_name_conflict(exc):
                raise
            logger.warning(
                "Crew name race on attempt %d/%d for product '%s': %s",
                attempt,
                AGENT_NAME_RACE_ATTEMPTS,
                sanitize(product_id),
                ", ".join(seeded_names),
            )
            if attempt == AGENT_NAME_RACE_ATTEMPTS:
                raise CrewNamingExhaustedError(
                    message=(
                        "Could not name this product's agents because another change was "
                        "happening at the same time. Please try creating the product again."
                    ),
                    context={"tenant_key": tenant_key, "product_id": product_id},
                ) from exc

    assignments = ProductAgentAssignmentService(db_manager=None, tenant_key=tenant_key, test_session=session)  # type: ignore[arg-type]
    await assignments.enable_for_product(session, product_id, seeded_ids)

    logger.info(
        "Seeded crew of %d agent(s) for product '%s' (tenant '%s'): %s",
        len(seeded_names),
        product_id,
        tenant_key,
        ", ".join(seeded_names),
    )
    return seeded_names
