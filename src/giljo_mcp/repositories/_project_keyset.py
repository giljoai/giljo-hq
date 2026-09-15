# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import and_, desc, or_

from giljo_mcp.models.projects import Project


COMPLETION_RECENCY_AXIS = "completion_recency"
CREATED_RECENCY_AXIS = "created_recency"

VALID_AXES = frozenset({COMPLETION_RECENCY_AXIS, CREATED_RECENCY_AXIS})


def _after_desc_value_then_id_asc(column: Any, sort_value: datetime, row_id: str) -> Any:
    return or_(
        column < sort_value,
        and_(column == sort_value, Project.id > row_id),
    )


def _after_in_completion_null_region(row_id: str) -> Any:
    return or_(
        and_(Project.completed_at.is_(None), Project.id > row_id),
        Project.completed_at.is_not(None),
    )


def keyset_axis_for_sort_key(sort_key: str | None) -> str:
    if sort_key is None:
        return CREATED_RECENCY_AXIS
    if sort_key == COMPLETION_RECENCY_AXIS:
        return COMPLETION_RECENCY_AXIS
    raise ValueError(f"keyset pagination is not supported for sort_key {sort_key!r}.")


def project_keyset_after(axis: str, sort_value: datetime | None, row_id: str) -> Any:
    if axis == COMPLETION_RECENCY_AXIS:
        if sort_value is None:
            return _after_in_completion_null_region(row_id)
        return and_(
            Project.completed_at.is_not(None),
            _after_desc_value_then_id_asc(Project.completed_at, sort_value, row_id),
        )
    if axis == CREATED_RECENCY_AXIS:
        if sort_value is None:
            raise ValueError(f"axis {CREATED_RECENCY_AXIS!r} has no NULL region; a NULL sort value is not a position.")
        return _after_desc_value_then_id_asc(Project.created_at, sort_value, row_id)
    raise ValueError(f"unknown project sort axis {axis!r}; expected one of {sorted(VALID_AXES)}.")


def project_sort_value(project: Project, axis: str) -> datetime | None:
    if axis == COMPLETION_RECENCY_AXIS:
        return project.completed_at
    if axis == CREATED_RECENCY_AXIS:
        return project.created_at
    raise ValueError(f"unknown project sort axis {axis!r}; expected one of {sorted(VALID_AXES)}.")


def completion_recency_order_clauses() -> list[Any]:
    return [desc(Project.completed_at).nulls_first(), Project.id.asc()]
