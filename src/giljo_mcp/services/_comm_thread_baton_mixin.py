# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""The baton — whose turn it is, and how the turn moves (BE-9365b extraction).

Three methods that answer one question between them: what is waiting on ME, and who
gets it next. ``get_my_turn`` is the poll every running agent lives on, ``pass_baton``
is the hand-off, and ``has_active_loop_directive`` is the cadence the poll re-reads.
They share the baton's vocabulary and nothing else in the service does, so they read
better together than interleaved with thread CRUD and history.

Lives in its own module rather than on ``CommThreadService`` for the reason
``_comm_thread_edit_mixin`` and the enrichment mixin already record: that module is
pinned at its shrink-only size budget, so a feature landing in it has to make room
rather than shave the rationale out of neighbouring code to fit. BE-9365b's operator
alias was that feature.

Mixed into ``CommThreadService``, so it uses that class's session/tenant plumbing
(``_resolve_tenant``, ``_scoped_session``) and its repositories (``_repo``,
``_user_repo``). The public API is unchanged.

Edition Scope: CE.
"""

from __future__ import annotations

from typing import Any

from giljo_mcp.exceptions import ResourceNotFoundError, ValidationError
from giljo_mcp.models.comm import CHT_TAXONOMY_ABBR
from giljo_mcp.schemas.comm_serializers import thread_dict
from giljo_mcp.services.comm_baton_targets import baton_target_rejection, resolve_operator_alias
from giljo_mcp.utils.taxonomy_alias import format_taxonomy_alias


class CommThreadBatonMixin:
    """Baton queries and hand-off. Mixed into CommThreadService."""

    async def has_active_loop_directive(self, *, agent_id: str, tenant_key: str | None = None) -> bool:
        """Whether an agent currently has a live loop directive (BE-6054c).

        Used by the mission composer to decide whether to inject the loop/sleep
        directive. True iff a loop_directive message targets this agent on a
        non-terminal thread."""
        tk = self._resolve_tenant(tenant_key)
        async with self._scoped_session(tk) as session:
            return await self._repo.has_active_loop_directive(session, tk, agent_id)

    async def get_my_turn(self, *, agent_id: str, tenant_key: str | None = None) -> dict[str, Any]:
        """The baton query: threads where next_action_owner == agent_id (or 'all').

        BE-9207: ALSO surfaces threads where this agent has an UNRESOLVED directed
        ``requires_action`` post, independent of who holds the single
        ``next_action_owner`` baton. Before this, once the EM directed a different
        lane the baton moved and a worker's own open directive vanished from
        get_my_turn (the multi-lane clobber). The directed-pending threads are
        APPENDED to ``threads`` (existing baton entries keep their shape + order —
        external callers pattern-match that list) and also named in the additive
        ``directed_action`` list ``[{thread_id, chat_id}]`` so a caller can tell a
        directive from a baton. "Unresolved" = not yet acknowledged (mark_read) and
        the thread non-terminal; see the repo query for the exact predicate.

        FE-6140: also surfaces ``loop_directives`` — the active auto-check-in
        requests for EVERY thread this agent participates in (not only the threads
        where it holds the baton). This is the harness-neutral inject: a running
        agent polling get_my_turn reads its cadence(s) and self-schedules a wake.
        Each entry is ``{thread_id, chat_id, interval_minutes}`` (interval may be
        None when a directive was armed without an explicit cadence)."""
        tk = self._resolve_tenant(tenant_key)
        if not agent_id:
            raise ValidationError("agent_id is required", context={"operation": "comm_thread.get_my_turn"})
        async with self._scoped_session(tk) as session:
            # BE-9289a: the baton poll is the most common sign of life for an agent that
            # is waiting rather than talking. It is thread-agnostic, so it stamps every
            # thread this agent belongs to.
            await self._repo.touch_participant_last_seen(session, tk, agent_id)
            mine = await self._repo.list_threads(session, tk, next_action_owner=agent_id)
            broadcast = await self._repo.list_threads(session, tk, next_action_owner="all")
            # Baton-derived entries FIRST, in their existing order (dicts preserve
            # insertion order) — the legacy shape external callers key on.
            threads = {t.id: t for t in [*mine, *broadcast]}
            # BE-9207: append directed-pending threads (dedup by id) + name them in
            # the additive directed_action list. A thread already held via the baton
            # is not re-appended, but IS still reported in directed_action so the
            # agent knows an unacked directive lives there.
            directed = await self._repo.get_threads_with_pending_directed_action(session, tk, agent_id)
            directed_action = [{"thread_id": t.id, "chat_id": t.taxonomy_alias} for t in directed]
            for t in directed:
                if t.id not in threads:
                    threads[t.id] = t
            directives = await self._repo.get_active_loop_directives_for_agent(session, tk, agent_id)
            return {
                "agent_id": agent_id,
                "count": len(threads),
                "threads": [thread_dict(t) for t in threads.values()],
                "directed_action": directed_action,
                "loop_directives": [
                    {
                        "thread_id": d["thread_id"],
                        "chat_id": format_taxonomy_alias(CHT_TAXONOMY_ABBR, d["serial"]),
                        "interval_minutes": d["interval_minutes"],
                    }
                    for d in directives
                ],
            }

    async def pass_baton(self, *, thread_id: str, to: str, tenant_key: str | None = None) -> dict[str, Any]:
        """Hand the baton: set next_action_owner to an agent_id / user_id / 'all' / 'none'."""
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
            # BE-9365b: same expansion as the post path, and it must precede `owner` or
            # the baton is set to the literal "user" — the dead-baton shape BE-9292a fixed.
            to = await resolve_operator_alias(self._user_repo, session, tk, to) or to
            owner = None if to == "none" else to
            # BE-9292a: the same reachability guard as the atomic post-with-baton
            # hand-off — otherwise the fix is one call away from being bypassed.
            rejection = await baton_target_rejection(
                self._repo, self._user_repo, session, tk, thread_id, to, current_owner=current.next_action_owner
            )
            if rejection is not None:
                return rejection
            thread = await self._repo.set_next_action_owner(session, tk, thread_id, owner)
            return {"thread_id": thread_id, "next_action_owner": thread.next_action_owner}
