# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import json
import random
from typing import Any
from unittest.mock import create_autospec
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy.exc import ProgrammingError

from api.endpoints.mcp_sdk_server import mcp
from api.endpoints.mcp_tools._base import _SANITIZED_TOOL_ERROR
from giljo_mcp.models.agent_identity import AgentJob
from giljo_mcp.models.organizations import Organization
from giljo_mcp.models.products import Product
from giljo_mcp.models.projects import Project
from giljo_mcp.models.settings import Settings
from giljo_mcp.tenant import TenantManager
from giljo_mcp.tools.tool_accessor import ToolAccessor
from tests.helpers.mcp_session_fixture import create_connected_server_and_client_session




def _content_text(result) -> str:
    parts = []
    for block in result.content or []:
        text = getattr(block, "text", None)
        if text:
            parts.append(text)
    return "\n".join(parts)


def _parse_content_dict(result) -> dict[str, Any]:
    text = _content_text(result)
    return json.loads(text)


_LEAK_MARKERS = ("[SQL:", "[parameters:", "Traceback", "INSERT INTO", "psycopg")


def _assert_no_leak(text: str) -> None:
    for marker in _LEAK_MARKERS:
        assert marker not in text, f"agent-facing error leaked {marker!r}: {text!r}"




@pytest_asyncio.fixture
async def memory_tool_client(db_manager, db_session, monkeypatch):
    from api import app_state
    from api.endpoints.mcp_tools import _base
    from giljo_mcp.tools.project_closeout import close_project_and_update_memory
    from giljo_mcp.tools.write_memory_entry import write_360_memory

    state = app_state.state
    prior_tool_accessor = state.tool_accessor
    prior_tenant_manager = state.tenant_manager
    prior_db_manager = state.db_manager

    if state.tenant_manager is None:
        state.tenant_manager = TenantManager()
    state.db_manager = db_manager

    tenant_key = TenantManager.generate_tenant_key()
    accessor = ToolAccessor(db_manager=db_manager, tenant_manager=state.tenant_manager)

    async def _write_memory_entry_with_session(
        tenant_key: str,
        **kwargs: Any,
    ) -> dict[str, Any]:
        return await write_360_memory(
            tenant_key=tenant_key,
            session=db_session,
            db_manager=db_manager,
            **kwargs,
        )

    accessor.write_memory_entry = _write_memory_entry_with_session

    async def _write_project_closeout_with_session(
        tenant_key: str,
        **kwargs: Any,
    ) -> dict[str, Any]:
        return await close_project_and_update_memory(
            tenant_key=tenant_key,
            session=db_session,
            db_manager=db_manager,
            **kwargs,
        )

    accessor.write_project_closeout = _write_project_closeout_with_session
    state.tool_accessor = accessor

    monkeypatch.setattr(_base, "_resolve_tenant", lambda ctx: tenant_key)
    monkeypatch.setattr(_base, "_resolve_user_id", lambda ctx: None)

    def _client():
        return create_connected_server_and_client_session(mcp)

    try:
        yield _client, tenant_key, db_session
    finally:
        state.tool_accessor = prior_tool_accessor
        state.tenant_manager = prior_tenant_manager
        state.db_manager = prior_db_manager




async def _seed_product_and_project(db_session, tenant_key: str):
    suffix = TenantManager.generate_tenant_key()[:8]

    org = Organization(
        name=f"BE6081 Org {suffix}",
        slug=f"be6081-{suffix}",
        tenant_key=tenant_key,
        is_active=True,
    )
    db_session.add(org)
    await db_session.flush()

    product = Product(
        id=f"be6081-prod-{suffix}",
        name=f"BE6081 Product {suffix}",
        description="BE-6081 boundary contract test",
        tenant_key=tenant_key,
        is_active=True,
        product_memory={},
    )
    db_session.add(product)
    await db_session.flush()

    project = Project(
        id=f"be6081-proj-{suffix}",
        tenant_key=tenant_key,
        product_id=product.id,
        name=f"BE6081 Project {suffix}",
        description="BE-6081",
        mission="Contract test",
        status="active",
        staging_status="staging_complete",
        series_number=random.randint(1, 9000),
    )
    db_session.add(project)
    await db_session.flush()

    return product, project


