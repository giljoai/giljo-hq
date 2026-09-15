# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import logging
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.database import tenant_session_context
from giljo_mcp.models import AgentTemplate
from giljo_mcp.template_seeder import (
    _get_default_templates_v103,
    _get_mcp_bootstrap_section,
    _seeded_user_instructions,
)


logger = logging.getLogger(__name__)


@dataclass
class TemplateRefreshReport:

    bootstrap_refreshed: int = 0
    user_instructions_rewritten: int = 0
    skipped_edited: list[str] = field(default_factory=list)
    archived: int = 0


async def refresh_tenant_template_instructions(
    session: AsyncSession,
    tenant_key: str,
    *,
    force: bool = False,
    archived_by: str = "system:template-refresh",
) -> TemplateRefreshReport:
    if not tenant_key:
        raise ValueError("tenant_key must be non-empty string")

    with tenant_session_context(session, tenant_key):
        return await _refresh_tenant_template_instructions(session, tenant_key, force=force, archived_by=archived_by)


async def _refresh_tenant_template_instructions(
    session: AsyncSession,
    tenant_key: str,
    *,
    force: bool,
    archived_by: str,
) -> TemplateRefreshReport:
    try:
        bootstrap = _get_mcp_bootstrap_section()

        default_templates_by_name = {t["name"]: t for t in _get_default_templates_v103()}

        stmt = select(AgentTemplate).where(AgentTemplate.tenant_key == tenant_key)
        result = await session.execute(stmt)
        templates = result.scalars().all()

        report = TemplateRefreshReport()
        if not templates:
            logger.info(f"No templates found for tenant '{tenant_key}'")
            return report

        for template in templates:
            template.system_instructions = bootstrap
            report.bootstrap_refreshed += 1

            default_def = default_templates_by_name.get(template.name)
            if default_def is None:
                continue

            seeded_ui = _seeded_user_instructions(default_def)
            is_unedited = template.user_instructions == seeded_ui

            if not is_unedited and not force:
                report.skipped_edited.append(template.name)
                continue

            if not is_unedited and force:
                await _archive_before_force_overwrite(session, template, archived_by)
                report.archived += 1

            template.user_instructions = seeded_ui
            template.behavioral_rules = []
            template.success_criteria = []
            report.user_instructions_rewritten += 1

        await session.commit()
        logger.info(
            "Refreshed %d templates for tenant '%s' (user_instructions rewritten=%d, "
            "skipped user-edited=%d, archived=%d)",
            report.bootstrap_refreshed,
            tenant_key,
            report.user_instructions_rewritten,
            len(report.skipped_edited),
            report.archived,
        )
        if report.skipped_edited:
            logger.info(
                "Preserved user-edited default-named templates for tenant '%s': %s "
                "(pass force=True to overwrite; edits are archived first)",
                tenant_key,
                ", ".join(sorted(report.skipped_edited)),
            )
        return report

    except Exception as e:
        logger.error(f"Failed to refresh templates for tenant '{tenant_key}': {e}", exc_info=True)
        raise


async def _archive_before_force_overwrite(session: AsyncSession, template: AgentTemplate, archived_by: str) -> None:
    from giljo_mcp.services.template_service import TemplateService

    service = TemplateService(db_manager=None, tenant_manager=None, session=session)  # type: ignore[arg-type]
    await service.create_template_archive(
        session,
        template,
        archive_reason="Template refresh (force overwrite)",
        archive_type="auto",
        archived_by=archived_by,
    )
