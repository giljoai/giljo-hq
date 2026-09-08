# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""The operator's read watermark (FE-9586).

``comm_participants.last_read_at`` is the cursor every "is there anything new"
answer keys on, and until this it was advanced only by AGENTS -- through
``get_thread_history(as_participant=..., mark_read=True)`` over MCP. The dashboard
never advanced it: ``commHubStore.markThreadRead()`` zeroes an in-memory counter
and persists nothing, and ``GET /api/v1/threads/{id}`` passes neither
``as_participant`` nor ``mark_read``.

So the operator had NO watermark, and the BE-9289b card ``unread`` flag was stuck
TRUE forever once anything had been posted. It also meant "the operator read
this" was a fact the server had never been told, so no banner family could
project off it -- which is why FE-9586's mention work needed this first.

WHY THIS DELEGATES INSTEAD OF WRITING THE CURSOR ITSELF. The whole point is that
the operator's watermark and an agent's are the SAME object, not two spellings
that can drift, so this composes the two existing writes rather than reaching for
the repository:

  join_thread(participant_type='user')  -- collision-safe, so write-on-open is
      idempotent, and it is REQUIRED rather than incidental: the cursor lives ON
      the participant row, so a watermark without one is not representable.
      ``get_thread_history(mark_read=True)`` refuses a reader with nothing
      delivered to it (NOT_A_PARTICIPANT, BE-9292a) -- correct for an agent, but
      the operator is named on nothing and would be refused every time.

  get_thread_history(as_participant=..., mark_read=True) -- with NO filters, on
      purpose. ``_apply_mark_read`` advances the cursor only on a clean forward
      drain (BE-9012a): any narrowing means the returned set is not the contiguous
      run up to newest, and advancing would skip the posts it excluded. A tail or
      a marker here would silently mark-read a thread while leaving earlier posts
      unread, which is the one failure this must not have.

By design: the participant row is inserted and the participant
directory is left UNFILTERED -- reading-with-a-watermark IS a form of
participation, and "the operator has looked at this thread" is true information.
Excluding ``participant_type='user'`` from the directory read would be a silent
display divergence.

Edition Scope: Both.
"""

from __future__ import annotations

from typing import Any

from giljo_mcp.exceptions import ValidationError


class CommThreadOperatorReadMixin:
    """The operator's read watermark. Inherited by CommThreadService."""

    async def mark_thread_read_for_user(
        self,
        *,
        thread_id: str,
        user_id: str,
        display_name: str | None = None,
        tenant_key: str | None = None,
    ) -> dict[str, Any]:
        """Advance ``user_id``'s read cursor on ``thread_id`` to the newest post.

        Idempotent: write-on-open fires on every open, so a second call enrols
        nobody twice and advances nothing. Returns ``{thread_id, participant_id,
        marked_read, cursor_advanced}`` -- ``cursor_advanced`` false simply means
        there was nothing newer, which is the ordinary case on a re-open and not
        a failure.

        The caller is expected to treat this as fire-and-forget: a failed
        watermark write must never delay or break the thread view, and the next
        open retries it.
        """
        await self.join_thread(
            thread_id=thread_id,
            participant_id=user_id,
            participant_type="user",
            display_name=display_name,
            tenant_key=tenant_key,
        )
        # No filters -- see the module docblock on why a narrowed read must not be
        # used here.
        read = await self.get_thread_history(
            thread_id=thread_id,
            as_participant=user_id,
            mark_read=True,
            tenant_key=tenant_key,
        )
        return {
            "thread_id": thread_id,
            "participant_id": user_id,
            "marked_read": read.get("marked_read", 0),
            "cursor_advanced": bool(read.get("cursor_advanced", False)),
        }

    async def get_attention_for_user(
        self,
        *,
        user_id: str,
        tenant_key: str | None = None,
    ) -> dict[str, Any]:
        """What is asking for ``user_id`` right now, in ONE read (FE-9586).

        Returns ``{"mentions": [{thread_id, chat_id}], "directed_action": [...]}``.

        ONE read, because the banner family needs ONE loaded state. Two independent
        fetches give the family two hydration moments, and "not fetched yet" then
        becomes indistinguishable from "nothing waiting" for whichever half is late
        -- the FE-9553 near-miss exactly, where an unhydrated store read as a
        cleared banner and would have closed every popout on mount.

        THE DISPLAY NAME IS RESOLVED HERE, never accepted from the caller. "Mention"
        must have one definition; the client's display-name match is deleted in this
        same change, and a name parameter would simply relocate the second
        definition into whichever caller passed it. The name comes off the
        authenticated user's own row, through the same ``User.display_name`` property
        the API already serves to that client. An unresolvable user yields no name,
        which the repository turns into NO mentions -- never the empty-pattern match
        that would report every thread in the tenant.

        A BROADCAST ``requires_action`` post appears in NEITHER list. That is BE-9197
        as a museum-rule invariant -- such a post is "whoever picks it up" and
        obligates nobody in particular -- and it comes free here because BE-9207's
        directed query already excludes broadcasts. The client is aligned to this
        rather than the reverse: it kept raising an actionable signal for broadcasts,
        which was quietly contradicting the invariant.

        Both classes resolve on the SAME gesture: the operator reading the thread.
        A mention clears when the read watermark passes it; a directed ask clears on
        its acknowledgment, and ``mark_thread_read_for_user`` writes both.
        """
        tk = self._resolve_tenant(tenant_key)
        if not user_id:
            raise ValidationError("user_id is required", context={"operation": "comm_thread.get_attention_for_user"})
        async with self._scoped_session(tk) as session:
            user = await self._user_repo.get_user_by_id(session, user_id, tk)
            display_name = user.display_name if user is not None else None

            mentioned = await self._repo.get_unread_mentions(session, tk, viewer_id=user_id, display_name=display_name)
            directed = await self._repo.get_threads_with_pending_directed_action(session, tk, user_id)

            # Grouped by thread for the banner, but every naming POST is named, in
            # newest-first order. The bell row keys on the post and the popout
            # deep-links to it, so a thread-only payload would leave the client
            # guessing which arriving event a verdict referred to.
            mentions: list[dict[str, Any]] = []
            by_thread: dict[str, dict[str, Any]] = {}
            for thread, message_id in mentioned:
                entry = by_thread.get(thread.id)
                if entry is None:
                    entry = {"thread_id": thread.id, "chat_id": thread.taxonomy_alias, "message_ids": []}
                    by_thread[thread.id] = entry
                    mentions.append(entry)
                entry["message_ids"].append(message_id)

            return {
                "mentions": mentions,
                "directed_action": [{"thread_id": t.id, "chat_id": t.taxonomy_alias} for t in directed],
            }
