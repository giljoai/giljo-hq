# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from collections.abc import Mapping


WORKING = "working"
HOLDING = "holding"
SILENT = "silent"

LIVE_EXECUTION_STATUSES = frozenset({WORKING, SILENT})
OPEN_TODO_STATUSES = ("pending", "in_progress")


def todo_list_finished(todo_counts: Mapping[str, int] | None) -> bool:
    counts = todo_counts or {}
    if sum(counts.values()) <= 0:
        return False
    return all(counts.get(status, 0) == 0 for status in OPEN_TODO_STATUSES)


def activity_word(status: str | None, todo_counts: Mapping[str, int] | None) -> str:
    status = status or ""
    if status in LIVE_EXECUTION_STATUSES and todo_list_finished(todo_counts):
        return HOLDING
    return status
