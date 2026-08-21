# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""Keyset comparisons for the agent-facing project list's two sort axes (BE-9469).

``list_projects`` orders on one of TWO axes, chosen from the caller's question by
``_is_completion_oriented``:

* **completion recency** -- ``completed_at DESC NULLS FIRST, id ASC``, the BE-9455
  Symptom A ordering. Museum-protected; nothing here changes it.
* **creation recency** -- ``created_at DESC, id ASC``, the fallback every other read uses.

A continuation cursor is "give me the rows that sort strictly AFTER this one", so its
comparison has to match the ORDER BY exactly -- same columns, same directions, same NULL
placement. This module is where that agreement lives, so the two cannot be read apart.

**The completion axis has two REGIONS and the comparison cannot omit either.** Inside the
NULLs every row's ``completed_at`` is NULL, so ``id`` alone decides position; past them,
``(completed_at, id)`` decides. Measured before this was written: a single-column
``completed_at < cursor_value`` **cannot even be constructed** while the cursor stands in
the NULL region -- SQLAlchemy rejects ``column < None`` outright -- and past the NULLs it
compiles and silently drops the whole tie group (2 of 5 rows returned). An implementer who
works around the first failure by skipping the keyset when the value is NULL rebuilds the
tolerate-and-restart defect this project's item 1 removed from the thread list. So the
region is part of the comparison, not a refinement of it.

Pure functions over SQLAlchemy expressions: no session, no tenant, no ``self``. Tenant
scoping stays on the caller's query, where every other predicate in this repository keeps
it. See ``tests/repositories/test_be9469_nulls_first_keyset.py``.

Edition Scope: Both.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import and_, desc, or_

from giljo_mcp.models.projects import Project


# The axis names a cursor token carries. A token records WHICH ordering it was issued
# against, because the same position means different rows on a different axis -- replaying
# a completion-axis cursor against a creation-axis read would page through an unrelated
# sequence and lose rows without any comparison being wrong.
COMPLETION_RECENCY_AXIS = "completion_recency"
CREATED_RECENCY_AXIS = "created_recency"

VALID_AXES = frozenset({COMPLETION_RECENCY_AXIS, CREATED_RECENCY_AXIS})


def _after_desc_value_then_id_asc(column: Any, sort_value: datetime, row_id: str) -> Any:
    """Rows strictly after ``(sort_value, row_id)`` under ``column DESC, id ASC``.

    Written as an explicit OR and NOT as a row-value ``(column, id) < (sort_value,
    row_id)``. The row-value form is the shorter spelling and it is wrong here: it applies
    ONE direction to every element, so it would mean ``id`` DESCENDING while the ORDER BY
    sorts ``id`` ascending -- which skips at the far end of every tie group instead of the
    near end. A tidier-looking fix that loses different rows.
    """
    return or_(
        column < sort_value,
        and_(column == sort_value, Project.id > row_id),
    )


def _after_in_completion_null_region(row_id: str) -> Any:
    """Rows strictly after a cursor standing INSIDE the NULLs of the completion axis.

    Two disjuncts, and each is load-bearing:

    * the remaining NULLs, by ``id`` ASC -- the rest of the first region;
    * **every** non-NULL row -- the entire second region, because ``NULLS FIRST`` puts all
      of it after all of the NULLs. Omitting this disjunct is the failure mode that makes a
      walk stop at the boundary instead of crossing it.

    No ``completed_at`` value is compared, because the cursor has none to compare with.
    That is the whole reason a single-column comparison cannot express this position.
    """
    return or_(
        and_(Project.completed_at.is_(None), Project.id > row_id),
        Project.completed_at.is_not(None),
    )


def keyset_axis_for_sort_key(sort_key: str | None) -> str:
    """The keyset axis implied by a repository ``sort_key``. Derived, never passed in.

    Called with the SAME argument that chose the ORDER BY, so the comparison cannot be
    built against an ordering the query does not use. An axis supplied separately by the
    caller would be a second source of truth for one decision, and the failure that
    permits -- a keyset disagreeing with the ORDER BY -- produces a walk that skips or
    repeats while every test still passes.

    ``None`` is the repository's deterministic limit-fallback ordering, ``created_at DESC,
    id ASC``.

    **An ordering with no keyset support RAISES.** Only the two axes the agent-facing list
    actually uses are supported. The roadmap ordering sorts on a correlated subquery and
    the whitelisted ``_SORT_COLUMNS`` sorts are NULLS-LAST, so each would need its own
    comparison, and neither has a paging caller. Refusing is what keeps that honest: a
    fall-through default would page from the start on every request and look like it
    worked.
    """
    if sort_key is None:
        return CREATED_RECENCY_AXIS
    if sort_key == COMPLETION_RECENCY_AXIS:
        # ProjectRepository.COMPLETION_RECENCY_SORT_KEY carries this same string. The
        # comparison is written against the AXIS constant rather than importing the
        # repository's, which would be a cycle -- and the equality of the two is asserted
        # in tests/repositories/test_be9469_nulls_first_keyset.py rather than left as a
        # coincidence two modules quietly depend on.
        return COMPLETION_RECENCY_AXIS
    raise ValueError(f"keyset pagination is not supported for sort_key {sort_key!r}.")


