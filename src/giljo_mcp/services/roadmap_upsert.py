# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from typing import Any

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import func

from giljo_mcp.models.base import generate_uuid
from giljo_mcp.models.roadmaps import RoadmapItem
from giljo_mcp.services.roadmap_validation import (
    PATCH_FIELDS_KEY,
    PATCHABLE_ITEM_FIELDS,
)


def updated_columns(item: dict[str, Any], *, patch_fields: bool) -> tuple[str, ...]:
    if not patch_fields:
        return PATCHABLE_ITEM_FIELDS
    present = item.get(PATCH_FIELDS_KEY) or frozenset()
    return tuple(column for column in PATCHABLE_ITEM_FIELDS if column in present)


async def upsert_many(
    session: AsyncSession,
    tenant_key: str,
    roadmap_id: str,
    items: list[dict[str, Any]],
    *,
    patch_fields: bool = False,
) -> None:
    if not items:
        return

    deduped: dict[tuple[str, str | None, str | None], dict[str, Any]] = {}
    for v in items:
        deduped[(v["item_type"], v["project_id"], v["task_id"])] = v

    groups: dict[tuple[str, ...], list[dict[str, Any]]] = {}
    for v in deduped.values():
        groups.setdefault(updated_columns(v, patch_fields=patch_fields), []).append(v)

    for columns, rows in groups.items():
        values = [
            {
                "id": generate_uuid(),
                "tenant_key": tenant_key,
                "roadmap_id": roadmap_id,
                "item_type": v["item_type"],
                "project_id": v["project_id"],
                "task_id": v["task_id"],
                "sort_order": v["sort_order"],
                "risk": v["risk"],
                "complexity": v["complexity"],
                "blocked": v["blocked"],
                "blocked_reason": v["blocked_reason"],
            }
            for v in rows
        ]
        stmt = pg_insert(RoadmapItem).values(values)
        stmt = stmt.on_conflict_do_update(
            constraint="uq_roadmap_item",
            set_={
                **{column: getattr(stmt.excluded, column) for column in columns},
                "updated_at": func.now(),
            },
        )
        await session.execute(stmt)
