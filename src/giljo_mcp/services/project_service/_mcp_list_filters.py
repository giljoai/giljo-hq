# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""Post-fetch row filtering for the agent-facing project list (BE-9468 extraction).

Extracted from ``_mcp_adapter_query_mixin`` so that module stays under the 800-line
guardrail. Holds the cross-cutting predicates that deliberately do NOT live in the SQL
query, and the ISO parsing they need -- pure functions over plain rows, no database, no
session, no ``self``.

**Why these predicates are here rather than in SQL, which is load-bearing for BE-9468:**
status and product scoping are pushed down (Seq 161 / IMP-5036), but ``hidden``,
``project_type``, ``taxonomy_alias_prefix`` and the four date bounds slice across
enum-typed and computed columns that do not all live in a single index. Because they run
AFTER the fetch, the caller-facing ``limit`` has to be applied after them too -- a SQL
``LIMIT`` would cut before these ran and could hand back three rows to a caller asking
for fifty while fifty matching rows existed, with nothing in the response to say why.
That silent shortfall is the defect class this whole change exists to remove.

Behavior is unchanged by the extraction; the filtering suite covers every predicate on
both sides of the move.

Edition Scope: Both.
"""

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
    """Parse an ISO-8601 string into a tz-aware datetime; pass-through if already a datetime.

    Returns None for falsy/unparseable input. Naive datetimes are coerced to UTC
    so callers can compare against tz-aware boundary values without surprises.
    """
    from datetime import UTC

    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if not isinstance(value, str):
        return None
    try:
        # datetime.fromisoformat handles "2026-01-01T00:00:00+00:00"; the trailing
        # "Z" form is normalized below. Be defensive in case older inputs slip through.
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
    """Apply the cross-cutting predicates that do not live in the SQL query.

    Status and product scoping are pushed down to SQL (Seq 161 / IMP-5036); the v1.2.1
    predicates below stay in memory because they slice across enum-typed and computed
    columns that do not all live in a single index.

    Extracted verbatim from ``list_projects_for_mcp`` under BE-9468 to keep that
    function inside its length budget. Behavior is unchanged, and the filtering suite
    covers every predicate on both sides of the move.

    **This is also why BE-9468's ``limit`` is applied AFTER this rather than as a SQL
    LIMIT:** these predicates run here, so a SQL slice would cut before them and could
    return fewer rows than the caller asked for while more matching rows existed.
    """
    filtered: list = []
    for p in rows:
        # Superseded exclusion (BE-9157): audit-trail rows hidden by default.
        if exclude_superseded and p.status == ProjectStatus.SUPERSEDED.value:
            continue

        # Hidden filter (None = both)
        if hidden is not None and bool(p.hidden) != bool(hidden):
            continue

        # Project type filter
        if project_type_list is not None:
            pt_abbrev = p.project_type.abbreviation if p.project_type else None
            if pt_abbrev not in project_type_list:
                continue

        # Taxonomy alias prefix filter (case-sensitive prefix match)
        if taxonomy_alias_prefix and not (p.taxonomy_alias or "").startswith(taxonomy_alias_prefix):
            continue

        # Date range filters (created_at and completed_at are ISO strings on ProjectListItem)
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
    """Normalize + validate list_projects' agent-supplied filters (BE-9499a extraction).

    Extracted out of ``list_projects_for_mcp`` verbatim (same pattern as
    ``_apply_post_fetch_filters`` above) to keep that function -- and this
    module's owning file -- inside their length/size budgets. Behavior
    unchanged. ``get_valid_project_types`` is injected (rather than imported)
    because it is a tenant-scoped instance method on ``ProjectService``.
    """
    status_list = resolve_status_list(status, valid_filter_statuses)

    project_type_list: list[str] | None = None
    if project_type is not None:
        # BE-6079 (L3) / IMP-6262: TSK is filtered OUT of _get_valid_project_types
        # because a project can never be CREATED as TSK. Converting a task now STRIPS
        # the type (the project is born untyped) and the ce_0067 backfill un-typed any
        # legacy converted projects, so no project is TSK-typed -- this filter value is
        # a harmless no-op that now matches nothing, kept for back-compat. Create and
        # retag still reject TSK elsewhere.
        from giljo_mcp.services.taxonomy_ops import RESERVED_TASK_TYPE_ABBR

        valid_types = await get_valid_project_types(tenant_key)
        project_type_list = validate_project_type_list(
            project_type, {t["abbreviation"] for t in valid_types} | {RESERVED_TASK_TYPE_ABBR}
        )

    validate_taxonomy_alias_prefix(taxonomy_alias_prefix)

    # BE-9468: agent input reaching a SQL predicate and a row cut -- validated at
    # the boundary. See _mcp_list_bounds for the contract and its reasoning.
    query = resolve_search_query(query)
    effective_limit = resolve_row_limit(limit)

    return status_list, project_type_list, query, effective_limit
