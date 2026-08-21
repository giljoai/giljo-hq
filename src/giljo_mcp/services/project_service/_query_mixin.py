# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""Project read-path mixin for ProjectService (BE-6042c split).

Holds the project + taxonomy-type lookup and list operations. Composed into
``ProjectService``; references ``self.*`` / ``self._*`` only. Behavior is
byte-identical to the pre-split single-file class.
"""

from typing import Any

from sqlalchemy import select

from giljo_mcp.exceptions import (
    BaseGiljoError,
    ResourceNotFoundError,
    ValidationError,
)
from giljo_mcp.models.projects import TaxonomyType
from giljo_mcp.schemas.service_responses import (
    ProjectDetail,
    ProjectListItem,
)


class QueryMixin:
    """Project read-path methods (lookup + list). Composed into ProjectService."""

    async def get_project_type_by_label(self, label: str, tenant_key: str) -> TaxonomyType | None:
        """Resolve a project type by label or abbreviation (case-insensitive).

        Tries label first, then abbreviation. This allows agents to use either
        "MCP test" (label) or "TST" (abbreviation) when creating projects.

        Args:
            label: Human-readable label (e.g. 'Frontend') or abbreviation (e.g. 'FE', 'TST')
            tenant_key: Tenant key for multi-tenant isolation

        Returns:
            TaxonomyType if found, None otherwise
        """
        # BE-6049c / BE-6054a: TSK + CHT are reserved tags — a project may never be
        # created or retagged as either. Reject case-insensitively before the lookup
        # so both create_project call sites fall through to "Unknown project type".
        from giljo_mcp.services.taxonomy_ops import RESERVED_TYPE_ABBRS

        if (label or "").strip().upper() in RESERVED_TYPE_ABBRS:
            return None

        from giljo_mcp.services.taxonomy_ops import ensure_default_types_seeded

        async with self._get_session(tenant_key) as session:
            # INF-6174d: seed the defaults BEFORE resolving. On a fresh tenant the
            # taxonomy table is empty until something reads _get_valid_project_types
            # (which seeds lazily) — without this, the tenant's FIRST typed
            # create_project resolves against an empty table and fails with an
            # error whose own valid_types list (seeded while rendering the error)
            # contradicts the rejection; the retry then succeeds.
            await ensure_default_types_seeded(session, tenant_key)
            # Try label match first (Handover 0837b)
            match = await self._repo.get_project_type_by_label(session, tenant_key, label)
            if not match:
                # Fall back to abbreviation match (Handover 0841)
                match = await self._repo.get_project_type_by_abbreviation(session, tenant_key, label)

            # BE-6049c (H1) / BE-6054a: the early check only catches the literal
            # abbreviation. Resolving by the reserved row's LABEL ("Task" / "Chat
            # Thread") or a case variant still lands on the reserved row — the repo
            # lookups are case-insensitive. Reject post-resolution so a project can
            # NEVER be created/retagged as TSK or CHT by ANY spelling. IMP-6262:
            # TSK is now fully task-exclusive — converting a task STRIPS the type
            # (the project is born untyped), so no project is ever TSK-typed.
            if match and match.abbreviation in RESERVED_TYPE_ABBRS:
                return None
            return match

    async def get_project(self, project_id: str, tenant_key: str) -> ProjectDetail:
        """
        Get a specific project by ID with associated agent jobs.

        Args:
            project_id: Project UUID
            tenant_key: REQUIRED - Tenant key for multi-tenant isolation (Handover 0424 Phase 0)

        Returns:
            ProjectDetail: Typed project details (including agents)

        Raises:
            ValidationError: If tenant_key is None or empty (security requirement)
            ResourceNotFoundError: When project not found
            BaseGiljoError: When operation fails

        """
        # SECURITY FIX: Require tenant_key (Handover 0424 Phase 0)
        if not tenant_key:
            raise ValidationError("tenant_key is required for security (Handover 0424 Phase 0)")

        try:
            async with self._get_session(tenant_key) as session:
                # Get project with mandatory tenant isolation filter (Handover 0424 Phase 0)
                # Handover 0440a: Eagerly load project_type for taxonomy_alias property
                project = await self._repo.get_by_id_with_type(session, tenant_key, project_id)

                if not project:
                    raise ResourceNotFoundError(
                        message="Project not found or access denied",
                        context={"project_id": project_id, "tenant_key": tenant_key},
                    )

                # Get agent jobs for this project (defense-in-depth: tenant_key on join query)
                agent_pairs = await self._repo.get_agent_pairs_for_project(session, tenant_key, project_id)

                # Convert agents to simple dicts (matching AgentSimple schema)
                # Include messages for JobsTab WebSocket refresh fix (Handover 0358)
                agent_dicts = [
                    {
                        "id": job.job_id,
                        "job_id": job.job_id,
                        "agent_display_name": job.job_type,
                        "agent_name": execution.agent_name,
                        "status": execution.status,
                        "messages_sent_count": execution.messages_sent_count,
                        "messages_waiting_count": execution.messages_waiting_count,
                        "messages_read_count": execution.messages_read_count,
                        "thin_client": True,
                    }
                    for job, execution in agent_pairs
                ]

                self._logger.info(f"Retrieved project {project.name} with {len(agent_dicts)} agents")

                return ProjectDetail(
                    id=str(project.id),
                    alias=project.alias,
                    name=project.name,
                    mission=project.mission,
                    description=project.description,
                    status=project.status,
                    staging_status=project.staging_status,
                    # CE-0028b: frontend uses this to distinguish staging→impl
                    # handoff window from project-complete.
                    implementation_launched_at=(
                        project.implementation_launched_at.isoformat() if project.implementation_launched_at else None
                    ),
                    product_id=project.product_id,
                    tenant_key=project.tenant_key,
                    execution_mode=project.execution_mode,
                    auto_checkin_enabled=project.auto_checkin_enabled,
                    auto_checkin_interval=project.auto_checkin_interval,
                    cancellation_reason=project.cancellation_reason,
                    early_termination=project.early_termination,
                    created_at=project.created_at.isoformat() if project.created_at else None,
                    updated_at=project.updated_at.isoformat() if project.updated_at else None,
                    completed_at=project.completed_at.isoformat() if project.completed_at else None,
                    agents=agent_dicts,
                    agent_count=len(agent_dicts),
                    message_count=0,
                    # Handover 0440a: Taxonomy fields
                    project_type_id=project.project_type_id,
                    project_type=project.project_type,
                    series_number=project.series_number,
                    subseries=project.subseries,
                    taxonomy_alias=project.taxonomy_alias,
                    successor_project_id=project.successor_project_id,
                )

        except (ValueError, ResourceNotFoundError):
            # Re-raise our custom exceptions
            raise
        except Exception as e:  # Broad catch: service boundary, wraps in BaseGiljoError
            self._logger.exception("Failed to get project")
            raise BaseGiljoError(
                message=f"Failed to get project: {e!s}", context={"project_id": project_id, "tenant_key": tenant_key}
            ) from e

    async def list_projects(
        self,
        status: str | list[str] | None = None,
        tenant_key: str | None = None,
        include_cancelled: bool = False,
        product_id: str | None = None,
        hidden: bool | None = None,
        search: str | None = None,
        sort_key: str | None = None,
        sort_dir: str | None = None,
        limit: int | None = None,
        offset: int | None = None,
        after_key: tuple[Any, str] | None = None,
    ) -> list[ProjectListItem]:
        """
        List all projects with optional filters.

        Args:
            status: Filter by project status (optional)
            tenant_key: Tenant key for filtering (uses current tenant if not provided)
            hidden: Per-row UI declutter filter (BE-6078). None=no filter (both),
                False=exclude hidden, True=hidden only. Default None preserves the
                MCP adapter path (which filters hidden in Python).
            search: BE-6076 server-side substring search across name/id/alias.
            after_key: BE-9469 continuation position -- a ``(sort_value, row_id)`` pair on
                whichever axis ``sort_key`` selected. None (the default) emits no keyset
                predicate, so every pre-BE-9469 caller is byte-identical.
            sort_key/sort_dir: BE-6076 server-side sort (whitelisted columns).
            limit/offset: BE-6076 opt-in pagination. All five new args default to
                None so the MCP adapter + ``/deleted`` callers (which never pass
                them) get the pre-BE-6076 behavior byte-for-byte.

        Returns:
            List of project dicts

        Raises:
            ValidationError: When no tenant context is available
            BaseGiljoError: When operation fails

        """
        try:
            # Use provided tenant_key or get from context
            if not tenant_key:
                tenant_key = self.tenant_manager.get_current_tenant()

            if not tenant_key:
                raise ValidationError(message="No tenant context available", context={"operation": "list_projects"})

            async with self.db_manager.get_tenant_session_async(tenant_key) as session:
                projects = await self._repo.list_projects(
                    session,
                    tenant_key,
                    status,
                    include_cancelled,
                    product_id,
                    hidden=hidden,
                    search=search,
                    sort_key=sort_key,
                    sort_dir=sort_dir,
                    limit=limit,
                    offset=offset,
                    after_key=after_key,
                )

                # For list view, we include basic metrics
                # (agent_count and message_count would require additional queries)
                return [
                    ProjectListItem(
                        id=str(project.id),
                        name=project.name,
                        mission=project.mission,
                        description=project.description,
                        status=project.status,
                        staging_status=project.staging_status,
                        implementation_launched_at=(
                            project.implementation_launched_at.isoformat()
                            if project.implementation_launched_at
                            else None
                        ),
                        tenant_key=project.tenant_key,
                        product_id=project.product_id,
                        created_at=project.created_at.isoformat(),
                        updated_at=(
                            project.updated_at.isoformat() if project.updated_at else project.created_at.isoformat()
                        ),
                        completed_at=(project.completed_at.isoformat() if project.completed_at else None),
                        execution_mode=project.execution_mode,  # NULL-state: real mode (None until user picks)
                        # Handover 0440a: Taxonomy fields
                        project_type_id=project.project_type_id,
                        project_type=project.project_type,
                        series_number=project.series_number,
                        subseries=project.subseries,
                        taxonomy_alias=project.taxonomy_alias,
                        hidden=project.hidden is True,
                    )
                    for project in projects
                ]

        except ValidationError:
            # Re-raise our custom exceptions
            raise
        except Exception as e:  # Broad catch: service boundary, wraps in BaseGiljoError
            self._logger.exception("Failed to list projects")
            raise BaseGiljoError(message=f"Failed to list projects: {e!s}", context={"tenant_key": tenant_key}) from e

    async def board_counts(
        self,
        tenant_key: str | None = None,
        product_id: str | None = None,
    ) -> list[tuple]:
        """Board-wide grouped counts for a product (BE-9468). Peer of ``list_projects``.

        Returns the repository's raw ``(status, type_abbreviation, min_created,
        max_created, min_completed, max_completed, count)`` tuples; the MCP adapter owns
        the response shape.

        Deliberately a SERVICE method rather than a repository call made from the
        adapter: ``list_projects_for_mcp`` reaches every other read through this layer
        (``self.list_projects``), so a read that opened its own session and touched
        ``self._repo`` directly would be the only one bypassing it -- and would make the
        adapter untestable without a live database, which the existing filtering suite
        depends on not being the case.

        Takes NO caller filters by design. See ``ProjectRepository.board_counts``.
        """
        if not tenant_key:
            tenant_key = self.tenant_manager.get_current_tenant()
        if not tenant_key:
            raise ValidationError(message="No tenant context available", context={"operation": "board_counts"})

        async with self.db_manager.get_tenant_session_async(tenant_key) as session:
            return await self._repo.board_counts(session, tenant_key, product_id=product_id)

    async def count_projects(
        self,
        status: str | list[str] | None = None,
        tenant_key: str | None = None,
        include_cancelled: bool = False,
        product_id: str | None = None,
        hidden: bool | None = None,
        search: str | None = None,
    ) -> int:
        """Count projects matching the same filters as ``list_projects`` (BE-6076).

        Backs the ``X-Total-Count`` header for the dashboard list's v-data-table
        ``:items-length`` when paginating. Applies the identical WHERE clause as
        the paginated page (shared repo helper) so the total always reflects the
        FILTERED set, never the unfiltered table size.

        Raises:
            ValidationError: When no tenant context is available
            BaseGiljoError: When operation fails
        """
        try:
            if not tenant_key:
                tenant_key = self.tenant_manager.get_current_tenant()

            if not tenant_key:
                raise ValidationError(message="No tenant context available", context={"operation": "count_projects"})

            async with self.db_manager.get_tenant_session_async(tenant_key) as session:
                return await self._repo.count_projects(
                    session,
                    tenant_key,
                    status,
                    include_cancelled,
                    product_id,
                    hidden=hidden,
                    search=search,
                )

        except ValidationError:
            raise
        except Exception as e:  # Broad catch: service boundary, wraps in BaseGiljoError
            self._logger.exception("Failed to count projects")
            raise BaseGiljoError(message=f"Failed to count projects: {e!s}", context={"tenant_key": tenant_key}) from e

    async def get_project_type_by_id(self, type_id: str, tenant_key: str) -> TaxonomyType | None:
        """Resolve a project type by its primary-key id (tenant-scoped).

        FE-5073 / BE-5122 follow-up: the REST create endpoint receives
        project_type_id (UUID) directly, but needs the abbreviation to decide
        whether to invoke the CTX bootstrap render path. This is the read-only
        lookup that bridges that gap.
        """
        async with self._get_session(tenant_key) as session:
            result = await session.execute(
                select(TaxonomyType).where(
                    TaxonomyType.tenant_key == tenant_key,
                    TaxonomyType.id == type_id,
                )
            )
            return result.scalar_one_or_none()
