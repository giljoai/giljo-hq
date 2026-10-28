# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import json

import pytest
from sqlalchemy import select

from giljo_mcp.models.agent_identity import AgentExecution, AgentJob
from giljo_mcp.models.projects import Project
from giljo_mcp.product_crew import seed_product_crew
from tests.helpers.test_db_helper import purge_tenant_rows
from tests.integration.test_be9744a_split_stage_undo_mcp_boundary import (  # noqa: F401 -- fixture import
    _seed,
    be9744a_client,
)


pytestmark = pytest.mark.asyncio

PLAN = "BE-9831 plan: one implementer adds slugify with tests."
BASELINE_CALLS = 25
TARGET_CALLS = 20


def _payload(result) -> dict:
    return json.loads(result.content[0].text)


class _Walk:

    def __init__(self, session, calls: list[str]):
        self._session = session
        self._calls = calls

    async def call(self, name: str, args: dict) -> dict:
        self._calls.append(name)
        result = await self._session.call_tool(name, args)
        assert not result.is_error, f"{name} refused: {[getattr(b, 'text', b) for b in result.content]}"
        return _payload(result)


async def test_tiny_task_path_walk_is_twenty_calls_with_the_same_end_state(be9744a_client, db_manager):  # noqa: F811
    client, tenant_key, _ws = be9744a_client
    project_id = await _seed(db_manager, tenant_key, mission="")
    calls: list[str] = []
    try:
        async with db_manager.get_session_async(tenant_key=tenant_key) as session:
            product_id = (
                await session.execute(select(Project.product_id).where(Project.id == project_id))
            ).scalar_one()
            await session.execute(Project.__table__.delete().where(Project.id == project_id))
            await seed_product_crew(session, tenant_key, product_id)
            await session.commit()

        async with client() as raw:
            orch = _Walk(raw, calls)
            await orch.call("get_giljo_guide", {})
            await orch.call("get_context", {"categories": ["products"]})
            created = await orch.call(
                "create_project",
                {
                    "name": "BE-9831 slugify",
                    "description": "Add slugify with tests.",
                    "product_id": product_id,
                    "project_type": "BE",
                },
            )
            project_id = created["project_id"]
            staged = await orch.call("stage_project", {"project_id": project_id, "mode": "subagent"})
            orch_job, thread = staged["orchestrator_id"], staged["thread_id"]
            staging = await orch.call("get_staging_instructions", {"job_id": orch_job})
            assert "STEP 7: Persist Execution Plan (optional)" in json.dumps(staging)
            await orch.call(
                "report_progress",
                {"job_id": orch_job, "todo_items": [{"content": "slugify shipped", "status": "pending"}]},
            )
            await orch.call("update_project_mission", {"project_id": project_id, "mission": PLAN})
            spawned = await orch.call(
                "spawn_job",
                {
                    "agent_name": "implementer",
                    "agent_display_name": "implementer",
                    "project_id": project_id,
                    "phase": 1,
                    "mission": "Add slugify.",
                },
            )
            await orch.call("complete_job", {"job_id": orch_job, "result": {"summary": "staged, 1 worker"}})
            await orch.call("launch_implementation", {"project_id": project_id})
            mission = await orch.call("get_job_mission", {"job_id": orch_job})
            assert PLAN in mission["mission"], "no update_job_mission: the project plan must reach the orchestrator"
            orch_protocol = mission["full_protocol"]
            assert "Pre-closeout:" in orch_protocol
            pre_closeout = orch_protocol.split("**Pre-closeout:**")[1].split("**Git:**")[0]
            assert "get_thread_history" not in pre_closeout, "complete_job names unread posts; no separate drain"
            assert "only if that report is missing" in orch_protocol

            worker_job, worker_id = spawned["job_id"], spawned["agent_id"]
            worker = _Walk(raw, calls)
            worker_mission = await worker.call("get_job_mission", {"job_id": worker_job})
            phase4 = worker_mission["full_protocol"].split("### Phase 4")[1].split("### Phase 5")[0]
            assert "get_thread_history(" not in phase4 and "action-required messages unread" in phase4
            await worker.call(
                "get_thread_history",
                {"thread_id": thread, "as_participant": worker_id, "unread_only": True, "mark_read": True},
            )
            await worker.call(
                "report_progress",
                {
                    "job_id": worker_job,
                    "todo_items": [
                        {"content": "add slugify", "status": "in_progress"},
                        {"content": "test it", "status": "pending"},
                    ],
                },
            )
            await worker.call(
                "report_progress",
                {
                    "job_id": worker_job,
                    "todo_items": [
                        {"content": "add slugify", "status": "completed"},
                        {"content": "test it", "status": "completed"},
                    ],
                },
            )
            await worker.call(
                "complete_job",
                {"job_id": worker_job, "result": {"summary": "slugify added", "artifacts": ["textkit/core.py"]}},
            )

            await orch.call(
                "report_progress",
                {"job_id": orch_job, "todo_items": [{"content": "slugify shipped", "status": "completed"}]},
            )
            await orch.call("complete_job", {"job_id": orch_job, "result": {"summary": "slugify shipped"}})
            await orch.call(
                "write_project_closeout",
                {
                    "project_id": project_id,
                    "summary": "slugify added",
                    "key_outcomes": ["slugify"],
                    "decisions_made": ["one worker"],
                    "tags": ["feature"],
                    "git_commits": [],
                },
            )
            done = await orch.call("update_project", {"project_id": project_id, "status": "completed"})

        assert done["status"] == "completed"
        assert len(calls) == TARGET_CALLS, calls
        assert len(calls) <= BASELINE_CALLS - 5
        for removed in ("update_job_mission", "get_agent_result", "finalize_job"):
            assert removed not in calls
        assert calls.count("get_thread_history") == 1, "only the worker's startup read remains"

        async with db_manager.get_session_async(tenant_key=tenant_key) as verify:
            statuses = {
                row.agent_display_name: row.status
                for row in (
                    await verify.execute(
                        select(AgentExecution)
                        .join(AgentJob, AgentExecution.job_id == AgentJob.job_id)
                        .where(AgentJob.project_id == project_id)
                    )
                ).scalars()
            }
            project = (await verify.execute(select(Project).where(Project.id == project_id))).scalar_one()
        assert statuses == {"orchestrator": "closed", "implementer": "closed"}, statuses
        assert project.status == "completed" and project.completed_at is not None
    finally:
        await purge_tenant_rows(db_manager, tenant_key)
