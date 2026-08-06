# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""CommThreadRepository per-participant directed-action read (BE-9207 split).

Cohesive read-only query extracted from ``CommThreadRepository`` to keep that
module under the 800-line guardrail: the pending directed action-request query
that lets ``get_my_turn`` surface a lane's own unresolved directive independent of
the single ``next_action_owner`` baton. Inherited by ``CommThreadRepository`` so
the public repository API is unchanged. Tenant-scoped on every joined table; the
session is passed in by the caller. Behavior is byte-identical to the pre-split
single-class repository.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.models.comm import (
    LOOP_DIRECTIVE_MESSAGE_TYPE,
    TERMINAL_THREAD_STATUSES,
    CommThread,
)
from giljo_mcp.models.tasks import (
    Message,
    MessageAcknowledgment,
    MessageRecipient,
)


class CommThreadDirectedActionsMixin:
    """Per-participant pending directed-action read. Inherited by CommThreadRepository."""

    async def get_threads_with_pending_directed_action(
        self, session: AsyncSession, tenant_key: str, agent_id: str
    ) -> list[CommThread]:
        """Threads carrying an UNRESOLVED directed action-request for an agent (BE-9207).

        The per-participant complement to the single ``next_action_owner`` baton:
        a DIRECTED ``requires_action`` post is pending for ``agent_id`` regardless of
        who currently holds the thread-level baton, so ``get_my_turn`` can surface it
        even after the EM directs a different lane and the baton moves on. A thread
        qualifies when it holds at least one message that is ALL of:
          - DIRECTED, not a broadcast (``message_type`` is a direct message, not
            ``broadcast`` / a loop-directive). A broadcast ``requires_action`` post is
            "whoever picks it up" and deliberately does NOT obligate any single
            participant's turn list nor move the baton (BE-9197 museum rule) — only a
            DM (``to_participant``) is the per-lane directive this fix restores;
          - ``requires_action = True``;
          - delivered to ``agent_id`` (a ``message_recipients`` row — participation is
            implied, so a DM aimed at someone else never leaks into this agent's list);
          - NOT yet acknowledged by ``agent_id`` (no ``message_acknowledgments`` row —
            the resolve signal, written by ``get_thread_history(mark_read=True)``).
        The thread itself must be LIVE (``deleted_at IS NULL``) and NON-terminal —
        a resolved/closed thread silences the pending directive, the same gate that
        terminates a loop directive. DISTINCT so a thread with several pending posts
        returns once. Tenant-scoped on every joined table. No schema change: reuses
        the message_recipients + message_acknowledgments junctions.
        """
        ack_exists = (
            select(MessageAcknowledgment.id)
            .where(
                MessageAcknowledgment.message_id == Message.id,
                MessageAcknowledgment.agent_id == agent_id,
                MessageAcknowledgment.tenant_key == tenant_key,
            )
            .exists()
        )
        stmt = (
            select(CommThread)
            .join(Message, Message.thread_id == CommThread.id)
            .join(MessageRecipient, MessageRecipient.message_id == Message.id)
            .where(
                CommThread.tenant_key == tenant_key,
                CommThread.deleted_at.is_(None),
                CommThread.status.notin_(TERMINAL_THREAD_STATUSES),
                Message.tenant_key == tenant_key,
                Message.requires_action.is_(True),
                # DIRECTED only — a broadcast/loop-directive post is not a per-lane
                # obligation (keeps the BE-9197 "broadcast baton untouched" contract).
                Message.message_type.notin_(("broadcast", LOOP_DIRECTIVE_MESSAGE_TYPE)),
                MessageRecipient.tenant_key == tenant_key,
                MessageRecipient.agent_id == agent_id,
                ~ack_exists,
            )
            .distinct()
            .order_by(CommThread.created_at.desc())
        )
        result = await session.execute(stmt)
        return list(result.scalars().all())
