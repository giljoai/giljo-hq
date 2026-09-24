# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import json
import random
from typing import Any
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import select

from api.endpoints.mcp_sdk_server import mcp
from giljo_mcp.models.organizations import Organization
from giljo_mcp.models.product_memory_entry import ProductMemoryEntry
from giljo_mcp.models.products import Product
from giljo_mcp.models.projects import Project
from giljo_mcp.tenant import TenantManager
from giljo_mcp.tools.tool_accessor import ToolAccessor
from tests.helpers.mcp_session_fixture import create_connected_server_and_client_session


_SENTRY_COMMIT = {
    "hash": "0d2916cd1",
    "message": "BE-9520: serialize the metrics flusher shutdown",
    "edition_scope": "SaaS",
}


def _content_text(result) -> str:
    parts = []
    for block in result.content or []:
        text = getattr(block, "text", None)
        if text:
            parts.append(text)
    return "\n".join(parts)


@pytest_asyncio.fixture
async def closeout_mcp_client(db_manager, db_session, monkeypatch):
    from api import app_state
    from api.endpoints.mcp_tools import _base
    from giljo_mcp.tools.project_closeout import close_project_and_update_memory

    state = app_state.state
    prior_tool_accessor = state.tool_accessor
    prior_tenant_manager = state.tenant_manager
    prior_db_manager = state.db_manager

    if state.tenant_manager is None:
        state.tenant_manager = TenantManager()
    state.db_manager = db_manager

    tenant_key = TenantManager.generate_tenant_key()
    accessor = ToolAccessor(db_manager=db_manager, tenant_manager=state.tenant_manager)

    async def _closeout_with_session(tenant_key: str, **kwargs: Any) -> dict[str, Any]:
        return await close_project_and_update_memory(
            tenant_key=tenant_key,
            db_manager=db_manager,
            session=db_session,
            **kwargs,
        )

    accessor.write_project_closeout = _closeout_with_session
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


async def _seed_project(db_session, tenant_key: str) -> Project:
    suffix = uuid4().hex[:8]
    org = Organization(
        name=f"BE9634 Org {suffix}",
        slug=f"be9634-{suffix}",
        tenant_key=tenant_key,
        is_active=True,
    )
    db_session.add(org)
    await db_session.flush()

    product = Product(
        id=str(uuid4()),
        name=f"BE9634 Product {suffix}",
        description="BE-9634 commit hash alias",
        tenant_key=tenant_key,
        is_active=True,
        product_memory={},
    )
    db_session.add(product)
    await db_session.flush()

    project = Project(
        id=str(uuid4()),
        tenant_key=tenant_key,
        product_id=product.id,
        name=f"BE9634 Project {suffix}",
        description="BE-9634",
        mission="Commit hash alias regression",
        status="active",
        series_number=random.randint(1, 9000),
    )
    db_session.add(project)
    await db_session.flush()
    return project


async def _stored_commits(db_session, tenant_key: str, project_id: str) -> list[dict[str, Any]]:
    result = await db_session.execute(
        select(ProductMemoryEntry).where(
            ProductMemoryEntry.tenant_key == tenant_key,
            ProductMemoryEntry.project_id == project_id,
        )
    )
    entry = result.scalars().first()
    assert entry is not None, "expected a 360 memory entry for the closed project"
    return list(entry.git_commits or [])




