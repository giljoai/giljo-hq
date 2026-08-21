# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""Caller-facing bounds for the agent-facing project list (BE-9468).

Extracted from ``_mcp_adapter_query_mixin`` so that module stays under the 800-line
guardrail. Holds everything about how the agent-facing project list is BOUNDED and how
a bound is REPORTED: the ``limit`` constants, validation of the agent-supplied ``query``
and ``limit``, the row cut, the truncation detail block, and the response assembly that
picks which bound to name. All pure functions over plain values -- no database, no
session, no ``self``.

The distinction these two bounds draw is the useful one: the **ceiling**
(``_MCP_LIST_PROJECT_CEILING``, which stays in the mixin) protects the SERVER from a
pathological all-tenant fan-out; the **limit** here protects the CALLER's context
window, and is the one that binds in practice.

**Why the ceiling constant did NOT move, and why ``ceiling`` is a required argument.**
BE-9455 Symptom A's regression suite reaches the ceiling by monkeypatching the mixin
module's attribute. Had ``_truncation_note`` moved here while still reading a module
global, it would have read an UNPATCHED value while the fetch read the patched one --
and the suite would have stayed green while asserting a ceiling the code never used.
Taking the ceiling as an explicit parameter removes the hidden global read entirely, so
the caller passes whatever value it actually cut with. That is strictly safer than the
original and leaves the existing test seam working untouched.

