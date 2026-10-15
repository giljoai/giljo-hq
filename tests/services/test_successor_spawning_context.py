# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import pytest
from sqlalchemy import select

from giljo_mcp.models import AgentJob






@pytest.mark.asyncio
class TestSpawnWithPredecessor:

    async def test_mission_contains_predecessor_context(self, db_session, service, project, tenant_key):
        from tests.services.conftest import _spawn_and_complete

        predecessor_result = {
            "summary": "Implemented auth module with JWT tokens",
            "artifacts": ["src/auth.py", "tests/test_auth.py"],
            "commits": ["abc123 feat: add auth module"],
        }
        pred_spawn = await _spawn_and_complete(service, project.id, tenant_key, predecessor_result)

        successor = await service.spawn_job(
            agent_display_name="successor",
            agent_name="tdd-implementor",
            mission="Fix the JWT validation bug found by tester",
            project_id=project.id,
            tenant_key=tenant_key,
            predecessor_job_id=pred_spawn.job_id,
        )

        stmt = select(AgentJob).where(AgentJob.job_id == successor.job_id)
        res = await db_session.execute(stmt)
        job = res.scalar_one()

        assert "## PRIOR PHASE OUTPUT" in job.mission
        assert pred_spawn.job_id in job.mission
        assert "Implemented auth module with JWT tokens" in job.mission
        assert "abc123 feat: add auth module" in job.mission
        assert "Fix the JWT validation bug found by tester" in job.mission
        assert "get_agent_result" in job.mission

    async def test_predecessor_job_id_in_spawn_result(self, service, project, tenant_key):
        from tests.services.conftest import _spawn_and_complete

        pred_spawn = await _spawn_and_complete(service, project.id, tenant_key, {"summary": "Done"})

        successor = await service.spawn_job(
            agent_display_name="successor",
            agent_name="tdd-implementor",
            mission="Fix issues",
            project_id=project.id,
            tenant_key=tenant_key,
            predecessor_job_id=pred_spawn.job_id,
        )

        assert successor.predecessor_job_id == pred_spawn.job_id




@pytest.mark.asyncio
class TestPredecessorContextTruncation:

    async def test_long_summary_truncated_at_2000_chars(self, db_session, service, project, tenant_key):
        from tests.services.conftest import _spawn_and_complete

        long_summary = "A" * 3000
        pred_spawn = await _spawn_and_complete(service, project.id, tenant_key, {"summary": long_summary})

        successor = await service.spawn_job(
            agent_display_name="successor",
            agent_name="tdd-implementor",
            mission="Fix it",
            project_id=project.id,
            tenant_key=tenant_key,
            predecessor_job_id=pred_spawn.job_id,
        )

        stmt = select(AgentJob).where(AgentJob.job_id == successor.job_id)
        res = await db_session.execute(stmt)
        job = res.scalar_one()

        assert "[TRUNCATED]" in job.mission
        assert long_summary not in job.mission

    async def test_commits_capped_at_10(self, db_session, service, project, tenant_key):
        from tests.services.conftest import _spawn_and_complete

        many_commits = [f"commit_{i}" for i in range(20)]
        pred_spawn = await _spawn_and_complete(
            service, project.id, tenant_key, {"summary": "Done", "commits": many_commits}
        )

        successor = await service.spawn_job(
            agent_display_name="successor",
            agent_name="tdd-implementor",
            mission="Fix it",
            project_id=project.id,
            tenant_key=tenant_key,
            predecessor_job_id=pred_spawn.job_id,
        )

        stmt = select(AgentJob).where(AgentJob.job_id == successor.job_id)
        res = await db_session.execute(stmt)
        job = res.scalar_one()

        assert "commit_9" in job.mission
        assert "commit_10" not in job.mission
        assert "... and 10 more" in job.mission




