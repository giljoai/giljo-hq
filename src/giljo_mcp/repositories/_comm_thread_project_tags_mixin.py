# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""Plural project tagging on a thread (FE-9530, ruling 3).

Its own module for the same reason the chain-hub / directed-actions / list-
enrichment / participants / tenant-refs mixins each got one: the repository
sits under an 800-line cap, and this concern -- persisting the
``comm_thread_project_tags`` many-to-many rows -- is data access that ``create_thread``
and ``update_thread`` both need but that has nothing to do with thread CRUD itself.

Inherited by ``CommThreadRepository`` on the same seam.

Tenant-scoped on every query.
Edition Scope: CE.
"""

from __future__ import annotations

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.exceptions import ValidationError
from giljo_mcp.models.base import generate_uuid
from giljo_mcp.models.comm import CommThreadProjectTag
from giljo_mcp.models.projects import Project


class CommThreadProjectTagsMixin:
    """Read/replace the set of projects a thread is tagged with. Inherited by CommThreadRepository."""

    async def get_project_tags(self, session: AsyncSession, tenant_key: str, thread_id: str) -> list[str]:
        """Return this thread's tagged project ids (tenant-scoped), oldest tag first."""
        result = await session.execute(
            select(CommThreadProjectTag.project_id)
            .where(
                CommThreadProjectTag.tenant_key == tenant_key,
                CommThreadProjectTag.thread_id == thread_id,
            )
            .order_by(CommThreadProjectTag.created_at.asc())
        )
        return [row[0] for row in result.all()]

    async def get_project_tags_for_threads(
        self, session: AsyncSession, tenant_key: str, thread_ids: list[str]
    ) -> dict[str, list[str]]:
        """Batch form of ``get_project_tags`` -- one round trip for a whole list page.

        Returns ``{thread_id: [project_id, ...]}``; a thread with no tags is simply
        absent from the dict (callers treat a missing key as an empty list).
        """
        if not thread_ids:
            return {}
        result = await session.execute(
            select(CommThreadProjectTag.thread_id, CommThreadProjectTag.project_id)
            .where(
                CommThreadProjectTag.tenant_key == tenant_key,
                CommThreadProjectTag.thread_id.in_(thread_ids),
            )
            .order_by(CommThreadProjectTag.created_at.asc())
        )
        out: dict[str, list[str]] = {}
        for thread_id, project_id in result.all():
            out.setdefault(thread_id, []).append(project_id)
        return out

    async def set_project_tags(
        self, session: AsyncSession, tenant_key: str, thread_id: str, project_ids: list[str]
    ) -> list[str]:
        """Full-replace this thread's project tags with ``project_ids`` (order-preserving,
        de-duplicated). An empty list clears every tag -- that is how a caller says
        "no additional projects," distinct from ``None`` ("leave the tags alone") one
        layer up in ``update_thread``.

        Every id is verified to name a project IN THIS TENANT before anything is
        written -- mirrors ``CommThreadTenantRefsMixin._require_owned_reference``
        (BE-9420): a supplied id is not a capability, so a cross-tenant or made-up id
        is refused rather than silently accepted or silently dropped.
        """
        deduped: list[str] = []
        seen: set[str] = set()
        for pid in project_ids:
            if pid and pid not in seen:
                seen.add(pid)
                deduped.append(pid)

        if deduped:
            owned = (
                (
                    await session.execute(
                        select(Project.id).where(Project.tenant_key == tenant_key, Project.id.in_(deduped))
                    )
                )
                .scalars()
                .all()
            )
            missing = [pid for pid in deduped if pid not in set(owned)]
            if missing:
                raise ValidationError(
                    f"project_ids does not name a project in this workspace: {missing[0]}",
                    context={"operation": "comm_thread.update", "project_id": missing[0]},
                )

        await session.execute(
            delete(CommThreadProjectTag).where(
                CommThreadProjectTag.tenant_key == tenant_key,
                CommThreadProjectTag.thread_id == thread_id,
            )
        )
        if deduped:
            stmt = pg_insert(CommThreadProjectTag).values(
                [
                    {
                        "id": generate_uuid(),
                        "tenant_key": tenant_key,
                        "thread_id": thread_id,
                        "project_id": pid,
                    }
                    for pid in deduped
                ]
            )
            stmt = stmt.on_conflict_do_nothing(constraint="uq_comm_thread_project_tag")
            await session.execute(stmt)
        await session.flush()
        return deduped
