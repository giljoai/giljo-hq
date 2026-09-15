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
from sqlalchemy import func, select

from api.endpoints.mcp_sdk_server import mcp
from giljo_mcp.models.organizations import Organization
from giljo_mcp.models.product_memory_entry import ProductMemoryEntry
from giljo_mcp.models.products import Product
from giljo_mcp.models.projects import Project
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



_ABSORBED_TAIL_MARKUP = (
    "Swept 27 SaaS test modules for under-specified AsyncMock session doubles and re-armed "
    "the un-awaited-coroutine guard. Zero production code changed." + ("Padding prose. " * 90) + "</summary>\n"
    '<key_outcomes>["SaaS-mode never-awaited count reached 0", "The guard is live again"]</key_outcomes>\n'
    '<decisions_made>["Fixed the doubles, not the assertion"]</decisions_made>\n'
    '<tags>["test", "backend", "chore"]</tags>\n'
    "</invoke>\n"
)

_ABSORBED_TAIL_JSON = (
    "The changelog gate matched only a line that was exactly the bare marker, while the form "
    "written throughout the repo carries the reason on the same line. " + ("Padding prose. " * 60) + "The "
    'regression test reproduces the exact shape of the failing PR.", "That test asserts the fragment '
    'directory never existed, so it cannot pass for the wrong reason.", "Merged green on its own head."]'
)


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
        name=f"TSK9309 Org {suffix}",
        slug=f"tsk9309-{suffix}",
        tenant_key=tenant_key,
        is_active=True,
    )
    db_session.add(org)
    await db_session.flush()

    product = Product(
        id=str(uuid4()),
        name=f"TSK9309 Product {suffix}",
        description="TSK-9309 argument absorption",
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
        name=f"TSK9309 Project {suffix}",
        description="TSK-9309",
        mission="Argument absorption regression",
        status="active",
        series_number=random.randint(1, 9000),
    )
    db_session.add(project)
    await db_session.flush()
    return project


async def _memory_entry_count(db_session, tenant_key: str) -> int:
    result = await db_session.execute(
        select(func.count()).select_from(ProductMemoryEntry).where(ProductMemoryEntry.tenant_key == tenant_key)
    )
    return int(result.scalar_one())




@pytest.mark.parametrize(
    ("label", "absorbing_summary", "extra_args", "conclusive"),
    [
        ("markup-tail", _ABSORBED_TAIL_MARKUP, {}, True),
        (
            "json-array-tail",
            _ABSORBED_TAIL_JSON,
            {
                "decisions_made": ["Chose prefix-match over the bare-line requirement"],
                "tags": ["infrastructure", "chore"],
                "git_commits": [{"sha": "cf8dd14377ce4ebc5639c48f56ed17ff45e5c97c", "message": "INF-9301: accept"}],
            },
            False,
        ),
    ],
    ids=["markup-tail", "json-array-tail"],
)
@pytest.mark.asyncio
async def test_absorbed_argument_rejection_names_the_real_cause(
    closeout_mcp_client, label, absorbing_summary, extra_args, conclusive
):
    client, tenant_key, session = closeout_mcp_client
    project = await _seed_project(session, tenant_key)
    await session.commit()

    args: dict[str, Any] = {"project_id": project.id, "summary": absorbing_summary, **extra_args}

    async with client() as mcp_session:
        result = await mcp_session.call_tool("write_project_closeout", args)

    text = _content_text(result)
    assert result.is_error, f"[{label}] an absorbed-argument call must still be rejected, got: {text!r}"

    lowered = text.lower()
    assert "summary" in lowered, (
        f"[{label}] the rejection must name the argument that absorbed the field (summary); got: {text!r}"
    )
    assert str(len(absorbing_summary)) in text, (
        f"[{label}] the rejection must name the offending size ({len(absorbing_summary)} chars); got: {text!r}"
    )
    assert "key_outcomes" in text, f"[{label}] the rejection must still name the field that never arrived: {text!r}"
    assert any(word in lowered for word in ("absorb", "merged into", "did not arrive")), (
        f"[{label}] the rejection must state the field was absorbed into another argument, not merely missing; "
        f"got: {text!r}"
    )

    if conclusive:
        assert "may have been absorbed" not in lowered, (
            f"[{label}] tool-call markup is conclusive evidence — the message must assert the "
            f"absorption, not hedge it; got: {text!r}"
        )
    else:
        assert "may have been absorbed" in lowered, (
            f"[{label}] a JSON-list tail is the weakest signal and can occur in legitimate prose — "
            f"the message must state a possibility, not a certainty; got: {text!r}"
        )




@pytest.mark.asyncio
async def test_absorbed_argument_rejection_writes_nothing(closeout_mcp_client):
    client, tenant_key, session = closeout_mcp_client
    project = await _seed_project(session, tenant_key)
    await session.commit()

    before = await _memory_entry_count(session, tenant_key)

    async with client() as mcp_session:
        result = await mcp_session.call_tool(
            "write_project_closeout",
            {"project_id": project.id, "summary": _ABSORBED_TAIL_MARKUP},
        )

    assert result.is_error, f"expected rejection, got: {_content_text(result)!r}"

    after = await _memory_entry_count(session, tenant_key)
    assert after == before, f"a rejected closeout must write no 360 entry (before={before}, after={after})"

    await session.refresh(project)
    assert project.status == "active", f"a rejected closeout must not close the project, got: {project.status!r}"




@pytest.mark.asyncio
async def test_well_formed_closeout_still_succeeds(closeout_mcp_client):
    client, tenant_key, session = closeout_mcp_client
    project = await _seed_project(session, tenant_key)
    await session.commit()

    async with client() as mcp_session:
        result = await mcp_session.call_tool(
            "write_project_closeout",
            {
                "project_id": project.id,
                "summary": "Closed the lane. " + ("Long but entirely legitimate prose. " * 40),
                "key_outcomes": ["Shipped the fix", "Pinned it with a boundary test [see the suite]"],
                "decisions_made": ["Fixed at the dispatch seam so write_memory_entry is covered too"],
                "force": True,
            },
        )

    text = _content_text(result)
    assert not result.is_error, f"a well-formed closeout must still succeed, got: {text!r}"
    parsed = json.loads(text)
    assert parsed.get("entry_id"), f"the 360 entry must still be written, got: {parsed!r}"




@pytest.mark.asyncio
async def test_genuine_omission_still_gets_the_plain_validation_error(closeout_mcp_client):
    client, tenant_key, session = closeout_mcp_client
    project = await _seed_project(session, tenant_key)
    await session.commit()

    async with client() as mcp_session:
        result = await mcp_session.call_tool(
            "write_project_closeout",
            {"project_id": project.id, "summary": "Short and clean prose with no residue."},
        )

    text = _content_text(result)
    assert not result.is_error and '"VALIDATION_ERROR"' in text, (
        f"a missing required field must still be rejected, got: {text!r}"
    )
    assert "key_outcomes" in text, f"the rejection must name the missing field, got: {text!r}"
    assert "absorb" not in text.lower(), (
        f"a genuine omission must NOT be reported as absorption — that would name the wrong cause again: {text!r}"
    )
