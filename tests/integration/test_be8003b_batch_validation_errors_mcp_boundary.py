# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-8003b — batch validation + actionable error messages, MCP-boundary layer.

Delta-1 finding (see WO-8003b): the SERVICE layer (memory_entry_write_validator.py,
BE-6208a) already batches every offending field into
``MemoryEntryWriteValidationError.all_failures`` and already attaches the full
controlled-vocabulary list on the FIRST tag-vocab failure via ``.allowed`` --
``tests/unit/test_memory_entry_write_validator.py::test_batch_reports_all_failing_caps_together``
proves this at the unit layer. The bug this project fixes is that NONE of that
structured data reaches the agent: ``MemoryEntryWriteValidationError.__str__``
only renders the PRIMARY field/size/guidance line, and the FastMCP ``@mcp.tool``
wrapper (``_base.py::_call_tool``) surfaces raised ``_CLEAN_VALIDATION_ERRORS``
via a bare ``raise`` -> the SDK's ``ToolError(f"...: {e}")`` calls ``str(e)`` and
drops ``all_failures``/``allowed``/``invalid_tag`` on the floor. Exactly the
BE-5042 class of bug: correct unit coverage, broken MCP-boundary wrapper.

Drives the REAL transport (``create_connected_server_and_client_session``),
per CLAUDE.md's failing-layer regression-test mandate.
"""

from __future__ import annotations

import inspect
from uuid import uuid4

import pytest
import pytest_asyncio

from api.endpoints.mcp_sdk_server import mcp
from giljo_mcp.services.memory_entry_write_validator import (
    CONTROLLED_TAG_VOCABULARY,
    validate_memory_entry_write,
)
from giljo_mcp.tenant import TenantManager
from tests.helpers.mcp_session_fixture import create_connected_server_and_client_session


def _error_text(result) -> str:
    parts = []
    for block in result.content or []:
        text = getattr(block, "text", None)
        if text:
            parts.append(text)
    return "\n".join(parts)


@pytest_asyncio.fixture
async def autospec_mcp(monkeypatch):
    """Mirrors test_be3006d_mcp_boundary_validation.autospec_mcp: an autospec
    ToolAccessor on the in-memory transport so a test can plant a real
    MemoryEntryWriteValidationError as a specific accessor method's side_effect."""
    from unittest.mock import create_autospec

    from api import app_state
    from api.endpoints.mcp_tools import _base
    from giljo_mcp.tools.tool_accessor import ToolAccessor

    state = app_state.state
    prior_accessor = state.tool_accessor
    prior_tenant_manager = state.tenant_manager
    prior_db_manager = state.db_manager

    accessor = create_autospec(ToolAccessor, instance=True)
    for attr_name in dir(ToolAccessor):
        if attr_name.startswith("_"):
            continue
        if inspect.iscoroutinefunction(getattr(ToolAccessor, attr_name, None)):
            getattr(accessor, attr_name).return_value = {"ok": True}

    state.tool_accessor = accessor
    state.tenant_manager = TenantManager()
    state.db_manager = None

    tenant_key = TenantManager.generate_tenant_key()
    monkeypatch.setattr(_base, "_resolve_tenant", lambda ctx: tenant_key)
    monkeypatch.setattr(_base, "_resolve_user_id", lambda ctx: None)

    def _client():
        return create_connected_server_and_client_session(mcp)

    try:
        yield _client, accessor
    finally:
        state.tool_accessor = prior_accessor
        state.tenant_manager = prior_tenant_manager
        state.db_manager = prior_db_manager


def _real_combined_violation_error():
    """Build the REAL MemoryEntryWriteValidationError a simultaneous cap-violation
    + bad-tag payload produces, using production code (not a hand-rolled stub)."""
    with pytest.raises(Exception) as exc_info:  # noqa: PT011 - want the real validator exception
        validate_memory_entry_write(
            {
                "summary": "ok",
                "key_outcomes": [],
                "decisions_made": ["x"] * 6,  # > 5 items: cap violation
                "deliverables": [],
                "tags": ["not-a-real-tag"],  # simultaneous vocab violation
            }
        )
    return exc_info.value


class TestServiceLayerAlreadyBatches:
    """Confirms delta-1: the SERVICE layer already batches (this must PASS)."""

    def test_combined_violation_batches_both_fields(self):
        err = _real_combined_violation_error()
        assert err.all_failures is not None
        offending = {f["field"] for f in err.all_failures}
        assert {"decisions_made", "tags"} <= offending

    def test_combined_violation_tag_entry_carries_full_vocab_on_first_failure(self):
        err = _real_combined_violation_error()
        tag_failure = next(f for f in err.all_failures if f["field"] == "tags")
        assert tag_failure.get("allowed") is not None
        assert set(tag_failure["allowed"]) == CONTROLLED_TAG_VOCABULARY


@pytest.mark.asyncio
async def test_mcp_boundary_surfaces_all_failures_for_combined_violation(autospec_mcp):
    """The MCP-BOUNDARY layer must surface every simultaneous violation, not just
    the primary one. Reproduces the field report's N-resend dance: a caller that
    submits a decisions_made cap overflow AND a bad tag together must learn about
    BOTH from a single response, not just the first (`decisions_made`)."""
    client, accessor = autospec_mcp
    accessor.write_project_closeout.side_effect = _real_combined_violation_error()

    async with client() as session:
        result = await session.call_tool(
            "write_project_closeout",
            {
                "project_id": str(uuid4()),
                "summary": "ok",
                "key_outcomes": [],
                "decisions_made": ["x"] * 6,
                "tags": ["not-a-real-tag"],
            },
        )

    assert result.is_error is True
    text = _error_text(result)
    # The primary (first) violation is expected to surface.
    assert "decisions_made" in text
    # DoD #1: the SECOND simultaneous violation must ALSO surface in one round-trip.
    assert "tags" in text, f"batched second violation missing from MCP-boundary error text: {text!r}"


