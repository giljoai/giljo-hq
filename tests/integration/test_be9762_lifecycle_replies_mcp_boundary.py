# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import json

import pytest
from sqlalchemy import select, update

from giljo_mcp.models import AgentExecution
from giljo_mcp.services.next_action import PROJECT_STAGING_HINT
from tests.integration.test_be9717_stale_board_line_mcp_boundary import (  # noqa: F401 -- fixture import
    _seed_project,
    board_client,
)
from tests.integration.test_be9744a_split_stage_undo_mcp_boundary import (  # noqa: F401 -- fixture import
    _cleanup,
    _load,
    _seed,
    be9744a_client,
)


pytestmark = pytest.mark.asyncio


def _payload(result) -> dict:
    return json.loads(result.content[0].text)


def _error_text(result) -> str:
    return "\n".join(getattr(b, "text", "") or "" for b in result.content)


async def _status(db_manager, tenant_key: str, job_id: str) -> str:
    async with db_manager.get_session_async(tenant_key=tenant_key) as session:
        return (
            await session.execute(select(AgentExecution.status).where(AgentExecution.job_id == job_id))
        ).scalar_one()


class TestStageThenUndoAgree:

    async def test_the_full_staging_session_then_unstage_succeeds(self, be9744a_client, db_manager):  # noqa: F811
        client, tenant_key, _ws = be9744a_client
        project_id = await _seed(db_manager, tenant_key, mission="")
        try:
            async with client() as session:
                staged = _payload(
                    await session.call_tool("stage_project", {"project_id": project_id, "mode": "subagent"})
                )
                assert staged["status"] == "staged"
                assert not (await session.call_tool("health_check", {})).is_error
                instructions = await session.call_tool(
                    "get_staging_instructions", {"job_id": staged["orchestrator_id"]}
                )
                assert not instructions.is_error, _error_text(instructions)
                undo = await session.call_tool("unstage_project", {"project_id": project_id})

            assert not undo.is_error, _error_text(undo)
            assert _payload(undo)["status"] == "unstaged"
            assert (await _load(db_manager, tenant_key, project_id)).staging_status is None
        finally:
            await _cleanup(db_manager, tenant_key)

    @pytest.mark.parametrize("tool", ["get_workflow_status", "diagnose_project_state"])
    async def test_mid_staging_reads_never_say_stage_again(self, be9744a_client, db_manager, tool):  # noqa: F811
        client, tenant_key, _ws = be9744a_client
        project_id = await _seed(db_manager, tenant_key, mission="")
        try:
            async with client() as session:
                await session.call_tool("stage_project", {"project_id": project_id, "mode": "subagent"})
                result = await session.call_tool(tool, {"project_id": project_id})

            assert not result.is_error, _error_text(result)
            payload = _payload(result)
            assert payload["staging_status"] == "staged"
            hint = payload["next_action"]
            assert hint["tool"] == "get_staging_instructions"
            assert hint["why"] == PROJECT_STAGING_HINT
            assert "call stage_project" not in hint["why"]
            assert "unstage_project" in hint["why"]
        finally:
            await _cleanup(db_manager, tenant_key)


class TestBoardLineReachesTheOrchestrator:

    async def test_a_workers_own_complete_job_carries_no_board_line(self, board_client, db_manager):  # noqa: F811
        new_client, tenant_key = board_client
        ids = await _seed_project(db_manager, tenant_key, orchestrator_status="silent", quiet_minutes=14)

        async with new_client() as session:
            result = await session.call_tool(
                "complete_job", {"job_id": ids["implementer_job_id"], "result": {"summary": "done"}}
            )

        assert result.is_error is False, _error_text(result)
        assert "board" not in _payload(result)["_meta"]

    async def test_reading_a_workers_result_counts_as_orchestrator_activity(self, board_client, db_manager):  # noqa: F811
        new_client, tenant_key = board_client
        ids = await _seed_project(db_manager, tenant_key, orchestrator_status="silent", quiet_minutes=14)

        async with new_client() as session:
            result = await session.call_tool("get_agent_result", {"job_id": ids["implementer_job_id"]})

        assert result.is_error is False, _error_text(result)
        assert "board" not in _payload(result)["_meta"]
        assert await _status(db_manager, tenant_key, ids["orchestrator_job_id"]) == "working"

    async def test_reading_a_silent_workers_result_leaves_that_worker_silent(self, board_client, db_manager):  # noqa: F811
        new_client, tenant_key = board_client
        ids = await _seed_project(db_manager, tenant_key, orchestrator_status="silent", quiet_minutes=14)
        async with db_manager.get_session_async(tenant_key=tenant_key) as session:
            await session.execute(
                update(AgentExecution).where(AgentExecution.job_id == ids["implementer_job_id"]).values(status="silent")
            )
            await session.commit()

        async with new_client() as session:
            result = await session.call_tool("get_agent_result", {"job_id": ids["implementer_job_id"]})

        assert result.is_error is False, _error_text(result)
        assert await _status(db_manager, tenant_key, ids["implementer_job_id"]) == "silent"
        assert await _status(db_manager, tenant_key, ids["orchestrator_job_id"]) == "working"

    async def test_finalizing_a_job_counts_as_orchestrator_activity(self, board_client, db_manager):  # noqa: F811
        new_client, tenant_key = board_client
        ids = await _seed_project(db_manager, tenant_key, orchestrator_status="silent", quiet_minutes=14)

        async with new_client() as session:
            done = await session.call_tool(
                "complete_job", {"job_id": ids["tester_job_id"], "result": {"summary": "ok"}}
            )
            assert done.is_error is False, _error_text(done)
            result = await session.call_tool(
                "finalize_job", {"job_id": ids["tester_job_id"], "caller_job_id": ids["orchestrator_job_id"]}
            )

        assert result.is_error is False, _error_text(result)
        assert "board" not in _payload(result)["_meta"]
        assert await _status(db_manager, tenant_key, ids["orchestrator_job_id"]) == "working"

    async def test_a_call_on_the_orchestrators_own_job_still_carries_the_line(self, board_client, db_manager):  # noqa: F811
        new_client, tenant_key = board_client
        ids = await _seed_project(db_manager, tenant_key, orchestrator_status="silent", quiet_minutes=14)

        async with new_client() as session:
            result = await session.call_tool(
                "get_context", {"categories": ["todos"], "job_id": ids["orchestrator_job_id"]}
            )

        assert result.is_error is False, _error_text(result)
        assert "stale 14 min" in _payload(result)["_meta"]["board"]
