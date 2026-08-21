# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
ProjectService - Dedicated service for project domain logic

This service extracts all project-related operations from ToolAccessor
as part of Phase 1 of the god object refactoring (Handover 0121).

Responsibilities:
- CRUD operations for projects
- Project lifecycle management (complete, cancel, restore)
- Project state and status tracking
- Project metrics and statistics

Design Principles:
- Single Responsibility: Only project domain logic
- Dependency Injection: Accepts DatabaseManager and TenantManager
- Async/Await: Full SQLAlchemy 2.0 async support
- Error Handling: Consistent exception handling and logging
- Testability: Can be unit tested independently

BE-6042c: this god-class was mechanically split into domain mixins under the
``project_service/`` subpackage. The composed ``ProjectService`` below preserves
the load-bearing public import ``from giljo_mcp.services.project_service import
ProjectService`` (~30 importers across api/ and tests/). Shared construction
(``__init__`` + session/broadcast/helper methods + the ``_VALID_*`` projection
constants) stays here on the base; each concern lives in its own mixin module.
The status-constant re-export surface (``IMMUTABLE_PROJECT_STATUSES`` /
``LIFECYCLE_FINISHED_STATUSES`` / ``VALID_PROJECT_STATUSES``) and
``ALWAYS_MUTABLE_FIELDS`` are preserved via ``__all__``. Behavior is unchanged.
"""

import logging
from datetime import UTC, datetime
from typing import Any, ClassVar

from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.database import DatabaseManager

# BE-5039 Phase 2b: project status constants are re-exported below from
# giljo_mcp.domain.project_status -- the Single Source of Truth backed by
# the Postgres ENUM ``project_status`` (see migration ce_0008). Legacy
# importers keep resolving without churn via this module; new code
# should import directly from giljo_mcp.domain.project_status.
from giljo_mcp.domain.project_status import (
    IMMUTABLE_PROJECT_STATUSES,
    LIFECYCLE_FINISHED_STATUSES,
    VALID_PROJECT_STATUSES,
)
from giljo_mcp.domain.project_status import (
    VALID_UPDATE_STATUSES as _DOMAIN_VALID_UPDATE_STATUSES,
)
from giljo_mcp.repositories.project_repository import ProjectRepository
from giljo_mcp.services._session_helpers import optional_tenant_session
from giljo_mcp.services.project_service._archive_mixin import ArchiveMixin
from giljo_mcp.services.project_service._mcp_adapter_mixin import McpAdapterMixin
from giljo_mcp.services.project_service._mcp_adapter_query_mixin import McpAdapterQueryMixin
from giljo_mcp.services.project_service._mutation_mixin import (
    ALWAYS_MUTABLE_FIELDS,
    MutationMixin,
)
from giljo_mcp.services.project_service._query_mixin import QueryMixin
from giljo_mcp.tenant import TenantManager


logger = logging.getLogger(__name__)

__all__ = [
    "ALWAYS_MUTABLE_FIELDS",
    "IMMUTABLE_PROJECT_STATUSES",
    "LIFECYCLE_FINISHED_STATUSES",
    "VALID_PROJECT_STATUSES",
    "ProjectService",
]


class ProjectService(QueryMixin, MutationMixin, ArchiveMixin, McpAdapterMixin, McpAdapterQueryMixin):
    """
    Service for managing project lifecycle and operations.

    This service handles all project-related operations including:
    - Creating, reading, updating projects
    - Project status transitions (complete, cancel, restore)
    - Project metrics and status reporting
    - Mission updates with WebSocket integration

    Thread Safety: Each instance is session-scoped. Do not share across requests.
    """

    # BE-5039 Phase 2b: legacy filter sets now derive from the canonical
    # ProjectStatus enum metadata. ``_VALID_STATUS_FILTERS`` keeps the
    # extra ``"all"`` sentinel that means "do not filter".
    # NOTE (seq 161): the legacy ``status_filter`` kwarg path uses this set,
    # which excludes ``terminated`` and ``deleted`` (lifecycle-only statuses).
    # Use ``status`` (read-side) with ``_VALID_FILTER_STATUSES`` to query those.
    _VALID_STATUS_FILTERS = frozenset({s.value for s in _DOMAIN_VALID_UPDATE_STATUSES} | {"all"})
    # Writes via update_project remain limited to user-mutable statuses
    # (``is_user_mutable_via_mcp=True`` in PROJECT_STATUS_META).
    # "terminated" and "deleted" are set only by dedicated lifecycle endpoints
    # (archive_project / soft-delete) -- never by direct status writes.
    _VALID_UPDATE_STATUSES = frozenset(s.value for s in _DOMAIN_VALID_UPDATE_STATUSES)
    # Read-side filter accepts the full enum so agents can query
    # terminated/deleted projects explicitly. Mirrors module-level
    # VALID_PROJECT_STATUSES.
    _VALID_FILTER_STATUSES = frozenset(s.value for s in VALID_PROJECT_STATUSES)
    _VALID_DEPTH_LEVELS = frozenset({0, 1, 2, 3})
    # BE-5042: agent-facing mode names map to (depth, headlines, memory_limit).
    # ``mode`` wins over numeric ``depth`` when both are passed.
    _MODE_TO_PROJECTION: ClassVar[dict[str, tuple[int, bool, int | None]]] = {
        "triage": (0, False, None),
        "planning": (1, False, None),
        "audit": (2, True, 5),
        "forensic": (3, False, None),
    }
    _MEMORY_LIMIT_CAP = 50

    def __init__(
        self,
        db_manager: DatabaseManager,
        tenant_manager: TenantManager,
        test_session: AsyncSession | None = None,
        websocket_manager: Any | None = None,
    ):
        """
        Initialize ProjectService with database and tenant management.

        Args:
            db_manager: Database manager for async database operations
            tenant_manager: Tenant manager for multi-tenancy support (provides global context access)
            test_session: Optional AsyncSession for tests to share the same transaction

        Note:
            This service uses TenantManager.get_current_tenant() to retrieve tenant context.
            The tenant context is set by the get_tenant_key() dependency in the auth flow.
        """
        self.db_manager = db_manager
        self.tenant_manager = tenant_manager
        self._test_session = test_session
        self._websocket_manager = websocket_manager
        self._logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")
        self._repo = ProjectRepository()

        # Facade sub-services (Handover 0769: ProjectService split, 0950i: launch extraction,
        #                      0950n: summary extraction)
        from giljo_mcp.services.project_closeout_service import ProjectCloseoutService
        from giljo_mcp.services.project_deletion_service import ProjectDeletionService
        from giljo_mcp.services.project_launch_service import ProjectLaunchService
        from giljo_mcp.services.project_lifecycle_service import ProjectLifecycleService
        from giljo_mcp.services.project_summary_service import ProjectSummaryService

        # Sprint 002f: Public sub-services for direct caller access (collapsed pass-throughs)
        self.lifecycle = ProjectLifecycleService(db_manager, tenant_manager, test_session, websocket_manager)
        self.closeout = ProjectCloseoutService(db_manager, tenant_manager, test_session, websocket_manager)
        self.deletion = ProjectDeletionService(db_manager, tenant_manager, test_session, websocket_manager)
        self.launch = ProjectLaunchService(db_manager, tenant_manager, test_session, websocket_manager)
        self.summary = ProjectSummaryService(db_manager, tenant_manager, test_session, websocket_manager)

        from giljo_mcp.services.project_query_service import ProjectQueryService

        self.query = ProjectQueryService(db_manager, tenant_manager, test_session)

    def _get_session(self, tenant_key: str | None = None):
        """Yield a tenant-scoped DB session, honoring an injected test session (shared helper, BE-8000d)."""
        return optional_tenant_session(self.db_manager, tenant_key, self._test_session)

    async def _broadcast_mission_update(self, project_id: str, mission: str, tenant_key: str) -> None:
        """
        Broadcast mission update via WebSocketManager (in-process).

        Args:
            project_id: Project UUID
            mission: Updated mission text
            tenant_key: Tenant key for routing
        """
        self._logger.info(f"[WEBSOCKET DEBUG] About to broadcast mission_updated for project {project_id}")

        if not self._websocket_manager:
            self._logger.debug("[WEBSOCKET] No WebSocket manager available for project:mission_updated")
            return

        try:
            await self._websocket_manager.broadcast_to_tenant(
                tenant_key=tenant_key,
                event_type="project:mission_updated",
                data={
                    "project_id": project_id,
                    "mission": mission,
                    "token_estimate": len(mission) // 4,
                    "user_config_applied": False,
                    "generated_by": "orchestrator",
                    "timestamp": datetime.now(UTC).isoformat(),
                },
            )

        except Exception as ws_error:  # Broad catch: WebSocket resilience, non-critical broadcast
            self._logger.error(
                f"[WEBSOCKET ERROR] Failed to broadcast project:mission_updated: {ws_error}",
                exc_info=True,
            )

    @staticmethod
    def _extract_git_commits(memory_entries: list[dict]) -> list[dict]:
        """Extract git commits from 360 memory entries."""
        commits = []
        for entry in memory_entries:
            entry_commits = entry.get("git_commits", [])
            if isinstance(entry_commits, list):
                commits.extend(entry_commits)
        return commits

    async def _get_valid_project_types(self, tenant_key: str) -> list[dict[str, Any]]:
        """Return available project types for a tenant.

        BE-6049c / BE-6054a: the reserved ``TSK`` (task) and ``CHT`` (chat-thread)
        tags are filtered out — neither is a valid PROJECT type and must not
        appear in project-facing valid_types.
        """
        from giljo_mcp.services.taxonomy_ops import (
            RESERVED_TYPE_ABBRS,
            ensure_default_types_seeded,
            list_taxonomy_types,
        )

        async with self.db_manager.get_session_async() as session:
            await ensure_default_types_seeded(session, tenant_key)
            types = await list_taxonomy_types(session, tenant_key)
            return [
                {"abbreviation": t.abbreviation, "label": t.label, "color": t.color}
                for t in types
                if t.abbreviation not in RESERVED_TYPE_ABBRS
            ]
