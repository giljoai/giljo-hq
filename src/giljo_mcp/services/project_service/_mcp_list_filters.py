# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any

from giljo_mcp.domain.project_status import ProjectStatus
from giljo_mcp.services.project_service._mcp_list_bounds import (
    resolve_row_limit,
    resolve_search_query,
    resolve_status_list,
    validate_project_type_list,
    validate_taxonomy_alias_prefix,
)


def _parse_iso_datetime(value: Any) -> datetime | None:
    from datetime import UTC

    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if not isinstance(value, str):
        return None
    try:
        normalized = value.replace("Z", "+00:00") if value.endswith("Z") else value
        dt = datetime.fromisoformat(normalized)
        return dt if dt.tzinfo else dt.replace(tzinfo=UTC)
    except (ValueError, TypeError):
        return None


def _apply_post_fetch_filters(
    rows: list,
    *,
    exclude_superseded: bool,
    hidden: bool | None,
    project_type_list: list[str] | None,
    taxonomy_alias_prefix: str | None,
    created_after: datetime | None,
    created_before: datetime | None,
    completed_after: datetime | None,
    completed_before: datetime | None,
) -> list:
    filtered: list = []
    for p in rows:
        if exclude_superseded and p.status == ProjectStatus.SUPERSEDED.value:
            continue

        if hidden is not None and bool(p.hidden) != bool(hidden):
            continue

        if project_type_list is not None:
            pt_abbrev = p.project_type.abbreviation if p.project_type else None
            if pt_abbrev not in project_type_list:
                continue

        if taxonomy_alias_prefix and not (p.taxonomy_alias or "").startswith(taxonomy_alias_prefix):
            continue

        if created_after is not None or created_before is not None:
            created_dt = _parse_iso_datetime(p.created_at)
            if created_after is not None and (created_dt is None or created_dt < created_after):
                continue
            if created_before is not None and (created_dt is None or created_dt > created_before):
                continue

        if completed_after is not None or completed_before is not None:
            completed_dt = _parse_iso_datetime(p.completed_at) if p.completed_at else None
            if completed_after is not None and (completed_dt is None or completed_dt < completed_after):
                continue
            if completed_before is not None and (completed_dt is None or completed_dt > completed_before):
                continue

        filtered.append(p)
    return filtered


async def resolve_list_projects_query_filters(
    status: str | list[str] | None,
    project_type: str | list[str] | None,
    taxonomy_alias_prefix: str | None,
    query: str | None,
    limit: int | None,
    *,
    valid_filter_statuses: frozenset[str],
    tenant_key: str,
    get_valid_project_types: Callable[[str], Awaitable[list[dict[str, Any]]]],
) -> tuple[list[str] | None, list[str] | None, str | None, int]:
    status_list = resolve_status_list(status, valid_filter_statuses)

    project_type_list: list[str] | None = None
    if project_type is not None:
        from giljo_mcp.services.taxonomy_ops import RESERVED_TASK_TYPE_ABBR

        valid_types = await get_valid_project_types(tenant_key)
        project_type_list = validate_project_type_list(
            project_type, {t["abbreviation"] for t in valid_types} | {RESERVED_TASK_TYPE_ABBR}
        )

    validate_taxonomy_alias_prefix(taxonomy_alias_prefix)

    query = resolve_search_query(query)
    effective_limit = resolve_row_limit(limit)

    return status_list, project_type_list, query, effective_limit
