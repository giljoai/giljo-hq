# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from collections.abc import Callable
from typing import Any

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.domain.task_status import TaskStatus
from giljo_mcp.models import Task
from giljo_mcp.models.projects import TaxonomyType
from giljo_mcp.services._mcp_wire_bounds import (
    MCP_LIST_CHAR_CEILING,
    CursorRejectedError,
    decode_cursor,
    encode_cursor,
    filter_fingerprint,
    fit_rows_to_char_ceiling,
    wire_length,
)


LIST_TASKS_CHAR_CEILING = MCP_LIST_CHAR_CEILING


LIST_TASKS_LIMIT_DEFAULT = 50

LIST_TASKS_LIMIT_MAX = 500


def truncation_note(
    *,
    reason: str,
    ceiling: int,
    rows_fetched: int,
    dropped: str,
    advice: str,
    next_cursor: str | None = None,
) -> dict[str, Any]:
    note = {
        "reason": reason,
        "ceiling": ceiling,
        "rows_fetched": rows_fetched,
        "dropped": dropped,
        "advice": advice,
    }
    if next_cursor:
        note["next_cursor"] = next_cursor
    return note


LIMIT_ADVICE = (
    "This list is INCOMPLETE -- do not treat it as the full set. The counts block on this "
    "response states the size of the whole board, so you can choose deliberately: narrow "
    "with status, priority, due_before or query, ask for a leaner row with mode='index', "
    f"or raise limit (max {LIST_TASKS_LIMIT_MAX}) to request more on purpose."
)

SIZE_ADVICE = (
    "This list is INCOMPLETE -- do not treat it as the full set. It was cut by RESPONSE "
    "SIZE rather than by row count, so a higher limit will not return more: ask for a "
    "leaner row with mode='index', pass memory_limit to shorten descriptions in "
    "mode='full', or narrow with status, priority, due_before or query."
)

CURSOR_ADVICE_PREFIX = (
    "There is more: pass truncation.next_cursor back as the cursor parameter (with the "
    "SAME filters) to continue from where this page stopped, and keep going until a "
    "response comes back with truncated=false. "
)


def advice_for(base_advice: str, *, next_cursor: str | None, mode: str | None) -> str:
    advice = base_advice
    if mode == "index":
        advice = advice.replace("ask for a leaner row with mode='index', ", "")
        advice = advice.replace(
            "pass memory_limit to shorten descriptions in mode='full', or narrow",
            "narrow",
        )
    if next_cursor:
        advice = CURSOR_ADVICE_PREFIX + advice
    return advice


DROPPED_TASKS = "the OLDEST-CREATED tasks"


def _worst_case_note(effective_limit: int, next_cursor: str | None = None, mode: str | None = None) -> dict[str, Any]:
    limit_note = truncation_note(
        reason="limit",
        ceiling=effective_limit,
        rows_fetched=effective_limit,
        dropped=DROPPED_TASKS,
        advice=advice_for(LIMIT_ADVICE, next_cursor=next_cursor, mode=mode),
        next_cursor=next_cursor,
    )
    size_note = truncation_note(
        reason="response_size",
        ceiling=LIST_TASKS_CHAR_CEILING,
        rows_fetched=effective_limit,
        dropped=DROPPED_TASKS,
        advice=advice_for(SIZE_ADVICE, next_cursor=next_cursor, mode=mode),
        next_cursor=next_cursor,
    )
    return max(limit_note, size_note, key=wire_length)


