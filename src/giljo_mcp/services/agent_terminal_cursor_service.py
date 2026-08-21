# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-9242: resolve a terminal agent's dead message cursors.

Root cause: no lifecycle hook ever resolved a closed/decommissioned agent's
outstanding message cursors, so an unread badge could linger forever on an
agent nobody will ever reactivate to drain it -- and, far worse, a genuinely
action-required post addressed to that agent had no path forward at all
(silently invisible work).

Two layers, deliberately split so the SAME primitives cover both a
close-time cleanup (this project, P1/BE-9242) and a send-time redirect (the
sibling project, P2/BE-9247, which reuses ``forward_action_required_to_orchestrator``
and ``build_forwarded_annotation`` VERBATIM at the moment a NEW post is about
to be addressed to an already-terminal recipient):

- ``build_forwarded_annotation`` / ``forward_action_required_to_orchestrator``:
  the reusable primitives. Resolve "who is the live orchestrator right now"
  (``AgentCompletionRepository.find_active_orchestrator_in_project``) and
  re-post content to them via the SAME side-effect-free thread-message persist
  ``post_to_thread`` uses (``CommThreadRepository.persist_thread_message``), so
  a forwarded post behaves exactly like any other thread post (gates
  completion, shows up in get_thread_history, etc).
- ``resolve_terminal_agent_cursors``: the BE-9242-specific orchestration that
  walks every live (unacked) cursor a newly-terminal agent still holds and
  calls the primitives above for each one.

Caller owns the session/transaction (same "session-in" pattern as
``ProjectCloseoutService.decommission_project_agents``); every function here
only flushes, never commits.
"""

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
    """The single canonical wrapper for a message re-routed off a terminal agent.

    BE-9242 / BE-9247 shared format: both the close-time cleanup here and the
    P2 send-time redirect render a forwarded post with this SAME text shape,
    so a recipient sees one consistent "why am I getting this" explanation
    regardless of which seam did the redirecting.
    """
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
    """Resolve the live orchestrator for `project_id` and re-post `original_content`
    to them, wrapped in the canonical forwarded annotation.

    Returns the newly created Message, or None if no live orchestrator
    execution exists right now. A None return means "could not forward" --
    the caller MUST NOT treat that as success and must NOT silently drop
    whatever cursor/post prompted the forward (see
    ``resolve_terminal_agent_cursors``, which leaves the source message
    un-acked in that case).
    """
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
        # Deliberately requires_action=True, auto_generated left at the model
        # default (False): this forwarded post must actually gate the live
        # orchestrator's own completion, exactly like the work it replaces --
        # auto_generated=True would exempt it from the closeout gate
        # (agent_completion_repository.get_unread_messages_for_agent) and
        # silently defeat the whole point of forwarding it.
        requires_action=True,
        recipient_ids=[orchestrator_execution.agent_id],
    )


@dataclass
class TerminalCursorResolution:
    """Outcome of resolving one terminal agent's live cursors (BE-9242)."""

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
    """Auto-resolve every live (unacked) message cursor a now-TERMINAL agent
    still holds (BE-9242 deliverable #1).

    - Informational / auto-generated posts: auto-acknowledged for the dead
      agent. They will never be read and nothing depends on them for action,
      so clearing them is exactly what a live agent's own mark_read would
      have done.
    - Genuine action-required, non-auto-generated posts: NEVER just acked --
      forwarded to the live orchestrator first (see
      ``forward_action_required_to_orchestrator``), THEN acked for the dead
      agent. The dead agent's cursor is legitimately resolved because the
      work now has a new, live owner -- not because it was discarded.
    - If no live orchestrator exists to forward to, the action-required
      message is left un-acked (fails open and visibly, via a warning log)
      instead of being silently swallowed.

    Call this from a terminal lifecycle transition (job close, project
    closeout decommission/close) -- NOT from ``complete_job``, since
    'complete' stays reactivatable and an agent that may still come back
    should keep its live cursors.

    Caller owns the session/transaction; this only flushes.
    """
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
