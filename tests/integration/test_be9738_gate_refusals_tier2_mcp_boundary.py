# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import json
from typing import Any
from unittest.mock import create_autospec

import pytest
from sqlalchemy import select
from sqlalchemy.exc import ProgrammingError

from api.endpoints.mcp_sdk_server import mcp
from api.endpoints.mcp_tools._base import _SANITIZED_TOOL_ERROR
from giljo_mcp.models.agent_identity import AgentJob
from giljo_mcp.tenant import TenantManager
from giljo_mcp.tools.tool_accessor import ToolAccessor
from tests.helpers.mcp_session_fixture import create_connected_server_and_client_session
from tests.integration.test_be6081_mcp_boundary_contract import (
    _enable_git_integration,
    _seed_org_product_project,
    memory_tool_client,  # noqa: F401 -- pytest fixture
)
from tests.integration.test_be9292b_silent_job_terminal_states_mcp_boundary import (
    _seed_org_product,
    _seed_project,
    _seed_specialist,
    _seed_todo,
    terminal_state_mcp_client,  # noqa: F401 -- pytest fixture
)
from tests.integration.test_be9325_spawn_boundary_trashed_template import (
    _seed_project_and_trashed_template,
    spawn_boundary_client,  # noqa: F401 -- pytest fixture
)


pytestmark = pytest.mark.asyncio


def _text(result) -> str:
    return "\n".join(getattr(b, "text", "") or "" for b in result.content or [])


def _refusal(result) -> dict[str, Any]:
    assert not result.is_error, f"a deliberate refusal must not be isError; wire text: {_text(result)!r}"
    payload = result.structured_content or json.loads(_text(result))
    assert payload.get("success") is False, f"a refusal must say success=False: {payload!r}"
    return payload




async def test_complete_job_open_todo_is_tier2_completion_blocked(terminal_state_mcp_client):  # noqa: F811
    client, tenant_key, db_session = terminal_state_mcp_client
    _org, product = await _seed_org_product(db_session, tenant_key)
    project = await _seed_project(db_session, tenant_key, product.id)
    job, _execution = await _seed_specialist(db_session, tenant_key, project.id, status="working")
    await _seed_todo(db_session, tenant_key, job.job_id, "Write the regression test")

    async with client() as session:
        result = await session.call_tool("complete_job", {"job_id": job.job_id, "result": {"summary": "done"}})

    payload = _refusal(result)
    assert payload["error"] == "COMPLETION_BLOCKED", payload
    assert payload["job_id"] == job.job_id, payload
    assert payload["incomplete_todos"] == 1, payload
    assert any("Write the regression test" in r for r in payload["reasons"]), payload
    assert payload["next_action"]["tool"] == "report_progress", payload
    assert tenant_key not in json.dumps(payload), "the refusal must not echo the tenant key"




async def test_write_project_closeout_open_agent_is_tier2_closeout_blocked(memory_tool_client):  # noqa: F811
    client, tenant_key, db_session = memory_tool_client
    _product, project = await _seed_org_product_project(db_session, tenant_key, "BE9738Blocked")
    await _seed_specialist(db_session, tenant_key, project.id, status="working")

    async with client() as session:
        result = await session.call_tool(
            "write_project_closeout",
            {"project_id": project.id, "summary": "s", "key_outcomes": ["k"], "decisions_made": ["d"]},
        )

    assert _refusal(result)["error"] == "CLOSEOUT_BLOCKED"


async def test_write_project_closeout_missing_commits_is_tier2_git_commits_required(memory_tool_client):  # noqa: F811
    client, tenant_key, db_session = memory_tool_client
    _product, project = await _seed_org_product_project(db_session, tenant_key, "BE9738Git")
    await _enable_git_integration(db_session, tenant_key)

    async with client() as session:
        result = await session.call_tool(
            "write_project_closeout",
            {"project_id": project.id, "summary": "s", "key_outcomes": ["k"], "decisions_made": ["d"]},
        )

    assert _refusal(result)["error"] == "GIT_COMMITS_REQUIRED"


async def test_write_project_closeout_over_cap_decision_is_tier2_validation_error(memory_tool_client):  # noqa: F811
    client, tenant_key, db_session = memory_tool_client
    _product, project = await _seed_org_product_project(db_session, tenant_key, "BE9738Cap")

    async with client() as session:
        result = await session.call_tool(
            "write_project_closeout",
            {
                "project_id": project.id,
                "summary": "s",
                "key_outcomes": ["k"],
                "decisions_made": ["x" * 300],
            },
        )

    payload = _refusal(result)
    assert payload["error"] == "VALIDATION_ERROR", payload
    assert payload["field"] == "decisions_made", payload
    assert payload["constraint"] == "too_long", payload
    assert "max=250" in payload["message"], "the message must still name the cap"


