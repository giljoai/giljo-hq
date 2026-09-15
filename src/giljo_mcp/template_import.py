# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.database import tenant_session_context
from giljo_mcp.exceptions import AlreadyExistsError, ValidationError
from giljo_mcp.models import AgentTemplate
from giljo_mcp.system_roles import SYSTEM_MANAGED_ROLES
from giljo_mcp.template_seeder import (
    _get_default_templates_v103,
    _get_mcp_bootstrap_section,
    _seeded_user_instructions,
)
from giljo_mcp.template_validation import slugify_name
from giljo_mcp.utils.log_sanitizer import sanitize


logger = logging.getLogger(__name__)

DUPLICATE_SUFFIX = "duplicate"


@dataclass
class TemplateImportReport:

    added: list[str] = field(default_factory=list)
    added_as_duplicate: list[str] = field(default_factory=list)
    skipped_identical: list[str] = field(default_factory=list)


async def import_default_templates(session: AsyncSession, tenant_key: str, product_id: str) -> TemplateImportReport:
    if not tenant_key:
        raise ValueError("tenant_key must be non-empty string")
    if not product_id:
        raise ValueError("product_id must be non-empty string")

    from giljo_mcp.services.template_write_paths import require_own_product

    with tenant_session_context(session, tenant_key):
        await require_own_product(session, product_id, tenant_key)
        return await _import_default_templates(session, tenant_key, product_id)


async def _import_default_templates(session: AsyncSession, tenant_key: str, product_id: str) -> TemplateImportReport:
    from giljo_mcp.services.product_agent_assignment_service import ProductAgentAssignmentService
    from giljo_mcp.services.template_service import TemplateService

    service = TemplateService(db_manager=None, tenant_manager=None, session=session)  # type: ignore[arg-type]

    stmt = select(AgentTemplate).where(
        AgentTemplate.tenant_key == tenant_key,
        AgentTemplate.deleted_at.is_(None),
    )
    all_live = list((await session.execute(stmt)).scalars().all())
    live_names = {t.name for t in all_live}
    existing = [t for t in all_live if t.product_id == product_id]

    bootstrap = _get_mcp_bootstrap_section()
    report = TemplateImportReport()
    now = datetime.now(UTC)
    imported_ids: list[str] = []

    for template_def in _get_default_templates_v103():
        if template_def["role"] in SYSTEM_MANAGED_ROLES:
            continue

        default_name = template_def["name"]
        pristine_ui = _seeded_user_instructions(template_def)

        if any(t.user_instructions == pristine_ui for t in existing):
            report.skipped_identical.append(default_name)
            continue

        if default_name in live_names:
            new_name = slugify_name(template_def["role"], DUPLICATE_SUFFIX)
            base_name = new_name
            counter = 2
            while await service.check_template_name_exists(session, tenant_key, new_name):
                new_name = f"{base_name}-{counter}"
                counter += 1
                if counter > 20:
                    raise ValidationError(message=f"Too many agents named '{base_name}' — clean up copies first")
            is_default = False
            report.added_as_duplicate.append(new_name)
        else:
            new_name = default_name
            is_default = not any(t.role == template_def["role"] and t.is_default for t in existing)
            report.added.append(new_name)

        template = AgentTemplate(
            id=str(uuid4()),
            tenant_key=tenant_key,
            product_id=product_id,
            name=new_name,
            category="role",
            role=template_def["role"],
            cli_tool=template_def["cli_tool"],
            background_color=template_def["background_color"],
            description=template_def["description"],
            system_instructions=bootstrap,
            user_instructions=pristine_ui,
            model=template_def.get("model", "sonnet"),
            tools=template_def.get("tools"),
            variables=[],
            behavioral_rules=template_def.get("behavioral_rules", []),
            success_criteria=template_def.get("success_criteria", []),
            tool=template_def["cli_tool"],
            version=template_def.get("version", "1.0.0"),
            is_active=template_def.get("is_active", True),
            is_default=is_default,
            tags=["default", "product"],
            created_at=now,
        )
        try:
            await service.add_and_commit_template(session, template)
        except IntegrityError as e:
            await session.rollback()
            raise AlreadyExistsError(
                message=(f"An agent template named '{new_name}' already exists (concurrent import). Please retry."),
                context={"tenant_key": tenant_key, "name": new_name},
            ) from e
        existing.append(template)
        live_names.add(new_name)
        imported_ids.append(template.id)

    if imported_ids:
        assignments = ProductAgentAssignmentService(db_manager=None, tenant_key=tenant_key, test_session=session)  # type: ignore[arg-type]
        await assignments.enable_for_product(session, product_id, imported_ids)
        await session.commit()

    logger.info(
        "Imported default agents into product '%s' (tenant '%s'): %d added, %d added as duplicate, %d skipped identical",
        sanitize(product_id),
        sanitize(tenant_key),
        len(report.added),
        len(report.added_as_duplicate),
        len(report.skipped_identical),
    )
    return report
