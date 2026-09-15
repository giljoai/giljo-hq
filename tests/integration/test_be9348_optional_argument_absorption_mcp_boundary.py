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



_ABSORBED_TAGS_SUMMARY = (
    "Swept the remaining actively-referenced instructional surfaces and repaired every "
    "pointer, then closed the naming gap the earlier chain left behind."
    '</summary>\n<parameter name="tags">["docs", "chore", "infrastructure"]'
)

_ABSORBED_GIT_COMMITS_SUMMARY = (
    "Built the pane, bound it to the API, and shipped the drag-reorder rail. "
    "vitest 27/27, eslint clean, vite build clean."
    '</summary>\n<parameter name="git_commits">[{"sha": "7dafbb675", "message": '
    '"feat(roadmap): frontend pane"}]'
)

_ABSORBED_TAGS_OLD_STYLE_SUMMARY = (
    "Chain cold-start hardening landed and the live deadlock is gone."
    '</summary>\n<tags>["backend", "frontend", "bug-fix", "test"]'
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
        name=f"BE9348 Org {suffix}",
        slug=f"be9348-{suffix}",
        tenant_key=tenant_key,
        is_active=True,
    )
    db_session.add(org)
    await db_session.flush()

    product = Product(
        id=str(uuid4()),
        name=f"BE9348 Product {suffix}",
        description="BE-9348 optional argument absorption",
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
        name=f"BE9348 Project {suffix}",
        description="BE-9348",
        mission="Optional argument absorption regression",
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
    ("label", "absorbing_summary", "absorbed_name"),
    [
        ("tags-parameter-tag", _ABSORBED_TAGS_SUMMARY, "tags"),
        ("git-commits-parameter-tag", _ABSORBED_GIT_COMMITS_SUMMARY, "git_commits"),
        ("tags-old-style-tag", _ABSORBED_TAGS_OLD_STYLE_SUMMARY, "tags"),
    ],
    ids=["tags-parameter-tag", "git-commits-parameter-tag", "tags-old-style-tag"],
)
@pytest.mark.asyncio
async def test_absorbed_optional_argument_is_rejected_and_writes_nothing(
    closeout_mcp_client, label, absorbing_summary, absorbed_name
):
    client, tenant_key, session = closeout_mcp_client
    project = await _seed_project(session, tenant_key)
    await session.commit()

    before = await _memory_entry_count(session, tenant_key)

    async with client() as mcp_session:
        result = await mcp_session.call_tool(
            "write_project_closeout",
            {
                "project_id": project.id,
                "summary": absorbing_summary,
                "key_outcomes": ["The filter matches what rotation writes"],
                "decisions_made": ["Fixed at the rotation layer"],
                "force": True,
            },
        )

    text = _content_text(result)
    assert result.is_error, f"[{label}] an absorbed optional argument must be rejected, got: {text!r}"

    lowered = text.lower()
    assert absorbed_name in text, (
        f"[{label}] the rejection must name the optional argument that was absorbed ({absorbed_name}); got: {text!r}"
    )
    assert "summary" in lowered, (
        f"[{label}] the rejection must name the argument that absorbed it (summary); got: {text!r}"
    )
    assert any(word in lowered for word in ("absorb", "merged into", "did not arrive")), (
        f"[{label}] the rejection must state the argument was absorbed, not merely wrong; got: {text!r}"
    )

    after = await _memory_entry_count(session, tenant_key)
    assert after == before, f"[{label}] a rejected closeout must write no 360 entry (before={before}, after={after})"

    await session.refresh(project)
    assert project.status == "active", f"[{label}] a rejected closeout must not close the project: {project.status!r}"




@pytest.mark.asyncio
async def test_legitimate_json_list_tail_still_succeeds(closeout_mcp_client):
    client, tenant_key, session = closeout_mcp_client
    project = await _seed_project(session, tenant_key)
    await session.commit()

    async with client() as mcp_session:
        result = await mcp_session.call_tool(
            "write_project_closeout",
            {
                "project_id": project.id,
                "summary": (
                    'Corrected the archive filter. The offending values were ["giljo.log.1", "giljo.log.2026-08-01"]'
                ),
                "key_outcomes": ["The filter now matches rotation output [verified on disk]"],
                "decisions_made": ["Matched the real filename shape, not the assumed one"],
                "force": True,
            },
        )

    text = _content_text(result)
    assert not result.is_error, f"a summary legitimately ending in a JSON list must still succeed, got: {text!r}"
    parsed = json.loads(text)
    assert parsed.get("entry_id"), f"the 360 entry must still be written, got: {parsed!r}"




@pytest.mark.asyncio
async def test_prose_quoting_tool_call_markup_still_succeeds(closeout_mcp_client):
    client, tenant_key, session = closeout_mcp_client
    project = await _seed_project(session, tenant_key)
    await session.commit()

    async with client() as mcp_session:
        result = await mcp_session.call_tool(
            "write_project_closeout",
            {
                "project_id": project.id,
                "summary": (
                    "A caller's serializer sometimes merges an argument into its neighbour, so a "
                    "summary would end with a <tags> marker followed by a JSON array. The server now "
                    "refuses that call at the dispatch seam instead of storing the markup, and says "
                    "which argument was absorbed."
                ),
                "key_outcomes": ["Absorbed optional arguments are refused, not persisted"],
                "decisions_made": ["Rejected only on conclusive evidence with a pure call-syntax tail"],
                "force": True,
            },
        )

    text = _content_text(result)
    assert not result.is_error, f"prose that merely quotes tool-call markup must still succeed, got: {text!r}"
    parsed = json.loads(text)
    assert parsed.get("entry_id"), f"the 360 entry must still be written, got: {parsed!r}"




