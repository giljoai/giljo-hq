# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-3006d — MCP-boundary validation + sanitizing error catch-all (two-sided).

CLAUDE.md mandates a regression test at the failing layer. The bugs this project
fixes live in the FastMCP @mcp.tool wrapper layer + the single ``_call_tool``
dispatch chokepoint, so every test here drives the REAL transport
(``create_connected_server_and_client_session``) — the wrapper arg-validation,
the ``_call_tool`` catch-all, and the service-layer JSONB validator are all
exercised, not mocked around.

Two-sided coverage (DoD):

* NEGATIVE — invalid input must surface as a clean 422-style ToolError, never a
  500/stack trace:
    - invalid enum (message_type / task status) -> rejected at FastMCP arg
      validation, no SQL/traceback in the wire error.
    - over-length param (content / title) -> same.
    - a PLANTED unexpected DB error inside the accessor -> the catch-all
      SANITIZES it: the agent-facing text carries NO SQL, NO bind parameters,
      and NO "Traceback".
    - a curated client error (our ValidationError, 4xx) -> surfaces VERBATIM
      (the catch-all must not swallow actionable agent-facing errors).

* POSITIVE (load-bearing) — every legitimate call still dispatches cleanly after
  the Literals/caps were added, and complete_job's new AgentExecutionResult
  validator accepts a valid result.

Parallel-safe: the autospec section needs no DB; the complete_job section uses
the rolled-back ``db_session`` (TransactionalTestContext-equivalent via the
shared-session service rebind). No module-level mutable state; tenant keys are
freshly generated per test.
"""

from __future__ import annotations

import inspect
import random
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import create_autospec
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy.exc import ProgrammingError

from api.endpoints.mcp_sdk_server import mcp
from api.endpoints.mcp_tools._base import (
    _SANITIZED_TOOL_ERROR,
    MCP_DESCRIPTION_MAX,
    MCP_MESSAGE_MAX,
    MCP_NAME_MAX,
)
from giljo_mcp.exceptions import ValidationError as GiljoValidationError
from giljo_mcp.models.agent_identity import AgentExecution, AgentJob
from giljo_mcp.models.organizations import Organization
from giljo_mcp.models.products import Product
from giljo_mcp.models.projects import Project
from giljo_mcp.tenant import TenantManager
from tests.helpers.mcp_dispatch import attach_registry_service_autospecs
from tests.helpers.mcp_session_fixture import create_connected_server_and_client_session


# Substrings that would prove a raw DB/driver leak reached the agent.
_LEAK_MARKERS = ("[SQL:", "[parameters:", "Traceback", "INSERT INTO", "psycopg", "secret-bind-value")


def _error_text(result) -> str:
    parts = []
    for block in result.content or []:
        text = getattr(block, "text", None)
        if text:
            parts.append(text)
    return "\n".join(parts)


def _assert_no_leak(text: str) -> None:
    for marker in _LEAK_MARKERS:
        assert marker not in text, f"agent-facing error leaked {marker!r}: {text!r}"


# ---------------------------------------------------------------------------
# Section 1 — autospec transport (no DB): caps, enums, sanitization.
# ---------------------------------------------------------------------------
@pytest_asyncio.fixture
async def autospec_mcp(monkeypatch):
    """Install an autospec ToolAccessor + tenant resolution on the in-memory
    transport (mirrors the INF-3000b smoke harness). Yields a client factory and
    the accessor so a test can force a specific method to raise."""
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

    # BE-3010b: PURE tools dispatch straight to the terminal service method via
    # TOOL_DISPATCH; wire autospec'd service sub-objects so they resolve (and a
    # test can plant a side_effect on the real terminal method).
    attach_registry_service_autospecs(accessor, {"ok": True})

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


# --- NEGATIVE: invalid enum / over-length -> clean 422, no leak --------------


@pytest.mark.asyncio
async def test_invalid_thread_status_enum_is_clean_422(autospec_mcp):
    """BE-9012d: retargeted from the retired send_message's message_type Literal
    onto post_to_thread's set_status Literal (the Hub tool that replaced it)."""
    client, _accessor = autospec_mcp
    async with client() as session:
        result = await session.call_tool(
            "post_to_thread",
            {
                "thread_id": str(uuid4()),
                "content": "hi",
                "set_status": "not-a-real-status",  # not in the Literal
            },
        )
    assert result.is_error is True
    _assert_no_leak(_error_text(result))


