# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
OrchestratorFixtureMixin -- orchestrator-fixture row lifecycle for ProjectLifecycleService.

Extracted from ``project_lifecycle_service.py`` (INF-6129) to keep that module
under the 800-line file-size guardrail after BE-6123 added the never-run
orchestrator reset path. The three private helpers grouped here all manage an
orchestrator *fixture* -- the placeholder orchestrator AgentJob/AgentExecution
shown in the UI before "Stage Project":

- ``_ensure_orchestrator_fixture``        create it on activate (Handover 0431)
- ``_maybe_reset_never_run_orchestrator`` delete a never-run one on deactivate (BE-6085/BE-6123)
- ``_broadcast_agents_removed``           emit ``agent:removed`` for the deleted rows (BE-6123)

Mixed into ``ProjectLifecycleService``; the methods rely on the host's
``self._repo``, ``self._logger``, ``self.tenant_manager`` and
``self._websocket_manager`` (all set in ``ProjectLifecycleService.__init__``).
This is a pure relocation -- behavior is unchanged.
"""

from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.models.projects import Project


class OrchestratorFixtureMixin:
    """Orchestrator-fixture row lifecycle helpers for ProjectLifecycleService."""

    async def _ensure_orchestrator_fixture(
        self,
        session: AsyncSession,
        project: Project,
        websocket_manager: Any | None = None,
    ) -> dict[str, str] | None:
        """
        Ensure an orchestrator fixture exists for the activated project (Handover 0431).

        Creates orchestrator AgentJob + AgentExecution as a "fixture" that appears
        in the UI before the user clicks "Stage Project". This indicates to the user
        that an agent is ready to stage.

        The orchestrator is created with status='waiting' and no mission yet.
        When user clicks "Stage Project", the staging endpoint will reuse this
        existing orchestrator and generate the staging prompt.

        Args:
            session: Active database session
            project: The project being activated
            websocket_manager: Optional WebSocket manager for real-time UI updates

        Returns:
            Dict with orchestrator job_id and agent_id if created, None if already exists
        """
        tenant_key = self.tenant_manager.get_current_tenant()

        # Check if orchestrator already exists for this project
        # FIX 1 (Handover 0485): Use exclusion-based filter (finds: waiting, working, complete, blocked)
        existing = await self._repo.find_existing_orchestrator(session, tenant_key, str(project.id))

        if existing:
            self._logger.info(
                f"[ORCHESTRATOR FIXTURE] Orchestrator already exists for project {project.id}, "
                f"job_id={existing.job_id}, status={existing.status}"
            )
            return None

        # Create orchestrator fixture via repository
        fixture_ids = await self._repo.create_orchestrator_fixture(session, tenant_key, project)

        # BE-3006c: the repo flushes; the owner commits HERE, before the
        # agent:created broadcast below, so a failed commit can never leave
        # phantom "orchestrator created" dashboard state
        # (TRANSACTION_OWNERSHIP_CONVENTION -- events emit only post-commit).
        await session.commit()

        job_id = fixture_ids["job_id"]
        agent_id = fixture_ids["agent_id"]
        execution_id = fixture_ids["execution_id"]

        self._logger.info(
            f"[ORCHESTRATOR FIXTURE] Created orchestrator fixture for project {project.id}: "
            f"job_id={job_id}, agent_id={agent_id}"
        )

        # Broadcast agent:created event for UI update
        if websocket_manager:
            try:
                await websocket_manager.broadcast_to_tenant(
                    tenant_key=tenant_key,
                    event_type="agent:created",
                    data={
                        "project_id": project.id,
                        # BE-9525c: additive -- missing on this emitter (BE-9518 left
                        # it out).
                        "product_id": project.product_id,
                        "execution_id": execution_id,  # Handover 0457: Unique row ID for frontend Map key
                        "agent_id": agent_id,
                        "job_id": job_id,
                        "agent_display_name": "orchestrator",
                        "agent_name": "orchestrator",
                        "status": "waiting",
                        "fixture": True,  # Indicates this is a fixture, not from staging
                        "timestamp": datetime.now(UTC).isoformat(),
                    },
                )
                self._logger.info(f"[ORCHESTRATOR FIXTURE] Broadcast agent:created for {job_id}")
            except Exception as ws_error:  # noqa: BLE001 - WebSocket resilience: non-critical broadcast
                self._logger.warning(f"[ORCHESTRATOR FIXTURE] WebSocket broadcast failed: {ws_error}")

        return {
            "job_id": job_id,
            "agent_id": agent_id,
        }

    async def _maybe_reset_never_run_orchestrator(
        self,
        session: AsyncSession,
        tenant_key: str,
        project: Project,
    ) -> list[dict]:
        """BE-6085/BE-6123: on deactivate, DELETE a NEVER-RUN orchestrator so the
        project is re-stageable after reactivation without piling up tombstones.

        A project wedges when an orchestrator fixture is created (Stage clicked)
        but the orchestrator session never runs: the Stage button is disabled (an
        orchestrator already exists) and no Unstage shows (not 'staged'), leaving
        no UI recovery path. Deactivate becomes the recovery -- but ONLY in this
        empty-orchestrator case; a real run is never touched.

        Detection (all three required, UNCHANGED from BE-6085) -- "never ran":
          1. A non-decommissioned orchestrator execution exists, parked in
             'waiting' or 'staged'.
          2. EVERY such execution has working_started_at IS NULL -- the BE-5107
             event listener anchors it on the first transition into 'working', so
             NULL == the session never entered 'working' == never ran. (Detecting
             on the orchestrator AgentJob.mission is unreliable: both creation
             paths write a non-NULL placeholder, so a mission-NULL check would be
             dead code -- BE-6085.)
          3. Zero non-orchestrator (subagent) executions exist.

        Reset action (BE-6123): instead of flipping the orchestrator to
        'decommissioned' (which accumulated one tombstone per activate/deactivate
        cycle in the Agents panel), HARD DELETE the never-run fixture rows
        (AgentExecution + AgentJob) FK-safely via the repository, then reset
        staging_status to the clean pre-staging None and clear
        mission/implementation_launched_at for a clean re-stage. The fixture is
        NOT recreated here -- reactivate's _ensure_orchestrator_fixture builds a
        fresh one. PRESERVES title, description, the project row, tasks, and 360
        history. Orchestrators that ACTUALLY RAN (working_started_at SET) are
        never matched, so they remain as audit history (BE-6085 cases b/c/d).

        Returns:
            List of {execution_id, agent_id, job_id} for the deleted rows (empty
            list when the orchestrator ran / has subagents / none exists -- the
            project's agent state is then left untouched).
        """
        orchestrators = await self._repo.find_active_orchestrator_executions(session, tenant_key, str(project.id))
        if not orchestrators:
            return []

        # Never-ran gate: every live orchestrator execution is parked pre-run.
        never_ran = all(o.status in ("waiting", "staged") and o.working_started_at is None for o in orchestrators)
        if not never_ran:
            return []

        # Zero-subagents gate: any spawned child means the orchestrator did work.
        if await self._repo.count_non_orchestrator_executions(session, tenant_key, str(project.id)) > 0:
            return []

        deleted = await self._repo.delete_never_run_orchestrator_fixtures(
            session, tenant_key, str(project.id), ["waiting", "staged"]
        )
        project.staging_status = None
        project.mission = ""
        project.implementation_launched_at = None

        self._logger.info(
            "[BE-6123] Deleted never-run orchestrator fixture for project %s (%d row(s) removed)",
            project.id,
            len(deleted),
        )
        return deleted

    async def _broadcast_agents_removed(
        self,
        ws_mgr: Any | None,
        tenant_key: str,
        project_id: str,
        removed: list[dict],
        product_id: str | None = None,
    ) -> None:
        """BE-6123: broadcast one agent:removed event per deleted never-run
        orchestrator row so an open dashboard drops the agent live (the frontend
        only refetches agent jobs when the active projectId changes). Mirrors the
        agent:created broadcast in _ensure_orchestrator_fixture. WS failure must
        not fail the deactivate.

        BE-9525c: ``product_id`` is additive, threaded from the caller's
        already-loaded project (this emitter never queries for it itself).
        """
        if not ws_mgr or not removed:
            return
        for row in removed:
            try:
                await ws_mgr.broadcast_to_tenant(
                    tenant_key=tenant_key,
                    event_type="agent:removed",
                    data={
                        "project_id": project_id,
                        "product_id": product_id,
                        "agent_id": row["agent_id"],
                        "execution_id": row["execution_id"],
                        "job_id": row["job_id"],
                        "timestamp": datetime.now(UTC).isoformat(),
                    },
                )
            except Exception as ws_error:  # noqa: BLE001 - WebSocket resilience: non-critical broadcast
                self._logger.warning(f"[BE-6123] agent:removed broadcast failed: {ws_error}")
