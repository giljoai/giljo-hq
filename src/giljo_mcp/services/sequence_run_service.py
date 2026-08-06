# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""SequenceRunService — owning service for sequence_runs (BE-6131a).

Owns ALL writes to ``sequence_runs``. Mirrors RoadmapService conventions:
session handling, tenant scoping, exceptions-on-error (post-0480 — never a
success-dict). Every read and write filters ``tenant_key``.

Validation discipline: execution_mode / status / review_policy / per-project
status values are membership-validated here BEFORE any DB write, raising
ValidationError (-> 422) rather than letting a DB constraint produce a 500.
JSONB columns (project_ids, resolved_order, project_statuses) are validated at
the write boundary via jsonb_validators.

Edition Scope: CE.
"""

import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.database import DatabaseManager
from giljo_mcp.exceptions import (
    BaseGiljoError,
    ResourceNotFoundError,
    ValidationError,
)
from giljo_mcp.models.agent_identity import AgentExecution, AgentJob
from giljo_mcp.models.base import generate_uuid
from giljo_mcp.models.projects import Project
from giljo_mcp.models.sequence_runs import CHAIN_TERMINAL_PROJECT_STATUSES, SequenceRun
from giljo_mcp.schemas.jsonb_validators import (
    validate_sequence_run_project_ids,
    validate_sequence_run_project_statuses,
    validate_sequence_run_reviewed_project_ids,
)
from giljo_mcp.services._session_helpers import optional_tenant_session
from giljo_mcp.services.conductor_job_minter import mint_conductor_job
from giljo_mcp.services.sequence_run_query_mixin import SequenceRunQueryMixin
from giljo_mcp.services.sequence_run_serialization import serialize_sequence_run
from giljo_mcp.services.sequence_run_validation import (
    MAX_CHAIN_MISSION_CHARS,
    refuse_mode_change_if_live,
    validate_create_fields,
    validate_update_fields,
)
from giljo_mcp.tenant import TenantManager
from giljo_mcp.utils.log_sanitizer import sanitize


logger = logging.getLogger(__name__)

# BE-6165e: release-verb modes. graceful -> terminated (conductor closed out);
# cancel -> cancelled (hard reset, the killed-terminals escape hatch).
VALID_RELEASE_MODES: frozenset[str] = frozenset({"graceful", "cancel"})

# Re-exported for back-compat callers that import the cap from this module
# (the canonical definition now lives in sequence_run_validation, BE-6185).
__all__ = ["MAX_CHAIN_MISSION_CHARS", "VALID_RELEASE_MODES", "SequenceRunService"]


class SequenceRunService(SequenceRunQueryMixin):
    """Service for the multi-project sequential runner state machine.

    Session-scoped; do not share across requests.
    """

    def __init__(
        self,
        db_manager: DatabaseManager = None,
        tenant_manager: TenantManager = None,
        session: AsyncSession | None = None,
        websocket_manager=None,
    ):
        self.db_manager = db_manager
        self.tenant_manager = tenant_manager
        self._session = session  # injected test session for transaction isolation
        self._websocket_manager = websocket_manager
        self._logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")

    def _get_session(self, tenant_key: str | None = None):
        """Yield a tenant-scoped DB session, honoring an injected test session (shared helper, BE-8000d)."""
        return optional_tenant_session(
            self.db_manager,
            tenant_key or (self.tenant_manager.get_current_tenant() if self.tenant_manager else None),
            self._session,
        )

    async def create(
        self,
        *,
        project_ids: list[str],
        resolved_order: list[str],
        execution_mode: str,
        review_policy: str = "per_card",
        status: str = "pending",
        current_index: int = 0,
        project_statuses: dict[str, str] | None = None,
        tenant_key: str | None = None,
    ) -> dict[str, Any]:
        """Create a new sequence run record.

        Returns the serialized run dict on success. Raises ValidationError (-> 422)
        for invalid field values. Never returns a success/failure dict on error.
        """
        try:
            effective_tenant_key = tenant_key or (
                self.tenant_manager.get_current_tenant() if self.tenant_manager else None
            )
            if not effective_tenant_key:
                raise ValidationError(message="tenant_key is required", context={"operation": "create_sequence_run"})

            ps = project_statuses or {}

            validate_create_fields(
                project_ids=project_ids,
                execution_mode=execution_mode,
                status=status,
                review_policy=review_policy,
                project_statuses=ps,
            )

            # JSONB boundary validation.
            validated_project_ids = validate_sequence_run_project_ids(project_ids)
            validated_resolved_order = validate_sequence_run_project_ids(resolved_order)
            validated_project_statuses = validate_sequence_run_project_statuses(ps)

            if current_index < 0:
                raise ValidationError(
                    message="current_index must be >= 0",
                    context={"field": "current_index"},
                )

            run_id = generate_uuid()
            async with self._get_session(effective_tenant_key) as session:
                # BE-6184: run row + its DEDICATED project-less conductor minted in ONE
                # savepoint: a failed conductor insert atomically removes the run, so a
                # run can never exist without an addressable conductor (no orphans). The
                # conductor owns NO project (conductor_project_id stays NULL).
                async with session.begin_nested():
                    run = SequenceRun(
                        id=run_id,
                        tenant_key=effective_tenant_key,
                        project_ids=validated_project_ids,
                        resolved_order=validated_resolved_order,
                        execution_mode=execution_mode,
                        status=status,
                        review_policy=review_policy,
                        current_index=current_index,
                        project_statuses=validated_project_statuses,
                    )
                    session.add(run)
                    await session.flush()

                    conductor_agent_id = await mint_conductor_job(
                        session,
                        tenant_key=effective_tenant_key,
                        run_id=run_id,
                    )
                    run.conductor_agent_id = conductor_agent_id

                await session.commit()
                await session.refresh(run)
                result = _serialize(run)

            # BE-6221a: broadcast sequence:updated on CREATE too (parity with update()).
            # A headless start_chain_run then lights up the dashboard election tickboxes
            # the instant the run is minted, and a multi-tab REST create no longer goes
            # stale until the next update(). No-ops when no websocket_manager is injected.
            await self._broadcast_sequence_updated(run_id, effective_tenant_key)

            self._logger.info(
                "Created sequence_run %s (tenant=%s, mode=%s, projects=%d, conductor_agent_id=%s)",
                run_id,
                effective_tenant_key,
                sanitize(execution_mode),
                len(validated_project_ids),
                conductor_agent_id,
            )
            return result
        except (BaseGiljoError, ResourceNotFoundError, ValidationError):
            raise
        except Exception as exc:
            self._logger.exception("Failed to create sequence_run")
            raise BaseGiljoError(message=str(exc), context={"operation": "create_sequence_run"}) from exc

    async def update(
        self,
        *,
        run_id: str,
        tenant_key: str | None = None,
        current_index: int | None = None,
        status: str | None = None,
        project_statuses: dict[str, str] | None = None,
        review_policy: str | None = None,
        execution_mode: str | None = None,
        resolved_order: list[str] | None = None,
        locked: bool | None = None,
        chain_mission: str | None = None,
        conductor_agent_id: str | None = None,
        conductor_project_id: str | None = None,
        conductor_label: str | None = None,
        clear_conductor: bool = False,
    ) -> dict[str, Any]:
        """Partial update of a sequence run.

        Only fields explicitly passed (non-None) are updated. Raises
        ResourceNotFoundError (-> 404) if the run does not exist under this
        tenant. Raises ValidationError (-> 422) for invalid field values.

        ``execution_mode`` + ``resolved_order`` are mutable here (BE-6165b) so the
        cockpit can set the mode at staging and reorder the cards pre-Stage;
        ``project_ids`` stays immutable (no param). The three ``conductor_*``
        fields are written by the sequence driver's self-registration (BE-6165c).

        ``locked`` is the FE-6171 edit lock: Stage -> True, Unstage -> False. Once
        the run is ultralocked (running, or a member reached ``staging_complete``)
        a request to UNLOCK (``locked=False``) is refused with ValidationError
        (-> 422) so the API and FE agree that Unstage is no longer available.

        ``chain_mission`` (BE-6185) is the conductor-owned cross-project plan: the
        FE edit pen PATCHes it pre-Implement. It is length-capped
        (``MAX_CHAIN_MISSION_CHARS``; over-cap -> ValidationError -> 422). A write
        is REFUSED once the run is ultralocked (the same staging-complete / running
        gate that freezes Unstage), making it read-only after Implement.
        """
        try:
            effective_tenant_key = tenant_key or (
                self.tenant_manager.get_current_tenant() if self.tenant_manager else None
            )
            if not effective_tenant_key:
                raise ValidationError(message="tenant_key is required", context={"operation": "update_sequence_run"})

            resolved_order, project_statuses = validate_update_fields(
                status=status,
                review_policy=review_policy,
                current_index=current_index,
                execution_mode=execution_mode,
                chain_mission=chain_mission,
                resolved_order=resolved_order,
                project_statuses=project_statuses,
            )

            async with self._get_session(effective_tenant_key) as session:
                result = await session.execute(
                    select(SequenceRun).where(
                        SequenceRun.id == run_id,
                        SequenceRun.tenant_key == effective_tenant_key,
                    )
                )
                run = result.scalar_one_or_none()
                if run is None:
                    raise ResourceNotFoundError(
                        message="sequence_run not found",
                        context={"run_id": run_id, "tenant_key": effective_tenant_key},
                    )

                # FE-6171 ultralock gate: refuse to UNLOCK (Unstage) once the run is
                # ultralocked (running, or a member reached staging_complete). Locking
                # (Stage) and other field updates stay allowed.
                #
                # BE-6185: the chain_mission write reuses the SAME gate — once the run
                # is ultralocked (Implement reached) the conductor-owned mission is
                # read-only. Compute the gate once and share it across both refusals.
                needs_ultralock_check = locked is False or chain_mission is not None
                ultralocked = (
                    await self._is_ultralocked(session, run, effective_tenant_key) if needs_ultralock_check else False
                )
                if locked is False and ultralocked:
                    raise ValidationError(
                        message=(
                            "Cannot unstage: the run is staging-complete or running. Use Terminate or Release instead."
                        ),
                        context={"field": "locked", "run_id": run_id, "status": run.status},
                    )
                if chain_mission is not None and ultralocked:
                    raise ValidationError(
                        message=(
                            "Cannot edit the chain mission: the run is staging-complete or running "
                            "(read-only after Implement)."
                        ),
                        context={"field": "chain_mission", "run_id": run_id, "status": run.status},
                    )
                if execution_mode is not None:
                    await refuse_mode_change_if_live(session, run, run_id, effective_tenant_key)

                if current_index is not None:
                    run.current_index = current_index
                if locked is not None:
                    run.locked = locked
                if status is not None:
                    run.status = status
                if review_policy is not None:
                    run.review_policy = review_policy
                if project_statuses is not None:
                    run.project_statuses = project_statuses
                if execution_mode is not None:
                    run.execution_mode = execution_mode
                if resolved_order is not None:
                    run.resolved_order = resolved_order
                if chain_mission is not None:
                    run.chain_mission = chain_mission
                if conductor_agent_id is not None:
                    run.conductor_agent_id = conductor_agent_id
                if conductor_project_id is not None:
                    run.conductor_project_id = conductor_project_id
                if conductor_label is not None:
                    run.conductor_label = conductor_label
                # FE-6180: explicit conductor reset on chain back-out (None values
                # alone can't clear, since the writes above are non-None-gated).
                if clear_conductor:
                    run.conductor_agent_id = None
                    run.conductor_project_id = None
                    run.conductor_label = None
                run.updated_at = datetime.now(UTC)

                await session.commit()
                await session.refresh(run)
                serialized = _serialize(run)

            await self._broadcast_sequence_updated(run_id, effective_tenant_key)
            self._logger.info(
                "Updated sequence_run %s (tenant=%s, status=%s, index=%s)",
                sanitize(run_id),
                effective_tenant_key,
                sanitize(run.status),
                sanitize(run.current_index),
            )
            return serialized
        except (BaseGiljoError, ResourceNotFoundError, ValidationError):
            raise
        except Exception as exc:
            self._logger.exception("Failed to update sequence_run")
            raise BaseGiljoError(message=str(exc), context={"operation": "update_sequence_run"}) from exc

    async def _broadcast_sequence_updated(self, run_id: str, tenant_key: str) -> None:
        """Fire sequence:updated WS event after a run update. Fire-and-forget: failure never breaks the update."""
        if self._websocket_manager is None:
            return
        try:
            event = {"type": "sequence:updated", "data": {"run_id": run_id}}
            await self._websocket_manager.broadcast_event_to_tenant(tenant_key, event)
        except Exception as exc:  # noqa: BLE001 — WS broadcast is a best-effort side-effect
            self._logger.warning("sequence:updated broadcast failed for run %s: %s", sanitize(run_id), exc)

    async def release(
        self,
        *,
        run_id: str,
        mode: str,
        tenant_key: str | None = None,
    ) -> dict[str, Any]:
        """End a run and free its membership (BE-6165e convenience verb).

        ``graceful`` -> status=terminated (the conductor drained + closed out the
        in-flight project): REQUIRES the in-flight project at ``current_index`` to
        already be in a terminal per-project status. ``cancel`` -> status=cancelled
        (no precondition — the "I killed all my terminals" escape hatch).

        Released downstream members are NOT mutated (``released`` is modeled as
        drop-out-of-run, NOT a status value): the run going terminal removes it
        from ``list_active`` so the FE unlocks their checkboxes. No ProjectStatus
        write. Routes through the existing ``update()`` writer — no new write path.
        """
        if mode not in VALID_RELEASE_MODES:
            raise ValidationError(
                message=f"Invalid release mode {mode!r}. Valid: {sorted(VALID_RELEASE_MODES)}",
                context={"field": "mode", "valid": sorted(VALID_RELEASE_MODES)},
            )

        if mode == "graceful":
            run = await self.get(run_id=run_id, tenant_key=tenant_key)
            resolved_order = run.get("resolved_order") or []
            idx = run.get("current_index", 0)
            in_flight_pid = resolved_order[idx] if 0 <= idx < len(resolved_order) else None
            project_statuses = run.get("project_statuses") or {}
            if in_flight_pid is not None and project_statuses.get(in_flight_pid) not in CHAIN_TERMINAL_PROJECT_STATUSES:
                raise ValidationError(
                    message=(
                        "graceful release requires the in-flight project to be closed out first; "
                        "use mode=cancel for a hard reset"
                    ),
                    context={"field": "mode", "run_id": run_id, "in_flight_project": in_flight_pid},
                )
            new_status = "terminated"
        else:  # cancel
            new_status = "cancelled"

        return await self.update(run_id=run_id, tenant_key=tenant_key, status=new_status)

    async def deactivate_chain(
        self,
        *,
        run_id: str,
        tenant_key: str | None = None,
    ) -> dict[str, Any]:
        """Back out of a chain: RESET every member to original + dissolve the run.

        FE-6178/FE-6180: the destructive "Deactivate Chain" rewind (distinct from
        Terminate, which preserves audit). Each member is returned to pre-stage state
        via the owning ``ProjectStagingService.reset_to_prestage`` (clears staging /
        mission / implementation_launched_at, status->inactive, HARD-DELETES the
        orchestrator + spawned agent jobs — no audit); a hard-deleted member is
        skipped. The run is then cancelled + conductor cleared. Raises
        ResourceNotFoundError if the run is not found for this tenant.
        """
        # Local import avoids a module-load cycle (ProjectService is a heavy facade).
        from giljo_mcp.services.project_service import ProjectService

        run = await self.get(run_id=run_id, tenant_key=tenant_key)
        member_ids: list[str] = run.get("resolved_order") or run.get("project_ids") or []

        proj_svc = ProjectService(
            db_manager=self.db_manager,
            tenant_manager=self.tenant_manager,
            test_session=self._session,
        )
        for pid in member_ids:
            try:
                await proj_svc.lifecycle.reset_to_prestage(pid, tenant_key=tenant_key)
            except ResourceNotFoundError:
                # Member hard-deleted — skip; the run dissolve below still runs.
                continue

        return await self.update(
            run_id=run_id,
            tenant_key=tenant_key,
            status="cancelled",
            clear_conductor=True,
        )

    async def purge_run(
        self,
        *,
        run_id: str,
        tenant_key: str | None = None,
    ) -> dict[str, Any]:
        """DELETE a finished run + its project-less conductor rows in one txn.

        The owning service is the ONLY writer that deletes ``sequence_runs`` — there
        is no parallel delete path. Called from ``complete_chain_run_if_finished``
        when every project in the chain is terminal: the durable record is each
        project row + its 360 memory, so the chain GROUPING is ephemeral and the
        dead ``completed`` run row is removed rather than left forever.

        In ONE tenant-scoped transaction:
          * DELETE the ``sequence_runs`` row (tenant-filtered). BE-9291: exactly one FK
            references it — ``comm_threads.sequence_run_id``, the chain hub's link —
            and it is ``ON DELETE SET NULL`` precisely so this delete stays safe. The
            hub thread OUTLIVES its run (the coordination history is durable; the chain
            grouping is not) and is simply unlinked here. Nothing cascades.
          * DELETE the conductor's ``AgentJob`` + ``AgentExecution`` rows. These are
            PROJECT-LESS (``project_id IS NULL``) and linked to the run ONLY via
            ``agent_jobs.job_metadata->>'run_id'`` (JSON, not an FK) — so they would
            ORPHAN unless deleted here. Executions go first (FK to agent_jobs),
            then the jobs (``agent_todo_items`` cascade at the DB level).

        IDEMPOTENT: the run / rows already gone is a clean no-op (the hook is
        best-effort and can fire more than once). Fires the existing
        ``sequence:updated`` broadcast so the FE re-hydrates and drops the run live.

        Returns a small summary dict (run_id + counts) for observability. Never
        returns a success/failure dict on error — raises (post-0480).
        """
        try:
            effective_tenant_key = tenant_key or (
                self.tenant_manager.get_current_tenant() if self.tenant_manager else None
            )
            if not effective_tenant_key:
                raise ValidationError(message="tenant_key is required", context={"operation": "purge_sequence_run"})

            async with self._get_session(effective_tenant_key) as session:
                # Resolve the run's project-less conductor jobs via the JSON run_id
                # link (mint_conductor_job stamps job_metadata.run_id). Tenant-scoped.
                job_id_rows = await session.execute(
                    select(AgentJob.job_id).where(
                        AgentJob.tenant_key == effective_tenant_key,
                        AgentJob.project_id.is_(None),
                        AgentJob.job_metadata["run_id"].astext == run_id,
                    )
                )
                conductor_job_ids = [row[0] for row in job_id_rows.all()]

                if conductor_job_ids:
                    await session.execute(
                        delete(AgentExecution).where(
                            AgentExecution.tenant_key == effective_tenant_key,
                            AgentExecution.job_id.in_(conductor_job_ids),
                        )
                    )
                    await session.execute(
                        delete(AgentJob).where(
                            AgentJob.tenant_key == effective_tenant_key,
                            AgentJob.job_id.in_(conductor_job_ids),
                        )
                    )

                run_delete = await session.execute(
                    delete(SequenceRun).where(
                        SequenceRun.id == run_id,
                        SequenceRun.tenant_key == effective_tenant_key,
                    )
                )
                await session.commit()

            await self._broadcast_sequence_updated(run_id, effective_tenant_key)
            self._logger.info(
                "Purged sequence_run %s (tenant=%s, run_rows=%d, conductor_jobs=%d)",
                run_id,
                effective_tenant_key,
                run_delete.rowcount or 0,
                len(conductor_job_ids),
            )
            return {
                "run_id": run_id,
                "run_deleted": bool(run_delete.rowcount),
                "conductor_jobs_deleted": len(conductor_job_ids),
            }
        except (BaseGiljoError, ResourceNotFoundError, ValidationError):
            raise
        except Exception as exc:
            self._logger.exception("Failed to purge sequence_run")
            raise BaseGiljoError(
                message=str(exc), context={"operation": "purge_sequence_run", "run_id": run_id}
            ) from exc

    # ------------------------------------------------------------------
    # Ultralock + membership editing (FE-6171)
    # ------------------------------------------------------------------

    # Run statuses that mean "implementation is in flight" -> ultralocked.
    _RUNNING_STATUSES: frozenset[str] = frozenset({"running", "stalled"})

    async def _is_ultralocked(self, session: AsyncSession, run: SequenceRun, tenant_key: str) -> bool:
        """Return True if the run is in the ultralock tier (FE-6171).

        Ultralock = staging-complete / implement-available / running. Reuses the
        EXISTING signals (no new concept beyond the ``locked`` flag):
          * ``run.status`` in {running, stalled}  -> implementation in flight; OR
          * any member project's ``projects.staging_status == 'staging_complete'``
            -> the Implement button is live for the chain.

        At this tier the server refuses Unstage (unlock) + member edits, so the
        API and FE agree. Tenant-scoped membership lookup.
        """
        if run.status in self._RUNNING_STATUSES:
            return True
        member_ids = list(run.project_ids or [])
        if not member_ids:
            return False
        stmt = (
            select(Project.id)
            .where(
                Project.tenant_key == tenant_key,
                Project.id.in_(member_ids),
                Project.staging_status == "staging_complete",
            )
            .limit(1)
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none() is not None

    async def remove_member(
        self,
        *,
        run_id: str,
        project_id: str,
        tenant_key: str | None = None,
    ) -> dict[str, Any]:
        """Remove ONE project from a run's membership (FE-6171 granular removal).

        Drops ``project_id`` from ``project_ids`` + ``resolved_order`` +
        ``project_statuses`` and recomputes ``current_index`` so it still points at
        the same in-flight project. Tenant-scoped; the SequenceRun owning service is
        the only writer of these columns (no parallel write path).

        Refuses (ValidationError -> 422) when the run is ultralocked (staging-
        complete / running) — only Terminate/Release may end such a run.

        Reduce-to-one: when removal leaves EXACTLY ONE project the run is dissolved
        (status=cancelled). The lone project is NOT auto-activated — a one-project
        chain is not a valid chain, so the run simply ends and the project returns
        to its normal pre-run state (the FE election surface shows the "select at
        least 2, or use play" warning; FE-6174b removed the old collapse-to-solo
        auto-flip). Idempotent: removing a project already absent is a no-op that
        returns the current run.
        """
        try:
            effective_tenant_key = tenant_key or (
                self.tenant_manager.get_current_tenant() if self.tenant_manager else None
            )
            if not effective_tenant_key:
                raise ValidationError(message="tenant_key is required", context={"operation": "remove_member"})
            if not isinstance(project_id, str) or not project_id.strip():
                raise ValidationError(
                    message="project_id must be a non-empty string",
                    context={"field": "project_id"},
                )

            async with self._get_session(effective_tenant_key) as session:
                run = await self._load_run(session, run_id, effective_tenant_key)

                if await self._is_ultralocked(session, run, effective_tenant_key):
                    raise ValidationError(
                        message=(
                            "Cannot edit membership: the run is staging-complete or running. "
                            "Use Terminate or Release instead."
                        ),
                        context={"field": "project_id", "run_id": run_id, "status": run.status},
                    )

                project_ids = list(run.project_ids or [])
                if project_id not in project_ids:
                    # Idempotent no-op: nothing to remove.
                    return _serialize(run)

                remaining = [pid for pid in project_ids if pid != project_id]

                # Reduce-to-one: removal leaves exactly one project. A one-project
                # chain is not viable, so dissolve the run (status=cancelled). The
                # lone project is deliberately left in its existing status — FE-6174b
                # removed the collapse-to-solo auto-activate (new rule: reduce-to-1 is
                # a warning, never an auto-flip to active).
                if len(remaining) == 1:
                    lone_project_id = remaining[0]
                    run.status = "cancelled"
                    run.updated_at = datetime.now(UTC)
                    await session.commit()
                    await session.refresh(run)
                    serialized = _serialize(run)
                    self._logger.info(
                        "Dissolved sequence_run %s (reduced to lone project %s, tenant=%s; no auto-activate)",
                        sanitize(run_id),
                        lone_project_id,
                        effective_tenant_key,
                    )
                    return serialized

                # Normal removal: still >= 2 members remain.
                resolved_order = [pid for pid in (run.resolved_order or []) if pid != project_id]
                project_statuses = {pid: st for pid, st in (run.project_statuses or {}).items() if pid != project_id}

                # Recompute current_index so it keeps pointing at the same in-flight
                # project; clamp into range if the removed project was at/before it.
                old_order = list(run.resolved_order or [])
                old_index = run.current_index or 0
                in_flight_pid = old_order[old_index] if 0 <= old_index < len(old_order) else None
                if in_flight_pid is not None and in_flight_pid in resolved_order:
                    new_index = resolved_order.index(in_flight_pid)
                else:
                    new_index = min(old_index, max(len(resolved_order) - 1, 0))

                run.project_ids = remaining
                run.resolved_order = resolved_order
                run.project_statuses = project_statuses
                run.current_index = new_index
                run.updated_at = datetime.now(UTC)
                await session.commit()
                await session.refresh(run)
                serialized = _serialize(run)

            self._logger.info(
                "Removed project %s from sequence_run %s (tenant=%s, remaining=%d)",
                sanitize(project_id),
                sanitize(run_id),
                effective_tenant_key,
                len(remaining),
            )
            return serialized
        except (BaseGiljoError, ResourceNotFoundError, ValidationError):
            raise
        except Exception as exc:
            self._logger.exception("Failed to remove member from sequence_run")
            raise BaseGiljoError(message=str(exc), context={"operation": "remove_member", "run_id": run_id}) from exc

    async def mark_member_reviewed(
        self,
        *,
        run_id: str,
        project_id: str,
        tenant_key: str | None = None,
    ) -> dict[str, Any]:
        """Durably record that a chain member has been reviewed (BE-9098).

        Append-only write to ``reviewed_project_ids``, tenant-scoped. This is the
        persistence the FE was missing: before it, review acknowledgment lived only
        in a client-side Pinia Map that reset on every refresh, so the Review badge
        returned on each page load.

        NON-GATING by construction: writes ONLY ``reviewed_project_ids`` and NEVER
        ``project_statuses`` — so purge_run and chain advancement (which key on
        CHAIN_TERMINAL_PROJECT_STATUSES) are wholly unaffected, and the known
        stale-spread eject risk on project_statuses is avoided.

        Idempotent: marking an already-reviewed project is a clean no-op that returns
        the current run. Raises ResourceNotFoundError (-> 404) if the run is not found
        for this tenant, ValidationError (-> 422) if ``project_id`` is empty or is not
        a member of this run. The SequenceRun owning service is the only writer of this
        column (no parallel write path).
        """
        try:
            effective_tenant_key = tenant_key or (
                self.tenant_manager.get_current_tenant() if self.tenant_manager else None
            )
            if not effective_tenant_key:
                raise ValidationError(message="tenant_key is required", context={"operation": "mark_member_reviewed"})
            if not isinstance(project_id, str) or not project_id.strip():
                raise ValidationError(
                    message="project_id must be a non-empty string",
                    context={"field": "project_id"},
                )

            async with self._get_session(effective_tenant_key) as session:
                run = await self._load_run(session, run_id, effective_tenant_key)

                # Membership guard: only a project actually in this run may be marked
                # reviewed (keeps the array a bounded subset of members).
                members = set(run.project_ids or []) | set(run.resolved_order or [])
                if project_id not in members:
                    raise ValidationError(
                        message="project_id is not a member of this run",
                        context={"field": "project_id", "run_id": run_id},
                    )

                current = list(run.reviewed_project_ids or [])
                if project_id in current:
                    # Idempotent no-op — already reviewed.
                    return _serialize(run)

                current.append(project_id)
                # Reassign (not in-place mutate) so SQLAlchemy flags the JSONB dirty;
                # the boundary validator caps length + item shape.
                run.reviewed_project_ids = validate_sequence_run_reviewed_project_ids(current)
                run.updated_at = datetime.now(UTC)

                await session.commit()
                await session.refresh(run)
                serialized = _serialize(run)

            await self._broadcast_sequence_updated(run_id, effective_tenant_key)
            self._logger.info(
                "Marked project %s reviewed in sequence_run %s (tenant=%s, reviewed=%d)",
                sanitize(project_id),
                sanitize(run_id),
                effective_tenant_key,
                len(current),
            )
            return serialized
        except (BaseGiljoError, ResourceNotFoundError, ValidationError):
            raise
        except Exception as exc:
            self._logger.exception("Failed to mark member reviewed on sequence_run")
            raise BaseGiljoError(
                message=str(exc), context={"operation": "mark_member_reviewed", "run_id": run_id}
            ) from exc

    async def _load_run(self, session: AsyncSession, run_id: str, tenant_key: str) -> SequenceRun:
        result = await session.execute(
            select(SequenceRun).where(
                SequenceRun.id == run_id,
                SequenceRun.tenant_key == tenant_key,
            )
        )
        run = result.scalar_one_or_none()
        if run is None:
            raise ResourceNotFoundError(
                message="sequence_run not found",
                context={"run_id": run_id, "tenant_key": tenant_key},
            )
        return run


# Serialization extracted to sequence_run_serialization.py (800-line guardrail,
# BE-6184). Aliased to the prior private name so all internal call sites are unchanged.
_serialize = serialize_sequence_run
