# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""Thread soft-delete lifecycle — trash, recover, and the reaper (BE-9289b split).

PURE MOVE out of ``CommThreadService``: signatures, ordering and behaviour are
identical to the pre-split methods, and the diff is location plus imports only. The
seam is the one ``_comm_thread_directed_actions_mixin`` and
``_comm_thread_participants_mixin`` already established.

Extracted because BE-9289b adds thread EDIT operations (rename / operator status), and
edit and lifecycle are different concerns that should not share a module — the size
budget forced the question, but keeping them apart is right on its own terms.

Mixed into ``CommThreadService``, so it uses that class's session/tenant plumbing
(``_resolve_tenant``, ``_scoped_session``, ``_require_thread``, ``_repo``) and the
public service API is unchanged.

Edition Scope: CE.
"""

from __future__ import annotations

import logging
from typing import Any

from giljo_mcp.domain.soft_delete import RECOVER_WINDOW_DAYS, recover_window_expired
from giljo_mcp.exceptions import ResourceNotFoundError, ValidationError
from giljo_mcp.schemas.comm_serializers import thread_dict


logger = logging.getLogger(__name__)


class CommThreadSoftDeleteMixin:
    """Soft-delete / restore / trash listing / reaper. Mixed into CommThreadService."""

    async def delete_thread(self, *, thread_id: str, tenant_key: str | None = None) -> dict[str, Any]:
        """Soft-delete a thread (Message Hub trash action).

        Stamps ``deleted_at`` so the thread drops out of every read; message
        history + participants stay intact. Raises ResourceNotFoundError when the
        thread does not exist (or is already deleted) for the tenant.
        BE-9289b: REFUSES a project-bound thread. That thread is the project's audit
        record and is kept with its 360 memory. The invariant was previously asserted
        in a ``ThreadList.vue`` comment and enforced only by hiding the button — so any
        other client, or a stale tab, could still delete a project's chat log. Left
        unrestored, the 30-day reaper then hard-deletes the row and the whole message
        subtree goes with it via ``ON DELETE CASCADE``. The guard lives HERE, at the
        owning service, so MCP / REST / internal callers all inherit it rather than
        each client re-implementing it.

        Status is deliberately NOT restricted the same way — see ``update_thread``.
        Resolving or closing a project thread is a normal operator action."""
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
        """Restore a soft-deleted thread (Message Hub recover action).

        Clears ``deleted_at`` so the thread (and its intact message history +
        participants) surfaces again in every read. Raises ResourceNotFoundError
        when no soft-deleted thread matches the id for the tenant."""
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
        """List soft-deleted threads (the recover dialog's source). Includes
        ``deleted_at`` so the UI can show how long ago each was trashed."""
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
        """Hard-delete trashed threads past the recovery window (TSK-6132 reaper).

        Walks this tenant's soft-deleted threads and permanently removes those
        whose ``deleted_at`` is past ``RECOVER_WINDOW_DAYS`` (the same boundary
        ``restore_thread`` refuses to recover past). Cascade is DB-level. Returns
        the count purged; tenant-isolated and idempotent (re-running finds none).
        """
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
