# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import itertools


_SERIES_LOW = 1000
_SERIES_SPAN = 8000
_SERIES_STEP = 100
_SERIES_COUNTER = itertools.count()


def _series_for(index: int) -> int:
    lap, position = divmod(index % _SERIES_SPAN, _SERIES_SPAN // _SERIES_STEP)
    return _SERIES_LOW + position * _SERIES_STEP + lap


def next_series_number() -> int:
    return _series_for(next(_SERIES_COUNTER))


_THREAD_SERIAL_COUNTER = itertools.count()


def next_thread_serial() -> int:
    return _series_for(next(_THREAD_SERIAL_COUNTER))


async def seed_projects(session, tenant_key: str, project_ids: list[str]) -> None:
    from uuid import uuid4

    from sqlalchemy import select

    from giljo_mcp.database import tenant_session_context
    from giljo_mcp.models import Product, Project

    wanted = list(dict.fromkeys(project_ids))
    with tenant_session_context(session, tenant_key):
        owned = set(
            await session.scalars(select(Project.id).where(Project.tenant_key == tenant_key, Project.id.in_(wanted)))
        )
    missing = [pid for pid in wanted if pid not in owned]
    if not missing:
        return
    product = Product(id=str(uuid4()), name=f"Seeded product {uuid4().hex[:6]}", tenant_key=tenant_key, is_active=False)
    session.add(product)
    await session.flush()
    for pid in missing:
        session.add(
            Project(
                id=pid,
                name=f"Seeded member {pid[:8]}",
                description="seeded",
                mission="seeded",
                tenant_key=tenant_key,
                product_id=product.id,
                series_number=next_series_number(),
            )
        )
    await session.flush()
