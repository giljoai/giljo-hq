# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import logging
from typing import Any

from giljo_mcp.domain.soft_delete import RECOVER_WINDOW_DAYS, recover_window_expired
from giljo_mcp.exceptions import ResourceNotFoundError, ValidationError
from giljo_mcp.schemas.comm_serializers import thread_dict


logger = logging.getLogger(__name__)


class CommThreadSoftDeleteMixin:

    async def delete_thread(self, *, thread_id: str, tenant_key: str | None = None) -> dict[str, Any]:
        tk = self._resolve_tenant(tenant_key)
        async with self._scoped_session(tk) as session:
            thread = await self._require_thread(session, tk, thread_id)
            if thread.project_id:
                raise ValidationError(
                    "This thread belongs to a project, so it is the project's chat record and "
                    "is kept with the project's 360 memory — it cannot be deleted here. "
                    "You can still resolve or close it, or delete the project itself.",
                    context={
                        "operation": "comm_thread.delete",
                        "thread_id": thread_id,
                        "project_id": thread.project_id,
                    },
                )
            chat_id = thread.taxonomy_alias
            deleted = await self._repo.soft_delete(session, tk, thread_id)
            if not deleted:  # pragma: no cover - _require_thread already guarantees presence
                raise ResourceNotFoundError(
                    message="Thread not found or access denied",
                    context={"operation": "comm_thread.delete", "thread_id": thread_id},
                )
            return {"thread_id": thread_id, "chat_id": chat_id, "deleted": True}

    async def restore_thread(self, *, thread_id: str, tenant_key: str | None = None) -> dict[str, Any]:
        tk = self._resolve_tenant(tenant_key)
        async with self._scoped_session(tk) as session:
            trashed = await self._repo.get_deleted_by_id(session, tk, thread_id)
            if trashed is None:
                raise ResourceNotFoundError(
                    message="Deleted thread not found or access denied",
                    context={"operation": "comm_thread.restore", "thread_id": thread_id},
                )
            if recover_window_expired(trashed.deleted_at):
                raise ValidationError(
                    f"This thread was deleted more than {RECOVER_WINDOW_DAYS} days ago and can no longer be recovered.",
                    context={"operation": "comm_thread.restore", "thread_id": thread_id},
                )
            thread = await self._repo.restore(session, tk, thread_id)
            return thread_dict(thread)

    async def list_deleted_threads(
        self,
        *,
        product_id: str | None = None,
        project_id: str | None = None,
        tenant_key: str | None = None,
    ) -> dict[str, Any]:
        tk = self._resolve_tenant(tenant_key)
        async with self._scoped_session(tk) as session:
            threads = await self._repo.list_deleted(session, tk, product_id=product_id, project_id=project_id)
            return {
                "count": len(threads),
                "threads": [
                    {
                        **thread_dict(t),
                        "deleted_at": t.deleted_at.isoformat() if t.deleted_at else None,
                    }
                    for t in threads
                ],
            }

    async def purge_expired_deleted_threads(self, *, tenant_key: str | None = None) -> int:
        tk = self._resolve_tenant(tenant_key)
        purged = 0
        async with self._scoped_session(tk) as session:
            for thread in await self._repo.list_deleted(session, tk):
                if not recover_window_expired(thread.deleted_at):
                    continue
                try:
                    if await self._repo.hard_delete(session, tk, thread.id):
                        purged += 1
                except Exception:
                    logger.exception("Reaper failed to purge thread %s", thread.id)
        return purged