@pytest.mark.asyncio
async def test_invalid_task_status_enum_is_clean_422(autospec_mcp):
    client, _accessor = autospec_mcp
    async with client() as session:
        result = await session.call_tool(
            "update_task",
            {"task_id": str(uuid4()), "status": "doing-stuff"},  # not in the Literal
        )
    assert result.is_error is True
    _assert_no_leak(_error_text(result))


@pytest.mark.asyncio
async def test_over_length_message_content_is_clean_422(autospec_mcp):
    """BE-9012d: retargeted from the retired send_message onto post_to_thread (the
    Hub tool that replaced it) — both cap content at MCP_MESSAGE_MAX."""
    client, _accessor = autospec_mcp
    async with client() as session:
        result = await session.call_tool(
            "post_to_thread",
            {
                "thread_id": str(uuid4()),
                "content": "x" * (MCP_MESSAGE_MAX + 1),  # over the cap
            },
        )
    assert result.is_error is True
    _assert_no_leak(_error_text(result))


@pytest.mark.asyncio
async def test_over_length_task_title_is_clean_422(autospec_mcp):
    client, _accessor = autospec_mcp
    async with client() as session:
        result = await session.call_tool(
            "create_task",
            {"title": "t" * (MCP_NAME_MAX + 1), "description": "d"},
        )
    assert result.is_error is True
    _assert_no_leak(_error_text(result))


# --- NEGATIVE: planted unexpected DB error -> sanitized ----------------------


@pytest.mark.asyncio
async def test_planted_db_error_is_sanitized(autospec_mcp):
    """An unexpected SQLAlchemy error (carrying SQL + bind params in its str())
    must be sanitized by the _call_tool catch-all before it reaches the agent."""
    client, accessor = autospec_mcp
    leaky = ProgrammingError(
        statement="INSERT INTO tasks (id, title) VALUES (%(id)s, %(title)s)",
        params={"id": "uuid", "title": "secret-bind-value"},
        orig=Exception("relation does not exist"),
    )
    # BE-3010b: create_task dispatches to the terminal service method, so plant
    # the leaky error there (not on the bypassed accessor mixin method).
    accessor._task_service.create_task_for_mcp.side_effect = leaky

    async with client() as session:
        result = await session.call_tool("create_task", {"title": "ok", "description": "d"})

    assert result.is_error is True
    text = _error_text(result)
    _assert_no_leak(text)
    # The agent gets the generic sanitized guidance, not the driver detail.
    assert "internal error" in text.lower() or _SANITIZED_TOOL_ERROR[:40] in text


@pytest.mark.asyncio
async def test_curated_client_error_surfaces_verbatim(autospec_mcp):
    """A curated 4xx BaseGiljoError must surface VERBATIM (not sanitized) so the
    agent keeps its actionable message."""
    client, accessor = autospec_mcp
    # BE-3010b: create_task dispatches to the terminal service method.
    accessor._task_service.create_task_for_mcp.side_effect = GiljoValidationError(
        "title must be a short actionable phrase",
        context={"field": "title"},
    )

    async with client() as session:
        result = await session.call_tool("create_task", {"title": "ok", "description": "d"})

    assert result.is_error is True
    text = _error_text(result)
    assert "title must be a short actionable phrase" in text
    assert _SANITIZED_TOOL_ERROR[:40] not in text


# --- POSITIVE: valid calls still dispatch after the caps/Literals were added --

_VALID_CALLS: dict[str, dict[str, Any]] = {
    "post_to_thread": {
        "thread_id": "11111111-1111-1111-1111-111111111111",
        "content": "status update",
        "from_agent": "implementer",
        "requires_action": False,
    },
    "create_task": {"title": "Tighten the type hint", "description": "details", "priority": "high"},
    "update_task": {"task_id": str(uuid4()), "status": "in_progress", "priority": "low", "title": "x"},
    "update_job_mission": {"job_id": str(uuid4()), "mission": "do the thing"},
    "update_project_mission": {"project_id": str(uuid4()), "mission": "the plan"},
    "set_agent_status": {"job_id": str(uuid4()), "status": "idle", "reason": "monitoring"},
    "request_approval": {
        "job_id": str(uuid4()),
        "project_id": str(uuid4()),
        "reason": "need a decision",
        "options": [{"id": "a", "label": "Option A"}],
    },
    "create_project": {"name": "P", "description": "d", "project_type": "BE"},
    "update_project": {"project_id": str(uuid4()), "name": "P2"},
    "save_roadmap": {"items": [], "summary": "s"},
    "apply_context_tuning": {"product_id": str(uuid4()), "proposals": []},
    "spawn_job": {
        "agent_display_name": "implementer",
        "agent_name": "tdd-implementor",
        "project_id": str(uuid4()),
        "mission": "m",
    },
}


