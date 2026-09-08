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
from giljo_mcp.exceptions import CloseoutRequiredError
from giljo_mcp.schemas.service_responses import ProjectArchiveResult
from giljo_mcp.services.project_closeout_readiness import shape_readiness_blockers
from giljo_mcp.utils.log_sanitizer import sanitize


logger = logging.getLogger(__name__)


class ArchiveMixin:
    """``ProjectService.archive_project`` -- the four-step terminal transition."""

    async def archive_project(
        self,
        project_id: str,
        tenant_key: str | None = None,
        websocket_manager: Any | None = None,
        force: bool = False,
    ) -> ProjectArchiveResult:
        """Run the full archive lifecycle and return what each step did.

        BE-9539: archive is the ONE writer both doors reach a terminal status
        through (the REST ``/archive`` endpoint and MCP's
        ``update_project(status="completed")``). Before BE-9539 neither door
        checked whether the project had ever closed out cleanly, so an
        orchestrator whose ``write_project_closeout`` call was refused
        (CLOSEOUT_BLOCKED -- e.g. an unread operator decision) could still
        reach here and archive silently, burying the decision.

        Step 0 (new): unless ``force`` or the project already carries a closeout
        (``project.closeout_executed_at`` is not None -- stamped by
        ``write_project_closeout`` for every solo project and every chain
        member on success), raise :class:`CloseoutRequiredError` naming the
        SAME blockers ``write_project_closeout`` itself would report, built
        from the SAME ``evaluate_closeout_readiness`` source. Callers resolve
        the blockers or pass ``force=True`` for a deliberate abandon.

        The four steps that follow, in order:

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
            force: Skip the closeout-required gate (BE-9539). The dashboard's
                deliberate one-click abandon path always passes ``True``; the
                MCP door defaults to ``False`` so an agent must either complete
                closeout first or explicitly opt into abandoning it.

        Returns:
            ProjectArchiveResult: the post-transition row plus which optional steps fired.

        Raises:
            ResourceNotFoundError: Project not found or access denied.
            CloseoutRequiredError: No closeout entry exists and ``force`` is False.
        """
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
            # BE-9539: force bypassed the gate -- log what was unsettled so the
            # buried state is at least visible, mirroring the existing
            # write_project_closeout force-close precedent (project_closeout.py
            # ``_handle_force_close``'s "Force-closed project ...: auto-
            # decommissioned N agent(s)" warning). ``blockers`` may be empty (a
            # project with no closeout but no active-agent blockers either) --
            # still worth a line, since "no closeout entry" is itself the fact
            # being buried.
            logger.warning(
                "Force-archived project %s without a closeout entry: %d blocker(s) unresolved: %s",
                sanitize(str(project_id)),
                len(blockers),
                sanitize(str(blockers)),
            )

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

    async def _missing_closeout_blockers(self, project_id: str, tenant_key: str) -> list[dict[str, Any]] | None:
        """BE-9539 step 0 read: ``None`` when the project already carries a
        closeout entry (nothing to gate); otherwise the readiness blockers
        (possibly empty) that explain why it doesn't.

        ``closeout_executed_at`` is read directly off the ORM row (it is not on
        ``ProjectData``, the DTO ``get_project`` returns) rather than duplicating
        a repository method for one column read.
        """
        async with self._get_session(tenant_key) as session:
            project = await self._repo.get_by_id(session, tenant_key, project_id)
            if project is not None and project.closeout_executed_at is not None:
                return None

            report = await self.closeout.evaluate_closeout_readiness(session, project_id, tenant_key)
            return shape_readiness_blockers(report)
