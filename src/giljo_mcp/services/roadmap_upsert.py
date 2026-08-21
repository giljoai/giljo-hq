# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""How validated roadmap items become rows (extracted from RoadmapService, BE-9477).

One responsibility: turn a list of already-validated, already-resolved items into
the ``INSERT ... ON CONFLICT DO UPDATE`` statements that persist them. Everything
before this point -- validation, alias resolution, the active-product assertion --
has already happened, and everything after it (the commit, the broadcast, the
returned counts) belongs to the service. Extracted for the same reason
``roadmap_references.py`` was: ``roadmap_service.py`` is under a flat 800-line cap
and this is a self-contained, independently testable step rather than session
orchestration.

**This module holds a live exhibit -- read BE-9144 before changing the statement.**
``upsert_many`` was a per-item INSERT loop until BE-9144 collapsed it into ONE
multi-row statement for performance, with ``test_be9144_roadmap_batch.py`` pinning
both the query count and the last-write-wins de-dup that the loop used to get for
free. You may harden that invariant; you may not change what it does without first
reproducing the original incident as a failing test.

Edition Scope: CE.
"""

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
    """Which metadata columns an existing row's UPDATE writes (BE-9477).

    Flag off: all of them, in ``PATCHABLE_ITEM_FIELDS`` order, which is the
    order they were written in before this function existed -- so the emitted
    ``SET`` clause is unchanged rather than merely equivalent.

    Flag on: only the ones the payload literally carried, again in canonical
    order so two rows supplying the same keys land in the same group whatever
    order the agent wrote them in. An item carrying no metadata at all yields an
    empty tuple: the row is still inserted-or-touched, and every stored value
    survives, which is the correct reading of "patch nothing".
    """
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
    """Batch-upsert roadmap items in ONE multi-row statement (BE-9144).

    Replaces the former per-item insert loop. Items are de-duped on the
    ``uq_roadmap_item`` key (item_type, project_id, task_id) keeping the LAST
    occurrence: a single ``ON CONFLICT DO UPDATE`` cannot affect the same
    conflict target twice (Postgres cardinality violation), so this de-dup
    reproduces the last-write-wins the per-item loop got for free (first row
    inserted, later duplicate updated it). ``items_upserted`` in the caller
    still reports the raw request length, unchanged.

    BE-9477 -- ``patch_fields`` and why the batching survives it. A statement's
    ``SET`` clause is fixed for every row in it, so rows that patch DIFFERENT
    columns cannot share one. They are therefore grouped by which columns they
    carry, one statement per distinct shape. That leaves BE-9144's collapse
    intact where it matters: with the flag OFF every row takes the same
    full-column shape and this is the identical single statement it has always
    been, and with the flag ON a uniform batch -- what any re-rank sends -- is
    still exactly one. The bound is the number of distinct shapes in the batch,
    at most 32 (the subsets of five metadata columns), reached only by a caller
    that deliberately varies the shape per row.

    The INSERT half is untouched by the flag, and correctly so: a row that does
    not exist yet has no stored value to preserve, so an omitted key takes its
    ordinary column default exactly as before.
    """
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
