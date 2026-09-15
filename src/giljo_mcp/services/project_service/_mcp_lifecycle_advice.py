# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any


_NARROWING_POST_FILTER_KEYS = (
    "project_type_list",
    "taxonomy_alias_prefix",
    "created_after",
    "created_before",
    "hidden",
)


def has_narrowing_filter(query: str | None, post_filter_kwargs: dict[str, Any]) -> bool:
    return bool(query) or any(post_filter_kwargs[k] is not None for k in _NARROWING_POST_FILTER_KEYS)


def _lifecycle_hidden_sentence(*, matched: int, hidden_total: int, project_type_list: list[str] | None) -> str:
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
