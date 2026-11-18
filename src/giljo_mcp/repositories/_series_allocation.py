# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from sqlalchemy import exists, literal, select, union, union_all
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.models.projects import Project
from giljo_mcp.models.tasks import Task
from giljo_mcp.repositories._project_enrichment_reads_mixin import project_not_trashed


async def lowest_free_series_number(session: AsyncSession, tenant_key: str, product_id: str | None) -> int:
    used = union(
        select(Project.series_number.label("n")).where(
            Project.tenant_key == tenant_key,
            Project.product_id == product_id,
            Project.series_number.is_not(None),
        ),
        select(Task.series_number.label("n")).where(
            Task.tenant_key == tenant_key,
            Task.product_id == product_id,
            Task.series_number.is_not(None),
        ),
    ).subquery("used")
    candidates = union_all(
        select(literal(1).label("c")),
        select((used.c.n + 1).label("c")),
    ).subquery("candidates")
    taken = select(used.c.n)
    query = select(candidates.c.c).where(candidates.c.c.not_in(taken)).order_by(candidates.c.c).limit(1)
    return (await session.execute(query)).scalar_one()


async def number_for_restore(
    session: AsyncSession,
    tenant_key: str,
    product_id: str | None,
    row_id: str,
    current: int,
) -> int:
    live_holder = select(
        exists().where(
            Project.tenant_key == tenant_key,
            Project.product_id == product_id,
            Project.series_number == current,
            Project.id != row_id,
            project_not_trashed(),
        )
        | exists().where(
            Task.tenant_key == tenant_key,
            Task.product_id == product_id,
            Task.series_number == current,
            Task.id != row_id,
            Task.deleted_at.is_(None),
        )
    )
    if (await session.execute(live_holder)).scalar_one():
        return await lowest_free_series_number(session, tenant_key, product_id)
    return current
