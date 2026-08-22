# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""Is this agent_id entirely finished (BE-9491)?

The batch liveness check the Hub message fan-out filter
(``CommThreadService._resolve_recipients``) and the five
``get_live_*_unread_counts_*`` queries both need: an agent_id is terminal only
when EVERY ``AgentExecution`` row it owns is complete/closed/decommissioned.

Its own module for the size-budget reason the sibling repository mixins already
record: ``AgentOperationsRepository`` sits at the flat 800-line cap with no
tolerance band, so a feature landing there has to make room rather than shave
rationale out of neighbouring code to fit.

Inherited by ``AgentOperationsRepository``, so its public API
(``get_terminal_agent_ids``) is unchanged.

Tenant-scoped.
Edition Scope: CE.
"""

from __future__ import annotations

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.models.agent_identity import TERMINAL_EXECUTION_STATUSES, AgentExecution
from giljo_mcp.models.tasks import Message, MessageRecipient


def _recipient_agent_is_terminal_clause(tenant_key: str):
    """Shared EXISTS-pair: true when ``MessageRecipient.agent_id`` names an agent
    whose EVERY ``AgentExecution`` row is terminal. Callers negate it
    (``~agent_is_terminal``) to keep only still-counting recipients, mirroring
    ``_already_acked_exists_clause``.

    TWO EXISTS, not one. ``MessageRecipient.agent_id`` also holds a HUMAN
    ``user_id`` for a directed Hub post addressed to the operator — a human has
    ZERO ``AgentExecution`` rows, so a naive single ``NOT EXISTS(non-terminal
    row)`` clause would be vacuously true for them too and silently zero the
    operator's own unread badge. Requiring at least one row first (the first
    EXISTS) is what keeps a human — and a headless agent that has never gone
    through the job system and so also has zero rows — out of this clause
    entirely.
    """
    has_any_execution = (
        select(AgentExecution.id)
        .where(
            AgentExecution.tenant_key == tenant_key,
            AgentExecution.agent_id == MessageRecipient.agent_id,
        )
        .exists()
    )
    has_active_execution = (
        select(AgentExecution.id)
        .where(
            AgentExecution.tenant_key == tenant_key,
            AgentExecution.agent_id == MessageRecipient.agent_id,
            AgentExecution.status.notin_(TERMINAL_EXECUTION_STATUSES),
        )
        .exists()
    )
    return and_(has_any_execution, ~has_active_execution)


def _should_hide_from_unread_clause(tenant_key: str):
    """Read-side mirror of the write-side fan-out filter (BE-9491 fix).

    True when a row must be treated as invisible to the unread / action-required
    counts: the recipient is entirely terminal AND the message is the exact
    shape ``CommThreadLivenessMixin._resolve_recipients`` drops going forward --
    a BROADCAST (its no-``to_participant`` branch, which drops a terminal
    candidate unconditionally, with no ``requires_action`` exemption) that is
    itself NOT ``requires_action``.

    The original ``_recipient_agent_is_terminal_clause`` was wired into all
    five ``get_live_*_unread_counts_*`` queries with no ``Message`` awareness at
    all, so it also hid every DIRECT post to a terminal recipient -- including
    ``requires_action`` DMs the write side deliberately delivered (BE-9247 /
    BE-9012b's reactivate-on-message exemption never intercepts a direct
    ``requires_action`` post, terminal or not) and plain directed informational
    posts, which the write side has only ever blocked for NEW deliveries, never
    retroactively for a row already on the books. That silently zeroed the
    action-required badge and, because the closeout gate
    (``agent_completion_repository.get_unread_messages_for_agent``) shares this
    same ack-based store, let a still-undrained ``requires_action`` DM stop
    blocking project completion (TSK-9268).

    ``requires_action`` is NEVER hidden here regardless of ``message_type``: an
    agent-flagged blocking message must stay visible to the badge and the gate
    for every shape the write side can produce, not only the direct one.
    """
    return and_(
        _recipient_agent_is_terminal_clause(tenant_key),
        Message.message_type == "broadcast",
        ~Message.requires_action.is_(True),
    )


class AgentLivenessMixin:
    """``get_terminal_agent_ids``, mixed into ``AgentOperationsRepository``."""

    async def get_terminal_agent_ids(
        self,
        session: AsyncSession,
        tenant_key: str,
        agent_ids: list[str],
    ) -> set[str]:
        """Which of ``agent_ids`` are entirely terminal.

        An agent_id is terminal when EVERY ``AgentExecution`` row it has is
        complete/closed/decommissioned -- mirrors ``get_active_agent_ids_for_project``'s
        "ANY non-terminal row => active" semantics, inverted, so a respawned/
        succeeded agent_id is never wrongly flagged dead just because an earlier
        execution under the same id finished (the succession trap).

        NOT flagged terminal: an agent_id with ZERO execution rows. A headless
        agent that posts via the Hub without ever going through the job system
        has no ``AgentExecution`` row at all; treating "never tracked" as
        "terminal" would silently drop every broadcast to it forever. Mirrors the
        existing ``if recipient_execution and ...`` guard in
        ``MessageRoutingService._auto_block_completed_recipients`` -- an unknown
        execution is left alone there too, never treated as dead.

        One query, tenant-isolated. Agent_ids absent from ``agent_ids`` or with no
        rows at all are simply absent from the returned set.
        """
        if not agent_ids:
            return set()
        stmt = select(AgentExecution.agent_id, AgentExecution.status).where(
            AgentExecution.tenant_key == tenant_key,
            AgentExecution.agent_id.in_(agent_ids),
        )
        rows = (await session.execute(stmt)).all()
        statuses_by_agent: dict[str, list[str]] = {}
        for agent_id, status in rows:
            statuses_by_agent.setdefault(agent_id, []).append(status)
        return {
            agent_id
            for agent_id, statuses in statuses_by_agent.items()
            if all(status in TERMINAL_EXECUTION_STATUSES for status in statuses)
        }
