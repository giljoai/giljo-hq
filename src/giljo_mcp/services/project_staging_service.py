# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
ProjectStagingService - Project staging workflow operations.

Sprint 002e: Extracted from ProjectLifecycleService to reduce god-class size.
Contains check_staging_allowed, restage, unstage, and cancel_staging.
"""

import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.database import DatabaseManager
from giljo_mcp.domain.project_status import ProjectStatus
from giljo_mcp.exceptions import (
    ImplementationNotReadyError,
    ProjectStateError,
    ResourceNotFoundError,
    ValidationError,
)
from giljo_mcp.models.projects import Project
from giljo_mcp.repositories.project_lifecycle_repository import ProjectLifecycleRepository
from giljo_mcp.repositories.project_repository import ProjectRepository
from giljo_mcp.schemas.service_responses import ProjectData
from giljo_mcp.services._session_helpers import optional_tenant_session
from giljo_mcp.services.project_helpers import _build_ws_project_data, advance_chain_member_to_implementing
from giljo_mcp.tenant import TenantManager
from giljo_mcp.utils.log_sanitizer import sanitize


logger = logging.getLogger(__name__)


class ProjectStagingService:
    """Service for project staging workflow operations.

    Extracted from ProjectLifecycleService (Sprint 002e).
    """

    def __init__(
        self,
        db_manager: DatabaseManager,
        tenant_manager: TenantManager,
        test_session: AsyncSession | None = None,
        websocket_manager: Any | None = None,
        lifecycle_service: Any | None = None,
    ):
        self.db_manager = db_manager
        self.tenant_manager = tenant_manager
        self._test_session = test_session
        self._websocket_manager = websocket_manager
        self._lifecycle = lifecycle_service
        self._logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")
        self._project_repo = ProjectRepository()
        self._lifecycle_repo = ProjectLifecycleRepository()

    def _get_session(self, tenant_key: str | None = None):
        """Yield a tenant-scoped DB session, honoring an injected test session (shared helper, BE-8000d)."""
        return optional_tenant_session(
            self.db_manager, tenant_key or self.tenant_manager.get_current_tenant(), self._test_session
        )

    def check_staging_allowed(self, project: Project) -> None:
        """Check if a project can be staged. Raises if staging is already in progress.

        Args:
            project: The project to check.

        Raises:
            ProjectStateError: If project.staging_status is 'staging'.
        """
        if project.staging_status == "staging":
            raise ProjectStateError(
                message="Staging already in progress. Use Re-Stage to reset first.",
                context={"project_id": project.id, "staging_status": project.staging_status},
            )

    @staticmethod
    def check_implementation_allowed(project: Project) -> None:
        """Shared implementation-readiness gate (INF-6049b).

        The single source of truth for the two preconditions that were inlined in
        ``api/endpoints/prompts.py::get_implementation_prompt``. Both the REST
        implementation-prompt endpoint and the ``implement_project`` MCP tool call
        this — neither copies the checks. Pure: reads two project fields and raises.

        The human gate is SACRED (feedback_staging_stop_do_not_execute, violated
        3x): this NEVER sets ``implementation_launched_at`` and offers NO bypass.
        The ``not_launched`` stage clears only when the user presses Implement in
        the dashboard (which stamps ``implementation_launched_at``).

        Args:
            project: The project to gate. Must have ``staging_status`` and
                ``implementation_launched_at`` loaded.

        Raises:
            ImplementationNotReadyError: reason ``'staging_incomplete'`` when
                staging is not complete; reason ``'not_launched'`` when staging is
                complete but the human Implement gate has not been pressed. The
                ``message`` values are byte-identical to the pre-extraction inline
                404 details so REST behavior is unchanged.
        """
        if project.staging_status != "staging_complete":
            raise ImplementationNotReadyError(
                reason="staging_incomplete",
                message="No orchestrator found for this project. Please ensure staging has been completed.",
                context={"project_id": project.id, "staging_status": project.staging_status},
            )
        if project.implementation_launched_at is None:
            raise ImplementationNotReadyError(
                reason="not_launched",
                message="Implementation has not been launched yet for this project.",
                context={"project_id": project.id},
            )

    async def restage(self, project_id: str) -> dict:
        """Reset a launched/completed staging cycle so it can be re-staged.

        Guards:
            1. project.staging_status must be 'staging' or 'staging_complete'
               -- otherwise reject. ('staging_complete' is the staging→impl
               handoff window: staging finished, Implement not yet clicked.)
            2. If staging is already complete AND implementation has been
               launched (project.implementation_launched_at is set), reject:
               restaging would strand already-spawned implementation jobs.
            3. The orchestrator AgentExecution must not be actively running.
               At staging-end CE-0032 parks it at status='waiting' (not
               'complete'), and the un-launched fixture is also 'waiting', so
               only 'working'/'blocked' (mid-staging) is rejected.

        Actions (single transaction):
            1. Set project.staging_status = None
            2. Clear mission to "" (BE-6047): releases the Handover-0343
               execution_mode lock so the user can re-pick the mode. Empty
               string (not None) because projects.mission is NOT NULL.
            3. Preserve project.execution_mode (BE-6047): do NOT force
               'multi_terminal' — the user's chosen mode survives a restage.
            4. Clear implementation_launched_at (CE-0032: clean-slate cycle).
            5. Decommission the existing orchestrator execution.
            6. Create a fresh orchestrator fixture.

        Args:
            project_id: Project UUID.

        Returns:
            Dict with message, project_id, and new_orchestrator fixture info.

        Raises:
            ResourceNotFoundError: Project not found.
            ProjectStateError: Invalid state for restage.
        """
        tenant_key = self.tenant_manager.get_current_tenant()

        async with self._get_session() as session:
            project = await self._project_repo.get_by_id(session, tenant_key, project_id)

            if not project:
                raise ResourceNotFoundError(
                    message="Project not found",
                    context={"project_id": project_id},
                )

            if project.staging_status not in ("staging", "staging_complete"):
                raise ProjectStateError(
                    message="Project is not currently staged",
                    context={
                        "project_id": project_id,
                        "staging_status": project.staging_status,
                    },
                )

            # BE-6047: recovery from the handoff window is only safe BEFORE the
            # user clicks Implement. Once implementation is launched, spawned
            # jobs exist and a restage would strand them.
            if project.staging_status == "staging_complete" and project.implementation_launched_at is not None:
                raise ProjectStateError(
                    message="Cannot recover mode: implementation already launched",
                    context={
                        "project_id": project_id,
                        "staging_status": project.staging_status,
                    },
                )

            orchestrator = await self._lifecycle_repo.find_existing_orchestrator(session, tenant_key, project_id)

            # CE-0032: at staging-end the orchestrator execution is parked at
            # 'waiting' (job_completion_service._apply_completion_status), and
            # the never-launched fixture is also 'waiting'. Only an actively
            # running staging session ('working'/'blocked') must block restage.
            if orchestrator and orchestrator.status not in ("waiting", "complete"):
                raise ProjectStateError(
                    message="Cannot restage: orchestrator agent is already active",
                    context={
                        "project_id": project_id,
                        "orchestrator_status": orchestrator.status,
                    },
                )

            project.staging_status = None
            project.mission = ""
            # CE-0032: restage is a clean-slate "new staging cycle, all prior
            # impl progress discarded" semantic. Stale impl_launched_at from
            # a prior completed cycle would otherwise stick the next
            # staging-end inside complete_job's TODOs-bypass key (which
            # checks `implementation_launched_at IS NULL`), regressing the
            # CE-0027 fix on restage-after-completion. Clearing here pairs
            # with the staging_status reset and the orch decommission below.
            # BE-9085b: deliberately do NOT clear ever_launched_at here --
            # restage is a clean-slate cycle for impl progress, not a rewind
            # of the project's history. ever_launched_at is the durable
            # "was ever launched" fact the BE-9085 detector relies on to
            # suppress this exact restage false-positive.
            project.implementation_launched_at = None
            project.updated_at = datetime.now(UTC)

            if orchestrator:
                orchestrator.status = "decommissioned"

            await session.commit()

            # Use parent lifecycle service to create fresh orchestrator fixture
            new_fixture = await self._lifecycle._ensure_orchestrator_fixture(session, project)

            self._logger.info(
                "[RESTAGE] Project %s restaged, new orchestrator: %s",
                project_id,
                new_fixture,
            )

            return {
                "message": "Project restaged successfully",
                "project_id": project.id,
                "new_orchestrator": new_fixture,
            }

    async def reset_to_prestage(self, project_id: str, tenant_key: str | None = None) -> dict:
        """FE-6180: return a project to its original pre-stage state (destructive).

        The single 'Reset' / Deactivate-Chain primitive. Unlike ``restage`` (which
        REFUSES a launched project and decommissions/preserves the orchestrator for
        audit), this UNCONDITIONALLY clears the staging artifacts and HARD-DELETES
        all agent jobs/executions, even after implementation launched — a clean
        slate with NO audit trail. ``Terminate`` is the audit-preserving graceful
        exit; this is the discard-everything rewind the user reaches for after
        ESC-ing / killing a terminal.

        Actions (single transaction):
          1. ``staging_status`` -> None
          2. ``mission`` -> "" (releases the execution_mode lock; NOT NULL column)
          3. ``implementation_launched_at`` -> None
          3a. ``ever_launched_at`` -> None (BE-9085b: full rewind clears the
              durable ever-launched signal too, unlike restage)
          4. ``status`` -> inactive
          5. hard-delete every AgentJob + AgentExecution (+ user_approvals) for the
             project (FK-safe), so no orchestrator/subagent rows linger.

        ``execution_mode`` is preserved (the user's chosen mode survives a reset,
        matching ``restage``). Idempotent — an already-clean project just no-ops the
        delete. Works for solo projects and chain members alike.

        Returns: ``{message, project_id, deleted: {jobs, executions, approvals}}``.
        Raises: ResourceNotFoundError if the project does not exist for this tenant.
        """
        effective_tenant_key = tenant_key or self.tenant_manager.get_current_tenant()

        async with self._get_session(effective_tenant_key) as session:
            project = await self._project_repo.get_by_id(session, effective_tenant_key, project_id)
            if not project:
                raise ResourceNotFoundError(message="Project not found", context={"project_id": project_id})

            project.staging_status = None
            project.mission = ""
            project.implementation_launched_at = None
            # BE-9085b: reset_to_prestage genuinely rewinds the project to
            # its original pre-stage birth state -- unlike restage, this DOES
            # clear the durable ever-launched signal too.
            project.ever_launched_at = None
            project.status = ProjectStatus.INACTIVE
            project.updated_at = datetime.now(UTC)

            deleted = await self._lifecycle_repo.delete_all_agent_state_for_project(
                session, effective_tenant_key, project_id
            )
            await session.commit()

            self._logger.info("[RESET] Project %s reset to pre-stage; deleted %s", project_id, deleted)
            return {
                "message": "Project reset to original state",
                "project_id": project.id,
                "deleted": deleted,
            }

    async def unstage(self, project_id: str) -> dict:
        """Revert a project from 'staged' back to ready state.

        Only allowed when staging_status == 'staged' (prompt generated, agent
        has not yet been launched / made first contact).

        Actions:
            1. Reset staging_status to None
            2. Clear mission to "" (BE-6047: prompt was generated but never
               used). This releases the Handover-0343 execution_mode lock in
               ProjectService._apply_project_updates, which keys on a truthy
               project.mission. Without this, a 'staged' project stays locked
               into its chosen execution_mode forever — the lock trap. Empty
               string (not None) because projects.mission is NOT NULL.

        No orchestrator recreation: at 'staged' the orchestrator fixture was
        created but never launched, so it remains usable as-is.

        Raises:
            ResourceNotFoundError: Project not found.
            ProjectStateError: Not in 'staged' state.
        """
        tenant_key = self.tenant_manager.get_current_tenant()

        async with self._get_session() as session:
            project = await self._project_repo.get_by_id(session, tenant_key, project_id)

            if not project:
                raise ResourceNotFoundError(
                    message="Project not found",
                    context={"project_id": project_id},
                )

            if project.staging_status != "staged":
                raise ProjectStateError(
                    message="Project is not in staged state. Cannot unstage.",
                    context={
                        "project_id": project_id,
                        "staging_status": project.staging_status,
                    },
                )

            project.staging_status = None
            project.mission = ""
            project.updated_at = datetime.now(UTC)
            await session.commit()

            self._logger.info("[UNSTAGE] Project %s unstaged", project_id)

            return {
                "message": "Project unstaged successfully",
                "project_id": project.id,
            }

    async def mark_staged(
        self,
        project_id: str,
        execution_mode: str,
        tenant_key: str | None = None,
        db_session: AsyncSession | None = None,
    ) -> None:
        """Persist the 'staged' state after a staging prompt has been generated.

        BE-3006a single-writer rule: the REST staging endpoint
        (``api/endpoints/prompts.py``) used to raw-write
        ``project.staging_status`` + ``execution_mode`` and ``db.commit()`` after
        generating the prompt. That write now lives here — the owning service —
        as a twin of ``restage``/``unstage`` (same session + commit pattern).

        Single-writer transaction fix: both callers that generate a
        staging prompt on their OWN session (the ``stage_project`` MCP tool, the
        REST staging endpoint) can now pass that same ``db_session`` + an
        explicit ``tenant_key`` so this write lands on ONE session instead of
        opening a second, independent one. Omitting both preserves the prior
        behaviour exactly (own session, contextvar-resolved tenant) — this is an
        additive-only signature change.

        Transaction note: when this call owns its session, the prompt generator
        commits its own orchestrator work in a separate transaction
        (``thin_prompt_generator`` sets ``staging_status='staging'``
        independently), so this flip to 'staged' is already a standalone write.
        When a caller-supplied session is used instead, this method STILL commits
        internally (does not defer to the caller's own commit) — see the design
        note in the mark_staged single-writer fix: neither of today's two
        callers does anything after this write that could plausibly roll it
        back, and deferring the commit would risk a project stuck at
        ``staging_status='staging'`` if something later in the request throws.
        The pre-generation re-stage guard stays at the endpoint (it is a read,
        runs BEFORE generation, and must reject 'staged' as well as 'staging' —
        semantics distinct from ``check_staging_allowed``). This method
        therefore does NOT re-call that guard, because the generator has
        legitimately set 'staging' by the time we get here.

        Args:
            project_id: Project UUID.
            execution_mode: The resolved, user-chosen execution mode. Written only
                while implementation has not launched (mirrors the PATCH-path
                lock in ``ProjectService._apply_project_updates``).
            tenant_key: Tenant for isolation. Defaults to the current tenant
                context when omitted (the MCP dispatch sets it via the
                contextvar; a caller with its own resolved tenant should pass
                it explicitly).
            db_session: Optional caller-owned session to write on instead of
                opening a new one. When provided, the write still commits (see
                the transaction note above) but never opens a second connection.

        Raises:
            ValidationError: No tenant could be resolved (neither the explicit
                argument nor the ambient contextvar).
            ResourceNotFoundError: Project not found.
        """
        resolved_tenant = tenant_key or self.tenant_manager.get_current_tenant()
        if not resolved_tenant:
            raise ValidationError(
                message="Tenant not set", context={"operation": "mark_staged", "project_id": project_id}
            )

        owns_session = db_session is None
        if owns_session:
            async with self._get_session(resolved_tenant) as session:
                await self._mark_staged_transaction(session, resolved_tenant, project_id, execution_mode)
        else:
            await self._mark_staged_transaction(db_session, resolved_tenant, project_id, execution_mode)

    async def _mark_staged_transaction(
        self, session: AsyncSession, tenant_key: str, project_id: str, execution_mode: str
    ) -> None:
        """The actual staged-state write, shared by both the owned- and caller-session paths.

        Takes the ALREADY-RESOLVED tenant explicitly (never re-derives via the
        ambient contextvar) so a caller that resolved its own tenant_key (as
        opposed to relying on the contextvar the MCP dispatch sets) gets a DB
        lookup scoped to the tenant it actually asked for -- not whatever the
        contextvar happens to hold at call time.
        """
        project = await self._project_repo.get_by_id(session, tenant_key, project_id)

        if not project:
            raise ResourceNotFoundError(
                message="Project not found",
                context={"project_id": project_id},
            )

        project.staging_status = "staged"
        if project.implementation_launched_at is None:
            project.execution_mode = execution_mode
        project.updated_at = datetime.now(UTC)

        await session.commit()

        self._logger.info("[MARK_STAGED] Project %s marked staged", project_id)

    async def launch_implementation(
        self,
        project_id: str,
        tenant_key: str | None = None,
        launched_by: str | None = None,
        websocket_manager: Any | None = None,
        origin: str | None = None,
    ) -> dict[str, Any]:
        """Stamp ``implementation_launched_at`` — the single human-gate release writer (BE-6115a).

        This is the ONE place a HUMAN press writes ``implementation_launched_at`` (the
        solo-gate writer). One non-human path also stamps the column: a conductor-released
        chain sub-orchestrator's OWN staging-end (``job_completion_service.py`` §14 gateless
        advance), never the solo human gate. BOTH human-authorized doors of the two-door
        implement gate call THIS method:
          1. the dashboard **Implement** button, via the REST endpoint
             ``PATCH /api/agent-jobs/projects/{id}/launch-implementation``; and
          2. the **launch_implementation** MCP tool (CLI door, ``mcp:agent``).
        The REST endpoint no longer raw-writes the column inline — that parallel
        write path is removed (BE-3006a single-writer rule, twin of ``mark_staged``).

        The human gate stays SACRED (feedback_staging_stop_do_not_execute). This
        method NEVER bypasses or weakens any downstream gate: it only flips the
        flag. The security boundary lives at the SURFACES that can reach it — the
        MCP tool is kept OUT of the orchestrator auto-tool bundle
        (``_canonical_tool_list``), so a spawned/staging agent has no schema for it
        and cannot self-unlock; the MCP permission prompt on the tool IS the human
        authorization. ``check_implementation_allowed`` (the read gate used by
        ``implement_project``/``get_job_mission``/``spawn_job``) refuses a SOLO project
        until this flag is set; a conductor-released CHAIN member (no human Implement
        button) is exempted via ``mission_service._is_chain_member`` — BE-9069 narrows
        that exemption so a member still parked at the solo Implement gate
        (staging_complete with the flag NULL) is NOT crossed.

        Idempotent: a second call does NOT re-stamp — it returns
        ``already_launched=True`` with the original timestamp.

        Args:
            project_id: Project UUID.
            tenant_key: Tenant for isolation. Defaults to the current tenant
                context when omitted (the MCP dispatch sets it; the REST caller
                passes ``current_user.tenant_key`` explicitly).
            launched_by: Attribution for the audit log line (username / user_id of
                the human who authorized the launch).
            websocket_manager: Optional WS manager for the
                ``project:implementation_launched`` broadcast. Defaults to the
                service's own manager. Broadcast failure never fails the write.
            origin: Optional event-origin tag (TSK-6219) carried into the
                ``project:implementation_launched`` payload as ``source``:
                ``"mcp"`` when the launch entered via the MCP tool (a headless
                drive), ``"ui"`` when via the dashboard Implement REST door.
                ``None`` (default) omits the field — the FE live-follow then falls
                back to its client-side anti-hijack window. Not persisted; needed
                only at event time.

        Returns:
            Dict mirroring the REST ``LaunchImplementationResponse`` shape:
            ``{success, implementation_launched_at, already_launched, launched_at}``.

        Raises:
            ResourceNotFoundError: Project not found for this tenant.
        """
        effective_tenant = tenant_key or self.tenant_manager.get_current_tenant()
        ws = websocket_manager or self._websocket_manager

        async with self._get_session(effective_tenant) as session:
            project = await self._project_repo.get_by_id(session, effective_tenant, project_id)

            if not project:
                raise ResourceNotFoundError(
                    message="Project not found",
                    context={"project_id": project_id},
                )

            already_launched = project.implementation_launched_at is not None

            if not already_launched:
                # BE-6181: staging-complete guard. The chain conductor auto-drives
                # 2..N by calling launch_implementation on each downstream project;
                # without this guard a premature call (project not yet staging-
                # complete) would stamp implementation_launched_at and mis-route the
                # project's staging-end complete_job into the implementation-closeout
                # gate (job_completion_service _is_staging_end_orchestrator_call /
                # deliverable-TODO bypass both key on this stamp being None) ->
                # COMPLETION_BLOCKED -> the chain dead-ends. This only enforces what
                # the read gate check_implementation_allowed (line 113) already
                # requires, so a normal solo Implement (reachable only after
                # staging_complete) passes it unchanged.
                if project.staging_status != "staging_complete":
                    raise ImplementationNotReadyError(
                        reason="staging_incomplete",
                        message=(
                            "Cannot launch implementation: project staging is not complete. "
                            "Complete this project's staging first (drive it to staging_complete "
                            "via the staging-end complete_job), then launch_implementation."
                        ),
                        context={"project_id": project.id, "staging_status": project.staging_status},
                    )

                # CE-0032: no impl-exec spawn here. The orchestrator's single
                # AgentExecution row parked at status='waiting' at staging-end;
                # get_job_mission flips it 'waiting'->'working' once the human
                # pastes the impl prompt. This endpoint only releases the gate.
                project.implementation_launched_at = datetime.now(UTC)
                # BE-9085b: set-once, durable "was ever launched" signal. A
                # re-launch (already_launched path never reaches here, but a
                # future re-entrant call could) must never overwrite the
                # original crossing — this survives restage on purpose.
                if project.ever_launched_at is None:
                    project.ever_launched_at = project.implementation_launched_at
                project.updated_at = datetime.now(UTC)
                await session.commit()
                await self._project_repo.refresh(session, project)

                # BE-6181: AUTO-ADVANCE — crossing the launch gate IS the chain
                # advance. The per-call MCP permission prompt on launch_implementation
                # is the human authorization for this project, so a successful launch
                # advances the run as a side-effect (no new MCP tool). FORWARD-ONLY:
                # never rewind current_index. Solo (no active run) -> no-op. This is
                # authorization-driven and distinct from advance_index_if_committed
                # (closeout-gate semantics). BEST-EFFORT: the launch already
                # committed; an advance failure must NEVER fail the launch.
                await self._advance_chain_on_launch(project_id, effective_tenant, websocket_manager=ws)

            launched_at_iso = project.implementation_launched_at.isoformat()
            # BE-9532: read inside the session -- the project object is detached below.
            project_active = project.status == ProjectStatus.ACTIVE
            # BE-9525c: same -- read while still attached, used in the WS payload below.
            product_id = project.product_id

            self._logger.info(
                "[LAUNCH_IMPL] Project %s implementation launched (already_launched=%s) by %s",
                sanitize(project_id),
                already_launched,
                launched_by or "unknown",
            )

        # Symmetric WS event for the staging->implementation transition. Fires on
        # BOTH first-launch and already-launched paths so newly-connected clients
        # can hydrate. Broadcast failure must not fail the write (resilience
        # pattern shared with mark_staging_complete / cancel_staging).
        if ws:
            payload = {
                "project_id": project_id,
                # BE-9525c: additive -- was missing on this emitter (mirrors the
                # sibling emitter fixed the same way in job_completion_staging.py).
                "product_id": product_id,
                "implementation_launched_at": launched_at_iso,
            }
            # TSK-6219: authoritative event-origin so the FE live-follow can tell a
            # headless MCP drive ("follow it") from a user's own click ("stay put").
            # Omitted when unknown so the FE falls back to its anti-hijack window.
            if origin is not None:
                payload["source"] = origin
            try:
                await ws.broadcast_to_tenant(
                    tenant_key=effective_tenant,
                    event_type="project:implementation_launched",
                    data=payload,
                )
            except Exception as ws_error:  # noqa: BLE001 — WS resilience
                self._logger.warning("[LAUNCH_IMPL] WS broadcast failed: %s", ws_error)

        # BE-9532: report the activation state, and name the step still required.
        #
        # Crossing the launch gate does NOT activate the project, in EITHER door --
        # the dashboard has its own Activate control and the harness has
        # update_project(status="active"). That separation is deliberate and is left
        # alone here. What was missing is that nothing SAID so: a headless drive got
        # {"success": true} back and then found no active project, with no error
        # anywhere to explain why.
        #
        # Reporting lives in this service because BOTH doors call it, so the REST
        # response and the MCP tool payload carry the same answer rather than a
        # second, drifting explanation on the agent-facing side.
        # BE-9541: BOTH timestamp keys always carry the same value on success.
        # Previously ``implementation_launched_at`` was populated only on the
        # first-launch path and ``launched_at`` only on the already-launched
        # path, so a caller that checked "the wrong one" for whichever path it
        # happened to take saw None and concluded the launch had failed.
        # ``already_launched`` remains the one
        # place that internal distinction is exposed; the old keys are both
        # kept (REST's ``LaunchImplementationResponse`` still reads them) but
        # neither is ever null on a successful call.
        result: dict[str, Any] = {
            "success": True,
            "implementation_launched_at": launched_at_iso,
            "already_launched": already_launched,
            "launched_at": launched_at_iso,
            "project_active": project_active,
        }
        if not project_active:
            result["next_action"] = (
                "The implementation gate is open, but this project is NOT ACTIVE, so the "
                "dashboard Jobs view will show 'No Active Project' and no work will surface "
                "there. Activate it to make the run visible: update_project(project_id, "
                "status='active') from the harness, or the Activate control on the project "
                "in the dashboard. Activation is a separate step by design."
            )
        return result

    async def _advance_chain_on_launch(
        self,
        project_id: str,
        tenant_key: str,
        websocket_manager: Any | None = None,
    ) -> None:
        """Advance the active sequence run when a chain member's launch gate is crossed (BE-6181).

        Crossing launch_implementation IS the chain advance (authorization-driven —
        the human approved the per-call MCP prompt). For a project that is a member
        of an active run at index ``idx``:
          - ``current_index = max(existing, idx)`` — FORWARD-ONLY (never rewind).
          - ``project_statuses[project_id] = "planning"`` (merged; FE-9493 — promoted to
            "implementing" separately once the member's first worker actually starts).

        Solo path (no active run) -> no-op. BEST-EFFORT: wrapped so a failure NEVER
        propagates to the already-committed launch. Tenant-scoped; the run write
        routes through SequenceRunService (the owning service).

        ``websocket_manager`` (BE-6198 live-update): the resolved manager from
        ``launch_implementation`` is threaded into BOTH the SequenceRunService and the
        SequenceChainContextResolver so the index/status advance fires
        ``sequence:updated`` and the chain badge moves live. None preserves the solo
        no-op (no broadcast).

        BE-6206 (§14): the bookkeeping itself now lives in the shared module helper
        ``advance_chain_member_to_implementing`` so the gateless chain flow's staging-end
        advance (job_completion_service._handle_staging_end) and this launch path stay a
        single source of truth. Solo (no active run) remains a clean no-op.
        """
        await advance_chain_member_to_implementing(
            db_manager=self.db_manager,
            tenant_manager=self.tenant_manager,
            project_id=project_id,
            tenant_key=tenant_key,
            session=self._test_session,
            websocket_manager=websocket_manager,
        )

    async def cancel_staging(self, project_id: str, websocket_manager: Any | None = None) -> ProjectData:
        """Cancel a project in staging state.

        State Transition: staging -> cancelled

        Args:
            project_id: Project UUID
            websocket_manager: Optional WebSocket manager for real-time updates

        Returns:
            ProjectData

        Raises:
            ResourceNotFoundError: Project not found
            ProjectStateError: Cannot cancel staging for project with current status
        """
        async with self._get_session() as session:
            project = await self._project_repo.get_by_id(session, self.tenant_manager.get_current_tenant(), project_id)

            if not project:
                raise ResourceNotFoundError(message="Project not found", context={"project_id": project_id})

            # BE-5039 Phase 2b: ``staging`` is no longer a value on the
            # canonical ``project_status`` ENUM. The actual staging
            # workflow tracker is the dedicated ``staging_status`` column
            # ('staging' | 'staging_complete' | NULL). Guard against the
            # right column so the precondition isn't dead code post-
            # migration. The project must currently be inactive AND have
            # an in-progress staging workflow.
            if project.staging_status != "staging" or project.status != ProjectStatus.INACTIVE:
                raise ProjectStateError(
                    message=(
                        f"Cannot cancel staging: project status='{project.status.value}', "
                        f"staging_status='{project.staging_status}' (need INACTIVE + staging)"
                    ),
                    context={
                        "project_id": project_id,
                        "current_status": project.status.value,
                        "staging_status": project.staging_status,
                    },
                )

            project.status = ProjectStatus.CANCELLED
            project.completed_at = datetime.now(UTC)
            project.updated_at = datetime.now(UTC)

            await session.commit()
            await self._project_repo.refresh(session, project)

            self._logger.info(f"Cancelled staging for project {project_id}")

            if websocket_manager:
                try:
                    await websocket_manager.broadcast_project_update(
                        project_id=project.id,
                        update_type="cancelled",
                        project_data=_build_ws_project_data(project),
                        tenant_key=project.tenant_key,
                    )
                except Exception as ws_error:  # noqa: BLE001 - WebSocket resilience
                    self._logger.warning(f"WebSocket broadcast failed: {ws_error}")

            return ProjectData(
                id=project.id,
                name=project.name,
                status=project.status,
                mission=project.mission,
                description=project.description,
                cancellation_reason=project.cancellation_reason,
                early_termination=project.early_termination,
                created_at=project.created_at.isoformat() if project.created_at else None,
                updated_at=project.updated_at.isoformat() if project.updated_at else None,
                completed_at=project.completed_at.isoformat() if project.completed_at else None,
                product_id=project.product_id,
            )
