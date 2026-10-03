# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import logging
import time
from collections import OrderedDict
from typing import Any

from sqlalchemy.exc import SQLAlchemyError


logger = logging.getLogger(__name__)

SILENCE_CLEARING_TOOLS: frozenset[str] = frozenset(
    {
        "report_progress",
        "get_job_mission",
        "get_staging_instructions",
        "set_agent_status",
        "request_approval",
    }
)

NON_SILENCE_CLEARING_TOOLS: frozenset[str] = frozenset(
    {
        "get_context",
        "get_agent_result",
        "close_job",
        "reactivate_job",
        "dismiss_reactivation",
        "update_job_mission",
        "complete_job",
    }
)


_BOARD_LINE_TTL_SECONDS = 30.0
_BOARD_LINE_MAX_KEYS = 2048
_BOARD_LINES: OrderedDict[tuple[str, str], tuple[float, str | None]] = OrderedDict()


def _forget_tenant(tenant_key: str) -> None:
    for key in [key for key in _BOARD_LINES if key[0] == tenant_key]:
        del _BOARD_LINES[key]


async def _read_board_line(tenant_key: str, project_id: str | None, job_id: str | None) -> str | None:
    from api.app_state import state as app_state
    from giljo_mcp.database import DatabaseManager
    from giljo_mcp.services.silence_detector import stale_orchestrator_states

    if not isinstance(app_state.db_manager, DatabaseManager):
        return None
    try:
        async with app_state.db_manager.get_session_async(tenant_key=tenant_key) as session:
            states = await stale_orchestrator_states(
                session, tenant_key, project_ids=[project_id] if project_id else None, job_id=job_id
            )
    except SQLAlchemyError:
        logger.warning("board line read failed (non-blocking)", exc_info=True)
        return None
    if not states:
        return None
    state = next(iter(states.values()))
    todos = f", to-dos {state.todos_done}/{state.todos_total}" if state.todos_total else ""
    return (
        f"Orchestrator entry for this project stale {state.stale_minutes} min{todos}; the board shows "
        f"{state.label}. The orchestrator of this project refreshes it with report_progress or "
        "set_agent_status(idle)."
    )


async def stale_board_line(tenant_key: str, method_name: str, arguments: dict[str, Any]) -> str | None:
    if method_name in SILENCE_CLEARING_TOOLS:
        _forget_tenant(tenant_key)
        return None
    project_id = arguments.get("project_id") if isinstance(arguments.get("project_id"), str) else None
    job_id = None if project_id else arguments.get("job_id")
    scope = project_id or (job_id if isinstance(job_id, str) else None)
    if not scope:
        return None
    key = (tenant_key, scope)
    cached = _BOARD_LINES.get(key)
    if cached is not None and time.monotonic() - cached[0] < _BOARD_LINE_TTL_SECONDS:
        return cached[1]
    line = await _read_board_line(tenant_key, project_id, job_id if not project_id else None)
    _BOARD_LINES[key] = (time.monotonic(), line)
    _BOARD_LINES.move_to_end(key)
    if len(_BOARD_LINES) > _BOARD_LINE_MAX_KEYS:
        _BOARD_LINES.popitem(last=False)
    return line
