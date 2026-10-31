# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import logging
from datetime import datetime
from typing import Any

from giljo_mcp.domain.project_status import LIFECYCLE_FINISHED_STATUSES, ProjectStatus
from giljo_mcp.exceptions import BaseGiljoError, CloseoutRequiredError, ProjectStateError, ResourceNotFoundError
from giljo_mcp.repositories.project_chain_membership import chain_member_ids
from giljo_mcp.schemas.service_responses import ProjectArchiveResult
from giljo_mcp.services.bulk_close import (
    REASON_IN_CHAIN,
    REASON_NOT_FOUND,
    BulkCloseOutcome,
    bulk_event_data,
    unique_ids,
)
from giljo_mcp.services.project_closeout_readiness import shape_readiness_blockers
from giljo_mcp.services.sequence_run_service import active_chain_run
from giljo_mcp.utils.log_sanitizer import sanitize


logger = logging.getLogger(__name__)

REVIEWABLE_STATUSES = frozenset({ProjectStatus.COMPLETED, ProjectStatus.TERMINATED})


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

        closed_names = await self.closeout.close_completed_agents_with_commit(
            project_id=project_id,
            tenant_key=resolved_tenant,
        )
        if closed_names:
            logger.info("Closed %d agent(s) on archive: %s", len(closed_names), ", ".join(closed_names))

        return ProjectArchiveResult(
            project=updated,
            deactivated=deactivated,
            closed_agents=closed_names or [],
        )

    async def mark_project_reviewed(self, project_id: str, tenant_key: str | None = None) -> datetime:
        resolved_tenant = tenant_key or self.tenant_manager.get_current_tenant()
        async with self._get_session(resolved_tenant) as session:
            return await self._stamp_review(session, resolved_tenant, project_id)

    async def _stamp_review(self, session: Any, tenant_key: str, project_id: str) -> datetime:
        project = await self._repo.get_by_id(session, tenant_key, project_id)
        if project is None:
            raise ResourceNotFoundError(
                message="Project not found or access denied", context={"project_id": project_id}
            )
        if project.status not in REVIEWABLE_STATUSES:
            raise ProjectStateError(
                message=f"Only a finished project can be reviewed (status is '{project.status}')",
                context={"project_id": project_id, "status": project.status},
            )
        await self._repo.stamp_reviewed(session, tenant_key, project_id)
        await session.refresh(project)
        return project.reviewed_at

    async def mark_projects_reviewed(self, project_ids: list[str], tenant_key: str | None = None) -> dict[str, Any]:
        resolved_tenant = tenant_key or self.tenant_manager.get_current_tenant()
        unique = list(dict.fromkeys(project_ids))
        marked = 0
        skipped: list[dict[str, str]] = []
        async with self._get_session(resolved_tenant) as session:
            in_chain = await chain_member_ids(session, resolved_tenant, unique)
            for project_id in unique:
                if project_id in in_chain:
                    skipped.append({"id": project_id, "reason": "chain"})
                    continue
                try:
                    await self._stamp_review(session, resolved_tenant, project_id)
                except ResourceNotFoundError:
                    skipped.append({"id": project_id, "reason": "not_found"})
                except ProjectStateError:
                    skipped.append({"id": project_id, "reason": "not_finished"})
                else:
                    marked += 1
        return {"marked": marked, "skipped": skipped}

    async def bulk_close_projects(
        self, action: str, project_ids: list[str], tenant_key: str | None = None
    ) -> dict[str, Any]:
        resolved_tenant = tenant_key or self.tenant_manager.get_current_tenant()
        outcome = BulkCloseOutcome()
        for project_id in unique_ids(project_ids):
            if action != "unarchive" and await self._in_active_chain(resolved_tenant, project_id):
                outcome.skip(project_id, REASON_IN_CHAIN)
                continue
            try:
                if action == "delete":
                    await self.deletion.delete_project(project_id, broadcast=False)
                else:
                    await self.update_project(project_id, {"hidden": action == "archive"}, broadcast=False)
            except ResourceNotFoundError:
                outcome.skip(project_id, REASON_NOT_FOUND)
            except BaseGiljoError as exc:
                outcome.fail(project_id, exc.message)
            else:
                outcome.done.append(project_id)
        if outcome.done and self._websocket_manager:
            await self._websocket_manager.broadcast_to_tenant(
                tenant_key=resolved_tenant,
                event_type="projects:bulk_updated",
                data=bulk_event_data(action, outcome.done),
            )
        return outcome.as_dict()

    async def _in_active_chain(self, tenant_key: str, project_id: str) -> bool:
        async with self._get_session(tenant_key) as session:
            return await active_chain_run(session, project_id, tenant_key) is not None

    async def _missing_closeout_blockers(self, project_id: str, tenant_key: str) -> list[dict[str, Any]] | None:
        async with self._get_session(tenant_key) as session:
            project = await self._repo.get_by_id(session, tenant_key, project_id)
            if project is not None and project.closeout_executed_at is not None:
                return None

            report = await self.closeout.evaluate_closeout_readiness(session, project_id, tenant_key)
            return shape_readiness_blockers(report)
