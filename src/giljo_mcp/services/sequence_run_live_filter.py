# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.domain.project_status import LIFECYCLE_FINISHED_STATUSES
from giljo_mcp.models.projects import Project
from giljo_mcp.models.sequence_runs import SequenceRun
from giljo_mcp.repositories._project_enrichment_reads_mixin import project_not_trashed


def _run_member_ids(run: SequenceRun) -> list[str]:
    return [str(p) for p in ((run.resolved_order or []) + (run.project_ids or [])) if p]


async def filter_runs_with_live_members(
    *,
    session: AsyncSession,
    runs: list[SequenceRun],
    tenant_key: str,
) -> list[SequenceRun]:
    member_ids: set[str] = set()
    for run in runs:
        member_ids.update(_run_member_ids(run))

    if not member_ids:
        return runs

    rows = await session.execute(
        select(Project.id, Project.status, Project.deleted_at).where(
            Project.tenant_key == tenant_key,
            Project.id.in_(member_ids),
        )
    )
    live_project_ids: set[str] = {
        str(pid)
        for pid, status, deleted_at in rows.all()
        if deleted_at is None and status not in LIFECYCLE_FINISHED_STATUSES
    }

    return [run for run in runs if any(pid in live_project_ids for pid in _run_member_ids(run))]


async def filter_runs_with_reviewable_members(
    *,
    session: AsyncSession,
    runs: list[SequenceRun],
    tenant_key: str,
) -> list[SequenceRun]:

    def unreviewed(run: SequenceRun) -> list[str]:
        statuses = run.project_statuses if isinstance(run.project_statuses, dict) else {}
        reviewed = set(run.reviewed_project_ids or [])
        return [str(pid) for pid, st in statuses.items() if st == "completed" and pid not in reviewed]

    wanted = {pid for run in runs for pid in unreviewed(run)}
    if not wanted:
        return runs
    rows = await session.execute(
        select(Project.id).where(
            Project.tenant_key == tenant_key,
            Project.id.in_(wanted),
            project_not_trashed(),
        )
    )
    present = {str(pid) for (pid,) in rows.all()}
    return [run for run in runs if any(pid in present for pid in unreviewed(run))]


async def filter_runs_by_product(
    *,
    session: AsyncSession,
    runs: list[SequenceRun],
    tenant_key: str,
    product_id: str,
) -> list[SequenceRun]:
    member_ids: set[str] = set()
    for run in runs:
        member_ids.update(_run_member_ids(run))

    if not member_ids:
        return []

    rows = await session.execute(
        select(Project.id).where(
            Project.tenant_key == tenant_key,
            Project.product_id == product_id,
            project_not_trashed(),
            Project.id.in_(member_ids),
        )
    )
    in_product: set[str] = {str(pid) for (pid,) in rows.all()}

    return [run for run in runs if any(pid in in_product for pid in _run_member_ids(run))]


async def member_product_ids(
    *,
    session: AsyncSession,
    runs: list[SequenceRun],
    tenant_key: str,
) -> dict[str, str | None]:
    member_ids = {pid for run in runs for pid in _run_member_ids(run)}
    product_of: dict[str, str] = {}
    if member_ids:
        rows = await session.execute(
            select(Project.id, Project.product_id).where(
                Project.tenant_key == tenant_key,
                Project.id.in_(member_ids),
                project_not_trashed(),
            )
        )
        product_of = {str(pid): str(product) for pid, product in rows.all() if product}
    return {run.id: next((product_of[pid] for pid in _run_member_ids(run) if pid in product_of), None) for run in runs}
