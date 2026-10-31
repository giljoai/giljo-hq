# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from collections.abc import Iterable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.models.sequence_runs import SequenceRun


async def chain_member_ids(session: AsyncSession, tenant_key: str, project_ids: Iterable[str]) -> set[str]:
    wanted = set(project_ids)
    result = await session.execute(
        select(SequenceRun.project_ids, SequenceRun.resolved_order).where(SequenceRun.tenant_key == tenant_key)
    )
    members: set[str] = set()
    for ids, order in result.all():
        members |= set(ids or []) | set(order or [])
    return members & wanted
