# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import pytest

from tests.integration.test_be6081_mcp_boundary_contract import (
    _enable_git_integration,
    _parse_content_dict,
    memory_tool_client,  # noqa: F401 -- pytest fixture
)
from tests.integration.test_be9653_closeout_no_code_changes_mcp_boundary import (
    _author_args,
    _closeout_args,
    _seed_uuid_project,
)


pytestmark = pytest.mark.asyncio

_DOORS = ("write_project_closeout", "write_memory_entry")
_COMMIT = {"sha": "b" * 40, "message": "real work", "author": "dev"}


async def _call(client, session, tenant_key: str, tool: str, project_id: str, **extra) -> dict:
    author = await _author_args(tool, session, tenant_key, project_id)
    async with client() as mcp_session:
        result = await mcp_session.call_tool(tool, _closeout_args(project_id, **extra, **author))
    assert not result.is_error, f"{tool}: a git outcome is content, never isError"
    return _parse_content_dict(result)


@pytest.mark.parametrize("tool", _DOORS)
async def test_commits_are_accepted_without_warning(memory_tool_client, tool):  # noqa: F811
    client, tenant_key, session = memory_tool_client
    project = await _seed_uuid_project(session, tenant_key)
    await _enable_git_integration(session, tenant_key)

    body = await _call(client, session, tenant_key, tool, project.id, git_commits=[_COMMIT])

    assert body.get("success") is not False, body
    assert body.get("git_commits_count") == 1
    assert "git_warning" not in body


@pytest.mark.parametrize("tool", _DOORS)
async def test_declaration_is_accepted_without_warning(memory_tool_client, tool):  # noqa: F811
    client, tenant_key, session = memory_tool_client
    project = await _seed_uuid_project(session, tenant_key)
    await _enable_git_integration(session, tenant_key)

    body = await _call(client, session, tenant_key, tool, project.id, no_code_changes="Review only, nothing to commit.")

    assert body.get("success") is not False, body
    assert body.get("git_commits_count") == 0
    assert "git_warning" not in body


@pytest.mark.parametrize("tool", _DOORS)
async def test_explicit_empty_list_is_accepted_with_a_warning(memory_tool_client, tool):  # noqa: F811
    client, tenant_key, session = memory_tool_client
    project = await _seed_uuid_project(session, tenant_key)
    await _enable_git_integration(session, tenant_key)

    body = await _call(client, session, tenant_key, tool, project.id, git_commits=[])

    assert body.get("success") is not False, body
    assert body.get("git_commits_count") == 0
    assert body.get("git_warning"), f"{tool}: an empty list closes with a warning; got {body!r}"


@pytest.mark.parametrize("tool", _DOORS)
async def test_omitted_commits_are_refused_naming_three_ways_through(memory_tool_client, tool):  # noqa: F811
    client, tenant_key, session = memory_tool_client
    project = await _seed_uuid_project(session, tenant_key)
    await _enable_git_integration(session, tenant_key)

    body = await _call(client, session, tenant_key, tool, project.id)

    assert body.get("success") is False, f"{tool}: omitted git_commits must be refused; got {body!r}"
    assert body.get("error") == "GIT_COMMITS_REQUIRED", body
    message = body.get("message", "")
    assert "git_commits=[]" in message and "no_code_changes" in message and "git_commits" in message, message
