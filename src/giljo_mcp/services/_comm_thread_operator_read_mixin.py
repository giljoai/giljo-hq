# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from typing import Any

from giljo_mcp.exceptions import ValidationError


class CommThreadOperatorReadMixin:

    async def mark_thread_read_for_user(
        self,
        *,
        thread_id: str,
        user_id: str,
        display_name: str | None = None,
        tenant_key: str | None = None,
    ) -> dict[str, Any]:
        await self.join_thread(
            thread_id=thread_id,
            participant_id=user_id,
            participant_type="user",
            display_name=display_name,
            tenant_key=tenant_key,
        )
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
        tk = self._resolve_tenant(tenant_key)
        if not user_id:
            raise ValidationError("user_id is required", context={"operation": "comm_thread.get_attention_for_user"})
        async with self._scoped_session(tk) as session:
            user = await self._user_repo.get_user_by_id(session, user_id, tk)
            display_name = user.display_name if user is not None else None

            mentioned = await self._repo.get_unread_mentions(session, tk, viewer_id=user_id, display_name=display_name)
            directed = await self._repo.get_threads_with_pending_directed_action(session, tk, user_id)

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
