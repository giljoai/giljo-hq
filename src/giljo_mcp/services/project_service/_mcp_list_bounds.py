# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from collections.abc import Callable
from typing import Any

from giljo_mcp.exceptions import ValidationError
from giljo_mcp.repositories._project_keyset import (
    COMPLETION_RECENCY_AXIS,
    CREATED_RECENCY_AXIS,
    project_sort_value,
)
from giljo_mcp.services._mcp_wire_bounds import (
    MCP_LIST_CHAR_CEILING,
    CursorRejectedError,
    decode_cursor,
    encode_cursor,
    filter_fingerprint,
    fit_rows_to_char_ceiling,
    wire_length,
)


LIST_PROJECTS_LIMIT_DEFAULT = 50
LIST_PROJECTS_LIMIT_MAX = 500

_QUERY_MAX_LENGTH = 200

_TAXONOMY_ALIAS_PREFIX_MAX_LENGTH = 64

_ADVICE_BY_REASON: dict[str, str] = {
    "limit": (
        "This list is INCOMPLETE -- do not treat it as the full set. It was bounded by the "
        "limit you asked for (or its default), so raising limit WILL return more. Read "
        "counts.matched (total hits) or counts.remaining (still ahead of your cursor, if "
        "walking) before you decide. To narrow instead, pass status, project_type, "
        "taxonomy_alias_prefix, query, or a created_after / completed_after window."
    ),
    "response_size": (
        "This list is INCOMPLETE -- do not treat it as the full set. It was cut by RESPONSE "
        "SIZE rather than by row count, so a HIGHER LIMIT WILL NOT RETURN MORE."
    ),
    "defensive_ceiling": (
        "This list is INCOMPLETE -- do not treat it as the full set. It hit the server's "
        "defensive ceiling, so raising limit will NOT complete it. Narrow the query to get a "
        "complete answer: pass status, project_type, taxonomy_alias_prefix, query, or a "
        "created_after / completed_after window."
    ),
}

_LEANER_ROW_REMEDY = " Ask for a leaner row with mode='triage', or drop back from a richer mode."
_NARROW_REMEDY = (
    " Narrow with status, project_type, taxonomy_alias_prefix, query, or a created_after / completed_after window."
)

_CURSOR_REMEDY = (
    "There is more: pass truncation.next_cursor back as the cursor parameter (with the "
    "SAME filters) to continue from where this page stopped, and keep going until a "
    "response comes back with truncated=false. "
)


def _advice(reason: str, *, next_cursor: str | None, mode: str | None) -> str:
    advice = _ADVICE_BY_REASON.get(reason, _ADVICE_BY_REASON["defensive_ceiling"])
    if reason == "response_size":
        if mode != "triage":
            advice += _LEANER_ROW_REMEDY
        advice += _NARROW_REMEDY
    if next_cursor:
        advice = _CURSOR_REMEDY + advice
    return advice


def resolve_search_query(query: Any) -> str | None:
    if query is None:
        return None
    if not isinstance(query, str):
        raise ValidationError(
            "query must be a string.",
            context={"operation": "list_projects"},
        )
    if len(query) > _QUERY_MAX_LENGTH:
        raise ValidationError(
            f"query exceeds {_QUERY_MAX_LENGTH}-character limit.",
            context={"operation": "list_projects"},
        )
    return query.strip() or None


def resolve_row_limit(limit: Any) -> int:
    if limit is None:
        return LIST_PROJECTS_LIMIT_DEFAULT
    if isinstance(limit, bool) or not isinstance(limit, int):
        raise ValidationError(
            "limit must be an integer.",
            context={"operation": "list_projects"},
        )
    return max(1, min(limit, LIST_PROJECTS_LIMIT_MAX))


def apply_row_limit(rows: list, limit: int) -> tuple[list, int, bool]:
    matched = len(rows)
    if matched <= limit:
        return rows, matched, False
    return rows[:limit], matched, True


def build_counts_block(
    grouped_rows: list,
    *,
    returned: int,
    matched: int | None,
    remaining: int | None = None,
) -> dict[str, Any]:
    from giljo_mcp.domain.project_status import ProjectStatus

    by_status: dict[str, int] = {s.value: 0 for s in ProjectStatus}
    by_type: dict[str, int] = {}
    total = 0
    created: list = []
    completed: list = []

    for status, abbreviation, min_created, max_created, min_completed, max_completed, count in grouped_rows:
        total += count
        if status is not None:
            by_status[str(status)] = by_status.get(str(status), 0) + count
        if abbreviation:
            by_type[abbreviation] = by_type.get(abbreviation, 0) + count
        created.extend(v for v in (min_created, max_created) if v is not None)
        completed.extend(v for v in (min_completed, max_completed) if v is not None)

    counts: dict[str, Any] = {
        "scope": "product",
        "total": total,
    }
    if matched is not None:
        counts["matched"] = matched
    if remaining is not None:
        counts["remaining"] = remaining
    counts["returned"] = returned
    counts["by_status"] = by_status
    counts["by_type"] = by_type
    counts["date_span"] = {
        "created_first": min(created).isoformat() if created else None,
        "created_last": max(created).isoformat() if created else None,
        "completed_first": min(completed).isoformat() if completed else None,
        "completed_last": max(completed).isoformat() if completed else None,
    }
    return counts