@pytest.mark.asyncio
@pytest.mark.parametrize("tool_name", sorted(_VALID_CALLS))
async def test_valid_hardened_calls_still_dispatch(tool_name, autospec_mcp):
    """The happy path is the half that matters most: a legitimate call for every
    hardened tool must still pass arg validation and dispatch (isError False)."""
    client, _accessor = autospec_mcp
    async with client() as session:
        result = await session.call_tool(tool_name, _VALID_CALLS[tool_name])
    assert result.is_error is False, f"{tool_name} valid call failed: {_error_text(result)}"


# --- BE-6209e (BE-9118 regroup): api_style / architecture_pattern are PROSE(20k).
# These write to unbounded Postgres ``Text`` columns (products.api_style,
# product_architectures.primary_pattern); the MCP-boundary cap is the only limit.
# BE-9118 (Option B) moved both fields INSIDE the ``architecture`` grouped dict —
# the per-field cap now lives on the nested Pydantic model, so the same cap must
# still bite through the transport. Drive the REAL transport (the failing layer is
# the @mcp.tool arg-validation wrapper, per CLAUDE.md): a value over the OLD 200
# label cap must dispatch (prose-sized), a legacy short value must dispatch, and
# the prose cap must still reject at the boundary — all now under architecture={}.


@pytest.mark.asyncio
async def test_update_product_context_long_api_arch_now_dispatches(autospec_mcp):
    """A prose-sized api_style / architecture_pattern (over the old 200 label cap)
    passes arg validation inside the BE-9118 architecture group."""
    client, _accessor = autospec_mcp
    long_value = "REST + gRPC; " * 100  # ~1300 chars: over 200, well under 20_000
    assert MCP_NAME_MAX < len(long_value) < MCP_DESCRIPTION_MAX
    async with client() as session:
        result = await session.call_tool(
            "update_product_context",
            {
                "product_id": str(uuid4()),
                "architecture": {"api_style": long_value, "architecture_pattern": long_value},
            },
        )
    assert result.is_error is False, f"widened grouped call must dispatch: {_error_text(result)}"


@pytest.mark.asyncio
async def test_update_product_context_legacy_short_values_still_dispatch(autospec_mcp):
    """Backward-compat: short api_style / architecture_pattern values are still
    accepted inside the BE-9118 architecture group (no min-length regression)."""
    client, _accessor = autospec_mcp
    async with client() as session:
        result = await session.call_tool(
            "update_product_context",
            {
                "product_id": str(uuid4()),
                "architecture": {"api_style": "REST", "architecture_pattern": "layered"},
            },
        )
    assert result.is_error is False, f"legacy short grouped call must dispatch: {_error_text(result)}"


@pytest.mark.asyncio
async def test_update_product_context_over_prose_cap_still_rejected(autospec_mcp):
    """The BE-9118 regroup preserved the cap: a value over MCP_DESCRIPTION_MAX
    inside the architecture group is still a clean 422 at the boundary, no leak."""
    client, _accessor = autospec_mcp
    async with client() as session:
        result = await session.call_tool(
            "update_product_context",
            {"product_id": str(uuid4()), "architecture": {"api_style": "x" * (MCP_DESCRIPTION_MAX + 1)}},
        )
    assert result.is_error is True
    _assert_no_leak(_error_text(result))


