# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import json

import pytest
from sqlalchemy import select

from giljo_mcp.models import AgentExecution
from tests.integration.test_be9717_stale_board_line_mcp_boundary import (  # noqa: F401 -- fixture import
    _seed_project,
    board_client,
)


pytestmark = pytest.mark.asyncio

RESULT = {"summary": "Tests pass", "artifacts": ["tests/test_x.py"], "commits": ["abc123"]}


def _error_text(result) -> str:
    return "\n".join(getattr(b, "text", "") or "" for b in result.content)


async def test_get_agent_result_after_finalize_job_returns_the_stored_result(board_client, db_manager):  # noqa: F811
    new_client, tenant_key = board_client
    ids = await _seed_project(db_manager, tenant_key, orchestrator_status="working", quiet_minutes=1)

    async with new_client() as session:
        done = await session.call_tool("complete_job", {"job_id": ids["tester_job_id"], "result": RESULT})
        assert done.is_error is False, _error_text(done)
        sealed = await session.call_tool(
            "finalize_job", {"job_id": ids["tester_job_id"], "caller_job_id": ids["orchestrator_job_id"]}
        )
        assert sealed.is_error is False, _error_text(sealed)
        reply = await session.call_tool("get_agent_result", {"job_id": ids["tester_job_id"]})

    async with db_manager.get_session_async(tenant_key=tenant_key) as db:
        status = (
            await db.execute(select(AgentExecution.status).where(AgentExecution.job_id == ids["tester_job_id"]))
        ).scalar_one()
    assert status == "closed"

    assert reply.is_error is False, _error_text(reply)
    payload = json.loads(reply.content[0].text)
    assert payload["result"] == RESULT
    assert "message" not in payload