def _truncation_note(
    rows_fetched: int,
    completion_oriented: bool,
    *,
    ceiling: int,
    reason: str = "defensive_ceiling",
    next_cursor: str | None = None,
    mode: str | None = None,
) -> dict[str, Any]:
    note = {
        "reason": reason,
        "ceiling": ceiling,
        "rows_fetched": rows_fetched,
        "dropped": "the OLDEST completions" if completion_oriented else "the OLDEST-CREATED projects",
        "advice": _advice(reason, next_cursor=next_cursor, mode=mode),
    }
    if next_cursor:
        note["next_cursor"] = next_cursor
    return note


def build_list_response(
    *,
    projects_out: list[dict[str, Any]],
    product_id: str,
    depth: int,
    mode: str | None,
    counts: dict[str, Any],
    ceiling: int,
    ceiling_truncated: bool,
    ceiling_rows_fetched: int,
    limit_truncated: bool,
    effective_limit: int,
    completion_oriented: bool,
    cursor_charge: str | None = None,
    mint_cursor: Callable[[list[dict[str, Any]]], str | None] | None = None,
    char_ceiling: int | None = None,
) -> dict[str, Any]:
    char_ceiling = MCP_LIST_CHAR_CEILING if char_ceiling is None else char_ceiling

    counts["returned"] = len(projects_out)
    candidate_notes = [
        _truncation_note(
            ceiling_rows_fetched, completion_oriented, ceiling=ceiling, next_cursor=cursor_charge, mode=mode
        ),
        _truncation_note(
            len(projects_out),
            completion_oriented,
            reason="limit",
            ceiling=effective_limit,
            next_cursor=cursor_charge,
            mode=mode,
        ),
        _truncation_note(
            len(projects_out),
            completion_oriented,
            reason="response_size",
            ceiling=char_ceiling,
            next_cursor=cursor_charge,
            mode=mode,
        ),
    ]
    envelope: dict[str, Any] = {
        "success": True,
        "product_id": product_id,
        "count": len(projects_out),
        "depth": depth,
        "truncated": True,
        "counts": counts,
        "projects": [],
        "truncation": max(candidate_notes, key=wire_length),
    }
    if mode is not None:
        envelope["mode"] = mode

    projects_out, size_dropped = fit_rows_to_char_ceiling(projects_out, envelope=envelope, ceiling=char_ceiling)

    next_cursor = mint_cursor(projects_out) if mint_cursor is not None else None

    returned = len(projects_out)
    counts["returned"] = returned
    response: dict[str, Any] = {
        "success": True,
        "product_id": product_id,
        "count": returned,
        "depth": depth,
        "truncated": ceiling_truncated or bool(size_dropped) or limit_truncated,
        "counts": counts,
        "projects": projects_out,
    }
    if ceiling_truncated:
        response["truncation"] = _truncation_note(
            ceiling_rows_fetched, completion_oriented, ceiling=ceiling, next_cursor=next_cursor, mode=mode
        )
    elif size_dropped:
        response["truncation"] = _truncation_note(
            returned,
            completion_oriented,
            reason="response_size",
            ceiling=char_ceiling,
            next_cursor=next_cursor,
            mode=mode,
        )
    elif limit_truncated:
        response["truncation"] = _truncation_note(
            returned,
            completion_oriented,
            reason="limit",
            ceiling=effective_limit,
            next_cursor=next_cursor,
            mode=mode,
        )
    if mode is not None:
        response["mode"] = mode
    return response




def project_filter_fingerprint(
    *,
    product_id: str,
    status_list: list[str] | None,
    include_completed: bool,
    include_superseded: bool,
    hidden: Any,
    project_type_list: list[str] | None,
    taxonomy_alias_prefix: str | None,
    created_after: Any,
    created_before: Any,
    completed_after: Any,
    completed_before: Any,
    query: str | None,
) -> str:
    return filter_fingerprint(
        {
            "product_id": product_id,
            "status": sorted(status_list) if status_list else None,
            "include_completed": include_completed,
            "include_superseded": include_superseded,
            "hidden": hidden,
            "project_type": sorted(project_type_list) if project_type_list else None,
            "taxonomy_alias_prefix": taxonomy_alias_prefix,
            "created_after": created_after,
            "created_before": created_before,
            "completed_after": completed_after,
            "completed_before": completed_before,
            "query": query,
        }
    )