@pytest.mark.asyncio
async def test_closeout_accepts_hash_as_an_alias_for_sha(closeout_mcp_client):
    client, tenant_key, session = closeout_mcp_client
    project = await _seed_project(session, tenant_key)
    await session.commit()

    async with client() as mcp_session:
        result = await mcp_session.call_tool(
            "write_project_closeout",
            {
                "project_id": project.id,
                "summary": "Closed the lane with a commit dict that names the field hash.",
                "key_outcomes": ["The closeout landed"],
                "decisions_made": ["Accepted the aliased key rather than rejecting the call"],
                "git_commits": [dict(_SENTRY_COMMIT)],
                "force": True,
            },
        )

    text = _content_text(result)
    assert not result.is_error, f"the Sentry payload must close the project, got: {text!r}"
    parsed = json.loads(text)
    assert parsed.get("entry_id"), f"the 360 entry must be written, got: {parsed!r}"

    commits = await _stored_commits(session, tenant_key, project.id)
    assert len(commits) == 1, f"expected exactly one stored commit, got: {commits!r}"
    assert commits[0]["sha"] == _SENTRY_COMMIT["hash"], (
        f"the aliased value must be stored under the canonical 'sha' key, got: {commits[0]!r}"
    )
    assert "hash" not in commits[0], f"the alias must not leak into storage, got: {commits[0]!r}"




@pytest.mark.asyncio
async def test_commit_with_neither_sha_nor_hash_is_refused_with_the_structured_shape(closeout_mcp_client):
    client, tenant_key, session = closeout_mcp_client
    project = await _seed_project(session, tenant_key)
    await session.commit()

    async with client() as mcp_session:
        result = await mcp_session.call_tool(
            "write_project_closeout",
            {
                "project_id": project.id,
                "summary": "Closed the lane with a commit dict that has no identifier at all.",
                "key_outcomes": ["Should not land"],
                "decisions_made": ["None — the call is refused"],
                "git_commits": [{"message": "BE-9634: a commit with no sha and no hash"}],
                "force": True,
            },
        )

    text = _content_text(result)
    assert not result.is_error, (
        f"an agent-actionable shape rejection is Tier-2 structured content, not isError, got: {text!r}"
    )
    parsed = json.loads(text)
    assert parsed.get("success") is False, f"the rejection must report success=False, got: {parsed!r}"
    assert parsed.get("error") == "VALIDATION_ERROR", (
        f"shape rejections use the single VALIDATION_ERROR shape, got: {parsed!r}"
    )
    assert "git_commits" in str(parsed.get("field", "")), f"the rejection must name the field, got: {parsed!r}"
    assert parsed.get("constraint"), f"the rejection must name the constraint, got: {parsed!r}"

    message = str(parsed.get("message", ""))
    assert "sha" in message and "hash" in message, (
        f"the remedy must name both accepted keys in plain words, got: {message!r}"
    )
    for artefact in ("validation error for", "GitCommitEntry", "Field required", "input_value="):
        assert artefact not in text, f"raw pydantic text {artefact!r} must not reach the agent, got: {text!r}"

    await session.refresh(project)
    assert project.status == "active", f"a refused closeout must not close the project, got: {project.status!r}"




@pytest.mark.asyncio
async def test_well_formed_sha_closeout_is_unchanged(closeout_mcp_client):
    client, tenant_key, session = closeout_mcp_client
    project = await _seed_project(session, tenant_key)
    await session.commit()

    canonical = {
        "sha": "cf8dd14377ce4ebc5639c48f56ed17ff45e5c97c",
        "message": "BE-9634: accept hash as an alias for sha",
        "author": "GiljoAI",
    }

    async with client() as mcp_session:
        result = await mcp_session.call_tool(
            "write_project_closeout",
            {
                "project_id": project.id,
                "summary": "Closed the lane with a canonical commit dict.",
                "key_outcomes": ["Existing callers unaffected"],
                "decisions_made": ["Kept the canonical key as the storage key"],
                "git_commits": [dict(canonical)],
                "force": True,
            },
        )

    text = _content_text(result)
    assert not result.is_error, f"a canonical closeout must still succeed, got: {text!r}"

    commits = await _stored_commits(session, tenant_key, project.id)
    assert len(commits) == 1, f"expected exactly one stored commit, got: {commits!r}"
    for key, value in canonical.items():
        assert commits[0][key] == value, f"stored {key!r} changed: {commits[0]!r}"
