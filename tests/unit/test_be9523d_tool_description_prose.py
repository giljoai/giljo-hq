# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from api.endpoints.mcp_sdk_server import mcp


def _tool_by_name(name: str):
    for tool in mcp._tool_manager.list_tools():
        if tool.name == name:
            return tool
    raise AssertionError(f"tool {name!r} is not registered on the live mcp instance")


def _tool_description(tool_name: str) -> str:
    tool = _tool_by_name(tool_name)
    description = getattr(tool, "description", "") or ""
    assert description, f"{tool_name} has no top-level description at all"
    return description


def _param_description(tool_name: str, param_name: str) -> str:
    tool = _tool_by_name(tool_name)
    properties = tool.parameters.get("properties", {}) if isinstance(tool.parameters, dict) else {}
    schema = properties.get(param_name)
    assert schema is not None, f"{tool_name} has no {param_name!r} parameter in its schema"
    description = schema.get("description", "")
    assert description, f"{tool_name}.{param_name} has no description at all"
    return description


class TestCreateProjectStatesShippedAmbiguityRule:

    def test_mentions_product_ambiguous(self):
        description = _tool_description("create_project")
        assert "PRODUCT_AMBIGUOUS" in description

    def test_does_not_claim_unconditional_active_product_fallback(self):
        description = _tool_description("create_project")
        assert "single-product tenant" in description


class TestCreateTaskStatesShippedAmbiguityRule:
    def test_mentions_product_ambiguous(self):
        description = _tool_description("create_task")
        assert "PRODUCT_AMBIGUOUS" in description

    def test_product_id_param_mentions_product_ambiguous(self):
        description = _param_description("create_task", "product_id")
        assert "PRODUCT_AMBIGUOUS" in description


class TestLaunchImplementationDropsCliFraming:
    def test_does_not_frame_as_cli_only(self):
        description = _tool_description("launch_implementation")
        assert "from the CLI" not in description
        assert "headless/CLI operation" not in description

    def test_states_any_mcp_client_admission(self):
        description = _tool_description("launch_implementation")
        assert "any MCP client" in description or "any other connected" in description

    def test_states_tenant_toggle_gating(self):
        description = _tool_description("launch_implementation")
        assert "Headless setting" in description

    def test_states_launch_does_not_activate(self):
        description = _tool_description("launch_implementation")
        assert "does NOT activate" in description
        assert "project_active" in description


class TestStageAndImplementProjectDescribeBothDoors:
    def test_stage_project_names_launch_implementation_as_a_door(self):
        description = _tool_description("stage_project")
        assert "launch_implementation" in description

    def test_get_implementation_prompt_names_launch_implementation_as_a_door(self):
        description = _tool_description("get_implementation_prompt")
        assert "launch_implementation" in description


class TestLinkedRunsTellTheAgentAdvancementIsAutomatic:

    def test_link_projects_says_advancement_is_automatic(self):
        description = _tool_description("link_projects")
        assert "automatic" in description.lower(), (
            "link_projects must tell the agent the next project becomes ready on its own. "
            "Without it an agent drives the run by hand or waits for a signal that never comes."
        )

    def test_link_projects_names_the_field_that_shows_it(self):
        description = _tool_description("link_projects")
        assert "ready_to_advance" in description, (
            "Naming the field is the difference between 'it happens somehow' and a check "
            "the agent can actually make -- get_workflow_status carries it."
        )


class TestGiljoSetupStatesNotifyNeverAutoInstall:
    def test_mentions_skills_version(self):
        description = _tool_description("giljo_setup")
        assert "skills_version" in description

    def test_states_never_without_explicit_ask(self):
        description = _tool_description("giljo_setup")
        assert "NEVER" in description
