# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""``counts.advice`` -- the lifecycle-hidden explanation for the project list (BE-9471).

QA units U74-F1/U76 measured a legibility trap: ``list_projects(project_type='UI')``
returns ``matched:0, projects:[]`` while the SAME response's ``counts.by_type.UI``
reads 6 -- every one of them completed, and hidden by the tool's own default
lifecycle filter (BE-5037: excludes completed/cancelled/terminated by default). An
agent that trusts the empty list concludes the type does not exist.

**BE-9471 follow-up (U80/U81) -- the shipped fix over-claimed the moment a second
filter narrowed the result.** ``by_type`` is a WHOLE-BOARD tally, correct only when
``project_type`` is the sole narrowing predicate. QA measured the advice stating a
whole-board number and a remedy that, when followed exactly, did not produce it:
``project_type='DOC'+query='zzzznotarealword'`` promised 11, the remedy returned 0;
``+query='documentation'`` promised 11, truth 3; ``+created_after=...`` promised
"the rest", truth zero additional rows; ``+taxonomy_alias_prefix='DOC-6167'``
(an exact single-alias lookup) told the agent its complete answer was incomplete.
Three of three tested co-filters (``query``, ``created_after``, ``taxonomy_alias_prefix``)
reproduced it -- the defect is general to any predicate beyond ``project_type``, not a
quirk of one filter. U79 additionally found the SILENT half of the same bug: a
``query`` alone that is entirely lifecycle-hidden (0 shown, 33 exist) got no advice at
all, because the pre-9471-follow-up trigger required ``project_type`` to be present.

**EM-ruled fix -- a truthful count, gated so the common path stays cheap.**

1. **Empty variant** (``matched == 0``, default lifecycle view, ANY narrowing filter
   present -- ``project_type`` is no longer required): run ONE extra COUNT under the
   caller's EXACT filter set with only the lifecycle predicate relaxed. Speak it if
   nonzero; stay silent if zero. An empty response is the cheap case in this tool
   already (the remedy fetch would itself be empty), so paying one COUNT there is
   acceptable and it also closes U79's silent-``query`` gap for free.
2. **Partial variant** (``matched > 0``): the free ``by_type``-vs-``matched``
   pre-trigger stays (cheap, ``project_type`` required, already computed on every
   response) but now only ARMS the check -- it decides whether to pay for the COUNT,
   never what number to speak. The spoken number always comes from the same relaxed
   COUNT, and if the truthful hidden delta is zero the advice stays silent (the
   ``created_after``/``taxonomy_alias_prefix`` "no rest" cases from U80-C/U81-B).
3. **Known, deliberate limit:** partial-hide with NO ``project_type`` (U79's
   129-of-140 query-only case) stays silent. There is no free pre-trigger without
   ``project_type`` to arm the check, and this module does not pay a COUNT on every
   non-empty default-view list just to rule out a gap that might not exist. Silence is
   honest; a whole-board number is not. This is an accepted scope limit, not an
   oversight -- see the work order this follow-up shipped under.
4. The relaxed COUNT reuses the caller's SAME filter-condition builder
   (``_fetch_under_ceiling`` + ``_apply_post_fetch_filters`` in
   ``_mcp_adapter_query_mixin``) with only the SQL-side lifecycle predicate
   (``inner_status``) relaxed to ``None`` -- never a hand-rolled second predicate set
   that could drift from the one that produced ``matched``.

