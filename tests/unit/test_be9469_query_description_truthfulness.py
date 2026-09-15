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


def _param_description(tool_name: str, param_name: str) -> str:
    tool = _tool_by_name(tool_name)
    properties = tool.parameters.get("properties", {}) if isinstance(tool.parameters, dict) else {}
    schema = properties.get(param_name)
    assert schema is not None, f"{tool_name} has no {param_name!r} parameter in its schema"
    description = schema.get("description", "")
    assert description, f"{tool_name}.{param_name} has no description at all"
    return description


def _tool_description(tool_name: str) -> str:
    tool = _tool_by_name(tool_name)
    description = getattr(tool, "description", "") or ""
    assert description, f"{tool_name} has no top-level description at all"
    return description


class TestListProjectsQueryDescriptionIsTruthful:

    def test_mentions_description(self):
        description = _param_description("list_projects", "query").lower()
        assert "description" in description, (
            "list_projects.query does not mention 'description' -- the search now reaches "
            f"project descriptions but the schema does not say so: {description!r}"
        )

    def test_mentions_project_alias_distinctly_from_taxonomy_alias(self):
        description = _param_description("list_projects", "query").lower()
        assert "project_alias" in description, (
            "list_projects.query does not mention 'project_alias' distinctly from "
            f"'taxonomy_alias' -- the search now reaches Project.alias too: {description!r}"
        )


class TestListTasksQueryDescriptionStaysTruthful:

    def test_still_mentions_description(self):
        description = _param_description("list_tasks", "query").lower()
        assert "description" in description


class TestSearchMemoryDescriptionIsTruthful:

    def test_mentions_git_commits(self):
        description = _tool_description("search_memory").lower()
        assert "git_commits" in description, (
            "search_memory's description does not mention 'git_commits' -- the search now "
            f"reaches closeout commit messages but the schema does not say so: {description!r}"
        )