def apply_bounds(
    response: dict[str, Any],
    rows: list[dict[str, Any]],
    *,
    limit_cut: bool,
    effective_limit: int,
    cursor_charge: str | None = None,
    mint_cursor: Callable[[list[dict[str, Any]]], str | None] | None = None,
    mode: str | None = None,
) -> dict[str, Any]:
    envelope = dict(
        response,
        tasks=[],
        truncated=True,
        truncation=_worst_case_note(effective_limit, next_cursor=cursor_charge, mode=mode),
    )
    kept, size_dropped = fit_rows_to_char_ceiling(rows, envelope=envelope)

    next_cursor = mint_cursor(kept) if mint_cursor is not None else None
    if size_dropped:
        response["tasks"] = kept
        response["count"] = len(kept)

    response["truncated"] = bool(limit_cut or size_dropped)
    if size_dropped:
        response["truncation"] = truncation_note(
            reason="response_size",
            ceiling=LIST_TASKS_CHAR_CEILING,
            rows_fetched=len(kept),
            dropped=DROPPED_TASKS,
            advice=advice_for(SIZE_ADVICE, next_cursor=next_cursor, mode=mode),
            next_cursor=next_cursor,
        )
    elif limit_cut:
        response["truncation"] = truncation_note(
            reason="limit",
            ceiling=effective_limit,
            rows_fetched=len(kept),
            dropped=DROPPED_TASKS,
            advice=advice_for(LIMIT_ADVICE, next_cursor=next_cursor, mode=mode),
            next_cursor=next_cursor,
        )
    return response


def apply_task_filters(
    stmt: Any,
    *,
    status: str | None,
    priority: str | None,
    task_type_id: str | None,
    due_before: Any,
    hidden: bool | None,
    query: str | None,
) -> Any:
    if status:
        stmt = stmt.where(Task.status == status)
    if priority:
        stmt = stmt.where(Task.priority == priority)
    if task_type_id:
        stmt = stmt.where(Task.task_type_id == task_type_id)
    if due_before is not None:
        stmt = stmt.where(Task.due_date < due_before)
    if hidden is not None:
        stmt = stmt.where(Task.hidden == hidden)
    if query and query.strip():
        needle = query.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        pattern = f"%{needle}%"
        stmt = stmt.where(
            or_(
                Task.title.ilike(pattern, escape="\\"),
                Task.description.ilike(pattern, escape="\\"),
                Task.taxonomy_alias.ilike(pattern, escape="\\"),
            )
        )
    return stmt


async def task_counts(
    session: AsyncSession,
    tenant_key: str,
    *,
    product_id: str,
    status: str | None,
    priority: str | None,
    task_type_id: str | None,
    due_before: Any,
    hidden: bool | None,
    query: str | None,
    after_key: tuple[Any, str] | None = None,
) -> dict[str, Any]:
    board_scope = [
        Task.tenant_key == tenant_key,
        Task.product_id == product_id,
        Task.deleted_at.is_(None),
    ]
    grouped = (
        await session.execute(
            select(
                Task.status,
                TaxonomyType.abbreviation,
                func.count(),
                func.min(Task.created_at),
                func.max(Task.created_at),
                func.min(Task.completed_at),
                func.max(Task.completed_at),
            )
            .outerjoin(TaxonomyType, TaxonomyType.id == Task.task_type_id)
            .where(*board_scope)
            .group_by(Task.status, TaxonomyType.abbreviation)
        )
    ).all()

    matched_stmt = apply_task_filters(
        select(func.count()).select_from(Task).where(*board_scope),
        status=status,
        priority=priority,
        task_type_id=task_type_id,
        due_before=due_before,
        hidden=hidden,
        query=query,
    )
    matched = (await session.execute(matched_stmt)).scalar_one()

    remaining = matched
    if after_key is not None:
        remaining = (await session.execute(matched_stmt.where(task_keyset_after(*after_key)))).scalar_one()

    return fold_counts([tuple(row) for row in grouped], matched=matched, remaining=remaining, returned=0)