async def _enable_git_integration(db_session, tenant_key: str) -> None:
    settings = Settings(
        tenant_key=tenant_key,
        category="integrations",
        settings_data={"git_integration": {"enabled": True}},
    )
    db_session.add(settings)
    await db_session.commit()


async def _seed_orchestrator_job(db_session, tenant_key: str, project_id: str) -> str:
    job = AgentJob(
        job_id=str(uuid4()),
        project_id=project_id,
        mission="orchestrator",
        job_type="orchestrator",
        status="active",
        tenant_key=tenant_key,
    )
    db_session.add(job)
    await db_session.flush()
    return job.job_id




@pytest.mark.asyncio
async def test_tier2_git_commits_required_is_content_not_error(memory_tool_client):
    client, tenant_key, session = memory_tool_client

    _product, project = await _seed_product_and_project(session, tenant_key)
    await _enable_git_integration(session, tenant_key)

    async with client() as mcp_session:
        result = await mcp_session.call_tool(
            "write_memory_entry",
            {
                "project_id": project.id,
                "summary": "Completed the integration work",
                "key_outcomes": ["Gate verified end-to-end"],
                "decisions_made": ["Boundary contract is two-tier"],
                "entry_type": "project_completion",
                "author_job_id": await _seed_orchestrator_job(session, tenant_key, project.id),
            },
        )

    assert not result.is_error, (
        "GIT_COMMITS_REQUIRED must be returned as normal content (Tier 2), "
        f"not raised as isError. content: {_content_text(result)!r}"
    )

    parsed = _parse_content_dict(result)
    assert parsed.get("success") is False, f"Expected success==False in the rejection dict, got: {parsed!r}"
    assert parsed.get("error") == "GIT_COMMITS_REQUIRED", f"Expected error=='GIT_COMMITS_REQUIRED', got: {parsed!r}"


async def _seed_org_product_project(session, tenant_key: str, label: str):
    import uuid

    suffix = TenantManager.generate_tenant_key()[:8]
    org = Organization(
        name=f"{label} Org {suffix}", slug=f"{label.lower()}-{suffix}", tenant_key=tenant_key, is_active=True
    )
    session.add(org)
    await session.flush()
    product = Product(
        id=str(uuid.uuid4()),
        name=f"{label} Product {suffix}",
        description=f"{label} boundary test",
        tenant_key=tenant_key,
        is_active=True,
        product_memory={},
    )
    session.add(product)
    await session.flush()
    project = Project(
        id=str(uuid.uuid4()),
        tenant_key=tenant_key,
        product_id=product.id,
        name=f"{label} Project {suffix}",
        description=label,
        mission="Boundary test",
        status="active",
        staging_status="staging_complete",
        series_number=random.randint(1, 9000),
    )
    session.add(project)
    await session.flush()
    return product, project


@pytest.mark.asyncio
async def test_bare_sha_git_commits_rejected_at_boundary(memory_tool_client):
    client, tenant_key, session = memory_tool_client
    _product, project = await _seed_org_product_project(session, tenant_key, "BE9256BareSha")
    await _enable_git_integration(session, tenant_key)

    async with client() as mcp_session:
        result = await mcp_session.call_tool(
            "write_memory_entry",
            {
                "project_id": project.id,
                "summary": "Completed the integration work",
                "key_outcomes": ["Bare-SHA git_commits rejected at the boundary"],
                "decisions_made": ["Boundary type stays list[dict | str]; service fails closed"],
                "entry_type": "project_completion",
                "author_job_id": await _seed_orchestrator_job(session, tenant_key, project.id),
                "git_commits": ["6c59b7e", "a775e8e4"],
            },
        )

    wire_text = _content_text(result)
    assert "valid dictionary" not in wire_text and "dict_type" not in wire_text, (
        f"bare-SHA git_commits was rejected by Pydantic at the @mcp.tool boundary "
        f"(BE-6208a boundary-type widening regressed): {wire_text!r}"
    )
    assert not result.is_error, f"GIT_COMMIT_TITLE_REQUIRED must be Tier 2 (normal content), not isError: {wire_text!r}"

    parsed = _parse_content_dict(result)
    assert parsed.get("success") is False, f"expected success==False, got: {parsed!r}"
    assert parsed.get("error") == "GIT_COMMIT_TITLE_REQUIRED", f"expected GIT_COMMIT_TITLE_REQUIRED, got: {parsed!r}"
    assert "git log --format=" in parsed.get("hint", ""), f"hint must carry the exact git command: {parsed!r}"


