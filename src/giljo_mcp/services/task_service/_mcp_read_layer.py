# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""Bounds and projections for the agent-facing task list (BE-9468).

Extracted from ``_mcp_adapter_mixin.py`` rather than added to it: that module sits at
654 lines against the 800-line cap, and these additions would have pushed it past.
Mirrors the split already next door in ``project_service`` (``_mcp_adapter_mixin`` +
``_mcp_adapter_query_mixin``). Nothing was moved OUT of the mixin -- only the new
concerns land here.

**The problem this file exists to solve is not "the list is big".** It is that nothing
told a caller how big an answer would be before it asked for one. An agent asked "what
did we ship" cannot know whether that is 5 rows or 5,000, so it asks for everything and
hopes. A size ceiling truncates the guess; it does not improve it. That is why the
counts block is the keystone and the ceiling below is only a backstop.

Everything here is edition-neutral: no ``saas/`` import, no SaaS-only table.
Edition Scope: Both.
"""

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


# BE-9468 (E96 sprint, second lane): ``wire_length``, ``fit_rows_to_char_ceiling`` and
# the transport allowance MOVED to ``services/_mcp_wire_bounds`` when ``list_projects``
# needed the identical rule. They are facts about the MCP wire, not about tasks, and a
# direct cross-service import would have made this package a runtime dependency of
# ``project_service`` for a helper that has nothing to do with tasks.
#
# The names below are kept as aliases so every shipped call site and test in this
# package keeps working verbatim -- the extraction moved code, it did not change any
# behaviour or any contract.
LIST_TASKS_CHAR_CEILING = MCP_LIST_CHAR_CEILING


# --------------------------------------------------------------------------
# Bounds
# --------------------------------------------------------------------------
#
# The contract copied from ``search_memory`` (``_context_tools.py:230-237``): a sane
# default AND a hard max, as module constants, surfaced in the parameter description so
# the caller reads the bound off the tool schema instead of discovering it from a
# truncated answer.
#
# **Measured on the REAL wire serializer, not the house convention.** The MCP result
# serializer is ``pydantic_core.to_json(data, fallback=str).decode()`` (compact JSON,
# ``fastmcp/tools/base.py``), and the in-repo ``chars // 4`` estimate is calibrated for
# prose. It is WRONG for identifier-dense list rows and wrong in the reassuring
# direction: a UUID is 38 chars but 23 tokens, an ISO timestamp 32 chars but 19. On 60
# real rows through the real @mcp.tool transport, tokenised with ``tiktoken``
# ``o200k_base``:
#
#     projection   B/row    tok/row   chars/token   `chars//4` understates by
#     index        284.7      93.7        3.04              24.0%
#     summary      456.9     156.7        2.92              27.1%
#     full         934.9     292.7        3.19              20.1%
#
# **Do not size anything here with ``chars // 4``.**
#
# 50 summary rows is ~22,846 chars ~= 7,833 tokens ~= 3.9% of a 200k context window --
# a read a caller can afford to make several times and still have room to work. It also
# matches what the rest of the codebase already treats as a page: the ``tasks`` context
# category caps at 50 and ``search_threads`` at 50.
LIST_TASKS_LIMIT_DEFAULT = 50

# The escape hatch, and it is a deliberate requirement rather than an oversight: asking
# for everything must stay POSSIBLE. It simply stops being the accidental default. A
# bound that cannot be raised is not a default, it is a refusal.
#
# **This maximum is not the real protection and should not be mistaken for it.** 500
# summary rows is ~78k tokens, well past a comfortable share of a 200k window; the
# CHARACTER ceiling below is what actually bounds the response. This value exists so a
# nonsense request (``limit=1000000``) is refused cheaply at the boundary, exactly as
# ``search_memory`` refuses one, instead of being absorbed silently.
#
# 500 rather than a larger figure for ONE reason, and it is not safety: the sibling
# project list ships the same parameter with the same maximum. **Two sibling tools with
# two different maxima is a rule the caller has to learn twice**, and the character
# ceiling sits behind both either way, so a larger value here would buy nothing.
LIST_TASKS_LIMIT_MAX = 500


# The backstop underneath the row limit, and at ``mode='full'`` the ONLY bound that
# means anything -- because ``description`` comes back untruncated unless ``memory_limit``
# is passed, so one row is arbitrarily large and no row count can bound the response.
# Measured: 40 full rows carrying 4,000-char descriptions is 185,535 characters, a
# request no sane row cap would ever stop.
#
def truncation_note(
    *,
    reason: str,
    ceiling: int,
    rows_fetched: int,
    dropped: str,
    advice: str,
    next_cursor: str | None = None,
) -> dict[str, Any]:
    """The truncation detail block carried on a cut response.

    **This is the SHIPPED vocabulary, extended, not a second one.** BE-9455 Symptom A
    established ``{reason, ceiling, rows_fetched, dropped, advice}`` on the project list
    (``project_service/_mcp_adapter_query_mixin.py``) and ``reason`` was already a
    discriminator carrying one value. New cuts add new ``reason`` values; they do not
    add a new shape. A caller that learned to read a truncated project list can read a
    truncated task list without learning anything.

    The signal travels on the RESPONSE rather than in a log line because the caller is
    an agent in someone else's process that will never see our server log -- which was
    the silent half of the original defect.
    """
    note = {
        "reason": reason,
        "ceiling": ceiling,
        "rows_fetched": rows_fetched,
        "dropped": dropped,
        "advice": advice,
    }
    # BE-9469: the continuation token lives INSIDE this block and only on a truncated
    # response -- the shipped vocabulary extended, never a second one beside it. Same
    # placement as the project list, so an agent that learned one learns nothing new.
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

# BE-9469: prepended when a continuation token exists. FIRST, because it is the only
# remedy that completes the answer without changing the question -- every other one asks
# the caller to want less. The narrowing advice is kept after it, since narrowing is still
# cheaper than a long walk when the caller only wanted a slice.
CURSOR_ADVICE_PREFIX = (
    "There is more: pass truncation.next_cursor back as the cursor parameter (with the "
    "SAME filters) to continue from where this page stopped, and keep going until a "
    "response comes back with truncated=false. "
)


def advice_for(base_advice: str, *, next_cursor: str | None, mode: str | None) -> str:
    """Request-aware advice: no remedy the caller has already applied.

    ``mode='index'`` is the leanest row this tool has, so recommending it to a caller
    ALREADY in index mode is advice that cannot be acted on -- the parked "advice
    recommends the mode you are already in" complaint. An agent that follows it changes
    nothing and truncates again, so the clause is REMOVED rather than reworded.
    """
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


# ⚠ Paired with the ``created_at DESC, id ASC`` ordering in ``_mcp_adapter_mixin``'s
# query, and only true because of it: both bounds drop from the TAIL, so the tail is the
# oldest. Change that ordering, or add a sort parameter, and this sentence becomes a
# false claim about which rows are missing -- with every test still green. See the
# matching note at the ordering site; the two must move together.
DROPPED_TASKS = "the OLDEST-CREATED tasks"


def _worst_case_note(effective_limit: int, next_cursor: str | None = None, mode: str | None = None) -> dict[str, Any]:
    """The LARGER of the two truncation blocks, for charging against the size budget.

    Which block a cut will carry is not known until the cut has happened, and the block
    is itself part of what has to fit. Charging the bigger one up front keeps the ceiling
    a real postcondition in both branches, at the cost of a few dozen characters of
    headroom.
    """
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
    # Measured on the wire serializer, not on ``str()`` -- the budget it is charged
    # against is measured that way too, and two different rulers is how an off-by-a-few
    # ceiling breach gets in.
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
    """Apply the size ceiling and stamp the truncation signal. Mutates and returns ``response``.

    ``limit_cut`` is whether the row limit already withheld rows; the caller learns it by
    fetching one row past the limit, which is cheaper than a second COUNT.

    ``truncated`` is set on EVERY response, ``True`` or ``False`` — never absent. An
    agent has to be able to read the field, and a missing key is indistinguishable from
    an older server. The ``truncation`` detail block appears only when there is something
    to detail.

    When both bounds bit, ``response_size`` wins the ``reason``, because it is the more
    actionable of the two: a caller told ``limit`` would raise the limit and get the same
    answer back, whereas a size cut has to say "a bigger limit will not help you".
    """
    envelope = dict(
        response,
        tasks=[],
        truncated=True,
        # The token is charged against the budget WITH the note, never added after the
        # last size check -- that is the documented way a ceiling stops holding.
        truncation=_worst_case_note(effective_limit, next_cursor=cursor_charge, mode=mode),
    )
    kept, size_dropped = fit_rows_to_char_ceiling(rows, envelope=envelope)

    # THE TOKEN IS MINTED HERE, after the cut, never before it. It must name the last row
    # actually DELIVERED: minted earlier it would point past rows the size backstop
    # dropped, which is a silent skip -- this feature reintroducing the defect it exists
    # to remove. The budget above was charged an upper-bound placeholder instead.
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
    """The caller's filters, in ONE place, applied to every statement that needs them.

    BE-9468: this exists because ``counts.matched`` is a separate ``COUNT(*)`` that must
    carry exactly the predicates the row query carried. Two places building the same
    WHERE clause is how they drift, and a drifted ``matched`` is a confidently wrong
    number -- the failure mode this whole change exists to remove. One builder makes them
    agree by construction rather than by review.

    **Every filter here is SQL-side, and that is load-bearing rather than incidental.**
    It is what makes ``matched`` exact in both directions: nothing is filtered later in
    Python, so the count cannot overstate, and nothing caps the fetch, so it cannot
    understate. The sibling project list cannot say the same -- several of its filters
    run after the fetch -- which is why ``matched`` is conditional there and not here.
    """
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
        # Case-insensitive substring across the three fields a person actually remembers
        # a task by -- what it is called, what it says, and its TSK-nnnn alias. Same
        # shape as search_memory's ``query`` and as the project repository's existing
        # ilike search, so a caller learns one rule.
        #
        # ``%`` and ``_`` are ESCAPED. Unescaped, a query of "100%" is a wildcard that
        # matches every row and returns the whole board while looking like a search
        # result -- narrow-seeming and maximally wide, which is the exact failure this
        # tool is being bounded to prevent. ``_`` is the worse of the two: a
        # single-character wildcard reads like an ordinary word character.
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
    """The board-wide counts block plus the filter-scoped ``matched``/``remaining`` (BE-9468).

    THREE queries, answering deliberately different questions. The GROUP BY is scoped to
    tenant + active product and carries NONE of the caller's filters -- it describes the
    whole board, including the part the caller filtered away, which is the part it could
    not otherwise see. ``matched`` carries every filter EXCLUDING the cursor, so it stays
    CONSTANT across a walk -- "your search hit N of M" must mean the same thing on every
    page (BE-9469 QA follow-up, U47-F2: a caller reading a drifting ``matched`` cannot
    tell whether it means the whole match set or the part not yet delivered). ``remaining``
    adds the cursor's keyset predicate back, so it decreases by ``returned`` each page --
    on a cursorless call, ``remaining == matched`` by construction (same query).

    Measured at 1,200 rows on real Postgres: the GROUP BY 4.62 ms, the COUNT 0.49 ms,
    against a 2.10 ms list query. The GROUP BY is a LINEAR scan -- there is no index on
    ``(tenant_key, product_id, status)`` -- so it grows with the board: ~38 ms
    extrapolated at 10,000 rows. Cheap now, not free forever.

    ``returned`` is left at 0 here on purpose. Its true value is not known until the
    size backstop has run, so the caller ASSIGNS it from the response's own count.
    """
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

    # No cursor -> the same query, so remaining == matched by construction rather than
    # by a second round trip.
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
    """Fold one GROUP BY's rows into the counts block. THE KEYSTONE of this change.

    ``grouped`` carries ``(status, type_abbreviation, count, created_min, created_max,
    completed_min, completed_max)`` per group -- a single round trip, folded here rather
    than issued as three queries.

    **Why this block exists, and why it ships on EVERY response rather than behind a
    flag.** Nothing told a caller how big an answer would be before it asked for one, so
    an agent asked "what did we ship" had to ask for everything and hope. A size ceiling
    truncates that guess; it does not improve it. **A signal you have to know to ask for
    cannot fix a problem whose whole shape is not knowing what to ask.**

    **The counts describe the WHOLE BOARD -- tenant + active product -- and deliberately
    ignore the caller's own filters.** Counting only what was already returned tells the
    caller the size of the array it is holding, which it can measure itself. The number
    that changes a decision is the one it CANNOT see: a caller that filtered to
    ``status='pending'`` and is told "total: 2" learns nothing about the archive it just
    filtered away, and that archive is exactly what it needed to know about.

    Four separately-named numbers, none of whose meaning shifts with the call: ``total``
    (the whole board), ``matched`` (rows matching the caller's filters, EXCLUDING any
    cursor -- constant across a walk), ``remaining`` (``matched`` narrowed by the cursor,
    when one is in play -- decreases by ``returned`` each page), and ``returned`` (rows in
    this response). BE-9469 QA follow-up U47-F2: ``matched`` used to drift with the cursor
    and reported two different quantities under one name; ``remaining`` is the additive fix.

    ``by_status`` carries **explicit zeros** for every status in the vocabulary;
    ``by_type`` **omits** absent types. That asymmetry is deliberate, not a compromise.
    Status is a CLOSED enum the caller can enumerate independently, so a missing key is
    ambiguous -- it cannot tell "zero pending" from "this server does not report that
    status", which is the absent-versus-false defect BE-9455 Symptom A fixed by making
    ``truncated`` always present. Taxonomy type is an OPEN, tenant-configured vocabulary
    the caller cannot enumerate, so an absent key claims nothing and emitting every
    configured type at zero would be noise.
    """
    by_status: dict[str, int] = {status.value: 0 for status in TaskStatus}
    by_type: dict[str, int] = {}
    total = 0
    created_first = created_last = completed_first = completed_last = None

    for status, type_abbr, count, cre_min, cre_max, cmp_min, cmp_max in grouped:
        total += count
        if status is not None:
            # A status outside the vocabulary is still counted in ``total`` and still
            # reported -- legacy rows predate the enum and hiding them would make the
            # parts disagree with the whole.
            by_status[status] = by_status.get(status, 0) + count
        if type_abbr is not None:
            by_type[type_abbr] = by_type.get(type_abbr, 0) + count
        created_first = _earlier(created_first, cre_min)
        created_last = _later(created_last, cre_max)
        completed_first = _earlier(completed_first, cmp_min)
        completed_last = _later(completed_last, cmp_max)

    counts: dict[str, Any] = {
        # Names the population ``total`` describes. This list is scoped to the ACTIVE
        # PRODUCT, not to the whole tenant, and without saying so "1,084" is ambiguous.
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
        # Present only when it can be computed TRUTHFULLY. On this tool that is always:
        # there is no defensive ceiling to bound the fetch, and every filter is applied
        # in SQL, so a COUNT carrying the same predicates can neither understate nor
        # overstate. The sibling project list cannot say the same -- several of its
        # filters run after the fetch -- so there the key is omitted rather than guessed.
        # A missing number beats a confident wrong one.
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
    """The lean index row: exactly what list-and-sort work needs, and nothing else.

    No description, no mission, no memory, no enrichment -- and critically **no embedded
    ``task_type`` block**. That block is 113 chars / 49 tokens, which is 24.9% of a
    summary row's characters and 31.2% of its tokens, and it is byte-identical on every
    row: it carries a second UUID per row purely to repeat a constant, because every
    task is tagged ``TSK`` by contract (BE-6049c) and the tool's own documentation says
    so. Here the type is the plain abbreviation.

    Measured against the summary row on the same 60 rows through the real transport:
    **37.7% fewer characters, 40.2% fewer tokens.** That claim is asserted on measured
    bytes in the regression suite rather than stated in a docstring -- the sibling tool
    documents a ``triage`` mode as its cheapest projection and it is not cheaper, which
    is the exact mistake a byte assertion catches and a field count does not.

    ``name`` rather than ``title``: the index row is deliberately the SAME shape across
    the task and project lists, and projects call that field ``name``. One index row
    shape means an agent learns it once.
    """
    return {
        "task_id": str(task.id),
        "taxonomy_alias": task.taxonomy_alias or "",
        "name": task.title,
        "status": task.status,
        "type": task.task_type.abbreviation if task.task_type else None,
        "due_date": task.due_date.isoformat() if task.due_date else None,
        "created_at": task.created_at.isoformat() if task.created_at else None,
    }


# --------------------------------------------------------------------------
# The continuation cursor for this list (BE-9469 item 2)
# --------------------------------------------------------------------------
#
# ``list_tasks`` has ONE ordering -- ``created_at DESC, id ASC``, set in
# ``_mcp_adapter_mixin``'s query -- and ``created_at`` is written on every row, so there is
# no NULLS region here and no axis to choose. The keyset is the plain two-column form. Same
# codec as the project list (``_mcp_wire_bounds``), because a token an agent gets from one
# list tool and hands to another should fail with a clear axis mismatch rather than with a
# decode error from a second, subtly different implementation.


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
    """Fingerprint the effective filter set of one ``list_tasks`` request.

    Fingerprinted from the RESOLVED values, notably ``task_type_id`` rather than the
    caller's ``task_type`` abbreviation: the abbreviation is looked up through the taxonomy
    service, so two spellings that resolve to the same type are the same filter set and must
    not refuse each other's cursors.

    ``limit`` and ``mode`` are absent for the reason given in
    ``_mcp_wire_bounds.filter_fingerprint`` -- they change page size and row shape, not
    which rows exist.
    """
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
    """Validate an incoming ``cursor`` and return its keyset position, or ``None`` if absent.

    Absent cursor -> ``None`` -> no keyset predicate is emitted at all, which is what makes
    a call without a cursor byte-identical to the shipped behaviour.
    """
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
    """Rows strictly after ``(sort_value, row_id)`` under ``created_at DESC, id ASC``.

    Explicit OR rather than a row-value ``(created_at, id) < (...)`` for the same reason as
    everywhere else in this change: the two columns sort in OPPOSITE directions, so a
    row-value comparison would silently mean ``id`` DESC and skip at the far end of every
    tie group. And the tie groups are real, not hypothetical -- ``created_at`` defaults to
    ``func.now()``, which PostgreSQL evaluates once per TRANSACTION, so every task written
    together carries a byte-identical timestamp. That is the same fact the ordering's own
    tiebreak comment records.
    """
    return or_(
        Task.created_at < sort_value,
        and_(Task.created_at == sort_value, Task.id > row_id),
    )


def mint_task_next_cursor(*, returned_rows: list[dict[str, Any]], fetched_rows: list, fingerprint: str) -> str | None:
    """The token for the page just built, or ``None`` when there is nothing to continue from.

    Simpler than the project list's equivalent, because this pipeline has no post-fetch
    Python filter: every fetched row either goes into the response or was withheld by a
    bound. So the only safe position is the LAST ROW IN THE RESPONSE -- rows cut by the row
    limit or by the size backstop were withheld rather than examined, and advancing past
    them would skip them silently.

    The position value is read off the ORM row, not off the serialized dict -- and the
    reason first written here was WRONG: ``mode='index'`` DOES project ``created_at``. The
    real reason is that every projection serializes it, so a token built from the row would
    depend on a formatting choice the projection owns and on the field continuing to be
    projected -- neither of which is a contract. Reading the column off the model makes the
    position mode-independent, which is what lets ``mode`` stay out of the filter
    fingerprint and a mid-walk mode change stay legal.
    """
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
    """Resolve the filter fingerprint and the incoming position together.

    Returns ``(fingerprint, after_key)``. Paired in one call because the fingerprint used to
    VALIDATE an incoming token and the one used to MINT the next must be the same value; two
    call sites computing it separately is how a walk starts refusing its own cursors.

    Called BEFORE the fetch, so a refused token costs no query.
    """
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


# BE-9470: resolve_list_mode, resolve_task_limit, validate_task_status_filter,
# validate_task_type_filter, resolve_task_type_id and normalize_task_priority_filter
# MOVED to _mcp_filter_validators.py to keep this module under the 800-line cap --
# see that module's header for why. Not re-exported here; the one call site
# (_mcp_adapter_mixin.py) imports them from their new home directly.