Edition Scope: Both.
"""

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


# The caller-facing row bound, modelled on ``search_memory``'s shipped contract
# (``SEARCH_MEMORY_LIMIT_DEFAULT`` / ``SEARCH_MEMORY_LIMIT_MAX``) rather than invented:
# a sane default AND a hard max, both surfaced in the tool's parameter description so
# an agent can read the bound before it calls. Public, unlike the ceiling, precisely
# because they cross the module boundary to be advertised at the MCP surface.
#
# **Why a default at all, when none existed before:** nothing tells a model how big an
# answer will be before it asks for it, so an agent asked "what did we ship" asks for
# everything and hopes. An unbounded default lets that guess be wrong by three orders
# of magnitude. Asking for everything stays possible -- it becomes a deliberate, stated
# request instead of the accidental default.
#
# Chosen against measured row cost and the real shape of a board, not as a round
# number: a depth-0 row measures ~92 tokens on controlled data and ~150 on real rows
# (longer names), so 50 rows is roughly 7,500 tokens -- under 4% of a 200k window for a
# bound that fires on every call. 50 also covers the realistic whole-board cases: an
# active project list is single digits, and a week of completions is ~25 rows.
LIST_PROJECTS_LIMIT_DEFAULT = 50
LIST_PROJECTS_LIMIT_MAX = 500

# Length cap on the agent-supplied search term, mirroring the ``taxonomy_alias_prefix``
# cap already applied on this surface.
_QUERY_MAX_LENGTH = 200

# The shipped cap on the alias-prefix filter. A constant rather than a literal because it
# is now asserted in two places -- the check and its own error message.
_TAXONOMY_ALIAS_PREFIX_MAX_LENGTH = 64

# One advice string per truncation reason. Keyed rather than branched because the whole
# point of the ``reason`` discriminator is that each bound has a DIFFERENT remedy -- a
# shared string would make the discriminator decorative.
# The base advice for each truncation reason: what is true about the cut regardless of
# what the caller asked for. The REQUEST-AWARE parts are added by ``_advice`` below.
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

# The leaner-row remedy, offered ONLY to a caller not already using it.
_LEANER_ROW_REMEDY = " Ask for a leaner row with mode='triage', or drop back from a richer mode."
_NARROW_REMEDY = (
    " Narrow with status, project_type, taxonomy_alias_prefix, query, or a created_after / completed_after window."
)

# The continuation remedy. First, because it is the only one that completes the answer
# without changing the question -- every other remedy asks the caller to want less.
_CURSOR_REMEDY = (
    "There is more: pass truncation.next_cursor back as the cursor parameter (with the "
    "SAME filters) to continue from where this page stopped, and keep going until a "
    "response comes back with truncated=false. "
)


def _advice(reason: str, *, next_cursor: str | None, mode: str | None) -> str:
    """The advice string for a cut -- request-aware, so no remedy is one the caller already used.

    Two things this fixes, both of which were real complaints about the shipped strings:

    * **A cut with a continuation token leads with the token.** "There is more, narrow your
      query" tells a caller to want less; "there is more, here is the rest" answers the
      question it actually asked. The narrowing advice is kept after it, because narrowing
      is still cheaper than a long walk when the caller only wanted a slice.
    * **``mode='triage'`` is no longer recommended to a caller ALREADY in triage.** That was
      the parked "advice recommends the mode you are already in" defect: advice that cannot
      be acted on reads as a server that has not understood the request, and an agent that
      follows it changes nothing and truncates again. The remedy is omitted when it is not
      available, rather than reworded.
    """
    advice = _ADVICE_BY_REASON.get(reason, _ADVICE_BY_REASON["defensive_ceiling"])
    if reason == "response_size":
        # Only offer the leaner row to someone who is not already asking for the leanest.
        if mode != "triage":
            advice += _LEANER_ROW_REMEDY
        advice += _NARROW_REMEDY
    if next_cursor:
        advice = _CURSOR_REMEDY + advice
    return advice


def resolve_search_query(query: Any) -> str | None:
    """Validate and normalize the agent-supplied ``query``. Returns None when absent.

    House rule: every field flowing from an MCP tool parameter into a database
    predicate is type-checked and length-capped HERE, at the boundary, not left for a
    DB constraint to reject with a 500. Tool parameters arrive from an AI agent, so
    "the constraint will catch it" produces the wrong status code and a useless
    message.

    An all-whitespace query normalizes to None rather than to ``""``: an empty search
    term would build a ``%%`` LIKE pattern that matches every row, so a caller that
    passed whitespace by accident would silently get the whole board back -- the exact
    unbounded read this project exists to prevent.
    """
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
    """Resolve the effective row limit: default when absent, clamped into [1, MAX].

    ``search_memory``'s contract exactly -- clamp rather than reject, so a caller
    asking for more than the max receives the max plus a truncation note instead of an
    error. Refusing would break the "ask for everything" call the operator explicitly
    wants to keep working; clamping keeps it working and tells the caller it was
    bounded.

    ``bool`` is rejected rather than accepted: it is an ``int`` subclass in Python, so
    ``limit=True`` would otherwise resolve to a silent limit of 1.
    """
    if limit is None:
        return LIST_PROJECTS_LIMIT_DEFAULT
    if isinstance(limit, bool) or not isinstance(limit, int):
        raise ValidationError(
            "limit must be an integer.",
            context={"operation": "list_projects"},
        )
    return max(1, min(limit, LIST_PROJECTS_LIMIT_MAX))


def apply_row_limit(rows: list, limit: int) -> tuple[list, int, bool]:
    """Cut ``rows`` to ``limit``. Returns ``(kept, matched, truncated)``.

    Called AFTER the post-fetch Python filters and on the ordering the ceiling already
    established -- deliberately, and not pushed down into SQL.

    **Why not a SQL LIMIT.** The cross-cutting predicates on this read (hidden,
    project_type, taxonomy_alias_prefix, the date ranges) run in Python after the
    fetch, so a SQL ``LIMIT`` would slice BEFORE them: a caller asking for 50 could
    receive 3 while 50 matching rows existed, with nothing in the response to say why.
    That is a silent shortfall, which is the defect class this project exists to close.
    Cutting where the true matched set is known makes ``matched`` exact, and therefore
    ``truncated`` exact rather than the conservative ``>=`` the defensive ceiling is
    forced into.

    **What it costs.** The SQL fetch is not reduced. That is the accepted trade: the
    cut still lands before the projection, so it skips the expensive part -- the
    depth>=1 enrichment queries and the entire serialized payload. The defect being
    fixed is the caller's context cost, not database cost.

    **What it must never do: re-sort.** ``rows`` arrives in the order BE-9455 Symptom A
    established (``completed_at DESC NULLS FIRST`` on a completion-oriented read,
    creation recency otherwise), which makes unfinished work un-droppable and lets a
    cut fall only on the oldest completions -- the one bucket where "older" honestly
    means "less wanted". Taking a head slice preserves that; sorting here would
    re-open the wound BE-9455 closed, at a smaller number.
    """
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
    """Fold the board-wide GROUP BY into the ``counts`` response block (BE-9468).

    THE KEYSTONE of this change. Nothing told a caller how big an answer would be
    before it asked for one, so an agent asked "what did we ship" could only ask for
    everything and hope. An agent that knows *"1,069 completed, 12 inactive, 3 active"*
    first can ask a narrow question; without it every other bound is just truncating a
    guess rather than improving it.

    ``grouped_rows`` are the raw tuples from ``ProjectRepository.board_counts``:
    ``(status, type_abbreviation, min_created, max_created, min_completed,
    max_completed, count)``.

    Four numbers, four different meanings, never one number whose meaning depends on
    the call:

    * ``total`` -- the whole board, ignoring every caller filter.
    * ``matched`` -- filter-set hits EXCLUDING the cursor -- constant across a walk. Was
      the one number that drifted mid-walk (BE-9469 QA, U47-F2); the keyset predicate
      never enters its computation now, so page 1 and page 5 report the same value.
    * ``remaining`` -- ``matched`` narrowed by the cursor: still at-or-ahead of the
      current position, decreasing by ``returned`` each page; equals ``matched`` with no
      cursor. What used to drift under the name ``matched`` now has its own name.
    * ``returned`` -- rows actually in this response, **assigned by the caller from the
      top-level ``count``, never recomputed** -- two independent ``len()`` calls at
      different pipeline points is how a redundant field drifts from its twin.

    **``matched`` and ``remaining`` are each OMITTED when they cannot be computed
    truthfully** (``int | None``, the R2 presence rule, unchanged). Each is derived after
    a fetch the defensive ceiling may have bounded -- reporting the ceiling would lie, and
    a SQL ``COUNT(*)`` does not rescue it either: several filters run in Python after the
    fetch, so a SQL-only count would OVERSTATE. The respective fetch already says
    ``truncated: true`` / ``reason: "defensive_ceiling"`` then, key simply absent.
    **A missing number beats a confident wrong one.**

    ``by_status`` carries **explicit zeros**; ``by_type`` **omits** them -- the two maps
    differ in kind. Status is a CLOSED enum the caller can enumerate independently, so a
    missing key is ambiguous between "none of these" and "not reported" (the
    absent-vs-false defect BE-9455 Symptom A fixed for ``truncated``). Type is an OPEN,
    tenant-configured vocabulary the caller cannot enumerate, so a missing key claims
    nothing and every configured type at zero would be noise.
    """
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
        # Names the population ``total`` describes. Without it 1,084 is ambiguous:
        # this list is active-PRODUCT-scoped, not tenant-wide.
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
    # Null rather than omitted, for the same reason by_status carries explicit zeros:
    # on a board with no completions the caller must be able to read the key and see
    # "none", not have to guess whether the server reports it at all.
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
    """The truncation detail block carried on a capped response (BE-9455 Symptom A).

    Names what was dropped and how to get a complete answer, because the caller is an
    agent that has to DO something about it. The old behavior logged a warning and
    returned a list indistinguishable from a complete one, so an agent reasoned over a
    partial answer as if it were whole and every downstream conclusion inherited the
    gap silently -- roadmap reads, closeout checks, any "what did we ship" question.

    BE-9468 -- THREE bounds can now cut this list, so the block carries which one did.
    ``reason`` was ALREADY the discriminator field; it gains values and the block keeps
    its shipped five keys exactly. A second truncation vocabulary would make one tool
    report two contradictory shapes depending on which bound happened to bind, and a
    caller that already understands this block would silently fail to read the new one.
    Extend the vocabulary; never fork it.

    ``dropped`` is identical for all three reasons on purpose: every cut falls on the
    SAME ordering (BE-9455's ``completed_at DESC NULLS FIRST`` for a completion-oriented
    read, creation recency otherwise), so unfinished work is un-droppable whichever
    bound bit.

    **Only ``advice`` differs, because only the REMEDY differs -- and the remedy is the
    entire reason the discriminator exists:**

    * ``limit`` -- self-inflicted; raising it genuinely returns more.
    * ``response_size`` -- raising ``limit`` returns the identical payload, so the advice
      must say so and point at a leaner row or a narrower query instead.
    * ``defensive_ceiling`` -- the underlying set was truncated before projection, so no
      parameter change completes it; only narrowing does.

    An agent sent to a remedy that cannot work is the silent-wrong-signal defect wearing
    a helpful voice.
    """
    note = {
        "reason": reason,
        "ceiling": ceiling,
        "rows_fetched": rows_fetched,
        "dropped": "the OLDEST completions" if completion_oriented else "the OLDEST-CREATED projects",
        "advice": _advice(reason, next_cursor=next_cursor, mode=mode),
    }
    # BE-9469: the continuation token lives INSIDE this block and appears ONLY on a
    # truncated response -- extending the shipped vocabulary rather than adding a second
    # one beside it. A caller that already reads this block to learn its answer was cut
    # finds the remedy in the same place; a second top-level key would make one tool
    # report two shapes and leave an existing reader unable to see the new one.
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
    """Assemble the agent-facing list response and pick which bound to report.

    BE-9455 Symptom A: ``truncated`` travels on the RESPONSE, not only in a server
    log the caller will never see -- see ``_truncation_note``.

    BE-9468: THREE bounds can cut this list and exactly one ``reason`` may be reported,
    so the choice is made here rather than at any cut site. **This is the only tool
    where all three are reachable**, so it is the only place the full order is
    observable:

    ``defensive_ceiling``  >  ``response_size``  >  ``limit``

    **The winner is the bound whose obvious remedy does NOT work -- severity, not
    application order:**

    * ``defensive_ceiling`` -- the underlying set was truncated before projection, so
      **no** parameter the caller can change yields a complete answer.
    * ``response_size`` -- raising ``limit`` returns the same payload, so the advice has
      to say a bigger limit will not help; the remedy is a leaner row or a narrower
      query.
    * ``limit`` -- self-inflicted and directly recoverable by asking for more.

    Reporting a recoverable reason while an unrecoverable one is also true would send
    the caller to a remedy that cannot work -- a fresh instance of the silent-wrong-signal
    defect this whole surface is being corrected for. ``advice`` names every bound that
    could apply, not only the winner.
    """
    # Resolved from the module global rather than taken as a default ARGUMENT: a
    # default is bound once at def time, so a test that monkeypatched the constant
    # would appear to patch the ceiling and silently not -- a green suite asserting a
    # bound the code never used, which is the exact trap the defensive ceiling's own
    # extraction was shaped to avoid.
    char_ceiling = MCP_LIST_CHAR_CEILING if char_ceiling is None else char_ceiling

    # ----- The size backstop, charged BEFORE the fit -----
    # The envelope is the response without its rows, and it must already carry the
    # truncation block a cut will add -- the WORST-CASE one of the three, because we do
    # not yet know which will win. Measuring the budget and only then adding metadata is
    # exactly how the in-repo trimmer overshoots its own ceiling by 64 chars while
    # reporting success. ``counts.returned`` is seeded with the PRE-fit count, which is
    # an upper bound on the final one, so the envelope can only shrink from here.
    counts["returned"] = len(projects_out)
    # An UPPER-BOUND placeholder token is charged against the budget with the notes, never
    # added after them: the token is ~120 chars that exist only on a truncated page, which
    # is exactly the page where the budget is tightest, and measuring the budget before
    # adding metadata is the documented way a ceiling silently stops holding. The real
    # token is minted below, after the cut -- see ``worst_case_cursor_charge``.
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

    # THE TOKEN IS MINTED HERE, after every cut, and never before one. It must name the
    # last row actually DELIVERED: a token minted before the size backstop would point
    # past rows the caller never received, which is a silent skip -- the defect this
    # whole feature exists to remove, reintroduced by its own implementation. The budget
    # above was charged an upper-bound placeholder instead, so the ceiling still holds.
    next_cursor = mint_cursor(projects_out) if mint_cursor is not None else None

    returned = len(projects_out)
    # ``counts.returned`` is ASSIGNED from the same value as the top-level ``count``,
    # never recomputed, and assigned AFTER the size backstop has run so it reports what
    # the caller actually received. Two independent len() calls at different points in a
    # pipeline is exactly how a redundant field drifts from its twin.
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
    # THE THREE-WAY ORDER. Exactly one ``reason`` may be reported, and the winner is the
    # one whose obvious remedy does NOT work -- severity, not application order.
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


# --------------------------------------------------------------------------
# The continuation cursor for this list (BE-9469 item 2)
# --------------------------------------------------------------------------


# The filters that decide WHICH projects are in the ordering. A cursor is only valid under
# the same set, so this list IS the contract -- and it lives next to the response assembly
# rather than at the tool boundary because that is where the values are already normalized
# (``query`` stripped, ``status`` widened to a list, the date bounds parsed). Fingerprinting
# raw tool arguments instead would make ``status="active"`` and ``status=["active"]``
# different filter sets, and refuse a cursor that is perfectly valid.
#
# ``limit``, ``depth`` and ``mode`` are deliberately ABSENT -- see
# ``_mcp_wire_bounds.filter_fingerprint`` for why changing page size or row shape mid-walk
# is legitimate and must not be refused.
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
    """Fingerprint the effective filter set of one ``list_projects`` request."""
    return filter_fingerprint(
        {
            "product_id": product_id,
            # Sorted so ["active","inactive"] and ["inactive","active"] -- the same
            # request written two ways -- do not fingerprint differently.
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
    """Validate an incoming ``cursor`` and return its keyset position, or ``None`` if absent.

    An empty/absent cursor returns ``None`` and the caller emits no keyset at all, which is
    what makes a call without a cursor byte-identical to the shipped behaviour.

    A non-string cursor is refused here rather than allowed to fail deeper: this value
    arrives from an AI agent, so it is type-checked at the boundary like every other tool
    parameter (house rule -- a DB or codec error would surface as a 500 with a useless
    message instead of a remedy the agent can act on). Null ``s`` is allowed ONLY on the
    completion axis (its real NULL region); the creation axis has none (BE-9469 QA, U50-F1).
    """
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
    """The token for the page just built, or ``None`` when there is nothing to continue from.

    **WHICH ROW the token points at is the whole correctness question**, because the
    position must be one where everything BEFORE it has been either delivered or
    definitively examined, and nothing after it has been silently withheld.

    * **Rows were returned -> the LAST ROW IN THE RESPONSE.** Not the last row fetched and
      not the last row that survived the filters: rows cut by the row limit or by the size
      backstop were withheld, not examined, so advancing past them would skip them.
      ``returned_rows`` is the final list after every cut, so its tail is exactly the
      furthest position the caller can be said to have received.
    * **No rows returned, but the fetch was ceiling-bounded and the FILTERS are what
      emptied it -> the last row FETCHED.** Every fetched row was examined and rejected, so
      the position is safe, and it is the only way a walk can cross a long run of
      filtered-out rows instead of stalling on a truncated-but-cursorless page.

      ⚠ **THE FILTER FINGERPRINT IS WHAT MAKES THIS CASE SOUND, and the dependency is not
      obvious from here.** "Every fetched row was examined and rejected" is only useful
      because a continuation is guaranteed to arrive under the SAME filter set -- the
      fingerprint refuses any replay that is not. Loosen the fingerprint (say, to tolerate
      an added filter) and this case starts advancing past rows the new filter set WOULD
      have matched, silently. If the fingerprint's strictness is ever revisited, revisit
      this case in the same change.
    * **No rows returned because a CUT emptied the page (``matched`` > 0) -> no token.**
      The page delivered nothing, so no position was reached. The response already says
      ``response_size`` with advice to ask for a leaner row, which is the real remedy; a
      token here would advance the walk past rows the caller never saw.

    ``fetched_rows`` are ORM rows (the keyset value comes off the model); ``returned_rows``
    are the serialized dicts actually being sent.
    """
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
    """The axis value of the fetched ORM row with this id.

    Read off the ORM row rather than out of the serialized dict, and **the reason stated in
    the first draft of this code was WRONG, so it is corrected here rather than quietly
    dropped.** That draft claimed ``mode='triage'`` omits ``completed_at`` from its row. It
    does not -- measured against the real transport, the triage row carries
    ``completed_at``. A test written on that false premise passed for the wrong reason and
    the premise was only caught because the test asserted it out loud.

    The real reason is coupling, not absence. Every projection SERIALIZES the value
    (``.isoformat()``), so a token built from the row would depend on a formatting decision
    the projection owns and is free to change -- and on the field continuing to be
    projected at all. Neither is a contract. Reading the column off the model instead makes
    the position **mode-independent**: the same row yields the same token in every mode and
    at every depth, which is exactly what lets ``mode`` stay out of the filter fingerprint
    and a mid-walk mode change stay legal. That property is asserted directly in
    ``tests/integration/test_be9469_cursor_walk_invariant.py`` rather than argued here.
    """
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
    """Resolve the axis, the filter fingerprint, and the incoming position in one call.

    Returns ``(axis, fingerprint, after_key)``. Grouped rather than left inline because the
    three are ONE decision -- which ordering this request uses, which filter set it uses,
    and where in that ordering the caller left off -- and because a caller that computed the
    fingerprint for validation separately from the fingerprint used to MINT the next token
    could get the two out of step, which is a walk that refuses its own cursors.

    The axis is derived from ``completion_oriented``, the same value that picks the ORDER BY,
    so a token can never be honoured against an ordering other than the one it was issued
    against. Called BEFORE the fetch, so a refused token costs no query.
    """
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
    """Normalize the caller's ``status`` to a list and validate every value.

    Extracted from ``list_projects_for_mcp`` under BE-9469 -- unchanged behaviour, moved so
    the function stayed inside its shrink-only length budget. It belongs here anyway: this
    module already owns every other piece of agent-input validation on this surface
    (``resolve_search_query``, ``resolve_row_limit``), and validating one parameter in the
    bounds module and its neighbour inline is how the boundary stops being one place.

    Read-side validation accepts the FULL project-status enum, lifecycle-finished values
    (``terminated``, ``deleted``) included. Update-side validation lives in
    ``update_project`` and stays restricted to its own narrower set -- the two are
    deliberately different, because reading about a deleted project is normal and setting a
    project to deleted through this path is not.

    ``valid_statuses`` is passed in rather than imported so the service's class-level set
    remains the single source of truth and no second copy can drift from it.
    """
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
    """Type-check and length-cap the agent-supplied alias prefix. Raises, returns nothing.

    Extracted alongside ``resolve_status_list``, same reason. House rule: a field flowing
    from an MCP tool parameter into a database predicate is checked HERE, at the boundary --
    not left for a DB constraint to reject with a 500 and a message no agent can act on.
    """
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
    """Normalize the caller's ``project_type`` to a list and validate every abbreviation.

    Extracted from ``list_projects_for_mcp`` under BE-9469, unchanged, for the same reason as
    its neighbours above: input validation for this surface lives in one module.

    ``valid_abbreviations`` is resolved by the caller, because the tenant's configured type
    vocabulary is an async database read and this module is deliberately synchronous and
    session-free. It arrives already including ``RESERVED_TASK_TYPE_ABBR``.
    """
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
