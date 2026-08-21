# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-6081 — Two-tier MCP-boundary error contract regression guard.

Reconciled rule: post-0480 ("all Python layers raise on error") and the
BE-5028 structured-rejection contract are NOT in tension — they govern
different cases, documented in api/endpoints/mcp_tools/_base.py.

  Tier 1 — ERRORS RAISE, surface as isError on the wire (post-0480).
    An unexpected/internal error must be caught by the _call_tool catch-all,
    logged server-side, and re-raised as a sanitized FastMCPError. The agent
    sees isError=True with a clean message — no SQL, no traceback.

  Tier 2 — DELIBERATE domain REJECTIONS RETURN, surface as normal content.
    A few tool implementations return a structured {"success": False,
    "error": <CODE>, ...} dict for an EXPECTED, agent-actionable declined
    request. No exception is raised, so the response flows through the
    success path UNCHANGED: the wire result is isError=False / not set, and
    the content is a parseable dict with success==False and the error code.

Known Tier-2 sites verified here:
  write_memory_entry — GIT_COMMITS_REQUIRED gate (line ~623,
    write_memory_entry.py): fires when git_integration_enabled AND
    entry_type=="project_completion" AND no git_commits supplied.
    author_job_id="" skips the ORCHESTRATOR_ONLY and CLOSEOUT_BLOCKED gates
    (both only fire when author_job_id is non-empty), so the call reaches
    the GIT_COMMITS_REQUIRED gate cleanly.
  write_memory_entry — GIT_COMMIT_TITLE_REQUIRED (BE-9256): fires when a
    supplied git_commits entry has no title (bare SHA, or empty message).
    validate_git_commits raises GitCommitTitleRequiredError, caught at the
    write_360_memory call site and returned as the Tier-2 dict.
  write_project_closeout — GIT_COMMIT_TITLE_REQUIRED (BE-9256 audit Finding
    #5): the symmetric sibling site in project_closeout.py's
    close_project_and_update_memory -- same GitCommitTitleRequiredError catch,
    same build_git_commit_title_required_rejection dict. Only write_memory_entry
    was transport-tested before this file; write_project_closeout was not.

Transport: every test drives the REAL @mcp.tool transport via
  ``create_connected_server_and_client_session`` — the wrapper, the
  _call_tool chokepoint, and the service gate are all exercised end-to-end.

Parallel-safe: each test generates a fresh tenant_key; the rolled-back
db_session provides transactional isolation (no cross-test data leaks);
no module-level mutable state.
"""

from __future__ import annotations

import json
import random
from typing import Any
from unittest.mock import create_autospec

import pytest
import pytest_asyncio
from sqlalchemy.exc import ProgrammingError

from api.endpoints.mcp_sdk_server import mcp
from api.endpoints.mcp_tools._base import _SANITIZED_TOOL_ERROR
from giljo_mcp.models.organizations import Organization
from giljo_mcp.models.products import Product
from giljo_mcp.models.projects import Project
from giljo_mcp.models.settings import Settings
from giljo_mcp.tenant import TenantManager
from giljo_mcp.tools.tool_accessor import ToolAccessor
from tests.helpers.mcp_session_fixture import create_connected_server_and_client_session


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _content_text(result) -> str:
    parts = []
    for block in result.content or []:
        text = getattr(block, "text", None)
        if text:
            parts.append(text)
    return "\n".join(parts)


def _parse_content_dict(result) -> dict[str, Any]:
    """Parse the first JSON content block into a dict."""
    text = _content_text(result)
    return json.loads(text)


_LEAK_MARKERS = ("[SQL:", "[parameters:", "Traceback", "INSERT INTO", "psycopg")


def _assert_no_leak(text: str) -> None:
    for marker in _LEAK_MARKERS:
        assert marker not in text, f"agent-facing error leaked {marker!r}: {text!r}"


# ---------------------------------------------------------------------------
# Fixture: DB-backed MCP client with ToolAccessor bound to rolled-back session
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def memory_tool_client(db_manager, db_session, monkeypatch):
    """Wire the real ToolAccessor (backed by the rolled-back test session) into
    the in-memory MCP transport.  Mirrors the complete_job_client pattern from
    test_be3006d_mcp_boundary_validation.py.

    The accessor's write_memory_entry AND write_project_closeout methods are
    both wrapped to inject the rolled-back db_session, so that seeded data
    written inside the transaction is visible to the tool call (both
    write_360_memory and close_project_and_update_memory accept a session
    kwarg) -- BE-9256 audit Finding #5 needs the write_project_closeout side
    transport-tested too, and reuses this same fixture rather than a near-
    duplicate one.

    Yields (client_factory, tenant_key, db_session).
    """
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

    # Wrap write_memory_entry to inject the test session so that seeded rows
    # (written inside the rolled-back transaction) are visible to the tool.
    # write_360_memory accepts ``session`` — pass it through so it reuses the
    # same transaction instead of opening a fresh connection from the pool.
    #
    # IMPORTANT: the wrapper must declare ``tenant_key`` as an explicit named
    # parameter. _call_tool uses inspect.signature to decide whether to inject
    # tenant_key; ``**kwargs``-only signatures fail the membership check and
    # the key is stripped before reaching us.
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

    # Same reasoning as _write_memory_entry_with_session above, for the
    # write_project_closeout tool (BE-9256 audit Finding #5). tenant_key must
    # stay an explicit named parameter for the same _call_tool signature-
    # inspection reason.
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


# ---------------------------------------------------------------------------
# Seed helpers
# ---------------------------------------------------------------------------


async def _seed_product_and_project(db_session, tenant_key: str):
    """Create a minimal org + product + project for write_memory_entry calls."""
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
    """Write a settings row that enables git integration for this tenant."""
    settings = Settings(
        tenant_key=tenant_key,
        category="integrations",
        settings_data={"git_integration": {"enabled": True}},
    )
    db_session.add(settings)
    await db_session.commit()


# ---------------------------------------------------------------------------
# Tier 2 — deliberate domain rejection flows as content, NOT isError
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tier2_git_commits_required_is_content_not_error(memory_tool_client):
    """TIER 2 (BE-5028 contract, core assertion): GIT_COMMITS_REQUIRED RETURNS as
    normal tool content, NOT raised as isError.

    Setup:
      - git integration ENABLED for the tenant (settings row)
      - entry_type = "project_completion" (only type that triggers the gate)
      - git_commits = None  (omitted — triggers the gate)
      - author_job_id = "" (empty — bypasses ORCHESTRATOR_ONLY + CLOSEOUT_BLOCKED
        gates, both of which only fire when author_job_id is non-empty)

    Expected wire result:
      - result.is_error is False (or absent / falsy) — NOT an error path
      - content parses to dict with success==False and error=="GIT_COMMITS_REQUIRED"
    """
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
                "author_job_id": "",
                # git_commits intentionally absent — triggers GIT_COMMITS_REQUIRED
            },
        )

    # Tier 2 contract: NOT an isError — the deliberate rejection flows as content.
    assert not result.is_error, (
        "GIT_COMMITS_REQUIRED must be returned as normal content (Tier 2), "
        f"not raised as isError. content: {_content_text(result)!r}"
    )

    parsed = _parse_content_dict(result)
    assert parsed.get("success") is False, f"Expected success==False in the rejection dict, got: {parsed!r}"
    assert parsed.get("error") == "GIT_COMMITS_REQUIRED", f"Expected error=='GIT_COMMITS_REQUIRED', got: {parsed!r}"


async def _seed_org_product_project(session, tenant_key: str, label: str):
    """Seed with real-UUID ids so write_360_memory's ``UUID(product.id)`` succeeds."""
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
    """BE-9256 (flips BE-6208a): a list of BARE SHA STRINGS for git_commits must be
    REJECTED at the @mcp.tool boundary as a Tier-2 structured domain rejection —
    NOT silently normalized to an empty-titled entry, and NOT raised as isError.

    BE-6208a widened the boundary type to ``list[dict | str]`` so a bare SHA string
    reaches the service layer instead of failing Pydantic's dict-shape check. That
    was correct plumbing, but the SERVICE-layer validator then normalized the bare
    string to ``{"sha": ..., "message": ""}``, and every UI surface (dashboard,
    closeout modal, 360 timeline) rendered that as a blank commit title. BE-9256
    fails closed at the validator instead: the boundary type stays widened (a bare
    string still reaches the service, avoiding the original dict_type regression),
    but the service now rejects it with GIT_COMMIT_TITLE_REQUIRED, delivered as
    normal tool content (Tier 2, not isError) with the exact git command to fix it.
    """
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
                "author_job_id": "",
                "git_commits": ["6c59b7e", "a775e8e4"],
            },
        )

    wire_text = _content_text(result)
    # The bare string must still REACH the service (BE-6208a's boundary-type fix
    # holds) -- a dict_type Pydantic rejection here would mean that regressed.
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
    """BE-9256: a titled {sha, message, author} dict is accepted and persists."""
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
                "author_job_id": "",
                "git_commits": [{"sha": "6c59b7e", "message": "Fix the widget", "author": "Alice"}],
            },
        )

    assert not result.is_error, f"titled closeout must not error at the boundary: {_content_text(result)!r}"
    parsed = _parse_content_dict(result)
    assert parsed.get("entry_id"), f"titled closeout should write an entry, got: {parsed!r}"
    assert parsed.get("git_commits_count") == 1, f"got: {parsed!r}"


