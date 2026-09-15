# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from unittest.mock import MagicMock
from uuid import uuid4

from giljo_mcp.services.protocol_builder import _generate_team_context_header


def create_mock_agent_execution(
    agent_display_name: str,
    agent_name: str | None = None,
    agent_id: str | None = None,
    job_id: str | None = None,
    status: str = "waiting",
    mission: str | None = None,
) -> MagicMock:
    mock_execution = MagicMock()
    mock_execution.agent_display_name = agent_display_name
    mock_execution.agent_name = agent_name or agent_display_name
    mock_execution.agent_id = agent_id or str(uuid4())
    mock_execution.job_id = job_id or str(uuid4())
    mock_execution.status = status
    mock_execution.mission = mission
    return mock_execution


class TestTeamContextHeader:

    def test_your_identity_section_contains_role_and_ids(self):
        agent_id = str(uuid4())
        job_id = str(uuid4())
        current_agent = create_mock_agent_execution(
            agent_display_name="analyzer",
            agent_name="analyzer",
            agent_id=agent_id,
            job_id=job_id,
        )

        header = _generate_team_context_header(
            current_job=current_agent,
            all_project_jobs=[current_agent],
            mission_lookup=None,
        )

        assert "## YOUR IDENTITY" in header, "Header must include YOUR IDENTITY section"

        assert "ANALYZER" in header, "YOUR IDENTITY must include capitalized role name"

        assert agent_id in header, "YOUR IDENTITY must include agent_id"

        assert job_id in header, "YOUR IDENTITY must include job_id"

        assert "analyzer" in header.lower(), "YOUR IDENTITY must mention agent_display_name"

    def test_your_team_section_lists_all_agents(self):
        analyzer = create_mock_agent_execution(
            agent_display_name="analyzer", mission="Analyze folder structure and design architecture"
        )
        implementer = create_mock_agent_execution(
            agent_display_name="implementer", mission="Implement backend API endpoints based on architecture"
        )

        all_agents = [analyzer, implementer]

        header = _generate_team_context_header(
            current_job=analyzer,
            all_project_jobs=all_agents,
            mission_lookup=None,
        )

        assert "## YOUR TEAM" in header, "Header must include YOUR TEAM section"

        assert "2 agent(s)" in header, "YOUR TEAM must show correct agent count"

        assert "| Agent |" in header, "YOUR TEAM must include table header"
        assert "| agent_id |" in header, "YOUR TEAM table must have agent_id column"
        assert "| Role |" in header, "YOUR TEAM table must have Role column"
        assert "| Deliverables |" in header, "YOUR TEAM table must have Deliverables column"

        assert "analyzer" in header.lower(), "YOUR TEAM must list analyzer"
        assert "implementer" in header.lower(), "YOUR TEAM must list implementer"

        assert "Analyze folder structure" in header or "architecture" in header.lower(), (
            "YOUR TEAM should show deliverable preview"
        )

    def test_your_dependencies_section_analyzer_has_downstream(self):
        analyzer = create_mock_agent_execution(agent_display_name="analyzer")
        implementer = create_mock_agent_execution(agent_display_name="implementer")
        documenter = create_mock_agent_execution(agent_display_name="documenter")

        all_agents = [analyzer, implementer, documenter]

        header = _generate_team_context_header(
            current_job=analyzer,
            all_project_jobs=all_agents,
            mission_lookup=None,
        )

        assert "## YOUR DEPENDENCIES" in header, "Header must include YOUR DEPENDENCIES section"

        assert "You depend on: None" in header, "Analyzer should have no upstream dependencies"

        assert "Others depend on you:" in header, "YOUR DEPENDENCIES must list downstream dependencies"
        assert "implementer" in header.lower(), "Analyzer should list implementer as downstream"
        assert "documenter" in header.lower(), "Analyzer should list documenter as downstream"

    def test_your_dependencies_section_documenter_has_upstream(self):
        analyzer = create_mock_agent_execution(agent_display_name="analyzer")
        implementer = create_mock_agent_execution(agent_display_name="implementer")
        documenter = create_mock_agent_execution(agent_display_name="documenter")

        all_agents = [analyzer, implementer, documenter]

        header = _generate_team_context_header(
            current_job=documenter,
            all_project_jobs=all_agents,
            mission_lookup=None,
        )

        assert "## YOUR DEPENDENCIES" in header, "Header must include YOUR DEPENDENCIES section"

        assert "You depend on:" in header, "YOUR DEPENDENCIES must list upstream dependencies"
        assert "analyzer" in header.lower(), "Documenter should list analyzer as upstream"
        assert "implementer" in header.lower(), "Documenter should list implementer as upstream"

        assert "Others depend on you: None" in header, "Documenter should have no downstream dependencies"

    def test_your_dependencies_section_implementer_has_both(self):
        analyzer = create_mock_agent_execution(agent_display_name="analyzer")
        implementer = create_mock_agent_execution(agent_display_name="implementer")
        tester = create_mock_agent_execution(agent_display_name="tester")
        documenter = create_mock_agent_execution(agent_display_name="documenter")

        all_agents = [analyzer, implementer, tester, documenter]

        header = _generate_team_context_header(
            current_job=implementer,
            all_project_jobs=all_agents,
            mission_lookup=None,
        )

        assert "## YOUR DEPENDENCIES" in header, "Header must include YOUR DEPENDENCIES section"

        assert "You depend on:" in header and "analyzer" in header.lower(), (
            "Implementer should list analyzer as upstream"
        )

        assert "Others depend on you:" in header, "Implementer should have downstream dependencies"
        assert "tester" in header.lower(), "Implementer should list tester as downstream"
        assert "documenter" in header.lower(), "Implementer should list documenter as downstream"

    def test_coordination_section_mentions_messaging_tools(self):
        current_agent = create_mock_agent_execution(agent_display_name="analyzer")

        header = _generate_team_context_header(
            current_job=current_agent,
            all_project_jobs=[current_agent],
            mission_lookup=None,
        )

        assert "## COORDINATION" in header, "Header must include COORDINATION section"

        assert "post_to_thread" in header, "COORDINATION must reference post_to_thread tool"
        assert "get_thread_history" in header, "COORDINATION must reference get_thread_history tool"

        assert "notify teammates" in header.lower() or "status message" in header.lower(), (
            "COORDINATION must provide messaging guidance"
        )

        assert "full_protocol" in header, "COORDINATION must reference full_protocol for detailed instructions"

    def test_single_agent_project_still_gets_all_sections(self):
        solo_agent = create_mock_agent_execution(agent_display_name="implementer")

        header = _generate_team_context_header(
            current_job=solo_agent,
            all_project_jobs=[solo_agent],
            mission_lookup=None,
        )

        assert "## YOUR IDENTITY" in header, "Single-agent must have YOUR IDENTITY"
        assert "## YOUR TEAM" in header, "Single-agent must have YOUR TEAM"
        assert "## YOUR DEPENDENCIES" in header, "Single-agent must have YOUR DEPENDENCIES"
        assert "## COORDINATION" in header, "Single-agent must have COORDINATION"

        assert "1 agent(s)" in header, "YOUR TEAM should show '1 agent(s)'"

        assert "None" in header, "Single-agent should have None dependencies"

    def test_mission_lookup_dict_used_when_provided(self):
        job_id_1 = str(uuid4())
        job_id_2 = str(uuid4())

        agent_1 = create_mock_agent_execution(
            agent_display_name="analyzer",
            job_id=job_id_1,
            mission="Should not appear",
        )
        agent_2 = create_mock_agent_execution(
            agent_display_name="implementer",
            job_id=job_id_2,
            mission="Should not appear",
        )

        mission_lookup = {
            job_id_1: "Analyze architecture using mission_lookup dict",
            job_id_2: "Implement features using mission_lookup dict",
        }

        all_agents = [agent_1, agent_2]

        header = _generate_team_context_header(
            current_job=agent_1,
            all_project_jobs=all_agents,
            mission_lookup=mission_lookup,
        )

        assert "mission_lookup dict" in header, "Deliverables should use mission_lookup text when provided"

        assert "Should not appear" not in header, (
            "Deliverables should NOT use mission attribute when mission_lookup provided"
        )

    def test_multi_agent_team_roster_completeness(self):
        agents = [
            create_mock_agent_execution(agent_display_name="analyzer"),
            create_mock_agent_execution(agent_display_name="implementer"),
            create_mock_agent_execution(agent_display_name="tester"),
            create_mock_agent_execution(agent_display_name="reviewer"),
            create_mock_agent_execution(agent_display_name="documenter"),
        ]

        header = _generate_team_context_header(
            current_job=agents[0],
            all_project_jobs=agents,
            mission_lookup=None,
        )

        assert "5 agent(s)" in header, "YOUR TEAM must show '5 agent(s)'"

        assert "analyzer" in header.lower()
        assert "implementer" in header.lower()
        assert "tester" in header.lower()
        assert "reviewer" in header.lower()
        assert "documenter" in header.lower()

        for agent in agents:
            assert agent.agent_id in header, f"YOUR TEAM must include agent_id for {agent.agent_display_name}"

    def test_dependency_inference_tester_depends_on_implementer(self):
        implementer = create_mock_agent_execution(agent_display_name="implementer")
        tester = create_mock_agent_execution(agent_display_name="tester")

        all_agents = [implementer, tester]

        header = _generate_team_context_header(
            current_job=tester,
            all_project_jobs=all_agents,
            mission_lookup=None,
        )

        assert "You depend on:" in header and "implementer" in header.lower(), (
            "Tester should list implementer as upstream dependency"
        )

    def test_unknown_role_has_no_dependencies(self):
        custom_agent = create_mock_agent_execution(agent_display_name="custom-role")
        implementer = create_mock_agent_execution(agent_display_name="implementer")

        all_agents = [custom_agent, implementer]

        header = _generate_team_context_header(
            current_job=custom_agent,
            all_project_jobs=all_agents,
            mission_lookup=None,
        )

        assert "You depend on: None" in header, "Unknown roles should have no upstream dependencies"
        assert "Others depend on you: None" in header, "Unknown roles should have no downstream dependencies"
