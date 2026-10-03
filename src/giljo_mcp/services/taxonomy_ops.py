# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import logging
from typing import Any

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.exceptions import ValidationError
from giljo_mcp.models.base import generate_uuid
from giljo_mcp.models.projects import TaxonomyType
from giljo_mcp.repositories.taxonomy_repository import TaxonomyRepository
from giljo_mcp.utils.log_sanitizer import sanitize


logger = logging.getLogger(__name__)

_repo = TaxonomyRepository()

RESERVED_TASK_TYPE_ABBR = "TSK"

RESERVED_CHAT_THREAD_TYPE_ABBR = "CHT"

RESERVED_HANDOVER_TYPE_ABBR = "HND"

RESERVED_TYPE_ABBRS = frozenset({RESERVED_TASK_TYPE_ABBR, RESERVED_CHAT_THREAD_TYPE_ABBR, RESERVED_HANDOVER_TYPE_ABBR})

VALID_TASK_TYPE_ABBRS: tuple[str, ...] = (RESERVED_TASK_TYPE_ABBR, RESERVED_HANDOVER_TYPE_ABBR)


def resolve_task_type_abbr(task_type: str | None, *, operation: str) -> str:
    normalized = (task_type or "").strip()
    if not normalized:
        return RESERVED_TASK_TYPE_ABBR
    if normalized not in VALID_TASK_TYPE_ABBRS:
        raise ValidationError(
            message=(
                f"Invalid task_type '{task_type}'. Valid types: "
                f"{', '.join(VALID_TASK_TYPE_ABBRS)} -- "
                f"'{RESERVED_TASK_TYPE_ABBR}' for an ordinary task (the default) and "
                f"'{RESERVED_HANDOVER_TYPE_ABBR}' for a session handover. Project taxonomy "
                "abbreviations are not task types."
            ),
            context={"operation": operation, "field": "task_type", "task_type": task_type},
        )
    return normalized


DEFAULT_TAXONOMY_TYPES: list[dict[str, Any]] = [
    {"abbr": "BE", "label": "Backend", "color": "#4CAF50"},
    {"abbr": "FE", "label": "Frontend", "color": "#2196F3"},
    {"abbr": "DB", "label": "Database", "color": "#FF9800"},
    {"abbr": "UI", "label": "UI/UX", "color": "#9C27B0"},
    {"abbr": "API", "label": "API/Integration", "color": "#00BCD4"},
    {"abbr": "INF", "label": "Infrastructure", "color": "#795548"},
    {"abbr": "DOC", "label": "Documentation", "color": "#607D8B"},
    {"abbr": "SEC", "label": "Security", "color": "#F44336"},
    {"abbr": "CTX", "label": "Context Update", "color": "#9E9E9E"},
    {"abbr": RESERVED_TASK_TYPE_ABBR, "label": "Task", "color": "#8b5cf6"},
    {"abbr": RESERVED_CHAT_THREAD_TYPE_ABBR, "label": "Chat Thread", "color": "#1565C0"},
    {"abbr": RESERVED_HANDOVER_TYPE_ABBR, "label": "Handover", "color": "#e6ecf7"},
]


async def ensure_default_types_seeded(session: AsyncSession, tenant_key: str) -> None:
    count = await _repo.count_for_tenant(session, tenant_key)
    if count:
        return

    logger.info("Seeding %d default taxonomy types for tenant %s", len(DEFAULT_TAXONOMY_TYPES), sanitize(tenant_key))

    for i, td in enumerate(DEFAULT_TAXONOMY_TYPES):
        taxonomy_type = TaxonomyType(
            tenant_key=tenant_key,
            abbreviation=td["abbr"],
            label=td["label"],
            color=td["color"],
            sort_order=i,
        )
        await _repo.add_taxonomy_type(session, taxonomy_type)

    await _repo.flush(session)


async def ensure_reserved_type(session: AsyncSession, tenant_key: str, abbreviation: str) -> TaxonomyType:
    spec = next(t for t in DEFAULT_TAXONOMY_TYPES if t["abbr"] == abbreviation)
    stmt = (
        pg_insert(TaxonomyType.__table__)
        .values(
            id=generate_uuid(),
            tenant_key=tenant_key,
            abbreviation=abbreviation,
            label=spec["label"],
            color=spec["color"],
            sort_order=len(DEFAULT_TAXONOMY_TYPES) + DEFAULT_TAXONOMY_TYPES.index(spec),
        )
        .on_conflict_do_nothing(constraint="uq_taxonomy_type_abbr")
    )
    await session.execute(stmt)

    row = await _repo.get_by_abbreviation(session, tenant_key, abbreviation)
    if row is None:  # pragma: no cover - insert+select within one tx always resolves
        raise RuntimeError(f"Failed to ensure reserved type {abbreviation} for tenant {sanitize(tenant_key)}")
    return row