@pytest.mark.asyncio
async def test_porcelain_git_commits_accepted_at_boundary(memory_tool_client):
    """BE-9256: a tab-delimited porcelain string (the raw `git log --format=...`
    output) is accepted and parsed into the titled shape."""
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
                "author_job_id": "",
                "git_commits": ["6c59b7e\tFix the widget\tAlice"],
            },
        )

    assert not result.is_error, f"porcelain closeout must not error at the boundary: {_content_text(result)!r}"
    parsed = _parse_content_dict(result)
    assert parsed.get("entry_id"), f"porcelain closeout should write an entry, got: {parsed!r}"
    assert parsed.get("git_commits_count") == 1, f"got: {parsed!r}"


@pytest.mark.asyncio
async def test_bare_sha_git_commits_rejected_at_closeout_boundary(memory_tool_client):
    """BE-9256 audit Finding #5: the symmetric write_project_closeout transport
    test. write_memory_entry's GIT_COMMIT_TITLE_REQUIRED path was transport-
    tested (test_bare_sha_git_commits_rejected_at_boundary above); its sibling
    site in close_project_and_update_memory (project_closeout.py, reached via
    the write_project_closeout @mcp.tool) was not. Same rejection shape, same
    Tier-2 contract (normal content, not isError), different tool."""
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
    """BE-9256 audit Finding #5 (happy-path sibling): a titled dict is accepted
    and persists through write_project_closeout, matching write_memory_entry's
    test_titled_git_commits_accepted_at_boundary above."""
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


# ---------------------------------------------------------------------------
# Tier 1 — unexpected/internal error raises and surfaces as isError (post-0480)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tier1_planted_accessor_error_is_sanitized_iserror(db_manager, db_session, monkeypatch):
    """TIER 1 (post-0480): an unexpected DB-level error in the accessor is caught
    by _call_tool's catch-all, sanitized (no SQL/traceback on the wire), and
    surfaced as isError=True.

    Mirrors the proven pattern from test_be3006d_mcp_boundary_validation.py
    (test_planted_db_error_is_sanitized). Uses an autospec accessor so the
    ProgrammingError is planted at the exact call site without hitting the DB.
    """
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

    # Tier 1 contract: unexpected error MUST surface as isError.
    assert result.is_error is True, (
        f"A planted unexpected DB error must produce isError=True. Got: {_content_text(result)!r}"
    )

    text = _content_text(result)
    _assert_no_leak(text)
    # The agent sees the sanitized generic message, not driver internals.
    assert "internal error" in text.lower() or _SANITIZED_TOOL_ERROR[:40] in text, (
        f"Expected sanitized error message, got: {text!r}"
    )