@pytest.mark.asyncio
class TestPredecessorNoResult:

    async def test_predecessor_not_completed_still_injects_context(self, db_session, service, project, tenant_key):
        pred_spawn = await service.spawn_job(
            agent_display_name="predecessor",
            agent_name="specialist-1",
            mission="Still working",
            project_id=project.id,
            tenant_key=tenant_key,
        )

        successor = await service.spawn_job(
            agent_display_name="successor",
            agent_name="tdd-implementor",
            mission="Fix the issues",
            project_id=project.id,
            tenant_key=tenant_key,
            predecessor_job_id=pred_spawn.job_id,
        )

        stmt = select(AgentJob).where(AgentJob.job_id == successor.job_id)
        res = await db_session.execute(stmt)
        job = res.scalar_one()

        assert "## PRIOR PHASE OUTPUT" in job.mission
        assert "No summary available" in job.mission
        assert "Fix the issues" in job.mission




@pytest.mark.asyncio
class TestSpawnWithoutPredecessorRegression:

    async def test_spawn_without_predecessor_works(self, db_session, service, project, tenant_key):
        result = await service.spawn_job(
            agent_display_name="implementer",
            agent_name="specialist-1",
            mission="Implement the feature",
            project_id=project.id,
            tenant_key=tenant_key,
        )

        assert result.job_id is not None
        assert result.agent_id is not None
        assert result.predecessor_job_id is None
        assert result.mission_stored is True

        stmt = select(AgentJob).where(AgentJob.job_id == result.job_id)
        res = await db_session.execute(stmt)
        job = res.scalar_one()

        assert "PREDECESSOR CONTEXT" not in job.mission
        assert "Implement the feature" in job.mission

    async def test_spawn_with_none_predecessor_works(self, service, project, tenant_key):
        result = await service.spawn_job(
            agent_display_name="implementer-2",
            agent_name="specialist-1",
            mission="Normal mission",
            project_id=project.id,
            tenant_key=tenant_key,
            predecessor_job_id=None,
        )

        assert result.job_id is not None
        assert result.predecessor_job_id is None




def _dependency_lines(mission: str) -> str:
    section = mission.split("## YOUR DEPENDENCIES\n", 1)[1]
    return section.split("\n\n", 1)[0]


@pytest.mark.asyncio
class TestMissionDependenciesFromJobLinks:

    async def test_parallel_phase1_documenter_depends_on_nothing(self, service, project, tenant_key):
        await service.spawn_job(
            agent_display_name="implementer",
            agent_name="specialist-1",
            mission="Implement the feature",
            project_id=project.id,
            tenant_key=tenant_key,
            phase=1,
        )
        documenter = await service.spawn_job(
            agent_display_name="documenter",
            agent_name="specialist-1",
            mission="Document the feature",
            project_id=project.id,
            tenant_key=tenant_key,
            phase=1,
        )

        response = await service.get_agent_mission(documenter.job_id, tenant_key)

        assert _dependency_lines(response.mission) == (
            "- You depend on: None (you can start immediately)\n- Others depend on you: None"
        )

    async def test_predecessor_link_is_stored_and_named_in_both_missions(
        self, db_session, service, project, tenant_key
    ):
        analyzer = await service.spawn_job(
            agent_display_name="analyzer",
            agent_name="specialist-1",
            mission="Analyze the module",
            project_id=project.id,
            tenant_key=tenant_key,
            phase=1,
        )
        implementer = await service.spawn_job(
            agent_display_name="implementer",
            agent_name="tdd-implementor",
            mission="Implement from the analysis",
            project_id=project.id,
            tenant_key=tenant_key,
            phase=2,
            predecessor_job_id=analyzer.job_id,
        )

        stored = (await db_session.execute(select(AgentJob).where(AgentJob.job_id == implementer.job_id))).scalar_one()
        assert stored.job_metadata["predecessor_job_id"] == analyzer.job_id

        successor_mission = (await service.get_agent_mission(implementer.job_id, tenant_key)).mission
        predecessor_mission = (await service.get_agent_mission(analyzer.job_id, tenant_key)).mission

        assert _dependency_lines(successor_mission) == (
            f"- You depend on: analyzer ({analyzer.agent_id}) (wait for their outputs if needed)\n"
            "- Others depend on you: None"
        )
        assert _dependency_lines(predecessor_mission) == (
            "- You depend on: None (you can start immediately)\n"
            f"- Others depend on you: implementer ({implementer.agent_id}) (notify them when your work is ready)"
        )
