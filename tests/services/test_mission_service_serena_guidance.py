# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from giljo_mcp.models.agent_identity import AgentExecution, AgentJob
from giljo_mcp.schemas.service_responses import MissionResponse
from giljo_mcp.services.mission_service import MissionService


TENANT_KEY = "tenant-serena-test"


def _make_service() -> MissionService:
    return MissionService(db_manager=MagicMock(), tenant_manager=MagicMock())


def _make_job_and_execution(role: str) -> tuple[AgentJob, AgentExecution]:
    job_id = str(uuid4())
    job = AgentJob(
        job_id=job_id,
        tenant_key=TENANT_KEY,
        project_id=str(uuid4()),
        mission="Do the assigned work.",
        job_type=role,
        status="active",
    )
    execution = AgentExecution(
        agent_id=str(uuid4()),
        job_id=job_id,
        tenant_key=TENANT_KEY,
        agent_display_name=role,
        agent_name=f"{role}-1",
        status="waiting",
    )
    return job, execution


def _assemble(service: MissionService, job, execution, integrations):
    return service._assemble_mission_context(
        job=job,
        execution=execution,
        project=None,
        agent_identity=None,
        all_project_executions=[execution],
        mission_lookup={},
        current_team_state=None,
        tenant_key=TENANT_KEY,
        integrations=integrations,
    )


class TestMissionSerenaGuidance:
    def test_implementer_gets_implementer_block_when_toggle_on(self):
        service = _make_service()
        job, execution = _make_job_and_execution("implementer")

        response = _assemble(service, job, execution, integrations={"serena_mcp": {"use_in_prompts": True}})

        assert isinstance(response, MissionResponse)
        mission = response.mission or ""
        assert "Implementation Guidance" in mission
        assert "replace_symbol_body" in mission
        assert "SYMBOLIC EDITING" in mission
        assert "cover only the language(s) its LSP is configured for in this workspace" in mission

    def test_tester_gets_tester_block_when_toggle_on(self):
        service = _make_service()
        job, execution = _make_job_and_execution("tester")

        response = _assemble(service, job, execution, integrations={"serena_mcp": {"use_in_prompts": True}})

        mission = response.mission or ""
        assert "Testing Guidance" in mission
        assert "SYMBOLIC EDITING" not in mission

    def test_no_serena_guidance_when_toggle_off(self):
        service = _make_service()
        job, execution = _make_job_and_execution("implementer")

        response = _assemble(service, job, execution, integrations={"serena_mcp": {"use_in_prompts": False}})

        mission = response.mission or ""
        assert "Serena MCP" not in mission

    def test_unknown_role_falls_back_to_generic_block(self):
        service = _make_service()
        job, execution = _make_job_and_execution("agent")

        response = _assemble(service, job, execution, integrations={"serena_mcp": {"use_in_prompts": True}})

        mission = response.mission or ""
        assert "Serena MCP Available" in mission
        assert "SYMBOLIC EDITING" not in mission


@pytest.mark.parametrize(
    ("role", "marker"),
    [
        ("orchestrator", "STAGING DISCOVERY"),
        ("analyzer", "Analysis Guidance"),
        ("reviewer", "Code Review Guidance"),
        ("documenter", "Documentation Guidance"),
    ],
)
def test_each_role_gets_its_own_block(role, marker):
    service = _make_service()
    job, execution = _make_job_and_execution(role)

    response = _assemble(service, job, execution, integrations={"serena_mcp": {"use_in_prompts": True}})

    assert marker in (response.mission or "")
