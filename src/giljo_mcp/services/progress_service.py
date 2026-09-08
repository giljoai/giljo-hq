# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
ProgressService - Agent job progress reporting.

Extracted from OrchestrationService (Handover 0769) as part of the facade pattern
refactoring to keep individual modules under 1000 lines.

Responsibilities:
- Progress reporting (report_progress)
- TODO item management (todo_items, todo_append)
- WebSocket broadcast for progress updates
- Missing TODO warning throttling
"""

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


# BE-6070 (F8): the canonical TODO statuses + the normalization the persist path
# applies. Centralized so the unchanged-list comparison and the in-hand WS
# payload build produce the EXACT shape that gets stored (status clamped,
# content truncated), keeping all three paths byte-identical.
_VALID_TODO_STATUSES = ("pending", "in_progress", "completed", "skipped")


def _normalize_todo_status(status: Any) -> str:
    """Clamp an incoming TODO status to the allowed set (default 'pending')."""
    return status if status in _VALID_TODO_STATUSES else "pending"


class ProgressService:
    """
    Service for agent job progress reporting.

    Extracted from OrchestrationService to reduce module size.
    """

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
        # Handover 0406: Track todo_items warning timestamps (throttle 1 per 5 min per job)
        self._todo_warning_timestamps: dict[str, datetime] = {}
        self._repo = ProgressRepository()

    def _get_session(self, tenant_key: str | None = None):
        """Yield a tenant-scoped DB session, honoring an injected test session (shared helper, BE-8000d)."""
        return optional_tenant_session(self.db_manager, tenant_key, self._test_session)

    def _can_warn_missing_todos(self, job_id: str, cooldown_minutes: int = 5) -> bool:
        """
        Check if we can send a todo_items warning (throttle: 1 per N minutes per job).

        Args:
            job_id: Job UUID
            cooldown_minutes: Minimum minutes between warnings (default: 5)

        Returns:
            True if we can warn, False if throttled
        """
        last_warning = self._todo_warning_timestamps.get(job_id)
        if not last_warning:
            return True
        elapsed = (datetime.now(UTC) - last_warning).total_seconds()
        return elapsed >= (cooldown_minutes * 60)

    def _record_todo_warning(self, job_id: str) -> None:
        """
        Record that a todo_items warning was sent for this job.

        Args:
            job_id: Job UUID
        """
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
        """
        Report job progress (store message in message queue).

        Args:
            job_id: Job UUID
            progress: Progress data dict (legacy format, optional)
            tenant_key: Optional tenant key (uses current if not provided)
            todo_items: Simplified TODO items array (Handover 0392)
                        [{"content": "Task A", "status": "completed"}, ...]
            todo_append: Steps to APPEND to existing TODO list (Handover 0827d).
                         Preserves existing completed steps, adds new ones.
            replace: Opt-in to a destructive full replacement (BE-6209a). When
                     False (default) a ``todo_items`` list SHORTER than the
                     persisted one is rejected, since ``todo_items`` is a full
                     replacement and a partial list would silently drop the
                     missing rows. Pass True only when you intend to remove items.

        Returns:
            ProgressResult with status, message, and warnings.

        Example (new simplified format):
            >>> result = await service.report_progress(
            ...     job_id="job-123",
            ...     todo_items=[
            ...         {"content": "Task A", "status": "completed"},
            ...         {"content": "Task B", "status": "in_progress"},
            ...         {"content": "Task C", "status": "pending"}
            ...     ]
            ... )

        Example (legacy format, still supported):
            >>> result = await service.report_progress(
            ...     job_id="job-123",
            ...     progress={"percent": 50, "message": "Half done"}
            ... )
        """

        try:
            # Use provided tenant_key or get from context
            if not tenant_key:
                tenant_key = self.tenant_manager.get_current_tenant()

            if not tenant_key:
                raise ValidationError(message="No tenant context available", context={"method": "report_progress"})

            if not job_id or not job_id.strip():
                raise ValidationError(message="job_id cannot be empty", context={"method": "report_progress"})

            # Handover 0827d: todo_append is mutually exclusive with todo_items
            if todo_append is not None and todo_items is not None:
                raise ValidationError(
                    message="Cannot use both todo_items and todo_append in the same call",
                    context={"method": "report_progress"},
                )

            # Derive progress dict from todo_items/todo_append or validate raw progress
            progress, todo_items = self._derive_progress_dict(progress, todo_items, todo_append)

            # Fetch execution and job info for progress tracking
            job = None
            execution = None
            blocked_to_working = False
            async with self._get_session(tenant_key) as session:
                execution = await self._fetch_active_execution(session, job_id, tenant_key)
                if execution is None:
                    # BE-6211d (S-4b): the job already completed/closed cleanly — a
                    # late progress report is a benign no-op, not a 404. The protocol
                    # tells agents to report after every action, so a post-completion
                    # report must not error.
                    self._logger.info(
                        "report_progress no-op: job %s already completed (no active execution)",
                        job_id,
                    )
                    return ProgressResult(
                        status="noop",
                        message=f"Job {job_id} is already complete; progress report ignored (no active execution).",
                    )
                job = await self._fetch_job(session, job_id, tenant_key)

                # Update execution progress fields
                execution.last_progress_at = datetime.now(UTC)

                # Auto-wake transition: if an agent reports progress while in a
                # resting state (blocked/idle/sleeping), resume "working" status.
                # Handover 0880: extended from blocked-only to all resting states.
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

                # Extract progress percentage and current task from progress dict
                if "percent" in progress:
                    execution.progress = min(100, max(0, int(progress["percent"])))
                if "message" in progress or "current_step" in progress:
                    execution.current_task = progress.get("message") or progress.get("current_step")

                # Process TODO items (replace or append strategies)
                await self._process_todo_items(session, job, job_id, tenant_key, progress, todo_append, replace)

                await session.commit()
                await self._repo.refresh(session, execution)
                await self._repo.refresh(session, job)

                # BE-6070 (F8b): build the WS todo payload here, on the SAME open
                # session, instead of opening a 2nd session to re-SELECT the rows
                # we just wrote. The hot replace path uses the in-hand list with no
                # query at all.
                todo_items_payload = await self._resolve_todo_payload(session, tenant_key, job_id, todo_items)

                # BE-9525c: job:progress_update was one of the emitters BE-9518 left
                # without product_id ("do not reliably carry product_id" per the FE
                # router's own comment). One cheap extra lookup, on the same open
                # session, so the broadcast below can carry it. None for a
                # project-less job (there is no such case for report_progress today,
                # but the column is nullable on AgentJob in principle).
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

            # Broadcast updates and build warnings
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
        except Exception as e:  # Broad catch: service boundary, wraps in BaseGiljoError
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
        """Build the WS todo payload from in-hand data (BE-6070 F8b).

        Hot path: when the agent sent a full ``todo_items`` list, derive the
        payload directly from it (normalized to the stored shape) — no query.
        For append / legacy-progress calls, read the current full list on the
        SAME already-open session (identical to the old 2nd-session SELECT, minus
        the extra session). Returns None when there are no items.
        """
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
        """Broadcast progress update via WebSocket using an in-hand todo payload.

        BE-6070 (F8b): the payload is computed by the caller on the request's open
        session, so this method no longer opens a 2nd session to re-SELECT rows.

        BE-9525c: ``product_id`` is additive, resolved by the caller on the same
        open session (this emitter never queries for it itself).
        """
        # Handover 0386: Direct WebSocket emission for progress updates
        # BE-9012d: MessageService/send_message are retired; this note is historical
        # (progress updates never went through the bus, by design).
        # Progress is already persisted in execution.progress and job.job_metadata["todo_steps"]
        # We only need to emit a WebSocket event for real-time UI updates
        try:
            if self._websocket_manager:
                await self._websocket_manager.broadcast_to_tenant(
                    tenant_key=tenant_key,
                    event_type="job:progress_update",
                    data={
                        "job_id": job_id,
                        "project_id": str(job.project_id) if job.project_id else None,
                        # BE-9525c: additive -- was missing on this emitter (BE-9518
                        # left it out); None for a project-less job, same as project_id.
                        "product_id": product_id,
                        # BE-6229: ride the chain_conductor flag on the WS payload
                        # (mirrors the REST serializer) so the FE JobsTab filter can
                        # exclude the project-less conductor on the live path too —
                        # completes BE-6200 (#6) on the WebSocket path.
                        "chain_conductor": bool(
                            (getattr(job, "job_metadata", None) or {}).get("chain_conductor", False)
                        ),
                        "agent_id": execution.agent_id,
                        "agent_display_name": execution.agent_display_name,
                        "agent_name": execution.agent_name,
                        "progress": progress,
                        "progress_percent": execution.progress,
                        "current_task": execution.current_task,
                        "todo_steps": job.job_metadata.get("todo_steps") if job.job_metadata else None,
                        "todo_items": todo_items_payload,  # Handover 0402: Include for Plan/TODOs tab
                        "last_progress_at": execution.last_progress_at.isoformat()
                        if execution.last_progress_at
                        else None,
                    },
                )
                self._logger.info(f"[WEBSOCKET] Broadcasted job:progress_update for {job_id}")
        except Exception as ws_error:  # noqa: BLE001 - WebSocket resilience: non-critical broadcast
            self._logger.warning(f"[WEBSOCKET] Failed to broadcast progress: {ws_error}")

    def _derive_progress_dict(
        self,
        progress: dict[str, Any] | None,
        todo_items: list[dict] | None,
        todo_append: list[dict] | None,
    ) -> tuple[dict[str, Any], list[dict] | None]:
        """Derive a normalised progress dict from the various input formats.

        Returns:
            Tuple of (progress_dict, todo_items).
        """
        # Handover 0392: Support top-level todo_items parameter (simplified format)
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
            # Handover 0827d: todo_append can be called standalone
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

        # Extract todo_items from progress dict if not already set (backwards compatibility)
        if todo_items is None and "todo_items" in progress:
            todo_items = progress.get("todo_items")

        return progress, todo_items

    async def _fetch_active_execution(
        self,
        session: AsyncSession,
        job_id: str,
        tenant_key: str,
    ) -> AgentExecution | None:
        """Fetch the latest active execution for a job.

        Returns the active execution, or ``None`` (signalling a tolerant no-op — see
        BE-6211d below) when no active execution exists but a cleanly completed/closed
        one does. Raises ResourceNotFoundError for the decommissioned and
        genuinely-not-found cases.
        """
        execution = await self._repo.get_active_execution(session, tenant_key, job_id)

        if not execution:
            # Check if decommissioned for better diagnostics (Handover 0824).
            # Checked FIRST so the decommissioned diagnostic stays intact.
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

            # BE-6211d (S-4b): a clean completed/closed execution -> tolerate a late
            # report_progress as a no-op (the protocol says report after every action),
            # signalled to the caller by returning None instead of raising a 404.
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
        """Fetch the job record, raising on not-found."""
        # TENANT ISOLATION: Filter by tenant_key (Phase D audit fix)
        job = await self._repo.get_job(session, tenant_key, job_id)

        if not job:
            raise ResourceNotFoundError(
                message=f"Job {job_id} not found", context={"job_id": job_id, "method": "report_progress"}
            )
        return job

    @staticmethod
    def _validated_job_metadata(metadata: dict) -> dict:
        """Validate job_metadata at the write boundary (BE-9000h).

        Surfaces an oversize/malformed agent-supplied field (notably
        ``todo_steps.current_step``) as a clean ValidationError instead of
        letting a raw blob reach the JSONB column or wrapping it as a generic
        OrchestrationError.
        """
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
        """Persist TODO-style steps tracking data (replace or append strategies)."""
        # Optional TODO-style steps tracking for Steps column (Handover 0297)
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

        # Handover 0402: Store todo_items in dedicated table for Plan/TODOs tab display
        todo_items = progress.get("todo_items")
        if isinstance(todo_items, list) and len(todo_items) > 0:
            # Build the exact (content, status, sequence) rows that WOULD be
            # persisted: skip no-content entries, sequence is the enumerate index
            # (matching the insert loop below — sequences may have gaps).
            normalized_incoming = [
                (str(item["content"])[:255], _normalize_todo_status(item.get("status", "pending")), seq)
                for seq, item in enumerate(todo_items)
                if isinstance(item, dict) and item.get("content")
            ]

            # BE-6070 (F8a): fetch the current rows ONCE (this also yields
            # existing_completed, folding in the old count query). If the incoming
            # list is identical to what's stored, skip the DELETE-all +
            # re-INSERT-all entirely — no dead tuples, no index churn. This is the
            # dominant case: agents re-send the same list every report_progress.
            existing = await self._repo.get_todo_items(session, tenant_key, job_id)
            existing_rows = [(row.content, row.status, row.sequence) for row in existing]

            if normalized_incoming != existing_rows:
                # Regression guard: reject todo_items that would lose completed work.
                # Agents sometimes rebuild the list from scratch, accidentally
                # resetting completed items back to pending. This check prevents that.
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

                # BE-6209a: guard the broader silent-wipe footgun. todo_items is
                # a FULL REPLACEMENT, so a SHORTER incoming list DELETES the
                # missing rows even when completed-count is preserved (e.g. an
                # agent re-sends only the finished items and drops still-pending
                # ones). The completed-regression guard above misses this. Reject
                # a shrink unless the caller explicitly opts in with replace=True.
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

                # Delete existing items for this job (replace strategy)
                # TENANT ISOLATION: Filter by tenant_key (Phase D audit fix)
                await self._repo.delete_todo_items(session, tenant_key, job_id)

                # Insert the normalized rows built above.
                for content, status, seq in normalized_incoming:
                    todo_item = AgentTodoItem(
                        job_id=job_id,
                        tenant_key=tenant_key,
                        content=content,
                        status=status,
                        sequence=seq,
                        # BE-9012b (D7): stamp the self-closeout kind once, at write,
                        # so the completion gate reads a durable marker instead of
                        # re-matching keyword regexes at complete_job time.
                        todo_kind=classify_todo_kind(content),
                    )
                    await self._repo.add_todo_item(session, todo_item)

        # Handover 0827d: Append new items without deleting existing ones
        if isinstance(todo_append, list) and len(todo_append) > 0:
            await self._append_todo_items(session, job, job_id, tenant_key, todo_append)

    async def _append_todo_items(
        self,
        session: AsyncSession,
        job: AgentJob,
        job_id: str,
        tenant_key: str,
        todo_append: list[dict],
    ) -> None:
        """Append new TODO items after existing ones and recount totals."""
        # Find current max sequence number
        max_seq = await self._repo.get_max_todo_sequence(session, tenant_key, job_id)

        # Insert only new items after existing ones
        appended_count = 0
        for i, item in enumerate(todo_append):
            if isinstance(item, dict) and item.get("content"):
                status = item.get("status", "pending")
                if status not in ("pending", "in_progress", "completed", "skipped"):
                    status = "pending"

                content = str(item["content"])[:255]
                todo_item = AgentTodoItem(
                    job_id=job_id,
                    tenant_key=tenant_key,
                    content=content,
                    status=status,
                    sequence=max_seq + 1 + i,
                    # BE-9012b (D7): classify the self-closeout kind at write time
                    # (same durable marker the completion gate reads).
                    todo_kind=classify_todo_kind(content),
                )
                await self._repo.add_todo_item(session, todo_item)
                appended_count += 1

        # Recount totals and update JSONB summary
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
        """Broadcast WebSocket events and return the progress result with warnings."""
        # Broadcast resting->working AFTER commit succeeds (not before)
        if blocked_to_working and self._websocket_manager:
            try:
                await self._websocket_manager.broadcast_to_tenant(
                    tenant_key=tenant_key,
                    event_type="agent:status_changed",
                    data={
                        "job_id": str(job_id),
                        "agent_display_name": execution.agent_display_name or "unknown",
                        "old_status": old_resting_status or "blocked",
                        "status": "working",
                        "project_id": str(job.project_id),
                        # BE-6229: ride the chain_conductor flag (mirrors REST serializer).
                        "chain_conductor": bool(
                            (getattr(job, "job_metadata", None) or {}).get("chain_conductor", False)
                        ),
                        "duration_seconds": execution.duration_seconds,  # BE-5107
                        "working_started_at": execution.working_started_at.isoformat()
                        if execution.working_started_at
                        else None,
                    },
                )
            except Exception as _exc:  # Broad catch: WebSocket resilience, non-critical broadcast
                self._logger.exception(
                    "Failed to broadcast %s->working for agent %s",
                    old_resting_status or "blocked",
                    execution.agent_id,
                )

        await self._fetch_and_broadcast_progress(
            tenant_key, job_id, job, execution, progress, todo_items_payload, product_id=product_id
        )

        # Handover 0406: Reactive warning for missing todo_items
        warnings: list[str] = []
        todo_items = progress.get("todo_items")
        # Check throttle - only warn once per 5 minutes per job
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
