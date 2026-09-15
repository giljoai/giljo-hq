# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import logging
from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.models.tasks import Message
from giljo_mcp.repositories.agent_completion_repository import AgentCompletionRepository
from giljo_mcp.repositories.comm_thread_repository import CommThreadRepository
from giljo_mcp.utils.log_sanitizer import sanitize


logger = logging.getLogger(__name__)


def build_forwarded_annotation(
    *,
    original_content: str,
    original_from_display_name: str,
    dead_agent_label: str,
    dead_agent_id: str,
    terminal_status: str,
) -> str:
    return (
        f"[FORWARDED: originally addressed to '{dead_agent_label}' ({dead_agent_id}), "
        f"now {terminal_status} and no longer reachable. Redirecting to you as the "
        f"live orchestrator so this action-required message is not silently dropped.]\n\n"
        f"--- original message from {original_from_display_name} ---\n"
        f"{original_content}"
    )


async def forward_action_required_to_orchestrator(
    session: AsyncSession,
    *,
    tenant_key: str,
    project_id: str,
    thread_id: str | None,
    dead_agent_id: str,
    dead_agent_label: str,
    terminal_status: str,
    original_content: str,
    original_from_display_name: str,
) -> Message | None:
    completion_repo = AgentCompletionRepository()
    orchestrator_execution = await completion_repo.find_active_orchestrator_in_project(session, tenant_key, project_id)
    if orchestrator_execution is None:
        return None

    thread_repo = CommThreadRepository()
    annotated_content = build_forwarded_annotation(
        original_content=original_content,
        original_from_display_name=original_from_display_name,
        dead_agent_label=dead_agent_label,
        dead_agent_id=dead_agent_id,
        terminal_status=terminal_status,
    )
    return await thread_repo.persist_thread_message(
        session,
        tenant_key=tenant_key,
        thread_id=thread_id,
        project_id=project_id,
        content=annotated_content,
        from_agent_id=dead_agent_id,
        from_display_name=f"{dead_agent_label} (forwarded, no longer active)",
        message_type="direct",
        priority="high",
        requires_action=True,
        recipient_ids=[orchestrator_execution.agent_id],
    )


@dataclass
class TerminalCursorResolution:

    auto_acked_count: int = 0
    forwarded_count: int = 0
    unforwarded_action_required_ids: list[str] = field(default_factory=list)


async def resolve_terminal_agent_cursors(
    session: AsyncSession,
    *,
    tenant_key: str,
    project_id: str,
    agent_id: str,
    agent_label: str,
    terminal_status: str,
) -> TerminalCursorResolution:
    completion_repo = AgentCompletionRepository()
    thread_repo = CommThreadRepository()

    live_messages = await completion_repo.get_undrained_messages_for_agent(session, tenant_key, project_id, agent_id)

    outcome = TerminalCursorResolution()
    ids_to_ack: list[str] = []

    for message in live_messages:
        if message.requires_action and not message.auto_generated:
            forwarded = await forward_action_required_to_orchestrator(
                session,
                tenant_key=tenant_key,
                project_id=project_id,
                thread_id=message.thread_id,
                dead_agent_id=agent_id,
                dead_agent_label=agent_label,
                terminal_status=terminal_status,
                original_content=message.content,
                original_from_display_name=message.from_display_name or message.from_agent_id or "unknown",
            )
            if forwarded is not None:
                outcome.forwarded_count += 1
                ids_to_ack.append(message.id)
            else:
                outcome.unforwarded_action_required_ids.append(message.id)
                logger.warning(
                    "BE-9242: no live orchestrator to forward action-required message %s "
                    "(dead agent %s, project %s, status %s) -- leaving cursor unresolved",
                    sanitize(message.id),
                    sanitize(agent_id),
                    sanitize(project_id),
                    sanitize(terminal_status),
                )
        else:
            ids_to_ack.append(message.id)
            outcome.auto_acked_count += 1

    if ids_to_ack:
        await thread_repo.ack_messages_for_participant(session, tenant_key, agent_id=agent_id, message_ids=ids_to_ack)

    return outcome