@pytest.mark.parametrize(
    ("label", "summary"),
    [
        ("cli-usage", "Documented the CLI entry point. Usage: giljo close <project_id>"),
        ("route-list", "Added the read routes:\n- GET /api/projects/<project_id>"),
        ("trailing-comma", "The archive filter now interpolates <project_id>,"),
        ("trailing-period", "The archive filter now interpolates <project_id>."),
        ("bare-placeholder-eos", "The archive filter now interpolates <project_id>"),
        ("optional-param-placeholder", "Documented the closeout call. Pass the vocabulary in <tags>"),
    ],
    ids=[
        "cli-usage",
        "route-list",
        "trailing-comma",
        "trailing-period",
        "bare-placeholder-eos",
        "optional-param-placeholder",
    ],
)
@pytest.mark.asyncio
async def test_angle_bracket_placeholder_in_prose_still_succeeds(closeout_mcp_client, label, summary):
    client, tenant_key, session = closeout_mcp_client
    project = await _seed_project(session, tenant_key)
    await session.commit()

    async with client() as mcp_session:
        result = await mcp_session.call_tool(
            "write_project_closeout",
            {
                "project_id": project.id,
                "summary": summary,
                "key_outcomes": ["The placeholder is prose, not an absorbed argument"],
                "decisions_made": ["Required a serialized value before claiming absorption"],
                "force": True,
            },
        )

    text = _content_text(result)
    assert not result.is_error, (
        f"[{label}] an angle-bracket placeholder in ordinary prose must NOT be read as absorption "
        f"-- master accepts this call; got: {text!r}"
    )
    parsed = json.loads(text)
    assert parsed.get("entry_id"), f"[{label}] the 360 entry must still be written, got: {parsed!r}"




@pytest.mark.parametrize(
    ("label", "absorbed_tail"),
    [
        ("integer", '<parameter name="force">3'),
        ("boolean", '<parameter name="force">true'),
        ("null", '<parameter name="force">null'),
    ],
    ids=["integer", "boolean", "null"],
)
@pytest.mark.asyncio
async def test_absorbed_bare_scalar_argument_is_rejected(closeout_mcp_client, label, absorbed_tail):
    client, tenant_key, session = closeout_mcp_client
    project = await _seed_project(session, tenant_key)
    await session.commit()

    before = await _memory_entry_count(session, tenant_key)

    async with client() as mcp_session:
        result = await mcp_session.call_tool(
            "write_project_closeout",
            {
                "project_id": project.id,
                "summary": "Closed the lane and pinned the regression.</summary>\n" + absorbed_tail,
                "key_outcomes": ["The scalar was absorbed, not omitted"],
                "decisions_made": ["Gated the scalar allowance on the serializer's own markup"],
            },
        )

    text = _content_text(result)
    assert result.is_error, f"[{label}] an absorbed bare scalar must be rejected, got: {text!r}"
    assert "force" in text, f"[{label}] the rejection must name the absorbed argument: {text!r}"

    after = await _memory_entry_count(session, tenant_key)
    assert after == before, f"[{label}] a rejected closeout must write no 360 entry"




@pytest.mark.asyncio
async def test_confirmed_be9348_prod_shape_still_names_absorption(closeout_mcp_client):
    client, tenant_key, session = closeout_mcp_client
    project = await _seed_project(session, tenant_key)
    await session.commit()

    absorbing_summary = (
        "Reworded the archive filter so it matches what rotation actually writes. "
        'The regression test pins the real filename shape."]</key_outcomes>\n'
        '<decisions_made>["Matched the real shape"]</decisions_made>\n'
    )

    async with client() as mcp_session:
        result = await mcp_session.call_tool(
            "write_project_closeout",
            {"project_id": project.id, "summary": absorbing_summary},
        )

    text = _content_text(result)
    assert result.is_error, f"expected rejection, got: {text!r}"
    assert "key_outcomes" in text, f"the rejection must name the absorbed required field: {text!r}"
    assert "absorb" in text.lower(), f"the rejection must name absorption as the cause: {text!r}"


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
    assert "absorb" not in text.lower(), f"a genuine omission must NOT be reported as absorption: {text!r}"




@pytest.mark.asyncio
async def test_large_payload_arrives_whole_at_the_server(closeout_mcp_client):
    client, tenant_key, session = closeout_mcp_client
    project = await _seed_project(session, tenant_key)
    await session.commit()

    oversized_summary = "S" * 180_000

    async with client() as mcp_session:
        result = await mcp_session.call_tool(
            "write_project_closeout",
            {
                "project_id": project.id,
                "summary": oversized_summary,
                "key_outcomes": ["o" * 200, "second outcome"],
                "decisions_made": ["d" * 200],
                "tags": ["backend", "bug-fix"],
                "force": True,
            },
        )

    text = _content_text(result)
    assert result.is_error, f"a 180 KB summary is over the documented cap and must be rejected, got: {text!r}"
    assert "180000" in text, (
        "the cap rejection must report the length the server actually received -- "
        f"if the transport truncated, this number would be smaller; got: {text!r}"
    )
    assert "Field required" not in text, (
        f"every parameter must have arrived; a missing one would mean the payload was mangled: {text!r}"
    )
