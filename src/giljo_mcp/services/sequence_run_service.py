# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


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
    VALID_REVIEWED_VIA,
    validate_sequence_run_project_ids,
    validate_sequence_run_project_statuses,
    validate_sequence_run_reviewed_project_ids,
    validate_sequence_run_reviewed_via,
)
from giljo_mcp.services._session_helpers import optional_tenant_session
from giljo_mcp.services.conductor_job_minter import broadcast_conductor_created, mint_conductor_job
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

VALID_RELEASE_MODES: frozenset[str] = frozenset({"graceful", "cancel"})

__all__ = ["MAX_CHAIN_MISSION_CHARS", "VALID_RELEASE_MODES", "SequenceRunService"]


class SequenceRunService(SequenceRunQueryMixin):

    def __init__(
        self,
        db_manager: DatabaseManager = None,
        tenant_manager: TenantManager = None,
        session: AsyncSession | None = None,
        websocket_manager=None,
    ):
        self.db_manager = db_manager
        self.tenant_manager = tenant_manager
        self._session = session
        self._websocket_manager = websocket_manager
        self._logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")

    def _get_session(self, tenant_key: str | None = None):
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

                    conductor_identity = await mint_conductor_job(
                        session,
                        tenant_key=effective_tenant_key,
                        run_id=run_id,
                    )
                    conductor_agent_id = conductor_identity["agent_id"]
                    run.conductor_agent_id = conductor_agent_id

                await session.commit()
                await session.refresh(run)
                result = _serialize(run)

            await self._broadcast_sequence_updated(run_id, effective_tenant_key)

            await broadcast_conductor_created(
                self._websocket_manager,
                tenant_key=effective_tenant_key,
                run_id=run_id,
                agent_id=conductor_identity["agent_id"],
                job_id=conductor_identity["job_id"],
                execution_id=conductor_identity["execution_id"],
            )

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
        else:
            new_status = "cancelled"

        return await self.update(run_id=run_id, tenant_key=tenant_key, status=new_status)

    async def deactivate_chain(
        self,
        *,
        run_id: str,
        tenant_key: str | None = None,
    ) -> dict[str, Any]:
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
        try:
            effective_tenant_key = tenant_key or (
                self.tenant_manager.get_current_tenant() if self.tenant_manager else None
            )
            if not effective_tenant_key:
                raise ValidationError(message="tenant_key is required", context={"operation": "purge_sequence_run"})

            async with self._get_session(effective_tenant_key) as session:
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


    _RUNNING_STATUSES: frozenset[str] = frozenset({"running", "stalled"})

    async def _is_ultralocked(self, session: AsyncSession, run: SequenceRun, tenant_key: str) -> bool:
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
                    return _serialize(run)

                remaining = [pid for pid in project_ids if pid != project_id]

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

                resolved_order = [pid for pid in (run.resolved_order or []) if pid != project_id]
                project_statuses = {pid: st for pid, st in (run.project_statuses or {}).items() if pid != project_id}

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
        via: str = "ui",
    ) -> dict[str, Any]:
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
            if via not in VALID_REVIEWED_VIA:
                raise ValidationError(
                    message=f"via must be one of {sorted(VALID_REVIEWED_VIA)}, got {via!r}",
                    context={"field": "via"},
                )

            async with self._get_session(effective_tenant_key) as session:
                run = await self._load_run(session, run_id, effective_tenant_key)

                members = set(run.project_ids or []) | set(run.resolved_order or [])
                if project_id not in members:
                    raise ValidationError(
                        message="project_id is not a member of this run",
                        context={"field": "project_id", "run_id": run_id},
                    )

                current = list(run.reviewed_project_ids or [])
                if project_id in current:
                    return _serialize(run)

                current.append(project_id)
                run.reviewed_project_ids = validate_sequence_run_reviewed_project_ids(current)
                via_map = dict(run.reviewed_via or {})
                via_map[project_id] = via
                run.reviewed_via = validate_sequence_run_reviewed_via(via_map)
                run.updated_at = datetime.now(UTC)

                await session.commit()
                await session.refresh(run)
                serialized = _serialize(run)

            await self._broadcast_sequence_updated(run_id, effective_tenant_key)
            self._logger.info(
                "Marked project %s reviewed (via=%s) in sequence_run %s (tenant=%s, reviewed=%d)",
                sanitize(project_id),
                sanitize(via),
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


_serialize = serialize_sequence_run