def resolve_cursor_position(cursor: Any, *, axis: str, fingerprint: str) -> tuple[Any, str] | None:
    if cursor is None or cursor == "":
        return None
    if not isinstance(cursor, str):
        raise CursorRejectedError(
            "CURSOR_MALFORMED",
            "cursor must be the string token returned in a previous response's "
            "truncation.next_cursor. Call again without cursor to restart the walk.",
        )
    allow_null = axis == COMPLETION_RECENCY_AXIS
    return decode_cursor(cursor, axis=axis, fingerprint=fingerprint, allow_null_sort_value=allow_null)


def mint_next_cursor(
    *,
    returned_rows: list[dict[str, Any]],
    fetched_rows: list,
    matched: int,
    ceiling_truncated: bool,
    axis: str,
    fingerprint: str,
) -> str | None:
    if returned_rows:
        row_id = returned_rows[-1].get("project_id") or returned_rows[-1].get("id")
        sort_value = _sort_value_by_id(fetched_rows, row_id, axis)
    elif matched == 0 and ceiling_truncated and fetched_rows:
        row_id = fetched_rows[-1].id
        sort_value = project_sort_value(fetched_rows[-1], axis)
    else:
        return None
    if row_id is None:
        return None
    return encode_cursor(axis=axis, sort_value=sort_value, row_id=row_id, fingerprint=fingerprint)


def _sort_value_by_id(fetched_rows: list, row_id: str | None, axis: str) -> Any:
    for row in fetched_rows:
        if row.id == row_id:
            return project_sort_value(row, axis)
    return None


def open_cursor_walk(
    cursor: Any,
    *,
    completion_oriented: bool,
    product_id: str,
    status_list: list[str] | None,
    include_completed: bool,
    include_superseded: bool,
    hidden: Any,
    project_type_list: list[str] | None,
    taxonomy_alias_prefix: str | None,
    created_after: Any,
    created_before: Any,
    completed_after: Any,
    completed_before: Any,
    query: str | None,
) -> tuple[str, str, tuple[Any, str] | None]:
    axis = COMPLETION_RECENCY_AXIS if completion_oriented else CREATED_RECENCY_AXIS
    fingerprint = project_filter_fingerprint(
        product_id=product_id,
        status_list=status_list,
        include_completed=include_completed,
        include_superseded=include_superseded,
        hidden=hidden,
        project_type_list=project_type_list,
        taxonomy_alias_prefix=taxonomy_alias_prefix,
        created_after=created_after,
        created_before=created_before,
        completed_after=completed_after,
        completed_before=completed_before,
        query=query,
    )
    return axis, fingerprint, resolve_cursor_position(cursor, axis=axis, fingerprint=fingerprint)


def resolve_status_list(status: Any, valid_statuses: Any) -> list[str] | None:
    if status is None:
        return None
    status_list = [status] if isinstance(status, str) else list(status)
    invalid = [s for s in status_list if s not in valid_statuses]
    if invalid:
        raise ValidationError(
            f"Invalid status value(s) {invalid}. Must be one of: {', '.join(sorted(valid_statuses))}",
            context={"operation": "list_projects", "invalid": invalid},
        )
    return status_list


def validate_taxonomy_alias_prefix(taxonomy_alias_prefix: Any) -> None:
    if taxonomy_alias_prefix is None:
        return
    if not isinstance(taxonomy_alias_prefix, str):
        raise ValidationError(
            "taxonomy_alias_prefix must be a string.",
            context={"operation": "list_projects"},
        )
    if len(taxonomy_alias_prefix) > _TAXONOMY_ALIAS_PREFIX_MAX_LENGTH:
        raise ValidationError(
            f"taxonomy_alias_prefix exceeds {_TAXONOMY_ALIAS_PREFIX_MAX_LENGTH}-character limit.",
            context={"operation": "list_projects"},
        )


def validate_project_type_list(project_type: Any, valid_abbreviations: set[str]) -> list[str] | None:
    if project_type is None:
        return None
    project_type_list = [project_type] if isinstance(project_type, str) else list(project_type)
    invalid_types = [t for t in project_type_list if t not in valid_abbreviations]
    if invalid_types:
        raise ValidationError(
            f"Invalid project_type value(s) {invalid_types}. Valid types: {', '.join(sorted(valid_abbreviations))}",
            context={"operation": "list_projects", "invalid": invalid_types},
        )
    return project_type_list