async def test_write_project_closeout_unknown_tag_names_the_vocabulary(memory_tool_client):  # noqa: F811
    client, tenant_key, db_session = memory_tool_client
    _product, project = await _seed_org_product_project(db_session, tenant_key, "BE9738Tag")

    async with client() as session:
        result = await session.call_tool(
            "write_project_closeout",
            {
                "project_id": project.id,
                "summary": "s",
                "key_outcomes": ["k"],
                "decisions_made": ["d"],
                "tags": ["not-a-tag"],
            },
        )

    payload = _refusal(result)
    assert payload["field"] == "tags", payload
    assert payload["constraint"] == "invalid_choice", payload
    assert "bug-fix" in payload["message"], "the allowed vocabulary must still reach the agent"



_TRASHED_TEMPLATE = "be9738-trashed"


def _spawn_args(project_id: str, **extra) -> dict[str, Any]:
    return {
        "agent_display_name": "implementer",
        "agent_name": "nobody-by-this-name",
        "project_id": project_id,
        "mission": "Do the work.",
        **extra,
    }


async def test_spawn_job_unknown_agent_name_is_tier2(spawn_boundary_client):  # noqa: F811
    new_client, tenant_key, db_session = spawn_boundary_client
    project_id = await _seed_project_and_trashed_template(db_session, tenant_key, _TRASHED_TEMPLATE)

    async with new_client() as session:
        result = await session.call_tool("spawn_job", _spawn_args(project_id))

    payload = _refusal(result)
    assert payload["error"] == "INVALID_AGENT_NAME", payload
    assert payload["agent_name"] == "nobody-by-this-name", payload
    assert payload["valid_names"] == [], payload
    assert tenant_key not in json.dumps(payload), "the refusal must not echo the tenant key"
    jobs = await db_session.execute(select(AgentJob).where(AgentJob.tenant_key == tenant_key))
    assert jobs.scalars().all() == [], "a refused spawn writes nothing"


async def test_spawn_job_later_phase_without_predecessor_is_tier2_validation_error(spawn_boundary_client):  # noqa: F811
    new_client, tenant_key, db_session = spawn_boundary_client
    project_id = await _seed_project_and_trashed_template(db_session, tenant_key, _TRASHED_TEMPLATE)

    async with new_client() as session:
        result = await session.call_tool("spawn_job", _spawn_args(project_id, phase=2))

    payload = _refusal(result)
    assert payload["error"] == "VALIDATION_ERROR", payload
    assert payload["field"] == "predecessor_job_id", payload


async def test_spawn_job_without_execution_mode_is_tier2(spawn_boundary_client):  # noqa: F811
    new_client, tenant_key, db_session = spawn_boundary_client
    project_id = await _seed_project_and_trashed_template(db_session, tenant_key, _TRASHED_TEMPLATE)
    from giljo_mcp.models import Project

    project = await db_session.get(Project, project_id)
    project.execution_mode = None
    await db_session.flush()

    async with new_client() as session:
        result = await session.call_tool("spawn_job", _spawn_args(project_id))

    assert _refusal(result)["error"] == "EXECUTION_MODE_NOT_SELECTED"




@pytest.mark.parametrize(
    ("tool", "args"),
    [
        ("complete_job", {"job_id": "job-1", "result": {"summary": "s"}}),
        ("spawn_job", {"agent_display_name": "a", "agent_name": "b", "project_id": "p"}),
        (
            "write_project_closeout",
            {"project_id": "p", "summary": "s", "key_outcomes": ["k"], "decisions_made": ["d"]},
        ),
    ],
)
async def test_server_side_fault_stays_iserror_and_sanitized(monkeypatch, tool, args):
    from api import app_state
    from api.endpoints.mcp_tools import _base

    leaky = ProgrammingError(
        statement="INSERT INTO agent_jobs (id) VALUES (%(id)s)",
        params={"id": "secret-bind-value"},
        orig=Exception("relation does not exist"),
    )

    async def _boom(**_kwargs):
        raise leaky

    accessor = create_autospec(ToolAccessor, instance=True)
    accessor.write_project_closeout.side_effect = leaky
    if tool in _base.TOOL_DISPATCH:
        monkeypatch.setitem(_base.TOOL_DISPATCH, tool, lambda acc: _boom)
    state = app_state.state
    monkeypatch.setattr(state, "tool_accessor", accessor)
    monkeypatch.setattr(state, "tenant_manager", state.tenant_manager or TenantManager())
    monkeypatch.setattr(state, "db_manager", None)
    monkeypatch.setattr(_base, "_resolve_tenant", lambda ctx: TenantManager.generate_tenant_key())
    monkeypatch.setattr(_base, "_resolve_user_id", lambda ctx: None)

    async with create_connected_server_and_client_session(mcp) as session:
        result = await session.call_tool(tool, args)

    assert result.is_error is True, f"a server-side fault must stay isError: {_text(result)!r}"
    text = _text(result)
    assert "[SQL:" not in text and "secret-bind-value" not in text, text
    assert _SANITIZED_TOOL_ERROR[:40] in text, text
