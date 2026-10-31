# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from giljo_mcp.domain.job_activity import HOLDING, SILENT, WORKING, activity_word


@dataclass(frozen=True)
class AgentStatusTally:
    total: int
    active: int
    holding: int
    silent: int
    completed: int
    closed: int
    pending: int
    blocked: int
    decommissioned: int
    words: Mapping[str, str]


def tally_agent_statuses(executions: Iterable[Any], todo_map: Mapping[str, Mapping[str, int]]) -> AgentStatusTally:
    rows = list(executions)
    words = {ex.job_id: activity_word(ex.status, todo_map.get(ex.job_id)) for ex in rows}

    def by_status(status: str) -> int:
        return sum(1 for ex in rows if ex.status == status)

    def by_word(word: str) -> int:
        return sum(1 for value in words.values() if value == word)

    return AgentStatusTally(
        total=len(rows),
        active=by_word(WORKING),
        holding=by_word(HOLDING),
        silent=by_word(SILENT),
        completed=by_status("complete"),
        closed=by_status("closed"),
        pending=by_status("waiting"),
        blocked=by_status("blocked"),
        decommissioned=by_status("decommissioned"),
        words=words,
    )
