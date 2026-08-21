# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""The archive lifecycle -- the supported way a solo project reaches a terminal status.

BE-9384: these four steps used to live inline in ``archive_project`` in
``api/endpoints/projects/lifecycle.py``, which made the dashboard's Archive button
the ONLY thing that could run them. An agent finishing a project over MCP had
``update_project(status="completed")`` and nothing else, so it reached step 3 alone
and silently skipped deactivation and agent closure -- a plausible-looking end state
(status and completed_at both read right) with spawned agents stranded at 'complete'.

Lifting the sequence here makes it a single writer with two callers: the REST
endpoint and the MCP terminal transition. Neither owns a private copy.

Lives in its own module rather than ``_mutation_mixin`` (757 lines) because the CI
guardrail hard-fails any ``src/`` or ``api/`` module over 800 lines.
"""

import logging
from typing import Any

from giljo_mcp.domain.project_status import LIFECYCLE_FINISHED_STATUSES, ProjectStatus
from giljo_mcp.schemas.service_responses import ProjectArchiveResult


logger = logging.getLogger(__name__)


class ArchiveMixin:
    """``ProjectService.archive_project`` -- the four-step terminal transition."""

    async def archive_project(
        self,
        project_id: str,
        tenant_key: str | None = None,
        websocket_manager: Any | None = None,
    ) -> ProjectArchiveResult:
        """Run the full archive lifecycle and return what each step did.

        The four steps, in order:

        1. Deactivate, unless the project is already finished or inactive.
        2. Choose the terminal status from ``early_termination`` -- the flag is the
           single source of truth for terminated-vs-completed, written by the owning
           service from the user's termination prompt. Callers do not get to pick.
        3. Write the status through ``update_project``.
        4. Transition 'complete' agents to 'closed', with the live WS update.

        Args:
            project_id: Project UUID.
            tenant_key: Optional tenant key; falls back to the current tenant.
            websocket_manager: Optional WS manager for the status broadcast.

        Returns:
            ProjectArchiveResult: the post-transition row plus which optional steps fired.

        Raises:
            ResourceNotFoundError: Project not found or access denied.
        """
        resolved_tenant = tenant_key or self.tenant_manager.get_current_tenant()
        ws = websocket_manager or self._websocket_manager

        proj = await self.get_project(project_id=project_id, tenant_key=resolved_tenant)

        # BE-5039 Phase 2b: the deactivate-skip gate derives from the canonical
        # ``LIFECYCLE_FINISHED_STATUSES`` set (COMPLETED, CANCELLED, TERMINATED,
        # DELETED, SUPERSEDED) plus INACTIVE. deactivate_project raises
        # ProjectStateError on anything but ACTIVE, so the gate is load-bearing.
        skip_deactivate = LIFECYCLE_FINISHED_STATUSES | {ProjectStatus.INACTIVE}
        deactivated = proj.status not in skip_deactivate
        if deactivated:
            await self.deactivate_project(project_id=project_id, tenant_key=resolved_tenant)

        # Handover 0498: early_termination decides which terminal status is written.
        target_status = ProjectStatus.TERMINATED if proj.early_termination else ProjectStatus.COMPLETED

        # BE-9343 (audit F3): deliberately does NOT pass completed_at. The service
        # stamps it on the transition into a terminal status when it is not already
        # set, so archiving fills a missing date but never overwrites a real one.
        #
        # It used to pass datetime.now(UTC) unconditionally, which silently destroyed
        # the ship date on the ordinary solo flow: an agent closes the project out at
        # T1 (the closeout stamps it), the user presses Archive at T2, and the stored
        # value became T2 -- the archive-press time. That is the same "archiving a
        # project changed its completion date" defect BE-9343 exists to remove, and it
        # contradicted ce_0088, which deliberately prefers the exact
        # closeout_executed_at over a drifted stamp.
        updated = await self.update_project(
            project_id=project_id,
            updates={"status": target_status},
            websocket_manager=ws,
        )

        # Handover 0435b: transition 'complete' agents to 'closed' on archive.
        # BE-9246: reuse ``self.closeout`` (constructed with this service's real
        # websocket_manager) instead of building a throwaway ProjectCloseoutService
        # with no WS manager -- that gap was exactly why the closed-agent tiles never
        # got a live update on archive.
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
