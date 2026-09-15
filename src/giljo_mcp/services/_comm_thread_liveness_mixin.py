# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


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
    if not skipped:
        return None
    if not is_broadcast:
        name = skipped[0]["display_name"]
        return f"message not delivered -- {name} is finished."
    names = ", ".join(s["display_name"] for s in skipped)
    if not recipient_ids:
        return f"broadcast delivered to 0 of {candidate_count} participants -- all were finished."
    plural = "s" if len(skipped) != 1 else ""
    return (
        f"{len(skipped)} of {candidate_count} recipient{plural} skipped -- {names} finished and were not delivered to."
    )


class CommThreadLivenessMixin:

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
        if to_participant:
            if not requires_action:
                terminal = await self._agent_ops.get_terminal_agent_ids(session, tenant_key, [to_participant])
                if to_participant in terminal:
                    skipped = [{"agent_id": to_participant, "display_name": to_participant}]
                    return [], skipped, 1
            await enrol_addressee(self._repo, self._user_repo, session, tenant_key, thread.id, to_participant)
            return [to_participant], [], 1
        if thread.project_id:
            await self._auto_enroll_project_roster(session, tenant_key, thread.id, thread.project_id)
        participants = await self._repo.get_participants(session, tenant_key, thread.id)
        candidates = [p for p in participants if p.participant_id != from_agent_id]
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
