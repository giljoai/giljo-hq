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
