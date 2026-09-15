# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import logging
from datetime import UTC, datetime
from typing import Any, ClassVar

from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.database import DatabaseManager

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

    _VALID_STATUS_FILTERS = frozenset({s.value for s in _DOMAIN_VALID_UPDATE_STATUSES} | {"all"})
    _VALID_UPDATE_STATUSES = frozenset(s.value for s in _DOMAIN_VALID_UPDATE_STATUSES)
    _VALID_FILTER_STATUSES = frozenset(s.value for s in VALID_PROJECT_STATUSES)
    _VALID_DEPTH_LEVELS = frozenset({0, 1, 2, 3})
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
        self.db_manager = db_manager
        self.tenant_manager = tenant_manager
        self._test_session = test_session
        self._websocket_manager = websocket_manager
        self._logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")
        self._repo = ProjectRepository()

        from giljo_mcp.services.project_closeout_service import ProjectCloseoutService
        from giljo_mcp.services.project_deletion_service import ProjectDeletionService
        from giljo_mcp.services.project_launch_service import ProjectLaunchService
        from giljo_mcp.services.project_lifecycle_service import ProjectLifecycleService
        from giljo_mcp.services.project_summary_service import ProjectSummaryService

        self.lifecycle = ProjectLifecycleService(db_manager, tenant_manager, test_session, websocket_manager)
        self.closeout = ProjectCloseoutService(db_manager, tenant_manager, test_session, websocket_manager)
        self.deletion = ProjectDeletionService(db_manager, tenant_manager, test_session, websocket_manager)
        self.launch = ProjectLaunchService(db_manager, tenant_manager, test_session, websocket_manager)
        self.summary = ProjectSummaryService(db_manager, tenant_manager, test_session, websocket_manager)

        from giljo_mcp.services.project_query_service import ProjectQueryService

        self.query = ProjectQueryService(db_manager, tenant_manager, test_session)

    def _get_session(self, tenant_key: str | None = None):
        return optional_tenant_session(self.db_manager, tenant_key, self._test_session)

    async def _broadcast_mission_update(self, project_id: str, mission: str, tenant_key: str) -> None:
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

        except Exception as ws_error:
            self._logger.error(
                f"[WEBSOCKET ERROR] Failed to broadcast project:mission_updated: {ws_error}",
                exc_info=True,
            )

    @staticmethod
    def _extract_git_commits(memory_entries: list[dict]) -> list[dict]:
        commits = []
        for entry in memory_entries:
            entry_commits = entry.get("git_commits", [])
            if isinstance(entry_commits, list):
                commits.extend(entry_commits)
        return commits

    async def _get_valid_project_types(self, tenant_key: str) -> list[dict[str, Any]]:
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