# ---------------------------------------------------------------------------
# Section 2 — DB-backed complete_job: AgentExecutionResult validator two-sided.
# ---------------------------------------------------------------------------
@pytest_asyncio.fixture
async def complete_job_client(db_manager, db_session, monkeypatch):
    """Rebind JobCompletionService to the rolled-back test session (same pattern
    as test_complete_job_mcp_boundary.phase_mcp_client)."""
    from api import app_state
    from api.endpoints.mcp_tools import _base
    from giljo_mcp.services.job_completion_service import JobCompletionService
    from giljo_mcp.tools.tool_accessor import ToolAccessor

    state = app_state.state
    prior_tool_accessor = state.tool_accessor
    prior_tenant_manager = state.tenant_manager
    prior_db_manager = state.db_manager

    if state.tenant_manager is None:
        state.tenant_manager = TenantManager()
    state.db_manager = db_manager

    tenant_key = TenantManager.generate_tenant_key()
    accessor = ToolAccessor(db_manager=db_manager, tenant_manager=state.tenant_manager)
    accessor._job_completion_service = JobCompletionService(
        db_manager=db_manager,
        tenant_manager=state.tenant_manager,
        test_session=db_session,
    )
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


async def _seed_impl_orchestrator(db_session, tenant_key: str) -> AgentJob:
    suffix = uuid4().hex[:8]
    org = Organization(name=f"Org {suffix}", slug=f"org-{suffix}", tenant_key=tenant_key, is_active=True)
    db_session.add(org)
    await db_session.flush()

    product = Product(
        id=str(uuid4()),
        name=f"Product {suffix}",
        description="BE-3006d complete_job boundary",
        tenant_key=tenant_key,
        is_active=True,
    )
    db_session.add(product)
    await db_session.flush()

    project = Project(
        id=str(uuid4()),
        tenant_key=tenant_key,
        product_id=product.id,
        name=f"Project {suffix}",
        description="BE-3006d",
        mission="x",
        status="active",
        staging_status="staging_complete",
        series_number=random.randint(1, 9000),
    )
    db_session.add(project)
    await db_session.flush()

    job = AgentJob(
        job_id=str(uuid4()),
        tenant_key=tenant_key,
        project_id=project.id,
        job_type="orchestrator",
        mission="BE-3006d impl orchestrator",
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
        agent_display_name="orchestrator",
        status="working",
        started_at=datetime.now(UTC) - timedelta(minutes=2),
        project_phase="implementation",
    )
    db_session.add(execution)
    await db_session.commit()
    return job


@pytest.mark.asyncio
async def test_complete_job_valid_result_succeeds(complete_job_client):
    """POSITIVE: a well-formed result (known fields + extensible extras) passes
    the AgentExecutionResult validator and completes."""
    new_client, tenant_key, session = complete_job_client
    job = await _seed_impl_orchestrator(session, tenant_key)

    async with new_client() as mcp_session:
        result = await mcp_session.call_tool(
            "complete_job",
            {
                "job_id": job.job_id,
                "result": {
                    "summary": "Did the work",
                    "artifacts": ["a.py", "b.py"],
                    "files_changed": ["a.py"],  # extra="allow" extra key rides along
                },
            },
        )
    assert result.is_error is False, f"valid complete_job must succeed: {_error_text(result)}"


@pytest.mark.asyncio
async def test_complete_job_wrong_typed_result_is_clean_422(complete_job_client):
    """NEGATIVE: a wrong-typed known field (summary as int) is rejected as a clean
    422-style error, NOT a sanitized 500 and NOT a raw DB/JSONB leak."""
    new_client, tenant_key, session = complete_job_client
    job = await _seed_impl_orchestrator(session, tenant_key)

    async with new_client() as mcp_session:
        result = await mcp_session.call_tool(
            "complete_job",
            {"job_id": job.job_id, "result": {"summary": 12345}},  # summary must be str
        )
    assert result.is_error is True
    text = _error_text(result)
    _assert_no_leak(text)
    # Actionable, not the generic sanitized message.
    assert _SANITIZED_TOOL_ERROR[:40] not in text


# ---------------------------------------------------------------------------
# Section 3 — unit: the AgentExecutionResult convenience validator.
# ---------------------------------------------------------------------------
def test_validate_agent_execution_result_accepts_and_preserves_extras():
    from giljo_mcp.schemas.jsonb_validators import validate_agent_execution_result

    payload = {"summary": "ok", "commits": ["abc"], "files_changed": ["a.py"]}
    out = validate_agent_execution_result(payload)
    # Shape preserved exactly (no reshaping, no dropped extras).
    assert out == payload


def test_validate_agent_execution_result_rejects_wrong_type():
    import pydantic

    from giljo_mcp.schemas.jsonb_validators import validate_agent_execution_result

    with pytest.raises(pydantic.ValidationError):
        validate_agent_execution_result({"summary": 123})