@pytest.mark.asyncio
async def test_mcp_boundary_surfaces_full_vocab_on_first_tag_failure(autospec_mcp):
    """DoD #2: an invalid-tag rejection must carry the full allowed vocabulary
    the FIRST time, not only after a second failed attempt (field report)."""
    client, accessor = autospec_mcp
    with pytest.raises(Exception) as exc_info:  # noqa: PT011
        validate_memory_entry_write(
            {
                "summary": "ok",
                "key_outcomes": [],
                "decisions_made": [],
                "deliverables": [],
                "tags": ["not-a-real-tag"],
            }
        )
    accessor.write_memory_entry.side_effect = exc_info.value

    async with client() as session:
        result = await session.call_tool(
            "write_memory_entry",
            {
                "project_id": str(uuid4()),
                "summary": "ok",
                "key_outcomes": [],
                "decisions_made": [],
                "tags": ["not-a-real-tag"],
            },
        )

    assert result.is_error is True
    text = _error_text(result)
    # The full controlled vocabulary must be inline on THIS (first) failure.
    missing = [tag for tag in CONTROLLED_TAG_VOCABULARY if tag not in text]
    assert not missing, f"allowed vocabulary missing from first-failure MCP-boundary text: {missing}"


# ---------------------------------------------------------------------------
# DoD #3/#5 -- "not found" family disambiguation (unknown-ID vs exists-but-
# wrong-state), driven through close_job. close_job is a TOOL_DISPATCH PURE
# tool (dispatches straight to OrchestrationAgentStateService.close_job,
# bypassing the ToolAccessor adapter), so it needs a real DB-backed session
# rather than an autospec accessor.
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def db_backed_client(db_manager, db_session, monkeypatch):
    from api import app_state
    from api.endpoints.mcp_tools import _base
    from giljo_mcp.tools.tool_accessor import ToolAccessor

    state = app_state.state
    prior_tool_accessor = state.tool_accessor
    prior_tenant_manager = state.tenant_manager
    prior_db_manager = state.db_manager

    if state.tenant_manager is None:
        state.tenant_manager = TenantManager()
    state.db_manager = db_manager

    tenant_key = TenantManager.generate_tenant_key()
    state.tool_accessor = ToolAccessor(
        db_manager=db_manager, tenant_manager=state.tenant_manager, test_session=db_session
    )

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


async def _seed_working_job(db_session, tenant_key: str):
    """A job whose only execution is 'working' (not 'complete') -- the
    exists-but-wrong-state half of the disambiguation."""
    import random
    from datetime import UTC, datetime

    from giljo_mcp.models.agent_identity import AgentExecution, AgentJob
    from giljo_mcp.models.organizations import Organization
    from giljo_mcp.models.products import Product
    from giljo_mcp.models.projects import Project

    suffix = uuid4().hex[:8]
    org = Organization(name=f"Org {suffix}", slug=f"org-{suffix}", tenant_key=tenant_key, is_active=True)
    db_session.add(org)
    await db_session.flush()

    product = Product(
        id=str(uuid4()), name=f"Product {suffix}", description="BE-8003b", tenant_key=tenant_key, is_active=True
    )
    db_session.add(product)
    await db_session.flush()

    project = Project(
        id=str(uuid4()),
        tenant_key=tenant_key,
        product_id=product.id,
        name=f"Project {suffix}",
        description="BE-8003b",
        mission="x",
        status="active",
        series_number=random.randint(1, 9000),
    )
    db_session.add(project)
    await db_session.flush()

    job = AgentJob(
        job_id=str(uuid4()),
        tenant_key=tenant_key,
        project_id=project.id,
        job_type="implementer",
        mission="BE-8003b",
        status="active",
        created_at=datetime.now(UTC),
    )
    db_session.add(job)
    await db_session.flush()

    execution = AgentExecution(
        id=str(uuid4()),
        agent_id=str(uuid4()),
        job_id=job.job_id,
        tenant_key=tenant_key,
        agent_display_name="implementer",
        status="working",
        started_at=datetime.now(UTC),
    )
    db_session.add(execution)
    await db_session.commit()
    return job


@pytest.mark.asyncio
async def test_close_job_mcp_boundary_disambiguates_wrong_state(db_backed_client):
    """close_job on a job that EXISTS but is not 'complete' must say so distinctly
    from an unknown job_id -- naming the actual status and diagnose_project_state."""
    client, tenant_key, session = db_backed_client
    job = await _seed_working_job(session, tenant_key)

    async with client() as mcp_session:
        result = await mcp_session.call_tool("close_job", {"job_id": job.job_id})

    assert result.is_error is True
    text = _error_text(result)
    assert "working" in text, f"actual status missing from wrong-state text: {text!r}"
    assert "not 'complete'" in text
    assert "diagnose_project_state" in text


@pytest.mark.asyncio
async def test_close_job_mcp_boundary_disambiguates_unknown_job_id(db_backed_client):
    """close_job on a job_id that does not exist AT ALL must say so distinctly
    from an exists-but-wrong-state job, not the old ambiguous shared message."""
    client, _tenant_key, _session = db_backed_client
    ghost_job_id = str(uuid4())

    async with client() as mcp_session:
        result = await mcp_session.call_tool("close_job", {"job_id": ghost_job_id})

    assert result.is_error is True
    text = _error_text(result)
    assert "No job found with ID" in text
    assert "diagnose_project_state" in text
    # Must NOT claim a status the job never had (that's the wrong-state message).
    assert "not 'complete'" not in text
