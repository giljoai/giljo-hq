# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import logging

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import func

from giljo_mcp.database import DatabaseManager, tenant_session_context
from giljo_mcp.exceptions import (
    BaseGiljoError,
    TemplateNotFoundError,
    ValidationError,
)

from giljo_mcp.models.templates import AgentTemplate, TemplateArchive
from giljo_mcp.repositories.template_repository import TemplateRepository
from giljo_mcp.schemas.jsonb_validators import validate_behavioral_rules, validate_success_criteria
from giljo_mcp.schemas.service_responses import (
    TemplateDetail,
    TemplateGetResult,
)
from giljo_mcp.services import template_lifecycle, template_write_paths
from giljo_mcp.services._session_helpers import optional_tenant_session
from giljo_mcp.system_roles import SYSTEM_MANAGED_ROLES
from giljo_mcp.tenant import TenantManager


logger = logging.getLogger(__name__)


FACTORY_ORIGIN_TAG = "default"


def factory_default_for(template: AgentTemplate) -> dict | None:
    from giljo_mcp.template_seeder import _get_default_templates_v103

    defaults = _get_default_templates_v103()
    by_name = {t["name"]: t for t in defaults}
    if template.name in by_name:
        return by_name[template.name]

    by_role = {t["role"]: t for t in defaults}
    if FACTORY_ORIGIN_TAG in (template.tags or []):
        return by_role.get(template.role)
    if not (template.user_instructions or "").strip():
        return by_role.get(template.role)
    return None


USER_MANAGED_AGENT_LIMIT = 15

_ALLOWED_TEMPLATE_UPDATE_FIELDS: frozenset[str] = frozenset(
    {
        "name",
        "category",
        "role",
        "user_instructions",
        "variables",
        "behavioral_rules",
        "success_criteria",
        "tool",
        "cli_tool",
        "background_color",
        "model",
        "effort",
        "tools",
        "description",
        "version",
        "is_active",
        "is_default",
        "tags",
        "meta_data",
    }
)