def fold_counts(
    grouped: list[tuple[str | None, str | None, int, Any, Any, Any, Any]],
    *,
    matched: int | None,
    remaining: int | None = None,
    returned: int,
) -> dict[str, Any]:
    by_status: dict[str, int] = {status.value: 0 for status in TaskStatus}
    by_type: dict[str, int] = {}
    total = 0
    created_first = created_last = completed_first = completed_last = None

    for status, type_abbr, count, cre_min, cre_max, cmp_min, cmp_max in grouped:
        total += count
        if status is not None:
            by_status[status] = by_status.get(status, 0) + count
        if type_abbr is not None:
            by_type[type_abbr] = by_type.get(type_abbr, 0) + count
        created_first = _earlier(created_first, cre_min)
        created_last = _later(created_last, cre_max)
        completed_first = _earlier(completed_first, cmp_min)
        completed_last = _later(completed_last, cmp_max)

    counts: dict[str, Any] = {
        "scope": "product",
        "total": total,
        "by_status": by_status,
        "by_type": by_type,
        "date_span": {
            "created_first": _iso(created_first),
            "created_last": _iso(created_last),
            "completed_first": _iso(completed_first),
            "completed_last": _iso(completed_last),
        },
        "returned": returned,
    }
    if matched is not None:
        counts["matched"] = matched
    if remaining is not None:
        counts["remaining"] = remaining
    return counts


def _earlier(current: Any, candidate: Any) -> Any:
    if candidate is None:
        return current
    return candidate if current is None or candidate < current else current


def _later(current: Any, candidate: Any) -> Any:
    if candidate is None:
        return current
    return candidate if current is None or candidate > current else current


def _iso(value: Any) -> str | None:
    return value.isoformat() if value is not None else None


def task_to_index_row(task: Task) -> dict[str, Any]:
    return {
        "task_id": str(task.id),
        "taxonomy_alias": task.taxonomy_alias or "",
        "name": task.title,
        "status": task.status,
        "type": task.task_type.abbreviation if task.task_type else None,
        "due_date": task.due_date.isoformat() if task.due_date else None,
        "created_at": task.created_at.isoformat() if task.created_at else None,
    }




TASK_CURSOR_AXIS = "task_created_recency"


def task_filter_fingerprint(
    *,
    product_id: str,
    status: str | None,
    priority: str | None,
    task_type_id: str | None,
    due_before: Any,
    hidden: Any,
    query: str | None,
) -> str:
    return filter_fingerprint(
        {
            "product_id": product_id,
            "status": status,
            "priority": priority,
            "task_type_id": task_type_id,
            "due_before": due_before,
            "hidden": hidden,
            "query": query,
        }
    )


def resolve_task_cursor(cursor: Any, *, fingerprint: str) -> tuple[Any, str] | None:
    if cursor is None or cursor == "":
        return None
    if not isinstance(cursor, str):
        raise CursorRejectedError(
            "CURSOR_MALFORMED",
            "cursor must be the string token returned in a previous response's "
            "truncation.next_cursor. Call again without cursor to restart the walk.",
        )
    return decode_cursor(cursor, axis=TASK_CURSOR_AXIS, fingerprint=fingerprint)


def task_keyset_after(sort_value: Any, row_id: str) -> Any:
    return or_(
        Task.created_at < sort_value,
        and_(Task.created_at == sort_value, Task.id > row_id),
    )


def mint_task_next_cursor(*, returned_rows: list[dict[str, Any]], fetched_rows: list, fingerprint: str) -> str | None:
    if not returned_rows:
        return None
    row_id = returned_rows[-1].get("task_id") or returned_rows[-1].get("id")
    if row_id is None:
        return None
    for row in fetched_rows:
        if row.id == row_id:
            return encode_cursor(
                axis=TASK_CURSOR_AXIS,
                sort_value=row.created_at,
                row_id=row_id,
                fingerprint=fingerprint,
            )
    return None


def open_task_cursor_walk(
    cursor: Any,
    *,
    product_id: str,
    status: str | None,
    priority: str | None,
    task_type_id: str | None,
    due_before: Any,
    hidden: Any,
    query: str | None,
) -> tuple[str, tuple[Any, str] | None]:
    fingerprint = task_filter_fingerprint(
        product_id=product_id,
        status=status,
        priority=priority,
        task_type_id=task_type_id,
        due_before=due_before,
        hidden=hidden,
        query=query,
    )
    return fingerprint, resolve_task_cursor(cursor, fingerprint=fingerprint)