def project_keyset_after(axis: str, sort_value: datetime | None, row_id: str) -> Any:
    """The WHERE clause for "rows after ``(sort_value, row_id)``" on ``axis``.

    ``sort_value`` is the cursor row's value on that axis' leading column -- ``None`` only
    on the completion axis, where it means the cursor stands in the NULL region.

    An unknown ``axis`` RAISES rather than falling through to a match-all. A predicate
    builder that returned ``True`` for an unrecognised axis would produce a cursor that
    pages from the start on every request while looking like it works -- the
    silent-restart defect one layer up, and a fall-through default is how it would get
    there.
    """
    if axis == COMPLETION_RECENCY_AXIS:
        if sort_value is None:
            # THE REGION BRANCH, and the reason it exists is a measurement rather than a
            # preference. A single-column ``completed_at < sort_value`` cannot be
            # CONSTRUCTED here at all -- SQLAlchemy rejects ``column < None``. So the
            # hazard is not a wrong query; it is the workaround. The cheapest way to
            # silence that error is "if the value is None, skip the keyset", and that
            # rebuilds the tolerate-and-restart defect this project removed from the
            # thread list: a walk that pages from the start forever while reporting
            # success. The region has to be IN the comparison, and this branch is it.
            return _after_in_completion_null_region(row_id)
        # Past the NULLs, so the NULL rows are all BEHIND the cursor and must be excluded.
        # ``completed_at < sort_value`` and ``completed_at == sort_value`` are both
        # NULL-false, so the exclusion is already implied -- but it is stated explicitly
        # because relying on three-valued logic to enforce a region boundary is how the
        # next reader talks themselves out of the region distinction entirely.
        return and_(
            Project.completed_at.is_not(None),
            _after_desc_value_then_id_asc(Project.completed_at, sort_value, row_id),
        )
    if axis == CREATED_RECENCY_AXIS:
        if sort_value is None:
            # ``created_at`` is written on every row, so a NULL here is not a region --
            # it is a corrupt or hand-edited token, and paging on it would be guessing.
            raise ValueError(f"axis {CREATED_RECENCY_AXIS!r} has no NULL region; a NULL sort value is not a position.")
        return _after_desc_value_then_id_asc(Project.created_at, sort_value, row_id)
    raise ValueError(f"unknown project sort axis {axis!r}; expected one of {sorted(VALID_AXES)}.")


def project_sort_value(project: Project, axis: str) -> datetime | None:
    """The cursor value to record for ``project`` on ``axis``.

    Here rather than at the call site so the value written into a token and the value
    compared against always come from ONE place. A cursor whose recorded column and whose
    compared column can disagree is a cursor that pages through the wrong sequence, and
    nothing in the response would say so.
    """
    if axis == COMPLETION_RECENCY_AXIS:
        return project.completed_at
    if axis == CREATED_RECENCY_AXIS:
        return project.created_at
    raise ValueError(f"unknown project sort axis {axis!r}; expected one of {sorted(VALID_AXES)}.")


def completion_recency_order_clauses() -> list[Any]:
    """ORDER BY completion recency, unfinished work first (BE-9455 Symptom A).

    ``completed_at DESC NULLS FIRST`` -- read as "work not yet finished, then the
    most recently finished". Exists because a LIMIT is a choice about which rows to
    keep, and a completion-oriented caller's rows are the recent completions: under
    the ``created_at DESC`` fallback a project created long ago and completed
    yesterday sorts last and a cap deletes it outright, which is how 145 completed
    projects went missing from the agent-facing list.

    NULLS FIRST rather than LAST is the load-bearing half. A mixed query
    (``include_completed=True`` asks for active work AND archived work) would
    otherwise spend its whole budget on completed rows and silently drop the ACTIVE
    projects -- trading the reported bug for its mirror image. Putting the NULLs
    first makes unfinished work un-droppable and lets the cap fall on the oldest
    completions, which is the only bucket where "older" means "less wanted".

    ``sort_dir`` is deliberately not consulted: this key names one ordering, and an
    ascending variant would mean "oldest completions first", which no caller wants
    and a cap would render actively harmful.
    """
    return [desc(Project.completed_at).nulls_first(), Project.id.asc()]