async def ensure_reserved_task_type(session: AsyncSession, tenant_key: str) -> TaxonomyType:
    return await ensure_reserved_type(session, tenant_key, RESERVED_TASK_TYPE_ABBR)


async def list_taxonomy_types(session: AsyncSession, tenant_key: str) -> list[Any]:
    rows = await _repo.list_with_project_counts(session, tenant_key)

    types_with_counts = []
    for row in rows:
        tt = row[0]
        tt.project_count = row[1] or 0
        types_with_counts.append(tt)

    return types_with_counts


UPDATABLE_FIELDS = {"label", "color", "sort_order"}


async def create_taxonomy_type(
    session: AsyncSession,
    tenant_key: str,
    *,
    abbreviation: str,
    label: str,
    color: str = "#607D8B",
    sort_order: int = 0,
) -> TaxonomyType:
    existing = await _repo.get_by_abbreviation(session, tenant_key, abbreviation)
    if existing:
        raise ValueError(f"Taxonomy type with abbreviation '{abbreviation}' already exists for this tenant")

    taxonomy_type = TaxonomyType(
        tenant_key=tenant_key,
        abbreviation=abbreviation,
        label=label,
        color=color,
        sort_order=sort_order,
    )
    await _repo.add_taxonomy_type(session, taxonomy_type)
    taxonomy_type = await _repo.flush_and_refresh(session, taxonomy_type)

    logger.info(
        "Created taxonomy type '%s' (%s) for tenant %s",
        sanitize(abbreviation),
        sanitize(label),
        sanitize(tenant_key),
    )
    return taxonomy_type


async def update_taxonomy_type(
    session: AsyncSession,
    tenant_key: str,
    type_id: str,
    **fields: Any,
) -> TaxonomyType:
    taxonomy_type = await _repo.get_by_id(session, tenant_key, type_id)

    if not taxonomy_type:
        raise ValueError(f"Taxonomy type '{type_id}' not found for this tenant")

    for field, value in fields.items():
        if field not in UPDATABLE_FIELDS:
            raise ValueError(f"Field '{field}' is not updatable on TaxonomyType")
        setattr(taxonomy_type, field, value)

    taxonomy_type = await _repo.flush_and_refresh(session, taxonomy_type)

    logger.info("Updated taxonomy type '%s' for tenant %s", sanitize(taxonomy_type.abbreviation), sanitize(tenant_key))
    return taxonomy_type


async def delete_taxonomy_type(session: AsyncSession, tenant_key: str, type_id: str) -> None:
    taxonomy_type = await _repo.get_by_id(session, tenant_key, type_id)

    if not taxonomy_type:
        raise ValueError(f"Taxonomy type '{type_id}' not found for this tenant")

    project_count = await get_project_count_for_type(session, tenant_key, type_id)

    if project_count > 0:
        raise ValueError(
            f"Cannot delete taxonomy type '{taxonomy_type.abbreviation}': "
            f"{project_count} project(s) assigned. Reassign or remove them first."
        )

    await _repo.delete_taxonomy_type(session, taxonomy_type)

    logger.info("Deleted taxonomy type '%s' for tenant %s", sanitize(taxonomy_type.abbreviation), sanitize(tenant_key))


async def get_project_count_for_type(session: AsyncSession, tenant_key: str, type_id: str) -> int:
    return await _repo.get_project_count_for_type(session, tenant_key, type_id)


async def get_next_series_number(
    session: AsyncSession, tenant_key: str, type_id: str, product_id: str | None = None
) -> int:
    return await _repo.get_next_series_number(session, tenant_key, type_id, product_id)


async def get_available_series_numbers(
    session: AsyncSession, tenant_key: str, type_id: str, limit: int = 5, product_id: str | None = None
) -> list[int]:
    used_numbers = await _repo.get_used_series_numbers(session, tenant_key, type_id, product_id)

    if not used_numbers:
        return list(range(1, limit + 1))

    max_used = max(used_numbers)
    available: list[int] = []

    for num in range(1, max_used + 1):
        if num not in used_numbers:
            available.append(num)
            if len(available) >= limit:
                return available

    next_num = max_used + 1
    while len(available) < limit:
        available.append(next_num)
        next_num += 1

    return available


async def check_series_available(
    session: AsyncSession,
    tenant_key: str,
    type_id: str | None,
    series_number: int,
    subseries: str | None = None,
    exclude_project_id: str | None = None,
    product_id: str | None = None,
) -> dict[str, Any]:
    available = await _repo.check_series_available(
        session, tenant_key, type_id, series_number, subseries, exclude_project_id, product_id
    )
    return {"available": available}


async def get_used_subseries(
    session: AsyncSession,
    tenant_key: str,
    type_id: str | None,
    series_number: int,
    exclude_project_id: str | None = None,
    product_id: str | None = None,
) -> dict[str, Any]:
    used = await _repo.get_used_subseries(session, tenant_key, type_id, series_number, exclude_project_id, product_id)
    return {"used_subseries": used}