@pytest.mark.asyncio
async def test_titled_git_commits_accepted_at_boundary(memory_tool_client):
    client, tenant_key, session = memory_tool_client
    _product, project = await _seed_org_product_project(session, tenant_key, "BE9256Titled")
    await _enable_git_integration(session, tenant_key)

    async with client() as mcp_session:
        result = await mcp_session.call_tool(
            "write_memory_entry",
            {
                "project_id": project.id,
                "summary": "Completed the integration work",
                "key_outcomes": ["Titled git_commits accepted at the boundary"],
                "decisions_made": ["Titled dict shape is the primary contract"],
                "entry_type": "project_completion",
                "author_job_id": await _seed_orchestrator_job(session, tenant_key, project.id),
                "git_commits": [{"sha": "6c59b7e", "message": "Fix the widget", "author": "Alice"}],
            },
        )

    assert not result.is_error, f"titled closeout must not error at the boundary: {_content_text(result)!r}"
    parsed = _parse_content_dict(result)
    assert parsed.get("entry_id"), f"titled closeout should write an entry, got: {parsed!r}"
    assert parsed.get("git_commits_count") == 1, f"got: {parsed!r}"


@pytest.mark.asyncio
async def test_porcelain_git_commits_accepted_at_boundary(memory_tool_client):
    client, tenant_key, session = memory_tool_client
    _product, project = await _seed_org_product_project(session, tenant_key, "porcelain-titled-commit")
    await _enable_git_integration(session, tenant_key)

    async with client() as mcp_session:
        result = await mcp_session.call_tool(
            "write_memory_entry",
            {
                "project_id": project.id,
                "summary": "Completed the integration work",
                "key_outcomes": ["Porcelain git_commits accepted at the boundary"],
                "decisions_made": ["Porcelain string is parsed server-side"],
                "entry_type": "project_completion",
                "author_job_id": await _seed_orchestrator_job(session, tenant_key, project.id),
                "git_commits": ["6c59b7e\tFix the widget\tAlice"],
            },
        )

    assert not result.is_error, f"porcelain closeout must not error at the boundary: {_content_text(result)!r}"
    parsed = _parse_content_dict(result)
    assert parsed.get("entry_id"), f"porcelain closeout should write an entry, got: {parsed!r}"
    assert parsed.get("git_commits_count") == 1, f"got: {parsed!r}"


@pytest.mark.asyncio
async def test_bare_sha_git_commits_rejected_at_closeout_boundary(memory_tool_client):
    client, tenant_key, session = memory_tool_client
    _product, project = await _seed_org_product_project(session, tenant_key, "closeout-bare-sha")

    async with client() as mcp_session:
        result = await mcp_session.call_tool(
            "write_project_closeout",
            {
                "project_id": project.id,
                "summary": "Completed the integration work",
                "key_outcomes": ["Bare-SHA git_commits rejected at the closeout boundary"],
                "decisions_made": ["write_project_closeout mirrors write_memory_entry's Tier-2 gate"],
                "git_commits": ["6c59b7e", "a775e8e4"],
            },
        )

    wire_text = _content_text(result)
    assert not result.is_error, f"GIT_COMMIT_TITLE_REQUIRED must be Tier 2 (normal content), not isError: {wire_text!r}"

    parsed = _parse_content_dict(result)
    assert parsed.get("success") is False, f"expected success==False, got: {parsed!r}"
    assert parsed.get("error") == "GIT_COMMIT_TITLE_REQUIRED", f"expected GIT_COMMIT_TITLE_REQUIRED, got: {parsed!r}"
    assert "git log --format=" in parsed.get("hint", ""), f"hint must carry the exact git command: {parsed!r}"


