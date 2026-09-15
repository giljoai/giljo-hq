# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import logging
from typing import Any

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.database import DatabaseManager
from giljo_mcp.domain.project_status import IMMUTABLE_PROJECT_STATUSES
from giljo_mcp.models.tasks import Message
from giljo_mcp.repositories.agent_completion_repository import AgentCompletionRepository
from giljo_mcp.repositories.comm_thread_repository import CommThreadRepository
from giljo_mcp.repositories.message_repository import MessageRepository
from giljo_mcp.services._session_helpers import optional_tenant_session
from giljo_mcp.services.agent_terminal_cursor_service import forward_action_required_to_orchestrator
from giljo_mcp.tenant import TenantManager
from giljo_mcp.utils.log_sanitizer import sanitize


logger = logging.getLogger(__name__)

_TERMINAL_DEAD_STATUSES = frozenset({"closed", "decommissioned"})


class AutoBlockOutcome(list):

    def __init__(self, auto_blocked_ids: list[str] | None = None) -> None:
        super().__init__(auto_blocked_ids or [])
        self.notice: str | None = None


class MessageRoutingService:

    def __init__(
        self,
        db_manager: DatabaseManager,
        tenant_manager: TenantManager,
        websocket_manager: Any | None = None,
        test_session: AsyncSession | None = None,
    ):
        self.db_manager = db_manager
        self.tenant_manager = tenant_manager
        self._websocket_manager = websocket_manager
        self._test_session = test_session
        self._logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")
        self._repo = MessageRepository()

    def _get_session(self, tenant_key: str | None = None):
        return optional_tenant_session(self.db_manager, tenant_key, self._test_session)

    async def _auto_block_completed_recipients(
        self,
        session: AsyncSession,
        resolved_to_agents: list[str],
        project: Any,
        sender_display_name: str,
        is_broadcast_fanout: bool,
        requires_action: bool = False,
        message: Message | None = None,
    ) -> AutoBlockOutcome:
        if is_broadcast_fanout:
            return AutoBlockOutcome()

        if not requires_action:
            return AutoBlockOutcome()

        if project.status in IMMUTABLE_PROJECT_STATUSES:
            return AutoBlockOutcome()

        assert len(resolved_to_agents) <= 1, (
            "_auto_block_completed_recipients processes at most one recipient per "
            "call -- _redirect_terminal_recipient's rollback-on-failure is only "
            "transaction-safe for a single-element resolved_to_agents"
        )

        auto_blocked_ids = []
        notices: list[str] = []
        pending_broadcasts: list[dict[str, Any]] = []
        for recipient_id in resolved_to_agents:
            recipient_execution = await self._repo.get_execution_by_agent_id(session, project.tenant_key, recipient_id)

            if recipient_execution and recipient_execution.status == "complete":
                old_status = recipient_execution.status
                recipient_execution.status = "blocked"
                recipient_execution.block_reason = f"Received message from {sender_display_name} while completed"
                await self._repo.flush(session)

                auto_blocked_ids.append(recipient_id)

                if self._websocket_manager:
                    job_row = await self._repo.get_job_id_and_project_for_execution(
                        session, project.tenant_key, recipient_execution.job_id
                    )
                    pending_broadcasts.append(
                        {
                            "job_id": recipient_execution.job_id,
                            "agent_display_name": recipient_execution.agent_display_name,
                            "tenant_key": project.tenant_key,
                            "old_status": old_status,
                            "new_status": "blocked",
                            "project_id": str(job_row.project_id) if job_row else None,
                            "product_id": str(job_row.product_id) if job_row and job_row.product_id else None,
                        }
                    )

                self._logger.info(
                    f"[AUTO-BLOCK] Agent {sanitize(recipient_execution.agent_display_name)} "
                    f"({sanitize(recipient_id)}) auto-blocked: message from {sanitize(sender_display_name)}"
                )
            elif recipient_execution and recipient_execution.status in _TERMINAL_DEAD_STATUSES and message is not None:
                recipient_notice = await self._redirect_terminal_recipient(
                    session,
                    tenant_key=project.tenant_key,
                    project_id=project.id,
                    message=message,
                    dead_execution=recipient_execution,
                )
                notices.append(recipient_notice)

        if auto_blocked_ids:
            await session.commit()

            if self._websocket_manager and pending_broadcasts:
                schedule = getattr(self._websocket_manager, "schedule", None)
                for kwargs in pending_broadcasts:
                    try:
                        coro = self._websocket_manager.broadcast_job_status_update(**kwargs)
                        if callable(schedule):
                            schedule(coro)
                        else:
                            await coro
                    except (RuntimeError, ValueError) as e:
                        self._logger.warning(
                            f"Failed to broadcast auto-block status change for {kwargs.get('job_id')}: {e}"
                        )

        outcome = AutoBlockOutcome(auto_blocked_ids)
        outcome.notice = "; ".join(notices) if notices else None
        return outcome

    async def _redirect_terminal_recipient(
        self,
        session: AsyncSession,
        *,
        tenant_key: str,
        project_id: str,
        message: Message,
        dead_execution: Any,
    ) -> str:
        completion_repo = AgentCompletionRepository()
        thread_repo = CommThreadRepository()
        dead_label = dead_execution.agent_display_name or dead_execution.agent_id
        finished_prefix = f"RECIPIENT_FINISHED: {dead_label} is finished ({dead_execution.status})"

        live_orchestrator = await completion_repo.find_active_orchestrator_in_project(session, tenant_key, project_id)

        if live_orchestrator is None:
            logger.warning(
                "BE-9247: no live orchestrator to forward action-required message %s "
                "(dead recipient %s, project %s, status %s) -- leaving cursor unresolved",
                message.id,
                sanitize(dead_execution.agent_id),
                project_id,
                dead_execution.status,
            )
            thread = await thread_repo.get_by_id(session, tenant_key, message.thread_id) if message.thread_id else None
            fallback_owner = thread.next_action_owner if thread else None
            if fallback_owner:
                return (
                    f"{finished_prefix} and no live orchestrator was found to redirect to; "
                    f"{fallback_owner} currently holds this thread's baton."
                )
            return f"{finished_prefix} and no live orchestrator was found to redirect to."

        orchestrator_identities = {
            live_orchestrator.agent_id,
            live_orchestrator.job_id,
            live_orchestrator.agent_display_name,
            "orchestrator",
        }
        if message.from_agent_id in orchestrator_identities:
            return f"{finished_prefix}; you are the live orchestrator for this project -- respawn or redirect this work yourself."

        try:
            forwarded = await forward_action_required_to_orchestrator(
                session,
                tenant_key=tenant_key,
                project_id=project_id,
                thread_id=message.thread_id,
                dead_agent_id=dead_execution.agent_id,
                dead_agent_label=dead_label,
                terminal_status=dead_execution.status,
                original_content=message.content,
                original_from_display_name=message.from_display_name or message.from_agent_id or "unknown",
            )
            if forwarded is None:
                logger.warning(
                    "BE-9247: forward_action_required_to_orchestrator returned None for message %s "
                    "(dead recipient %s, project %s) despite a live orchestrator resolving moments "
                    "earlier -- leaving cursor unresolved",
                    message.id,
                    sanitize(dead_execution.agent_id),
                    project_id,
                )
                return f"{finished_prefix} and the redirect to the live orchestrator failed; the message was not forwarded."

            await thread_repo.ack_messages_for_participant(
                session, tenant_key, agent_id=dead_execution.agent_id, message_ids=[message.id]
            )
            await session.commit()
        except SQLAlchemyError:
            logger.exception(
                "BE-9273: forward-on-send redirect raised persisting/committing the "
                "forwarded message for message %s (dead recipient %s, destination "
                "orchestrator %s, project %s) -- the original message was NOT forwarded "
                "and its cursor is left un-acked",
                message.id,
                sanitize(dead_execution.agent_id),
                sanitize(live_orchestrator.agent_id),
                project_id,
            )
            try:
                await session.rollback()
            except SQLAlchemyError:
                logger.exception(
                    "BE-9273: rollback after failed forward-on-send also raised for message %s", message.id
                )
            return (
                f"{finished_prefix} and the redirect to the live orchestrator raised an error "
                "while saving the forward; the message was not forwarded."
            )

        return (
            f"{dead_label} was {dead_execution.status} -- your message was forwarded to "
            f"{live_orchestrator.agent_display_name} ({live_orchestrator.agent_id})."
        )

    async def auto_block_for_thread_post(
        self,
        *,
        message_id: str,
        to_participant: str | None,
        sender_display_name: str,
        requires_action: bool,
        tenant_key: str | None = None,
    ) -> AutoBlockOutcome:
        if not requires_action or not to_participant:
            return AutoBlockOutcome()

        tenant_key = tenant_key or self.tenant_manager.get_current_tenant()
        if not tenant_key:
            return AutoBlockOutcome()

        async with self._get_session(tenant_key) as session:
            message = await self._repo.get_message_by_id(session, tenant_key, message_id)
            if message is None or not message.project_id:
                return AutoBlockOutcome()

            project = await self._repo.get_project(session, tenant_key, message.project_id)
            if not project:
                return AutoBlockOutcome()

            return await self._auto_block_completed_recipients(
                session,
                [to_participant],
                project,
                sender_display_name,
                is_broadcast_fanout=False,
                requires_action=requires_action,
                message=message,
            )