class TemplateService:

    def __init__(self, db_manager: DatabaseManager, tenant_manager: TenantManager, session: AsyncSession | None = None):
        self.db_manager = db_manager
        self.tenant_manager = tenant_manager
        self._session = session
        self._repo = TemplateRepository()
        self._logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")

    def _get_session(self, tenant_key: str | None = None):
        return optional_tenant_session(
            self.db_manager, tenant_key or self.tenant_manager.get_current_tenant(), self._session
        )

    async def get_template(
        self, template_id: str | None = None, template_name: str | None = None, tenant_key: str | None = None
    ) -> TemplateGetResult:
        try:
            if not template_id and not template_name:
                raise ValidationError(
                    message="Either template_id or template_name must be provided",
                    context={"operation": "get_template"},
                )

            if not tenant_key:
                tenant_key = self.tenant_manager.get_current_tenant()

            if not tenant_key:
                raise ValidationError(message="No tenant context available", context={"operation": "get_template"})

            async with self._get_session(tenant_key) as session:
                if template_id:
                    template = await self._repo.get_by_id(session, template_id, tenant_key)
                else:
                    template = await self._repo.get_by_name(session, template_name, tenant_key)

                if not template:
                    identifier = template_id if template_id else template_name
                    raise TemplateNotFoundError(
                        message=f"Template '{identifier}' not found",
                        context={
                            "template_id": template_id,
                            "template_name": template_name,
                            "tenant_key": tenant_key,
                        },
                    )

                return TemplateGetResult(
                    template=TemplateDetail(
                        id=str(template.id),
                        name=template.name,
                        role=template.role,
                        content=template.system_instructions,
                        cli_tool=template.cli_tool,
                        background_color=template.background_color,
                        category=template.category,
                        tenant_key=template.tenant_key,
                        product_id=template.product_id,
                    )
                )

        except (ValidationError, TemplateNotFoundError):
            raise
        except Exception as e:
            self._logger.exception("Failed to get template")
            raise BaseGiljoError(
                message=f"Failed to get template: {e!s}",
                context={
                    "template_id": template_id,
                    "template_name": template_name,
                    "tenant_key": tenant_key,
                },
            ) from e

    async def create_template_from_request(
        self,
        session: AsyncSession,
        data,
        tenant_key: str,
        created_by: str | None = None,
    ) -> AgentTemplate:
        return await template_write_paths.create_from_request(self, session, data, tenant_key, created_by)

    async def update_template_from_request(
        self,
        session: AsyncSession,
        template_id: str,
        updates,
        tenant_key: str,
        username: str | None = None,
    ) -> tuple[AgentTemplate, list[str]]:
        return await template_write_paths.update_from_request(self, session, template_id, updates, tenant_key, username)


    @staticmethod
    def _is_system_managed_role(role: str | None) -> bool:
        return bool(role and role in SYSTEM_MANAGED_ROLES)


    async def get_template_by_id(
        self,
        session: AsyncSession,
        template_id: str,
        tenant_key: str,
    ) -> AgentTemplate | None:
        with tenant_session_context(session, tenant_key):
            return await self._repo.get_by_id(session, template_id, tenant_key)

    async def list_templates_with_filters(
        self,
        session: AsyncSession,
        tenant_key: str,
        role: str | None = None,
        is_active: bool | None = None,
        product_id: str | None = None,
    ) -> list[AgentTemplate]:
        with tenant_session_context(session, tenant_key):
            return await self._repo.list_with_filters(session, tenant_key, role, is_active, product_id)

    async def check_template_name_exists(
        self,
        session: AsyncSession,
        tenant_key: str,
        name: str,
    ) -> bool:
        with tenant_session_context(session, tenant_key):
            return await self._repo.check_name_exists(session, tenant_key, name)

    async def get_default_templates_by_role(
        self,
        session: AsyncSession,
        tenant_key: str,
        role: str,
    ) -> list[AgentTemplate]:
        with tenant_session_context(session, tenant_key):
            return await self._repo.get_defaults_by_role(session, tenant_key, role)

    async def get_enabled_role_count(
        self,
        session: AsyncSession,
        tenant_key: str,
        product_id: str,
    ) -> int:
        from giljo_mcp.repositories.product_agent_assignment_repository import (
            ProductAgentAssignmentRepository,
        )

        roles = await ProductAgentAssignmentRepository().get_enabled_distinct_roles(session, product_id, tenant_key)
        return len(roles)


    async def purge_expired_deleted_templates(self, tenant_key: str | None = None) -> int:
        return await template_lifecycle.purge_expired_deleted_templates(self, tenant_key)

    async def delete_template(
        self,
        session: AsyncSession,
        template_id: str,
        tenant_key: str,
    ) -> bool:
        return await template_lifecycle.delete_template(self, session, template_id, tenant_key)

    async def restore_template(
        self,
        template_id: str,
        tenant_key: str,
    ) -> AgentTemplate:
        return await template_lifecycle.restore_template(self, template_id, tenant_key)

    async def list_deleted_templates(
        self,
        tenant_key: str | None = None,
    ) -> list[AgentTemplate]:
        return await template_lifecycle.list_deleted_templates(self, tenant_key)


    async def get_template_history(
        self,
        session: AsyncSession,
        template_id: str,
        tenant_key: str,
    ) -> list[TemplateArchive]:
        with tenant_session_context(session, tenant_key):
            return await self._repo.get_template_history(session, template_id, tenant_key)

    async def get_archive_by_id(
        self,
        session: AsyncSession,
        archive_id: str,
        template_id: str,
        tenant_key: str,
    ) -> TemplateArchive | None:
        with tenant_session_context(session, tenant_key):
            return await self._repo.get_archive_by_id(session, archive_id, template_id, tenant_key)

    async def create_template_archive(
        self,
        session: AsyncSession,
        template: AgentTemplate,
        archive_reason: str,
        archive_type: str,
        archived_by: str,
    ) -> TemplateArchive:
        archive = TemplateArchive(
            tenant_key=template.tenant_key,
            template_id=template.id,
            product_id=template.product_id,
            name=template.name,
            category=template.category,
            role=template.role,
            system_instructions=template.system_instructions,
            user_instructions=template.user_instructions,
            variables=template.variables,
            behavioral_rules=template.behavioral_rules,
            success_criteria=template.success_criteria,
            version=template.version,
            archive_reason=archive_reason,
            archive_type=archive_type,
            archived_by=archived_by,
            usage_count_at_archive=0,
            avg_generation_ms_at_archive=template.avg_generation_ms,
        )
        await self._repo.add_archive(session, archive)
        return archive

    async def restore_template_from_archive(
        self,
        session: AsyncSession,
        template: AgentTemplate,
        archive: TemplateArchive,
        restored_by: str | None = None,
    ) -> None:
        template.variables = archive.variables
        template.behavioral_rules = validate_behavioral_rules(archive.behavioral_rules)
        template.success_criteria = validate_success_criteria(archive.success_criteria)
        template.version = archive.version
        archive.restored_at = func.now()
        archive.restored_by = restored_by

    async def reset_template_to_defaults(
        self,
        session: AsyncSession,
        template: AgentTemplate,
    ) -> None:
        default_def = factory_default_for(template)
        template.user_instructions = default_def["user_instructions"] if default_def else None
        template.tags = ["default", "tenant"] if default_def else []
        template.behavioral_rules = validate_behavioral_rules(
            default_def.get("behavioral_rules", []) if default_def else []
        )
        template.success_criteria = validate_success_criteria(
            default_def.get("success_criteria", []) if default_def else []
        )

    async def reset_system_instructions(
        self,
        session: AsyncSession,
        template: AgentTemplate,
    ) -> None:
        from giljo_mcp.template_seeder import _get_mcp_bootstrap_section

        template.system_instructions = _get_mcp_bootstrap_section()


    async def add_and_commit_template(
        self,
        session: AsyncSession,
        template: "AgentTemplate",
    ) -> "AgentTemplate":
        template = await self._repo.add_and_flush_template(session, template)
        await session.commit()
        return template

    async def commit_and_refresh_template(
        self,
        session: AsyncSession,
        template: "AgentTemplate",
    ) -> "AgentTemplate":
        await session.commit()
        await session.refresh(template)
        return template
