# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.exceptions import ValidationError
from giljo_mcp.models.comm import CommThread


def thread_list_order_clauses() -> list[Any]:
    return [CommThread.created_at.desc(), CommThread.id.asc()]


def thread_keyset_after(cursor_ts: datetime, before_id: str) -> Any:
    return or_(
        CommThread.created_at < cursor_ts,
        and_(CommThread.created_at == cursor_ts, CommThread.id > before_id),
    )


async def resolve_thread_cursor(session: AsyncSession, tenant_key: str, before_id: str) -> datetime:
    cursor_ts = (
        await session.execute(
            select(CommThread.created_at).where(
                CommThread.tenant_key == tenant_key,
                CommThread.id == before_id,
            )
        )
    ).scalar_one_or_none()
    if cursor_ts is None:
        raise ValidationError(
            "before_id does not name a thread on this list. It may have been deleted "
            "since the page that produced it. Restart the walk by calling again without "
            "before_id.",
            context={"operation": "comm_thread.list"},
        )
    return cursor_ts
