# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from typing import Any

from giljo_mcp.exceptions import ResourceNotFoundError, ValidationError
from giljo_mcp.models.comm import CHT_TAXONOMY_ABBR
from giljo_mcp.schemas.comm_serializers import thread_dict
from giljo_mcp.services.comm_baton_targets import (
    _is_tenant_user,
    baton_target_rejection,
    resolve_operator_alias,
)
from giljo_mcp.services.comm_handover_notification import notify_baton_handed_to_operator
from giljo_mcp.utils.taxonomy_alias import format_taxonomy_alias


class CommThreadBatonMixin:

    async def has_active_loop_directive(self, *, agent_id: str, tenant_key: str | None = None) -> bool:
        tk = self._resolve_tenant(tenant_key)
        async with self._scoped_session(tk) as session:
            return await self._repo.has_active_loop_directive(session, tk, agent_id)

    async def get_my_turn(self, *, agent_id: str, tenant_key: str | None = None) -> dict[str, Any]:
        tk = self._resolve_tenant(tenant_key)
        if not agent_id:
            raise ValidationError("agent_id is required", context={"operation": "comm_thread.get_my_turn"})
        async with self._scoped_session(tk) as session:
            await self._repo.touch_participant_last_seen(session, tk, agent_id)
            mine = await self._repo.list_threads(session, tk, next_action_owner=agent_id, exclude_terminal=True)
            broadcast = await self._repo.list_threads(
                session, tk, next_action_owner="all", exclude_terminal=True, participant_id=agent_id
            )
            threads = {t.id: t for t in [*mine, *broadcast]}
            directed = await self._repo.get_threads_with_pending_directed_action(session, tk, agent_id)
            directed_action = [{"thread_id": t.id, "chat_id": t.taxonomy_alias} for t in directed]
            for t in directed:
                if t.id not in threads:
                    threads[t.id] = t
            directives = await self._repo.get_active_loop_directives_for_agent(session, tk, agent_id)
            default_cadence: int | None = None
            if any(d["interval_minutes"] is None for d in directives):
                from giljo_mcp.services.settings_service import resolve_checkin_cadence_safe

                default_cadence = await resolve_checkin_cadence_safe(session, tk)
            return {
                "agent_id": agent_id,
                "count": len(threads),
                "threads": [thread_dict(t) for t in threads.values()],
                "directed_action": directed_action,
                "loop_directives": [
                    {
                        "thread_id": d["thread_id"],
                        "chat_id": format_taxonomy_alias(CHT_TAXONOMY_ABBR, d["serial"]),
                        "interval_minutes": (
                            d["interval_minutes"] if d["interval_minutes"] is not None else default_cadence
                        ),
                    }
                    for d in directives
                ],
            }

    async def _handoff_identity(
        self, session, tenant_key: str, thread_id: str, from_agent: str | None
    ) -> tuple[str | None, str | None]:
        if not from_agent:
            return None, None
        participant = await self._repo.get_participant(session, tenant_key, thread_id, from_agent)
        if participant is None:
            return from_agent, "agent"
        return (participant.display_name or from_agent), (participant.participant_type or "agent")

    async def collect_handover_notice(
        self, session, tenant_key: str, thread, owner: str | None, handed_by: str | None
    ) -> dict[str, Any] | None:
        if not owner or owner == "none":
            return None
        if not await _is_tenant_user(self._user_repo, session, tenant_key, owner):
            return None
        return {
            "db_manager": self._db_manager,
            "session": self._session,
            "tenant_key": tenant_key,
            "user_id": owner,
            "thread_id": thread.id,
            "chat_id": thread.taxonomy_alias or thread.id,
            "handed_by": handed_by,
        }

    @staticmethod
    async def emit_handover_notice(notice: dict[str, Any] | None) -> None:
        if notice:
            await notify_baton_handed_to_operator(**notice)

    async def pass_baton(
        self, *, thread_id: str, to: str, from_agent: str | None = None, tenant_key: str | None = None
    ) -> dict[str, Any]:
        tk = self._resolve_tenant(tenant_key)
        if not to:
            raise ValidationError("to is required", context={"operation": "comm_thread.pass_baton"})
        async with self._scoped_session(tk) as session:
            current = await self._repo.get_by_id(session, tk, thread_id)
            if current is None:
                raise ResourceNotFoundError(
                    message="Thread not found or access denied",
                    context={"operation": "comm_thread.pass_baton", "thread_id": thread_id},
                )
            to = await resolve_operator_alias(self._user_repo, session, tk, to) or to
            owner = None if to == "none" else to
            rejection = await baton_target_rejection(
                self._repo, self._user_repo, session, tk, thread_id, to, current_owner=current.next_action_owner
            )
            if rejection is not None:
                return rejection
            thread = await self._repo.set_next_action_owner(session, tk, thread_id, owner)
            participant_ids = (
                [p.participant_id for p in await self._repo.get_participants(session, tk, thread_id)]
                if to == "all"
                else []
            )
            wake_targets = self._wake_targets(
                to_participant=None,
                requires_action=False,
                baton_to=to,
                participant_ids=participant_ids,
            )
            hander_name, hander_kind = await self._handoff_identity(session, tk, thread_id, from_agent)
            notice = await self.collect_handover_notice(session, tk, thread, owner, hander_name)
            result = {
                "thread_id": thread_id,
                "next_action_owner": thread.next_action_owner,
                "from_display_name": hander_name,
                "from_kind": hander_kind,
            }

        self._signal_wake(tk, wake_targets)
        await self.emit_handover_notice(notice)
        return result
