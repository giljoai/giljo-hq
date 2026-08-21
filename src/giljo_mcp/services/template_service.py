# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
TemplateService - Dedicated service for agent template management

This service extracts all template-related operations from ToolAccessor
as part of Phase 2 of the god object refactoring (Handover 0123).

Responsibilities:
- CRUD operations for agent templates
- Template retrieval and listing
- Template variable management
- Template tenant isolation

Design Principles:
- Single Responsibility: Only template domain logic
- Dependency Injection: Accepts DatabaseManager and TenantManager
- Async/Await: Full SQLAlchemy 2.0 async support
- Error Handling: Consistent exception handling and logging
- Testability: Can be unit tested independently

Updated Handover 0731: Migrated from dict returns to typed
TemplateGetResult (get_template).
Updated BE-8000j: the REST create/update endpoints now route their writes through
this owning service via create_template_from_request / update_template_from_request
(full materialization + WebSocket-payload fields live here, not in the endpoint).
Removed the never-production-called create_template / update_template / list_templates
/ hard_delete_template methods that the endpoint had drifted away from.
"""

import logging
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import func

from giljo_mcp.database import DatabaseManager, tenant_session_context
from giljo_mcp.exceptions import (
    BaseGiljoError,
    TemplateNotFoundError,
    ValidationError,
)

# Model imports: Use domain-specific imports (Post-0128a)
from giljo_mcp.models.templates import AgentTemplate, TemplateArchive
from giljo_mcp.repositories.product_agent_selection import record_product_export
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

# Agent limit constant (Handover 0103; BE-9211 raised 7->15). Single source of
# truth — the REST layer imports it: 15 user-managed + 1 orchestrator = 16 slots.
USER_MANAGED_AGENT_LIMIT = 15

# Field allowlist for template updates — only these fields may be set via the
# update path. Replaces a bare hasattr() gate that would have allowed setting any
# model attribute (id, tenant_key, created_at, ...). Moved from the REST endpoint
# into the owning service so the update write path lives in one place (BE-8000j).
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
        "tools",
        "description",
        "version",
        "is_active",
        "is_default",
        "tags",
        "meta_data",
        "user_managed_export",
    }
)


class TemplateService:
    """
    Service for managing agent templates.

    This service handles all template-related operations including:
    - Creating, reading, updating templates
    - Listing templates by tenant
    - Template variable management
    - Multi-tenant template isolation

    Thread Safety: Each instance is session-scoped. Do not share across requests.
    """

    def __init__(self, db_manager: DatabaseManager, tenant_manager: TenantManager, session: AsyncSession | None = None):
        """
        Initialize TemplateService with database and tenant management.

        Args:
            db_manager: Database manager for async database operations
            tenant_manager: Tenant manager for multi-tenancy support
            session: Optional AsyncSession for test transaction isolation
        """
        self.db_manager = db_manager
        self.tenant_manager = tenant_manager
        self._session = session
        self._repo = TemplateRepository()
        self._logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")

    def _get_session(self, tenant_key: str | None = None):
        """Yield a tenant-scoped DB session, honoring an injected test session (shared helper, BE-8000d)."""
        return optional_tenant_session(
            self.db_manager, tenant_key or self.tenant_manager.get_current_tenant(), self._session
        )

    async def get_template(
        self, template_id: str | None = None, template_name: str | None = None, tenant_key: str | None = None
    ) -> TemplateGetResult:
        """
        Get a specific template by ID or name.

        Args:
            template_id: Template UUID (optional if template_name provided)
            template_name: Template name (optional if template_id provided)
            tenant_key: Tenant key for filtering (uses current tenant if not provided)

        Returns:
            TemplateGetResult with template detail.

        Raises:
            ValidationError: When neither template_id nor template_name provided, or no tenant context
            TemplateNotFoundError: When template not found
            BaseGiljoError: When operation fails

        Example:
            >>> result = await service.get_template(template_name="orchestrator")
            >>> print(result.template.content)
        """
        try:
            if not template_id and not template_name:
                raise ValidationError(
                    message="Either template_id or template_name must be provided",
                    context={"operation": "get_template"},
                )

            # Use provided tenant_key or get from context
            if not tenant_key:
                tenant_key = self.tenant_manager.get_current_tenant()

            if not tenant_key:
                raise ValidationError(message="No tenant context available", context={"operation": "get_template"})

            async with self._get_session(tenant_key) as session:
                # Retrieve template by ID or name
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
            # Re-raise our custom exceptions
            raise
        except Exception as e:  # Broad catch: service boundary, wraps in BaseGiljoError
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
        """Create a template from a validated create request (owning-service write path).

        Delegates to :func:`giljo_mcp.services.template_write_paths.create_from_request`
        (BE-9394 extraction). This stays the owning-service entry point every caller and
        test uses; the full contract lives on that function.
        """
        return await template_write_paths.create_from_request(self, session, data, tenant_key, created_by)

    async def update_template_from_request(
        self,
        session: AsyncSession,
        template_id: str,
        updates,
        tenant_key: str,
        username: str | None = None,
    ) -> tuple[AgentTemplate, list[str]]:
        """Update a template from a validated update request (owning-service write path).

        Delegates to :func:`giljo_mcp.services.template_write_paths.update_from_request`
        (BE-9394 extraction). This stays the owning-service entry point every caller and
        test uses; the full contract lives on that function.
        """
        return await template_write_paths.update_from_request(self, session, template_id, updates, tenant_key, username)

    # ============================================================================
    # Validation Methods
    # ============================================================================

    @staticmethod
    def _is_system_managed_role(role: str | None) -> bool:
        """
        Check if a role is system-managed and cannot be toggled by users.

        Args:
            role: Role name to check

        Returns:
            True if role is system-managed, False otherwise

        Example:
            >>> TemplateService._is_system_managed_role("orchestrator")
            True
            >>> TemplateService._is_system_managed_role("reviewer")
            False
        """
        return bool(role and role in SYSTEM_MANAGED_ROLES)

    async def validate_active_agent_limit(
        self,
        session: AsyncSession,
        tenant_key: str,
        template_id: str,
        new_is_active: bool,
        role: str | None = None,
    ) -> tuple[bool, str]:
        """
        Validate the active-slot limit before toggling (Handover 0103; BE-9211).

        Context budget constraint: USER_MANAGED_AGENT_LIMIT (15) user roles + 1 reserved orchestrator = 16 total slots.

        Args:
            session: Database session (for transaction context)
            tenant_key: Tenant key for isolation
            template_id: Template being toggled
            new_is_active: Desired active state
            role: Role of the template being toggled (optional, will be fetched if not provided)

        Returns:
            (is_valid, error_message) tuple
            - (True, "") if validation passes
            - (False, error_msg) if validation fails

        Example:
            >>> async with db_manager.get_session_async() as session:
            ...     valid, msg = await service.validate_active_agent_limit(
            ...         session, "tenant-1", "tpl-123", True, "orchestrator"
            ...     )
            ...     if not valid:
            ...         raise HTTPException(409, msg)
        """
        # System-managed roles are not user-toggleable
        if self._is_system_managed_role(role):
            return False, "System-managed roles cannot be toggled"

        # If deactivating, always allow
        if not new_is_active:
            return True, ""

        # Get current template to fetch its role if not provided
        if role is None:
            role = await self._repo.get_template_role(session, template_id)
            if not role:
                return False, "Template not found"

        # Count currently active distinct roles (excluding the one being toggled)
        active_roles = await self._repo.get_active_distinct_roles(session, tenant_key, template_id)

        # If this role is already active elsewhere, allow toggle
        if role in active_roles:
            return True, ""

        # At the user-managed cap, block a new distinct role (orchestrator reserved).
        if len(active_roles) >= USER_MANAGED_AGENT_LIMIT:
            return (
                False,
                (
                    f"Maximum {USER_MANAGED_AGENT_LIMIT} active agent roles allowed "
                    f"(currently {len(active_roles)}). Deactivate another role first."
                ),
            )

        return True, ""

    # ============================================================================
    # Template Retrieval Methods (Phase 2 - Handover 1011)
    # ============================================================================

    async def get_template_by_id(
        self,
        session: AsyncSession,
        template_id: str,
        tenant_key: str,
    ) -> AgentTemplate | None:
        """
        Get a template by ID with tenant isolation.

        Args:
            session: Database session
            template_id: Template UUID
            tenant_key: Tenant key for isolation (REQUIRED)

        Returns:
            AgentTemplate ORM object or None if not found

        Example:
            >>> template = await service.get_template_by_id(session, "abc-123", "tenant-1")
            >>> if template:
            ...     print(template.name)
        """
        with tenant_session_context(session, tenant_key):
            return await self._repo.get_by_id(session, template_id, tenant_key)

    async def list_templates_with_filters(
        self,
        session: AsyncSession,
        tenant_key: str,
        role: str | None = None,
        is_active: bool | None = None,
    ) -> list[AgentTemplate]:
        """
        List templates for a tenant with optional filters.

        Args:
            session: Database session
            tenant_key: Tenant key for isolation (REQUIRED)
            role: Filter by role (optional)
            is_active: Filter by active status (optional)

        Returns:
            List of AgentTemplate ORM objects
        """
        with tenant_session_context(session, tenant_key):
            return await self._repo.list_with_filters(session, tenant_key, role, is_active)

    async def check_template_name_exists(
        self,
        session: AsyncSession,
        tenant_key: str,
        name: str,
    ) -> bool:
        """
        Check if a template name already exists for a tenant.

        Args:
            session: Database session
            tenant_key: Tenant key for isolation (REQUIRED)
            name: Template name to check

        Returns:
            True if name exists, False otherwise
        """
        with tenant_session_context(session, tenant_key):
            return await self._repo.check_name_exists(session, tenant_key, name)

    async def get_default_templates_by_role(
        self,
        session: AsyncSession,
        tenant_key: str,
        role: str,
    ) -> list[AgentTemplate]:
        """
        Get all default templates for a specific role.

        Args:
            session: Database session
            tenant_key: Tenant key for isolation (REQUIRED)
            role: Role to filter by

        Returns:
            List of default AgentTemplate ORM objects for the role

        Example:
            >>> defaults = await service.get_default_templates_by_role(
            ...     session, "tenant-1", "orchestrator"
            ... )
        """
        with tenant_session_context(session, tenant_key):
            return await self._repo.get_defaults_by_role(session, tenant_key, role)

    async def get_active_user_managed_count(
        self,
        session: AsyncSession,
        tenant_key: str,
    ) -> int:
        """
        Get count of active user-managed templates for a tenant.

        Args:
            session: Database session
            tenant_key: Tenant key for isolation (REQUIRED)

        Returns:
            Count of active user-managed templates
        """
        with tenant_session_context(session, tenant_key):
            return await self._repo.count_active_user_managed(session, tenant_key)

    # ============================================================================
    # Template Deletion Methods (Phase 2 - Handover 1011)
    # ============================================================================

    async def purge_expired_deleted_templates(self, tenant_key: str | None = None) -> int:
        """Hard-delete trashed templates past the recovery window (TSK-6132 reaper).

        Delegates to :func:`giljo_mcp.services.template_lifecycle.purge_expired_deleted_templates`
        (BE-9394 extraction). Full contract lives on that function.
        """
        return await template_lifecycle.purge_expired_deleted_templates(self, tenant_key)

    async def delete_template(
        self,
        session: AsyncSession,
        template_id: str,
        tenant_key: str,
    ) -> bool:
        """Soft-delete (trash) a template by stamping deleted_at.

        Delegates to :func:`giljo_mcp.services.template_lifecycle.delete_template`
        (BE-9394 extraction). Full contract lives on that function.
        """
        return await template_lifecycle.delete_template(self, session, template_id, tenant_key)

    async def restore_template(
        self,
        template_id: str,
        tenant_key: str,
    ) -> AgentTemplate:
        """Restore a soft-deleted (trashed) template within the 30-day window.

        Delegates to :func:`giljo_mcp.services.template_lifecycle.restore_template`
        (BE-9394 extraction). Full contract lives on that function.
        """
        return await template_lifecycle.restore_template(self, template_id, tenant_key)

    async def list_deleted_templates(
        self,
        tenant_key: str | None = None,
    ) -> list[AgentTemplate]:
        """List soft-deleted (trashed) templates for the recover dialog.

        Delegates to :func:`giljo_mcp.services.template_lifecycle.list_deleted_templates`
        (BE-9394 extraction). Full contract lives on that function.
        """
        return await template_lifecycle.list_deleted_templates(self, tenant_key)

    # ============================================================================
    # Template History Methods (Phase 2 - Handover 1011)
    # ============================================================================

    async def get_template_history(
        self,
        session: AsyncSession,
        template_id: str,
        tenant_key: str,
    ) -> list[TemplateArchive]:
        """
        Get template version history ordered by archived_at descending.

        Args:
            session: Database session
            template_id: Template UUID
            tenant_key: Tenant key for isolation (REQUIRED)

        Returns:
            List of TemplateArchive ORM objects (most recent first)

        Example:
            >>> history = await service.get_template_history(session, "tpl-123", "tenant-1")
            >>> for archive in history:
            ...     print(f"{archive.version} - {archive.archive_reason}")
        """
        with tenant_session_context(session, tenant_key):
            return await self._repo.get_template_history(session, template_id, tenant_key)

    async def get_archive_by_id(
        self,
        session: AsyncSession,
        archive_id: str,
        template_id: str,
        tenant_key: str,
    ) -> TemplateArchive | None:
        """
        Get a specific archive entry with tenant isolation.

        Args:
            session: Database session
            archive_id: Archive entry UUID
            template_id: Template UUID (for additional validation)
            tenant_key: Tenant key for isolation (REQUIRED)

        Returns:
            TemplateArchive ORM object or None if not found

        Example:
            >>> archive = await service.get_archive_by_id(
            ...     session, "arc-456", "tpl-123", "tenant-1"
            ... )
        """
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
        """
        Create an archive entry from a template's current state.

        Args:
            session: Database session
            template: AgentTemplate ORM object to archive
            archive_reason: Reason for archiving
            archive_type: Type of archive (e.g., "auto", "manual")
            archived_by: Username of person triggering archive

        Returns:
            Created TemplateArchive ORM object

        Example:
            >>> archive = await service.create_template_archive(
            ...     session, template, "Update user instructions", "auto", "alice"
            ... )
        """
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
        """
        Restore a template's content from an archive entry.

        Args:
            session: Database session
            template: AgentTemplate ORM object to restore into
            archive: TemplateArchive ORM object to restore from
            restored_by: Username performing the restore (audit trail)

        Example:
            >>> await service.restore_template_from_archive(session, template, archive, "admin")
        """
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
        """
        Reset a template's editable fields to default values.

        Default-named templates restore the shipped role prose; custom names stay blank.
        Args:
            session: Database session
            template: AgentTemplate ORM object to reset
        """
        from giljo_mcp.template_seeder import _get_default_templates_v103

        default_def = {t["name"]: t for t in _get_default_templates_v103()}.get(template.name)
        template.user_instructions = default_def["user_instructions"] if default_def else None
        template.tags = ["default", "tenant"] if default_def else []
        template.behavioral_rules = validate_behavioral_rules([])
        template.success_criteria = validate_success_criteria([])

    async def reset_system_instructions(
        self,
        session: AsyncSession,
        template: AgentTemplate,
    ) -> None:
        """
        Reset system instructions to canonical MCP bootstrap (Handover 0814).

        Uses _get_mcp_bootstrap_section() as the single source of truth,
        replacing the stale hardcoded fallback.

        Args:
            session: Database session
            template: AgentTemplate ORM object to reset
        """
        from giljo_mcp.template_seeder import _get_mcp_bootstrap_section

        template.system_instructions = _get_mcp_bootstrap_section()

    # ============================================================================
    # Export Tracking (Sprint 003b)
    # ============================================================================

    async def mark_templates_exported(
        self,
        template_ids: list[str],
        tenant_key: str,
        product_id: str | None = None,
    ) -> int:
        """
        Update last_exported_at timestamp for a set of templates.

        Used by list_agent_templates MCP tool after exporting templates
        to detect staleness on next export.

        Args:
            template_ids: List of template UUIDs to mark as exported.
            tenant_key: Tenant isolation key (REQUIRED).
            product_id: BE-9385e — the product that performed this export. When
                given, the same timestamp is recorded on that product's junction
                rows in this transaction, so the export does not read as fresh in
                every other product. None keeps the tenant-wide write alone.

        Returns:
            Number of templates updated.

        Example:
            >>> updated = await service.mark_templates_exported(
            ...     ["tpl-1", "tpl-2"], "tenant-1"
            ... )
        """
        if not template_ids:
            return 0

        export_timestamp = datetime.now(UTC)

        async with self._get_session(tenant_key) as session:
            updated_count = await self._repo.update_exported_timestamps(
                session, template_ids, tenant_key, export_timestamp
            )
            await record_product_export(session, product_id, tenant_key, template_ids, export_timestamp)
            self._logger.info(
                "Updated last_exported_at for %d template(s) via MCP export",
                updated_count,
            )
            return updated_count

    # ============================================================================
    # Session Commit Helpers (write discipline — no endpoint commits)
    # ============================================================================

    async def add_and_commit_template(
        self,
        session: AsyncSession,
        template: "AgentTemplate",
    ) -> "AgentTemplate":
        """
        Add a new template to the session, commit, and refresh.

        Used by endpoints that construct the AgentTemplate entity themselves
        (e.g., create_template with complex validation logic).

        Args:
            session: Database session
            template: Fully constructed AgentTemplate ORM object

        Returns:
            The refreshed AgentTemplate after commit.
        """
        # Repo flushes; this service helper owns the commit (the endpoint delegates
        # its write here so it never commits directly -- write-discipline pattern).
        template = await self._repo.add_and_flush_template(session, template)
        await session.commit()
        return template

    async def commit_and_refresh_template(
        self,
        session: AsyncSession,
        template: "AgentTemplate",
    ) -> "AgentTemplate":
        """
        Commit pending changes and refresh the template.

        Used after chained service operations (archive + restore, archive + reset)
        that mutate the template in-session but do not commit.

        Args:
            session: Database session
            template: AgentTemplate ORM object with pending changes

        Returns:
            The refreshed AgentTemplate after commit.
        """
        # Repo flushes; this service helper owns the commit (the endpoint delegates
        # its write here so it never commits directly -- write-discipline pattern).
        await session.commit()
        await session.refresh(template)
        return template
