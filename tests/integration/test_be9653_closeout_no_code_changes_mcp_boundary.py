# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import select

from giljo_mcp.models.product_memory_entry import ProductMemoryEntry
from giljo_mcp.models.products import Product
from giljo_mcp.models.projects import Project
from tests.integration.test_be6081_mcp_boundary_contract import (
    _enable_git_integration,
    _parse_content_dict,
    _seed_orchestrator_job,
    _seed_product_and_project,
    memory_tool_client,  # noqa: F401 -- pytest fixture
)
from tests.integration.test_complete_job_mcp_boundary import (
    _payload,
    _seed_message_sender,
    _seed_staging_context,
    phase_mcp_client,  # noqa: F401 -- pytest fixture
)


pytestmark = pytest.mark.asyncio

_REASON = "Review-only project: findings filed as tasks, nothing to commit."


def _closeout_args(project_id: str, **extra) -> dict:
    return {
        "project_id": project_id,
        "key_outcomes": ["Reviewed the closeout path"],
        "decisions_made": ["No code change was needed"],
        "tags": ["chore", "backend"],
        **extra,
        "summary": "BE-9653 closeout boundary test.",
    }


async def _author_args(tool: str, session, tenant_key: str, project_id: str) -> dict:
    if tool != "write_memory_entry":
        return {}
    return {"author_job_id": await _seed_orchestrator_job(session, tenant_key, project_id)}


async def _seed_uuid_project(session, tenant_key: str):
    product, project = await _seed_product_and_project(session, tenant_key)
    uuid_product = Product(
        id=str(uuid4()),
        name=product.name + " (uuid)",
        description=product.description,
        tenant_key=tenant_key,
        is_active=False,
        product_memory={},
    )
    session.add(uuid_product)
    await session.flush()
    uuid_project = Project(
        id=str(uuid4()),
        tenant_key=tenant_key,
        product_id=uuid_product.id,
        name=project.name + " (uuid)",
        description="BE-9653",
        mission="Boundary test",
        status="active",
        staging_status="staging_complete",
        series_number=project.series_number + 1,
    )
    session.add(uuid_project)
    await session.flush()
    return uuid_project


