# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-9292b — an accepted-but-stalled ('silent') job must close without being
labelled 'decommissioned'.

The incident (ledger-zero chain, 2026-07-25): an implementer stalled in a
wait-loop and never called ``complete_job``. Its work was fully committed and
independently audited to APPROVE. The health monitor had moved it to 'silent'.
The orchestrator, having verified the deliverable, wanted to accept it — and
found no way to. It fell back to ``write_project_closeout(force=true)``, which
auto-decommissions, so the dashboard now labels a successful contributor
'decommissioned' ("failed/replaced/abandoned" per ``close_job``'s own docstring).

**The transition was never missing.** ``complete_job``'s lookup
(``find_active_execution_for_completion``) excludes only
``('complete', 'closed', 'decommissioned')`` — 'silent' is NOT terminal, so
``complete_job`` accepts it and ``close_job`` then reaches 'closed'. The defect
is that this path is announced NOWHERE: ``close_job``'s wrong-state error said
only "not in 'complete' status" and pointed at ``diagnose_project_state``, a
dead end for an orchestrator acting on behalf of an agent that will never call
``complete_job`` itself.

Regression tests at the MCP transport (the boundary an orchestrator actually
calls), via ``create_connected_server_and_client_session``:

  1. close_job on a 'silent' execution NAMES the complete_job recovery  [RED before fix]
  2. silent → complete_job → close_job reaches 'closed', never 'decommissioned'
     (pins the path the fix documents, so it cannot be silently removed)
  3. the recovery hint is NOT offered where complete_job genuinely cannot
     recover ('decommissioned') — the hint must not lie in the other direction
  4. stranded TODOs still block completion, naming them — this is why the
     documented recovery must name report_progress as its first step

Parallel-safe: fresh tenant_key per test, rolled-back db_session, no
module-level mutable state, no ordering dependencies.
"""

from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest
import pytest_asyncio
from mcp.shared.memory import create_connected_server_and_client_session

from api.endpoints.mcp_sdk_server import mcp
from giljo_mcp.models import AgentTodoItem
from giljo_mcp.models.agent_identity import AgentExecution, AgentJob
from giljo_mcp.models.organizations import Organization
from giljo_mcp.models.products import Product
from giljo_mcp.models.projects import Project
from giljo_mcp.tenant import TenantManager
from giljo_mcp.tools.tool_accessor import ToolAccessor


# ---------------------------------------------------------------------------
# Wire helpers (mirrors test_be9165_closeout_deadlock_mcp_boundary.py)
# ---------------------------------------------------------------------------


def _content_text(result) -> str:
    parts = []
    for block in result.content or []:
        text = getattr(block, "text", None)
        if text:
            parts.append(text)
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Fixture: DB-backed MCP client wiring complete_job AND close_job to the
# rolled-back test session.
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def terminal_state_mcp_client(db_manager, db_session, monkeypatch):
    """Yield (client_factory, tenant_key, db_session) with the real ToolAccessor
    bound to the rolled-back test session for both tools under test.

    ``close_job`` dispatches to ``acc._agent_state_service.close_job`` and
    ``complete_job`` to ``acc._job_completion_service.complete_job``
    (``_base.TOOL_DISPATCH``), so both services are rebuilt with ``test_session``.

    The ``_base`` post-hooks are disabled for this fixture. They are keyed on a
    successful call carrying ``job_id`` and the first of them is
    ``auto_clear_silent``, which flips a 'silent' execution back to 'working' —
    on a SEPARATE session opened from ``app_state.db_manager``. That is correct
    production behavior (a live-but-slow agent clears its own silent flag on its
    next call; the stalled agent in the incident made no further calls, which is
    why it stayed silent), but here it would race the rolled-back test session
    and erase the exact state under test. Disabling the debounce gate switches
    both post-hooks off deterministically.
    """
    from api import app_state
    from api.endpoints.mcp_tools import _base
    from giljo_mcp.services.job_completion_service import JobCompletionService
    from giljo_mcp.services.orchestration_agent_state_service import OrchestrationAgentStateService

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
    accessor._agent_state_service = OrchestrationAgentStateService(
        db_manager=db_manager,
        tenant_manager=state.tenant_manager,
        test_session=db_session,
    )
    state.tool_accessor = accessor

    monkeypatch.setattr(_base, "_resolve_tenant", lambda ctx: tenant_key)
    monkeypatch.setattr(_base, "_resolve_user_id", lambda ctx: None)
    monkeypatch.setattr(_base, "should_run", lambda *args, **kwargs: False)

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


async def _seed_org_product(db_session, tenant_key: str):
    suffix = uuid4().hex[:8]
    org = Organization(
        name=f"BE9292b Org {suffix}",
        slug=f"be9292b-{suffix}",
        tenant_key=tenant_key,
        is_active=True,
    )
    db_session.add(org)
    await db_session.flush()

    product = Product(
        id=str(uuid4()),
        name=f"BE9292b Product {suffix}",
        description="BE-9292b job terminal states",
        tenant_key=tenant_key,
        is_active=True,
        product_memory={},
    )
    db_session.add(product)
    await db_session.flush()
    return org, product


async def _seed_project(db_session, tenant_key: str, product_id: str):
    project = Project(
        id=str(uuid4()),
        tenant_key=tenant_key,
        product_id=product_id,
        name=f"BE9292b Project {uuid4().hex[:8]}",
        description="BE-9292b",
        mission="Silent-job terminal state regression",
        status="active",
        execution_mode="subagent",
        staging_status="staging_complete",
        implementation_launched_at=datetime.now(UTC) - timedelta(hours=1),
        series_number=random.randint(1, 9000),
    )
    db_session.add(project)
    await db_session.flush()
    return project


async def _seed_specialist(db_session, tenant_key: str, project_id: str, *, status: str):
    """A spawned implementer whose execution sits in ``status``.

    'silent' reproduces the incident: the health monitor's auto-silent timeout
    fired on an agent that stalled mid-run (agent_health_monitor auto-silent).
    """
    job = AgentJob(
        job_id=str(uuid4()),
        tenant_key=tenant_key,
        project_id=project_id,
        job_type="implementer",
        mission="BE-9292b specialist",
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
        agent_name="implementer-backend",
        status=status,
        started_at=datetime.now(UTC) - timedelta(minutes=90),
        project_phase="implementation",
    )
    db_session.add(execution)
    await db_session.flush()
    return job, execution


async def _seed_todo(db_session, tenant_key: str, job_id: str, content: str):
    todo = AgentTodoItem(
        id=str(uuid4()),
        tenant_key=tenant_key,
        job_id=job_id,
        content=content,
        status="in_progress",
        sequence=1,
    )
    db_session.add(todo)
    await db_session.flush()
    return todo


# The deliverable the orchestrator independently verified before accepting.
_VERIFIED_RESULT: dict[str, Any] = {
    "summary": "Guard implemented and audited to APPROVE; commits landed before the stall.",
    "commits": ["b17b7901c", "0ad48106a"],
    "artifacts": ["src/giljo_mcp/services/guard.py"],
}


# ---------------------------------------------------------------------------
# Case 1 — RED before fix: close_job on 'silent' must name the recovery
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_close_job_on_silent_execution_names_the_complete_job_recovery(terminal_state_mcp_client):
    """An orchestrator that has verified a stalled worker's deliverable calls
    close_job and is refused. Refusing is correct — 'silent' is not 'complete'.
    But the refusal must NAME the one call that makes it complete, because the
    orchestrator cannot wait for an agent that will never run again.

    RED before fix: the payload named only ``diagnose_project_state`` — the dead
    end the BE-9288 orchestrator hit, which sent it to
    ``write_project_closeout(force=true)`` and mislabelled a successful agent.
    """
    client, tenant_key, session = terminal_state_mcp_client
    _org, product = await _seed_org_product(session, tenant_key)
    project = await _seed_project(session, tenant_key, product.id)
    job, execution = await _seed_specialist(session, tenant_key, project.id, status="silent")
    await session.commit()

    async with client() as mcp_session:
        result = await mcp_session.call_tool("close_job", {"job_id": job.job_id})

    text = _content_text(result)
    assert result.isError, f"close_job on a 'silent' execution must still refuse (gate kept), got: {text!r}"
    assert "silent" in text, f"the refusal must name the actual status, got: {text!r}"
    assert "complete_job" in text, (
        "close_job's wrong-state refusal must NAME the complete_job recovery for a "
        f"still-completable execution — otherwise the orchestrator's only visible exit is "
        f"force-decommission. Got: {text!r}"
    )

    await session.refresh(execution)
    assert execution.status == "silent", f"a refused close_job must not mutate the execution, got: {execution.status!r}"


# ---------------------------------------------------------------------------
# Case 2 — the accepting path reaches 'closed', never 'decommissioned'
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_silent_job_with_verified_deliverable_reaches_closed_not_decommissioned(terminal_state_mcp_client):
    """The recovery the fix documents, driven end-to-end through the MCP
    transport by the orchestrator (not by the stalled agent, which is gone):
    complete_job then close_job on a 'silent' execution reaches 'closed'.

    'closed' is an ACCEPTING terminal state — ``close_job`` is "final acceptance
    by orchestrator". 'decommissioned' is the failure label. This pins that the
    accepting exit exists and is reachable, so no future change to the
    non-terminal status predicate can quietly remove it and send orchestrators
    back to force-decommission.
    """
    client, tenant_key, session = terminal_state_mcp_client
    _org, product = await _seed_org_product(session, tenant_key)
    project = await _seed_project(session, tenant_key, product.id)
    job, execution = await _seed_specialist(session, tenant_key, project.id, status="silent")
    await session.commit()

    async with client() as mcp_session:
        complete_result = await mcp_session.call_tool(
            "complete_job",
            {"job_id": job.job_id, "result": _VERIFIED_RESULT},
        )
        complete_text = _content_text(complete_result)
        assert not complete_result.isError, (
            f"complete_job must accept a 'silent' execution ('silent' is not terminal), got: {complete_text!r}"
        )

        close_result = await mcp_session.call_tool("close_job", {"job_id": job.job_id})
        close_text = _content_text(close_result)
        assert not close_result.isError, f"close_job must accept the now-complete execution, got: {close_text!r}"

    await session.refresh(execution)
    assert execution.status == "closed", (
        f"a stalled-but-successful agent must reach the ACCEPTING terminal state, got: {execution.status!r}"
    )
    assert execution.status != "decommissioned", "an audited, committed contributor must never be labelled a failure"
    assert execution.result == _VERIFIED_RESULT, (
        f"the verified deliverable must be recorded on the execution row, got: {execution.result!r}"
    )


# ---------------------------------------------------------------------------
# Case 3 — two-sided: the hint must not be offered where it cannot work
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_close_job_on_decommissioned_execution_does_not_offer_complete_job_recovery(terminal_state_mcp_client):
    """'decommissioned' IS terminal — complete_job refuses it outright
    ("was decommissioned and cannot transition to 'completed'"). The recovery
    hint must therefore NOT appear here, or it would send an orchestrator into a
    second dead end. Scopes the fix to still-completable executions.
    """
    client, tenant_key, session = terminal_state_mcp_client
    _org, product = await _seed_org_product(session, tenant_key)
    project = await _seed_project(session, tenant_key, product.id)
    job, _execution = await _seed_specialist(session, tenant_key, project.id, status="decommissioned")
    await session.commit()

    async with client() as mcp_session:
        result = await mcp_session.call_tool("close_job", {"job_id": job.job_id})

    text = _content_text(result)
    assert result.isError, f"close_job on a decommissioned execution must refuse, got: {text!r}"
    assert "complete_job" not in text, (
        "a decommissioned execution cannot be recovered by complete_job — offering it "
        f"would be a second dead end. Got: {text!r}"
    )


# ---------------------------------------------------------------------------
# Case 3b — two-sided: a LIVE agent must not be completed out from under itself
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_close_job_on_working_execution_does_not_offer_complete_job_recovery(terminal_state_mcp_client):
    """A 'working' agent is alive and will report its own completion. Telling an
    orchestrator to call complete_job on it would be worse advice than the dead
    end this fix replaces — it invites completing a live agent's job out from
    under it. Only the unattended ('silent') case gets the recovery; everything
    still-reachable keeps the generic diagnose_project_state guidance.
    """
    client, tenant_key, session = terminal_state_mcp_client
    _org, product = await _seed_org_product(session, tenant_key)
    project = await _seed_project(session, tenant_key, product.id)
    job, _execution = await _seed_specialist(session, tenant_key, project.id, status="working")
    await session.commit()

    async with client() as mcp_session:
        result = await mcp_session.call_tool("close_job", {"job_id": job.job_id})

    text = _content_text(result)
    assert result.isError, f"close_job on a 'working' execution must refuse, got: {text!r}"
    assert "complete_job" not in text, (
        f"a live 'working' agent must NOT be offered the complete-it-yourself recovery, got: {text!r}"
    )
    assert "diagnose_project_state" in text, f"a reachable agent keeps the generic guidance, got: {text!r}"


# ---------------------------------------------------------------------------
# Case 4 — why the documented recovery must start at report_progress
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_silent_job_with_stranded_todos_is_completion_blocked_naming_the_todos(terminal_state_mcp_client):
    """A stalled agent leaves its TODO ledger mid-flight (the incident stranded
    six). ``complete_job`` still enforces the TODOs gate on a 'silent'
    execution, so "just call complete_job" is NOT a sufficient recovery — the
    orchestrator must settle the ledger with ``report_progress`` first.

    Pinned mechanically so the guidance the fix ships cannot drift from the gate
    it describes.
    """
    client, tenant_key, session = terminal_state_mcp_client
    _org, product = await _seed_org_product(session, tenant_key)
    project = await _seed_project(session, tenant_key, product.id)
    job, execution = await _seed_specialist(session, tenant_key, project.id, status="silent")
    await _seed_todo(session, tenant_key, job.job_id, "Wire the guard into the service layer")
    await session.commit()

    async with client() as mcp_session:
        result = await mcp_session.call_tool(
            "complete_job",
            {"job_id": job.job_id, "result": _VERIFIED_RESULT},
        )

    text = _content_text(result)
    assert result.isError, f"an incomplete TODO must still block complete_job on a silent job, got: {text!r}"
    assert "COMPLETION_BLOCKED" in text, f"the rejection must carry the COMPLETION_BLOCKED code, got: {text!r}"
    assert "Wire the guard into the service layer" in text, (
        f"the rejection must name the stranded TODO so the orchestrator can settle it, got: {text!r}"
    )

    await session.refresh(execution)
    assert execution.status == "silent", (
        f"a blocked complete_job must not mutate the execution, got: {execution.status!r}"
    )


# ---------------------------------------------------------------------------
# Case 4b (audit F2) — the wall must name the tool that clears it
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_completion_blocked_names_report_progress_and_speaks_to_the_orchestrator(
    terminal_state_mcp_client,
):
    """AUDIT_9292B F2: COMPLETION_BLOCKED listed the stranded TODOs and named NO tool.

    This is the wall an orchestrator hits while running the documented recovery for a
    stalled agent, so a rejection that only says "these TODOs are open" leaves it having
    to already know that ``report_progress`` exists and that it may drive another agent's
    ledger. It also addressed the caller as the agent whose ledger it is ("*your*
    coordination thread") — wrong for an orchestrator acting on behalf of a dead one.

    Pins the remedy, not just the diagnosis.
    """
    client, tenant_key, session = terminal_state_mcp_client
    _org, product = await _seed_org_product(session, tenant_key)
    project = await _seed_project(session, tenant_key, product.id)
    job, _execution = await _seed_specialist(session, tenant_key, project.id, status="silent")
    await _seed_todo(session, tenant_key, job.job_id, "Wire the guard into the service layer")
    await session.commit()

    async with client() as mcp_session:
        result = await mcp_session.call_tool(
            "complete_job",
            {"job_id": job.job_id, "result": _VERIFIED_RESULT},
        )

    text = _content_text(result)
    assert result.isError, f"an incomplete TODO must still block complete_job, got: {text!r}"
    assert "report_progress" in text, f"COMPLETION_BLOCKED must name the tool that settles the ledger, got: {text!r}"
    assert "replace" in text, (
        "replace=true is the load-bearing argument — without it the orchestrator cannot "
        f"rewrite a stalled agent's ledger to its honest final state. Got: {text!r}"
    )
    # An orchestrator acting for a dead agent must not be told to drain "your" thread.
    assert "your coordination thread" not in text, (
        f"COMPLETION_BLOCKED must not address the caller as the agent whose ledger it is, got: {text!r}"
    )
