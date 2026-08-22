# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""Who a post is actually delivered to (BE-9491, BE-6141).

Stops a broadcast or non-action-required direct post from delivering to a
TERMINAL agent participant (every ``AgentExecution`` row complete/closed/
decommissioned) — the fan-out filter that clears the reported phantom unread
badges on finished agents, going forward (no backfill of existing rows).

Lives in its own module rather than on ``CommThreadService`` for the reason
the sibling mixins already record: that class sits against the flat 800-line
cap with no tolerance band, so a feature landing in it has to make room
rather than shave rationale out of neighbouring code to fit.

Mixed into ``CommThreadService``, so it uses that class's repos
(``self._repo``, ``self._user_repo``, ``self._agent_ops``).

Edition Scope: CE.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.models.comm import CommThread
from giljo_mcp.services.comm_baton_targets import enrol_addressee


def _build_skipped_recipients_notice(
    skipped: list[dict[str, str]],
    recipient_ids: list[str],
    candidate_count: int,
    *,
    is_broadcast: bool,
) -> str | None:
    """BE-9491: sender-facing notice for ``post_to_thread``'s additive
    ``skipped_recipients`` field (mirrors BE-9247's ``forward_notice`` — the post
    ALWAYS succeeds; this only reports a shrunk delivery scope). None when
    nothing was skipped.
    """
    if not skipped:
        return None
    if not is_broadcast:
        name = skipped[0]["display_name"]
        return f"message not delivered -- {name} is finished."
    names = ", ".join(s["display_name"] for s in skipped)
    if not recipient_ids:
        # A status-detection bug that filtered out everyone must be LOUD, never a
        # silent success with zero effective delivery.
        return f"broadcast delivered to 0 of {candidate_count} participants -- all were finished."
    plural = "s" if len(skipped) != 1 else ""
    return (
        f"{len(skipped)} of {candidate_count} recipient{plural} skipped -- {names} finished and were not delivered to."
    )


class CommThreadLivenessMixin:
    """``_resolve_recipients`` + its BE-6141 auto-enroll helper, mixed into
    ``CommThreadService``."""

    async def _resolve_recipients(
        self,
        session: AsyncSession,
        tenant_key: str,
        thread: CommThread,
        *,
        to_participant: str | None,
        from_agent_id: str,
        requires_action: bool,
    ) -> tuple[list[str], list[dict[str, str]], int]:
        """Who this post is delivered to: a direct target, else every OTHER LIVE
        participant. Both branches also REGISTER their genuinely-delivered
        addressee (BE-9292a).

        BE-9491: a TERMINAL agent (every ``AgentExecution`` row complete/closed/
        decommissioned) is dropped from delivery. Returns ``(recipient_ids,
        skipped, candidate_count)`` -- ``skipped`` for the sender-facing notice,
        ``candidate_count`` so an all-terminal broadcast reads differently from a
        broadcast to nobody at all.
        """
        if to_participant:
            # gap (b): drop a NON-action-required direct post to a terminal agent.
            # Direct + action-required stays untouched -- BE-9247/BE-9012b's
            # reactivate-on-message path, including 'complete', must never be
            # intercepted here. get_terminal_agent_ids needs >=1 execution row, so
            # a human user_id addressed here is never wrongly matched.
            if not requires_action:
                terminal = await self._agent_ops.get_terminal_agent_ids(session, tenant_key, [to_participant])
                if to_participant in terminal:
                    skipped = [{"agent_id": to_participant, "display_name": to_participant}]
                    return [], skipped, 1
            # BE-9292a: delivering to someone enrols them (see enrol_addressee).
            await enrol_addressee(self._repo, self._user_repo, session, tenant_key, thread.id, to_participant)
            return [to_participant], [], 1
        # BE-6141: a broadcast on a PROJECT-ANCHORED thread auto-enrolls the
        # project's active roster; a standalone thread is unaffected.
        if thread.project_id:
            await self._auto_enroll_project_roster(session, tenant_key, thread.id, thread.project_id)
        participants = await self._repo.get_participants(session, tenant_key, thread.id)
        candidates = [p for p in participants if p.participant_id != from_agent_id]
        # gap (c): only 'agent' rows can ever be terminal -- a human is never "finished".
        agent_candidate_ids = [p.participant_id for p in candidates if p.participant_type == "agent"]
        terminal = await self._agent_ops.get_terminal_agent_ids(session, tenant_key, agent_candidate_ids)
        skipped = [
            {"agent_id": p.participant_id, "display_name": p.display_name or p.participant_id}
            for p in candidates
            if p.participant_id in terminal
        ]
        live_ids = [p.participant_id for p in candidates if p.participant_id not in terminal]
        return live_ids, skipped, len(candidates)

    async def _auto_enroll_project_roster(
        self, session: AsyncSession, tenant_key: str, thread_id: str, project_id: str
    ) -> None:
        """Enroll a project's ACTIVE agents as thread participants (BE-6141).

        Reuses the AgentExecution roster (the owning AgentOperationsRepository)
        and the collision-safe ``add_participant`` join, so a broadcast reaches
        agents that never manually joined. Re-enrolling an existing participant never
        duplicates the row. Scoped to the project's active agents — does not
        over-enroll terminal (complete/closed/decommissioned) agents.

        BE-9289a: a PLACEHOLDER writer (``authoritative=False``) — it fills blanks but
        never corrects. It re-runs on EVERY broadcast carrying a non-null roster name and
        the literal role ``"auto-enrolled"``, so were it allowed to overwrite, an agent's
        declared identity would flip back to the placeholder on every message.
        """
        roster = await self._agent_ops.get_active_agent_ids_for_project(session, tenant_key, project_id)
        for agent_id, display_name in roster:
            await self._repo.add_participant(
                session,
                tenant_key,
                thread_id,
                participant_id=agent_id,
                participant_type="agent",
                display_name=display_name,
                role="auto-enrolled",
            )