async def _entry_for(session, tenant_key: str, project_id: str) -> ProductMemoryEntry:
    rows = (
        (
            await session.execute(
                select(ProductMemoryEntry).where(
                    ProductMemoryEntry.tenant_key == tenant_key,
                    ProductMemoryEntry.project_id == project_id,
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1, f"expected exactly one memory entry, got {len(rows)}"
    return rows[0]


async def test_no_commits_and_no_declaration_is_refused_naming_both_options(memory_tool_client):  # noqa: F811
    client, tenant_key, session = memory_tool_client
    _product, project = await _seed_product_and_project(session, tenant_key)
    await _enable_git_integration(session, tenant_key)

    async with client() as mcp_session:
        author = await _seed_orchestrator_job(session, tenant_key, project.id)
        result = await mcp_session.call_tool("write_memory_entry", _closeout_args(project.id, author_job_id=author))

    assert not result.is_error, "the refusal is agent-actionable content, not isError"
    body = _parse_content_dict(result)
    assert body.get("success") is False, body
    assert body.get("error") == "GIT_COMMITS_REQUIRED", body
    text = str(body)
    assert "git_commits" in text and "no_code_changes" in text, f"the refusal must name both ways through; got {body!r}"


async def test_write_project_closeout_without_either_is_refused_like_the_other_door(
    memory_tool_client,  # noqa: F811
):
    client, tenant_key, session = memory_tool_client
    _product, project = await _seed_product_and_project(session, tenant_key)
    await _enable_git_integration(session, tenant_key)

    async with client() as mcp_session:
        result = await mcp_session.call_tool("write_project_closeout", _closeout_args(project.id))

    body = _parse_content_dict(result)
    assert body.get("success") is False, body
    assert body.get("error") == "GIT_COMMITS_REQUIRED", body
    assert "no_code_changes" in body.get("message", ""), body


@pytest.mark.parametrize("tool", ["write_project_closeout", "write_memory_entry"])
async def test_no_code_changes_declaration_is_accepted_and_recorded(memory_tool_client, tool):  # noqa: F811
    client, tenant_key, session = memory_tool_client
    project = await _seed_uuid_project(session, tenant_key)
    await _enable_git_integration(session, tenant_key)

    async with client() as mcp_session:
        author = await _author_args(tool, session, tenant_key, project.id)
        result = await mcp_session.call_tool(tool, _closeout_args(project.id, no_code_changes=_REASON, **author))

    assert not result.is_error, result
    body = _parse_content_dict(result)
    assert body.get("success") is not False, body
    assert body.get("git_commits_count") == 0
    assert "git_warning" not in body, "a declared no-code closeout is not a missing-commits warning"

    entry = await _entry_for(session, tenant_key, project.id)
    assert entry.git_commits in (None, [])
    assert (entry.metrics or {}).get("no_code_changes") == _REASON


async def test_no_code_changes_over_the_cap_is_a_validation_error(memory_tool_client):  # noqa: F811
    client, tenant_key, session = memory_tool_client
    _product, project = await _seed_product_and_project(session, tenant_key)

    async with client() as mcp_session:
        result = await mcp_session.call_tool(
            "write_project_closeout", _closeout_args(project.id, no_code_changes="x" * 501)
        )

    text = " ".join(getattr(b, "text", "") or "" for b in result.content or [])
    assert "VALIDATION_ERROR" in text and "no_code_changes" in text, text


async def test_declaration_and_commits_together_is_refused(memory_tool_client):  # noqa: F811
    client, tenant_key, session = memory_tool_client
    _product, project = await _seed_product_and_project(session, tenant_key)

    commit = {"sha": "a" * 40, "message": "real work", "author": "dev"}
    async with client() as mcp_session:
        result = await mcp_session.call_tool(
            "write_project_closeout",
            _closeout_args(project.id, git_commits=[commit], no_code_changes=_REASON),
        )

    text = " ".join(getattr(b, "text", "") or "" for b in result.content or [])
    assert "no_code_changes" in text and "git_commits" in text, text
    rows = (
        (await session.execute(select(ProductMemoryEntry).where(ProductMemoryEntry.tenant_key == tenant_key)))
        .scalars()
        .all()
    )
    assert rows == [], "a contradictory closeout must not be written"


async def test_solo_staging_end_says_awaiting_launch_and_names_both_doors(phase_mcp_client):  # noqa: F811
    new_client, tenant_key, session = phase_mcp_client
    seed = await _seed_staging_context(session, tenant_key, project_phase="staging", staging_status="staging")
    await _seed_message_sender(session, tenant_key, seed["project"].id)

    async with new_client() as mcp_session:
        result = await mcp_session.call_tool(
            "complete_job",
            {"job_id": seed["job"].job_id, "result": {"summary": "BE-9653 staging done"}},
        )

    assert result.is_error is False, result
    payload = _payload(result)
    directive = payload["staging_directive"]
    assert directive["implementation_gate"] == "AWAITING_LAUNCH", directive
    assert directive["action"] == "STOP", "the staging pause is unchanged"

    for label, envelope in (("directive", directive["next_action"]), ("response", payload["next_action"])):
        assert envelope["tool"] == "launch_implementation", f"{label} next_action: {envelope!r}"
        why = envelope["why"]
        assert "Implement" in why and "go" in why.lower(), f"{label} must name both doors: {why!r}"

    message = directive["message"]
    assert "Implement" in message and "launch_implementation" in message, message


async def test_close_project_without_code_changes_is_the_one_writer(memory_tool_client):  # noqa: F811
    from giljo_mcp.exceptions import ValidationError
    from giljo_mcp.tools.closeout_without_code_changes import close_project_without_code_changes

    _client, tenant_key, session = memory_tool_client
    project = await _seed_uuid_project(session, tenant_key)
    await _enable_git_integration(session, tenant_key)
    from api import app_state

    with pytest.raises(ValidationError):
        await close_project_without_code_changes(
            project.id, "   ", tenant_key=tenant_key, db_manager=app_state.state.db_manager, session=session
        )

    response = await close_project_without_code_changes(
        project.id, _REASON, tenant_key=tenant_key, db_manager=app_state.state.db_manager, session=session
    )

    assert response.get("success") is not False, response
    assert "git_warning" not in response
    entry = await _entry_for(session, tenant_key, project.id)
    assert (entry.metrics or {}).get("no_code_changes") == _REASON
    assert entry.summary == f"Closed with no code changes: {_REASON}"
