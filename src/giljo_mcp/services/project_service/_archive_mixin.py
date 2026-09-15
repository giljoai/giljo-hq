# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import logging
from typing import Any

from giljo_mcp.domain.project_status import LIFECYCLE_FINISHED_STATUSES, ProjectStatus
from giljo_mcp.exceptions import CloseoutRequiredError
from giljo_mcp.schemas.service_responses import ProjectArchiveResult
from giljo_mcp.services.project_closeout_readiness import shape_readiness_blockers
from giljo_mcp.utils.log_sanitizer import sanitize


logger = logging.getLogger(__name__)


class ArchiveMixin:

    async def archive_project(
        self,
        project_id: str,
        tenant_key: str | None = None,
        websocket_manager: Any | None = None,
        force: bool = False,
    ) -> ProjectArchiveResult:
        resolved_tenant = tenant_key or self.tenant_manager.get_current_tenant()
        ws = websocket_manager or self._websocket_manager

        proj = await self.get_project(project_id=project_id, tenant_key=resolved_tenant)

        blockers = await self._missing_closeout_blockers(project_id, resolved_tenant)
        if blockers is not None:
            if not force:
                raise CloseoutRequiredError(
                    message=(
                        "Cannot archive: no closeout entry exists for this project. Resolve the "
                        "blockers (drain unread messages, then complete_job, then "
                        "write_project_closeout), or pass force=True to abandon deliberately."
                    ),
                    blockers=blockers,
                    context={"project_id": project_id},
                )
            logger.warning(
                "Force-archived project %s without a closeout entry: %d blocker(s) unresolved: %s",
                sanitize(str(project_id)),
                len(blockers),
                sanitize(str(blockers)),
            )

        skip_deactivate = LIFECYCLE_FINISHED_STATUSES | {ProjectStatus.INACTIVE}
        deactivated = proj.status not in skip_deactivate
        if deactivated:
            await self.deactivate_project(project_id=project_id, tenant_key=resolved_tenant)

        target_status = ProjectStatus.TERMINATED if proj.early_termination else ProjectStatus.COMPLETED

        updated = await self.update_project(
            project_id=project_id,
            updates={"status": target_status},
            websocket_manager=ws,
        )

        closed_names: list[str] = []
        try:
            closed_names = await self.closeout.close_completed_agents_with_commit(
                project_id=project_id,
                tenant_key=resolved_tenant,
            )
            if closed_names:
                logger.info("Closed %d agent(s) on archive: %s", len(closed_names), ", ".join(closed_names))
        except OSError:
            logger.warning("Failed to close agents during project archive")

        return ProjectArchiveResult(
            project=updated,
            deactivated=deactivated,
            closed_agents=closed_names or [],
        )

    async def _missing_closeout_blockers(self, project_id: str, tenant_key: str) -> list[dict[str, Any]] | None:
        async with self._get_session(tenant_key) as session:
            project = await self._repo.get_by_id(session, tenant_key, project_id)
            if project is not None and project.closeout_executed_at is not None:
                return None

            report = await self.closeout.evaluate_closeout_readiness(session, project_id, tenant_key)
            return shape_readiness_blockers(report)