@pytest.mark.asyncio
async def test_titled_git_commits_accepted_at_closeout_boundary(memory_tool_client):
    client, tenant_key, session = memory_tool_client
    _product, project = await _seed_org_product_project(session, tenant_key, "BE9256CloseoutTitled")

    async with client() as mcp_session:
        result = await mcp_session.call_tool(
            "write_project_closeout",
            {
                "project_id": project.id,
                "summary": "Completed the integration work",
                "key_outcomes": ["Titled git_commits accepted at the closeout boundary"],
                "decisions_made": ["Titled dict shape is the primary contract"],
                "git_commits": [{"sha": "6c59b7e", "message": "Fix the widget", "author": "Alice"}],
            },
        )

    assert not result.is_error, f"titled closeout must not error at the boundary: {_content_text(result)!r}"
    parsed = _parse_content_dict(result)
    assert parsed.get("entry_id"), f"titled closeout should write an entry, got: {parsed!r}"
    assert parsed.get("git_commits_count") == 1, f"got: {parsed!r}"




@pytest.mark.asyncio
async def test_tier1_planted_accessor_error_is_sanitized_iserror(db_manager, db_session, monkeypatch):
    import inspect

    from api import app_state
    from api.endpoints.mcp_tools import _base

    state = app_state.state
    prior_tool_accessor = state.tool_accessor
    prior_tenant_manager = state.tenant_manager
    prior_db_manager = state.db_manager

    accessor = create_autospec(ToolAccessor, instance=True)
    for attr_name in dir(ToolAccessor):
        if attr_name.startswith("_"):
            continue
        if inspect.iscoroutinefunction(getattr(ToolAccessor, attr_name, None)):
            getattr(accessor, attr_name).return_value = {"ok": True}

    leaky_error = ProgrammingError(
        statement="INSERT INTO product_memory_entries (id) VALUES (%(id)s)",
        params={"id": "secret-bind-value"},
        orig=Exception("relation does not exist"),
    )
    accessor.write_memory_entry.side_effect = leaky_error

    state.tool_accessor = accessor
    if state.tenant_manager is None:
        state.tenant_manager = TenantManager()
    state.db_manager = None

    tenant_key = TenantManager.generate_tenant_key()
    monkeypatch.setattr(_base, "_resolve_tenant", lambda ctx: tenant_key)
    monkeypatch.setattr(_base, "_resolve_user_id", lambda ctx: None)

    def _client():
        return create_connected_server_and_client_session(mcp)

    try:
        async with _client() as mcp_session:
            result = await mcp_session.call_tool(
                "write_memory_entry",
                {
                    "project_id": "00000000-0000-0000-0000-000000000001",
                    "summary": "Tier-1 planted error test",
                    "key_outcomes": ["verify sanitization"],
                    "decisions_made": ["isError contract"],
                    "entry_type": "project_completion",
                },
            )
    finally:
        state.tool_accessor = prior_tool_accessor
        state.tenant_manager = prior_tenant_manager
        state.db_manager = prior_db_manager

    assert result.is_error is True, (
        f"A planted unexpected DB error must produce isError=True. Got: {_content_text(result)!r}"
    )

    text = _content_text(result)
    _assert_no_leak(text)
    assert "internal error" in text.lower() or _SANITIZED_TOOL_ERROR[:40] in text, (
        f"Expected sanitized error message, got: {text!r}"
    )
