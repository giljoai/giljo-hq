# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-9469 item 3, deliverables 2+3 -- tool schema descriptions must truthfully
name every field the tool actually searches.

The tool schema is read by every agent before it ever calls the tool; a
description that omits half the searched fields is the dishonest-signal class
this whole family of work exists to remove.

RED before the fix: ``list_projects``' registered ``query`` parameter description
says only "project name, id and taxonomy_alias" -- it does not mention
``description`` or ``project_alias`` even after the repository-layer fix widens
the actual search to include them. Likewise ``search_memory``'s top-level
description named summary/key_outcomes/decisions_made/project_name/tags but not
``git_commits``, before deliverable 3's fix widened the match set to include it
(constraint 3 on that ruling: the docstring must say so once it does).

Schema-level pin (same technique as ``test_be9464_summary_ordering_clause.py``):
inspects the registered tool surface directly via the live ``mcp`` instance,
rather than driving a call -- there is no detector/rejection path here, only the
advertised description text every connected client sees.

Edition Scope: Both.
"""

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
    """THE DEFECT (deliverable 2). list_projects.query must name every field the
    (fixed) search OR-clause actually reaches: name, id, taxonomy_alias,
    description, project_alias."""

    def test_mentions_description(self):
        description = _param_description("list_projects", "query").lower()
        assert "description" in description, (
            "list_projects.query does not mention 'description' -- the search now reaches "
            f"project descriptions but the schema does not say so: {description!r}"
        )

    def test_mentions_project_alias_distinctly_from_taxonomy_alias(self):
        """Must name 'project_alias' (Project.alias, the 6-char code) as a DISTINCT
        field from 'taxonomy_alias' (the computed 'BE-1042' style alias already
        searched) -- a bare 'alias' substring check would false-pass on
        'taxonomy_alias' alone and hide this half of the defect."""
        description = _param_description("list_projects", "query").lower()
        assert "project_alias" in description, (
            "list_projects.query does not mention 'project_alias' distinctly from "
            f"'taxonomy_alias' -- the search now reaches Project.alias too: {description!r}"
        )


class TestListTasksQueryDescriptionStaysTruthful:
    """CONTROL: list_tasks.query was already accurate (title, description,
    taxonomy_alias match the real search fields) -- this lane must not regress it."""

    def test_still_mentions_description(self):
        description = _param_description("list_tasks", "query").lower()
        assert "description" in description


class TestSearchMemoryDescriptionIsTruthful:
    """Deliverable 3, constraint 3: search_memory's own docstring must say
    commits are searchable once the fix lands -- the tool's description is
    read by every agent deciding whether to bother searching."""

    def test_mentions_git_commits(self):
        description = _tool_description("search_memory").lower()
        assert "git_commits" in description, (
            "search_memory's description does not mention 'git_commits' -- the search now "
            f"reaches closeout commit messages but the schema does not say so: {description!r}"
        )