**Review ruling (2026-08-19), overruling the first cut of this fix.** The first
version reused BE-9468's ``truncation``/``truncated`` machinery, setting
``truncated:true`` with a fourth ``reason``. That collides with the shipped walk
contract: ``truncated:true`` promises a continuable cut (``truncation.next_cursor``,
``keep paging until truncated is false``), and the QA harness's walk loop asserts
``truncated:true => next_cursor truthy``. This case has no cursor -- the effective
result set under the caller's filters IS complete, nothing was cut from it. Flipping
``truncated`` for a different fact (the caller's intent probably was not matched)
forks its meaning, which is the exact contortion the WO said to flag rather than
force. The fix instead lives on ``counts`` -- the block that already carries the
match numbers whose disagreement is what needs explaining -- as a new ``advice`` key,
INSIDE the existing block (no new top-level response field). ``truncated``/
``truncation`` are untouched by this feature, including by this follow-up.

Extracted into its own module rather than grown into ``_mcp_adapter_query_mixin``
or ``_mcp_list_bounds`` -- both already at the 800-line guardrail -- for the same
reason BE-9468 split ``_mcp_list_bounds`` out of the mixin in the first place:
extract, never shed, never raise.

Edition Scope: Both.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any


# The post_filter_kwargs keys that represent a real caller-narrowing predicate.
# ``exclude_superseded`` is always a bool (not a caller ask) and is deliberately excluded;
# ``completed_after``/``completed_before`` are guaranteed None whenever default_lifecycle_view
# is True (they force it False), so their inclusion would be inert either way.
_NARROWING_POST_FILTER_KEYS = (
    "project_type_list",
    "taxonomy_alias_prefix",
    "created_after",
    "created_before",
    "hidden",
)


def has_narrowing_filter(query: str | None, post_filter_kwargs: dict[str, Any]) -> bool:
    """True when the caller narrowed by anything beyond the bare lifecycle default.

    Reads straight off ``post_filter_kwargs`` -- the SAME dict already passed to
    ``_apply_post_fetch_filters`` -- plus ``query`` (SQL-pushed, not in that dict), so this
    can never enumerate a filter the fetch itself does not already honor.
    """
    return bool(query) or any(post_filter_kwargs[k] is not None for k in _NARROWING_POST_FILTER_KEYS)


def _lifecycle_hidden_sentence(*, matched: int, hidden_total: int, project_type_list: list[str] | None) -> str:
    """The advice sentence. ``hidden_total`` is the TRUE count under the caller's own
    filter set with only the lifecycle predicate relaxed -- never a whole-board number.
    No truncation vocabulary -- this is not a cut.
    """
    scope = f"project_type={','.join(project_type_list)}" if project_type_list else "your filters"
    if matched == 0:
        return (
            f"The empty result for {scope} does NOT mean none exist. {hidden_total} project(s) "
            "match your filters once the default lifecycle view is relaxed, but the default view "
            "hides completed/cancelled/terminated projects and every match is in that state. Pass "
            "include_completed=true (or an explicit status) to see them."
        )
    return (
        f"{matched} shown here for {scope} is not the whole count for your filters. {hidden_total} "
        "project(s) match once the default lifecycle view is relaxed; the rest are "
        "completed/cancelled/terminated and hidden by the default view. Pass include_completed=true "
        "(or an explicit status) to see them."
    )


async def attach_lifecycle_hidden_advice(
    counts: dict[str, Any],
    *,
    project_type_list: list[str] | None,
    default_lifecycle_view: bool,
    matched: int | None,
    any_filter_set: bool,
    relaxed_count: Callable[[], Awaitable[int | None]],
) -> dict[str, Any]:
    """Set ``counts["advice"]`` when the default lifecycle filter hid matching rows. Mutates and returns ``counts``.

    Called BEFORE ``_mcp_list_bounds.build_list_response`` assembles the response, so
    the string this sets is already inside ``counts`` -- and therefore inside the
    envelope -- by the time that function charges its char-ceiling budget.

    Fires only on the DEFAULT lifecycle view (no explicit ``status``, no
    ``include_completed``, no completion-date bound -- an explicit ask is not a
    surprise this project needs to correct) and only when ``matched`` is known
    (omitted -- never guessed -- when the fetch was ceiling-bound: "a missing number
    beats a confident wrong one"). Two distinct trigger shapes beyond that, per the
    module docstring's EM ruling:

    - ``matched == 0`` with ANY narrowing filter present: pays ``relaxed_count()``
      unconditionally (the cheap case) and speaks it only if nonzero.
    - ``matched > 0``: the free ``by_type``-vs-``matched`` pre-check (requires
      ``project_type_list``) decides whether to pay for ``relaxed_count()`` at all;
      the spoken number is always the relaxed count, never ``by_type``.

    ``relaxed_count`` returning ``None`` means its own fetch hit the defensive
    ceiling -- the true count is unknowable, so no advice is attached rather than
    guessing (same "missing beats wrong" rule as ``matched`` itself).
    """
    if not default_lifecycle_view or matched is None:
        return counts

    if matched == 0:
        if not any_filter_set:
            return counts
        hidden_total = await relaxed_count()
        if not hidden_total:
            return counts
        counts["advice"] = _lifecycle_hidden_sentence(
            matched=0, hidden_total=hidden_total, project_type_list=project_type_list
        )
        return counts

    # Partial variant: the free by_type pre-arm still requires project_type_list --
    # item 3's known, deliberate limit. No project_type means no free signal to arm
    # on, and this module will not pay a COUNT on every non-empty default-view list.
    if not project_type_list:
        return counts
    by_type = counts.get("by_type", {})
    by_type_total = sum(by_type.get(t, 0) for t in project_type_list)
    if by_type_total <= matched:
        return counts

    hidden_total = await relaxed_count()
    if hidden_total is None or hidden_total <= matched:
        return counts
    counts["advice"] = _lifecycle_hidden_sentence(
        matched=matched, hidden_total=hidden_total, project_type_list=project_type_list
    )
    return counts
