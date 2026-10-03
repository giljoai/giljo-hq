# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.database import DatabaseManager
from giljo_mcp.domain.todo_kinds import classify_todo_kind
from giljo_mcp.exceptions import (
    OrchestrationError,
    ResourceNotFoundError,
    ValidationError,
)
from giljo_mcp.models import (
    AgentExecution,
    AgentJob,
    AgentTodoItem,
    Project,
)
from giljo_mcp.repositories.progress_repository import ProgressRepository
from giljo_mcp.schemas.service_responses import ProgressResult
from giljo_mcp.services._error_helpers import not_found_or_wrong_state_error
from giljo_mcp.services._session_helpers import optional_tenant_session
from giljo_mcp.tenant import TenantManager


logger = logging.getLogger(__name__)


_VALID_TODO_STATUSES = ("pending", "in_progress", "completed", "skipped")


def _normalize_todo_status(status: Any) -> str:
    return status if status in _VALID_TODO_STATUSES else "pending"


class ProgressService:

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
        self._todo_warning_timestamps: dict[str, datetime] = {}
        self._repo = ProgressRepository()

    def _get_session(self, tenant_key: str | None = None):
        return optional_tenant_session(self.db_manager, tenant_key, self._test_session)

    def _can_warn_missing_todos(self, job_id: str, cooldown_minutes: int = 5) -> bool:
        last_warning = self._todo_warning_timestamps.get(job_id)
        if not last_warning:
            return True
        elapsed = (datetime.now(UTC) - last_warning).total_seconds()
        return elapsed >= (cooldown_minutes * 60)

    def _record_todo_warning(self, job_id: str) -> None:
        self._todo_warning_timestamps[job_id] = datetime.now(UTC)

    async def report_progress(
        self,
        job_id: str,
        progress: dict[str, Any] | None = None,
        tenant_key: str | None = None,
        todo_items: list[dict] | None = None,
        todo_append: list[dict] | None = None,
        replace: bool = False,
    ) -> ProgressResult:

        try:
            if not tenant_key:
                tenant_key = self.tenant_manager.get_current_tenant()

            if not tenant_key:
                raise ValidationError(message="No tenant context available", context={"method": "report_progress"})

            if not job_id or not job_id.strip():
                raise ValidationError(message="job_id cannot be empty", context={"method": "report_progress"})

            if todo_append is not None and todo_items is not None:
                raise ValidationError(
                    message="Cannot use both todo_items and todo_append in the same call",
                    context={"method": "report_progress"},
                )

            progress, todo_items = self._derive_progress_dict(progress, todo_items, todo_append)

            job = None
            execution = None
            blocked_to_working = False
            async with self._get_session(tenant_key) as session:
                execution = await self._fetch_active_execution(session, job_id, tenant_key)
                if execution is None:
                    self._logger.info(
                        "report_progress no-op: job %s already completed (no active execution)",
                        job_id,
                    )
                    return ProgressResult(
                        status="noop",
                        message=f"Job {job_id} is already complete; progress report ignored (no active execution).",
                    )
                job = await self._fetch_job(session, job_id, tenant_key)

                execution.last_progress_at = datetime.now(UTC)

                old_resting_status = None
                if execution.status in ("blocked", "idle", "sleeping"):
                    old_resting_status = execution.status
                    execution.status = "working"
                    execution.block_reason = None
                    blocked_to_working = True

                    self._logger.info(
                        "Agent resumed from %s: agent_id=%s, job_id=%s",
                        old_resting_status,
                        execution.agent_id,
                        job_id,
                    )

                if "percent" in progress:
                    execution.progress = min(100, max(0, int(progress["percent"])))
                if "message" in progress or "current_step" in progress:
                    execution.current_task = progress.get("message") or progress.get("current_step")

                await self._process_todo_items(session, job, job_id, tenant_key, progress, todo_append, replace)

                await session.commit()
                await self._repo.refresh(session, execution)
                await self._repo.refresh(session, job)

                todo_items_payload = await self._resolve_todo_payload(session, tenant_key, job_id, todo_items)

                product_id: str | None = None
                if job and job.project_id:
                    product_id = await session.scalar(
                        select(Project.product_id).where(Project.tenant_key == tenant_key, Project.id == job.project_id)
                    )

            if not job:
                raise ResourceNotFoundError(
                    message=f"Job {job_id} not found after commit",
                    context={"job_id": job_id, "method": "report_progress"},
                )

            return await self._broadcast_progress_update(
                tenant_key,
                job_id,
                job,
                execution,
                progress,
                blocked_to_working,
                old_resting_status=old_resting_status,
                todo_items_payload=todo_items_payload,
                product_id=product_id,
            )
        except (ValidationError, ResourceNotFoundError):
            raise
        except Exception as e:
            self._logger.exception("Failed to report progress")
            raise OrchestrationError(
                message="Failed to report progress", context={"job_id": job_id, "error": str(e)}
            ) from e

    async def _resolve_todo_payload(
        self,
        session: AsyncSession,
        tenant_key: str,
        job_id: str,
        todo_items: list[dict] | None,
    ) -> list[dict] | None:
        if isinstance(todo_items, list) and len(todo_items) > 0:
            payload = [
                {
                    "content": str(item["content"])[:255],
                    "status": _normalize_todo_status(item.get("status", "pending")),
                }
                for item in todo_items
                if isinstance(item, dict) and item.get("content")
            ]
            return payload or None

        items = await self._repo.get_todo_items(session, tenant_key, job_id)
        if not items:
            return None
        return [{"content": item.content, "status": item.status} for item in items]

    async def _fetch_and_broadcast_progress(
        self,
        tenant_key: str,
        job_id: str,
        job: "AgentJob",
        execution: "AgentExecution",
        progress: dict[str, Any],
        todo_items_payload: list[dict] | None,
        product_id: str | None = None,
    ) -> None:
        if self._websocket_manager:
            await self._websocket_manager.broadcast_to_tenant(
                tenant_key=tenant_key,
                event_type="job:progress_update",
                data={
                    "job_id": job_id,
                    "project_id": str(job.project_id) if job.project_id else None,
                    "product_id": product_id,
                    "chain_conductor": bool((getattr(job, "job_metadata", None) or {}).get("chain_conductor", False)),
                    "agent_id": execution.agent_id,
                    "agent_display_name": execution.agent_display_name,
                    "agent_name": execution.agent_name,
                    "progress": progress,
                    "progress_percent": execution.progress,
                    "current_task": execution.current_task,
                    "todo_steps": job.job_metadata.get("todo_steps") if job.job_metadata else None,
                    "todo_items": todo_items_payload,
                    "last_progress_at": execution.last_progress_at.isoformat() if execution.last_progress_at else None,
                },
            )
            self._logger.info(f"[WEBSOCKET] Broadcasted job:progress_update for {job_id}")

    def _derive_progress_dict(
        self,
        progress: dict[str, Any] | None,
        todo_items: list[dict] | None,
        todo_append: list[dict] | None,
    ) -> tuple[dict[str, Any], list[dict] | None]:
        if todo_items is not None:
            if not isinstance(todo_items, list):
                raise ValidationError(
                    message="todo_items must be a list",
                    context={"method": "report_progress", "todo_items_type": type(todo_items).__name__},
                )

            completed_steps = len([t for t in todo_items if t.get("status") == "completed"])
            total_steps = len(todo_items)
            in_progress_items = [t for t in todo_items if t.get("status") == "in_progress"]
            current_step = in_progress_items[0].get("content") if in_progress_items else None
            percent = (completed_steps / total_steps * 100) if total_steps > 0 else 0

            progress = {
                "mode": "todo",
                "percent": percent,
                "total_steps": total_steps,
                "completed_steps": completed_steps,
                "current_step": current_step,
                "todo_items": todo_items,
            }
        elif todo_append is not None:
            if not isinstance(todo_append, list):
                raise ValidationError(
                    message="todo_append must be a list",
                    context={"method": "report_progress", "todo_append_type": type(todo_append).__name__},
                )
            progress = {"mode": "append"}
        elif progress is None:
            raise ValidationError(
                message="Either progress, todo_items, or todo_append must be provided",
                context={"method": "report_progress"},
            )
        elif not isinstance(progress, dict):
            raise ValidationError(
                message="progress must be a dict",
                context={"method": "report_progress", "progress_type": type(progress).__name__},
            )

        if todo_items is None and "todo_items" in progress:
            todo_items = progress.get("todo_items")

        for field, items in (("todo_items", todo_items), ("todo_append", todo_append)):
            for item in items or []:
                status = item.get("status") if isinstance(item, dict) else None
                if status is not None and status not in _VALID_TODO_STATUSES:
                    raise ValidationError(
                        message=f"Unknown TODO status {status!r} in {field}. Valid: {list(_VALID_TODO_STATUSES)}",
                        context={"method": "report_progress", "field": field, "status": str(status)[:50]},
                    )

        return progress, todo_items

    async def _fetch_active_execution(
        self,
        session: AsyncSession,
        job_id: str,
        tenant_key: str,
    ) -> AgentExecution | None:
        execution = await self._repo.get_active_execution(session, tenant_key, job_id)

        if not execution:
            decommissioned_exec = await self._repo.get_decommissioned_execution(session, tenant_key, job_id)

            if decommissioned_exec:
                raise ResourceNotFoundError(
                    message=(
                        f"Job {job_id} was decommissioned and cannot report progress. "
                        f"This typically happens when write_project_closeout(force=true) "
                        f"was called before complete_job()."
                    ),
                    context={
                        "job_id": job_id,
                        "method": "report_progress",
                        "execution_status": "decommissioned",
                        "cause": "Project was force-closed before this job called complete_job()",
                    },
                )

            completed_exec = await self._repo.get_completed_execution(session, tenant_key, job_id)
            if completed_exec:
                return None

            raise await not_found_or_wrong_state_error(
                session,
                tenant_key,
                job_id,
                expected_status="active",
                method="report_progress",
                db_manager=self.db_manager,
            )

        return execution

    async def _fetch_job(
        self,
        session: AsyncSession,
        job_id: str,
        tenant_key: str,
    ) -> AgentJob:
        job = await self._repo.get_job(session, tenant_key, job_id)

        if not job:
            raise ResourceNotFoundError(
                message=f"Job {job_id} not found", context={"job_id": job_id, "method": "report_progress"}
            )
        return job

    @staticmethod
    def _validated_job_metadata(metadata: dict) -> dict:
        from pydantic import ValidationError as PydanticValidationError

        from giljo_mcp.schemas.jsonb_validators import validate_agent_job_metadata

        try:
            return validate_agent_job_metadata(metadata)
        except (PydanticValidationError, ValueError, TypeError) as e:
            raise ValidationError(
                message="Invalid job progress metadata (current_step too long or malformed)",
                context={"method": "report_progress", "error": str(e)},
            ) from e

    async def _process_todo_items(
        self,
        session: AsyncSession,
        job: AgentJob,
        job_id: str,
        tenant_key: str,
        progress: dict[str, Any],
        todo_append: list[dict] | None,
        replace: bool = False,
    ) -> None:
        mode = progress.get("mode")
        if mode == "todo":
            total_steps = progress.get("total_steps")
            completed_steps = progress.get("completed_steps")
            current_step = progress.get("current_step")

            if (
                isinstance(total_steps, int)
                and total_steps > 0
                and isinstance(completed_steps, int)
                and 0 <= completed_steps <= total_steps
            ):
                from sqlalchemy.orm.attributes import flag_modified

                metadata = job.job_metadata or {}
                skipped_steps = progress.get("skipped_steps", 0)
                todo_steps = {
                    "total_steps": total_steps,
                    "completed_steps": completed_steps,
                    "skipped_steps": skipped_steps if isinstance(skipped_steps, int) else 0,
                }
                if isinstance(current_step, str) and current_step.strip():
                    todo_steps["current_step"] = current_step

                metadata["todo_steps"] = todo_steps
                job.job_metadata = self._validated_job_metadata(metadata)
                flag_modified(job, "job_metadata")

        todo_items = progress.get("todo_items")
        if isinstance(todo_items, list) and len(todo_items) > 0:
            normalized_incoming = [
                (str(item["content"])[:255], _normalize_todo_status(item.get("status", "pending")), seq)
                for seq, item in enumerate(todo_items)
                if isinstance(item, dict) and item.get("content")
            ]

            existing = await self._repo.get_todo_items(session, tenant_key, job_id)
            existing_rows = [(row.content, row.status, row.sequence) for row in existing]

            if normalized_incoming != existing_rows:
                existing_completed = sum(1 for row in existing if row.status == "completed")
                if existing_completed > 0:
                    incoming_completed = len([t for t in todo_items if t.get("status") == "completed"])
                    if incoming_completed < existing_completed:
                        raise ValidationError(
                            message=(
                                f"todo_items regression rejected: incoming list has {incoming_completed} completed "
                                f"items but DB already has {existing_completed}. todo_items is a FULL REPLACEMENT. "
                                f"To ADD new items without resubmitting the existing list, use todo_append — but note "
                                f"that todo_append CANNOT transition an existing pending item to completed. "
                                f"To modify the status of an existing item, first read the current list via "
                                f"get_context(categories=['todos'], job_id='{job_id}'), then resubmit the full "
                                f"reconstructed list via todo_items with the updated statuses."
                            ),
                            context={
                                "method": "report_progress",
                                "job_id": job_id,
                                "existing_completed": existing_completed,
                                "incoming_completed": incoming_completed,
                            },
                        )

                if not replace and len(normalized_incoming) < len(existing_rows):
                    raise ValidationError(
                        message=(
                            f"todo_items would SHRINK the list from {len(existing_rows)} to "
                            f"{len(normalized_incoming)} items and silently drop the missing ones. "
                            f"todo_items is a FULL REPLACEMENT — send the COMPLETE list (every "
                            f"pending + in_progress + completed item). To ADD items without "
                            f"resubmitting the full list, use todo_append. If you genuinely intend "
                            f"to REMOVE items, pass replace=True to confirm the destructive replace."
                        ),
                        context={
                            "method": "report_progress",
                            "job_id": job_id,
                            "existing_count": len(existing_rows),
                            "incoming_count": len(normalized_incoming),
                        },
                    )

                await self._repo.delete_todo_items(session, tenant_key, job_id)

                for content, status, seq in normalized_incoming:
                    await self._add_todo_row(session, job_id, tenant_key, content, status, seq)

        if isinstance(todo_append, list) and len(todo_append) > 0:
            await self._append_todo_items(session, job, job_id, tenant_key, todo_append)

    async def _add_todo_row(
        self, session: AsyncSession, job_id: str, tenant_key: str, content: str, status: str, sequence: int
    ) -> None:
        todo_item = AgentTodoItem(
            job_id=job_id,
            tenant_key=tenant_key,
            content=content,
            status=status,
            sequence=sequence,
            todo_kind=classify_todo_kind(content),
        )
        await self._repo.add_todo_item(session, todo_item)

    async def _append_todo_items(
        self,
        session: AsyncSession,
        job: AgentJob,
        job_id: str,
        tenant_key: str,
        todo_append: list[dict],
    ) -> None:
        max_seq = await self._repo.get_max_todo_sequence(session, tenant_key, job_id)

        appended_count = 0
        for i, item in enumerate(todo_append):
            if isinstance(item, dict) and item.get("content"):
                status = _normalize_todo_status(item.get("status", "pending"))
                await self._add_todo_row(
                    session, job_id, tenant_key, str(item["content"])[:255], status, max_seq + 1 + i
                )
                appended_count += 1

        if appended_count > 0:
            from sqlalchemy.orm.attributes import flag_modified

            await self._repo.flush(session)

            total_count = await self._repo.count_all_todos(session, tenant_key, job_id)
            completed_count = await self._repo.count_todos_by_status(session, tenant_key, job_id, "completed")
            skipped_count = await self._repo.count_todos_by_status(session, tenant_key, job_id, "skipped")

            metadata = job.job_metadata or {}
            metadata["todo_steps"] = {
                "total_steps": total_count,
                "completed_steps": completed_count,
                "skipped_steps": skipped_count,
            }
            job.job_metadata = self._validated_job_metadata(metadata)
            flag_modified(job, "job_metadata")

    async def _broadcast_progress_update(
        self,
        tenant_key: str,
        job_id: str,
        job: AgentJob,
        execution: AgentExecution,
        progress: dict[str, Any],
        blocked_to_working: bool,
        old_resting_status: str | None = None,
        todo_items_payload: list[dict] | None = None,
        product_id: str | None = None,
    ) -> ProgressResult:
        if blocked_to_working and self._websocket_manager:
            await self._websocket_manager.broadcast_to_tenant(
                tenant_key=tenant_key,
                event_type="agent:status_changed",
                data={
                    "job_id": str(job_id),
                    "agent_display_name": execution.agent_display_name or "unknown",
                    "old_status": old_resting_status or "blocked",
                    "status": "working",
                    "project_id": str(job.project_id),
                    "chain_conductor": bool((getattr(job, "job_metadata", None) or {}).get("chain_conductor", False)),
                    "duration_seconds": execution.duration_seconds,
                    "working_started_at": execution.working_started_at.isoformat()
                    if execution.working_started_at
                    else None,
                },
            )

        await self._fetch_and_broadcast_progress(
            tenant_key, job_id, job, execution, progress, todo_items_payload, product_id=product_id
        )

        warnings: list[str] = []
        todo_items = progress.get("todo_items")
        if (not isinstance(todo_items, list) or len(todo_items) == 0) and self._can_warn_missing_todos(job_id):
            warnings.append(
                "WARNING: todo_items missing! Dashboard Steps shows '--'. "
                "Include todo_items=[{content, status}] in every report_progress() call."
            )
            self._record_todo_warning(job_id)

        return ProgressResult(
            status="success",
            message="Progress reported successfully",
            warnings=warnings,
        )
