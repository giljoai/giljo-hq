# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import json
import random
from datetime import UTC, datetime
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import select

from giljo_mcp import platform_registry
from giljo_mcp.exceptions import ImplementationNotReadyError
from giljo_mcp.models.agent_identity import AgentExecution, AgentJob
from giljo_mcp.models.organizations import Organization
from giljo_mcp.models.products import Product
from giljo_mcp.models.projects import Project
from giljo_mcp.models.sequence_runs import SequenceRun
from giljo_mcp.services.project_staging_service import ProjectStagingService
from giljo_mcp.tenant import TenantManager
from giljo_mcp.tools.tool_accessor._project_tools import (
    _STAGING_CHAIN_CONTINUE_INSTRUCTION,
    _STAGING_STOP_INSTRUCTION,
)
from tests.helpers.mcp_session_fixture import create_connected_server_and_client_session


pytestmark = pytest.mark.asyncio




def _payload(call_tool_result) -> dict:
    if getattr(call_tool_result, "structuredContent", None):
        return call_tool_result.structured_content
    first_block = call_tool_result.content[0]
    text = getattr(first_block, "text", None)
    if text is None:
        raise AssertionError(f"unexpected content block: {first_block!r}")
    return json.loads(text)


def _error_text(call_tool_result) -> str:
    parts = []
    for block in call_tool_result.content:
        text = getattr(block, "text", None)
        if text:
            parts.append(text)
    return "\n".join(parts)


async def _seed_product_project(
    db_session,
    tenant_key: str,
    *,
    staging_status: str | None = None,
    launched: bool = False,
    execution_mode: str = "claude_code_cli",
) -> dict:
    suffix = uuid4().hex[:8]
    org = Organization(name=f"Org {suffix}", slug=f"org-{suffix}", tenant_key=tenant_key, is_active=True)
    db_session.add(org)
    await db_session.flush()

    product = Product(
        id=str(uuid4()),
        name=f"Product {suffix}",
        description="INF-6049b lifecycle-tool tests",
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
        name=f"Project {suffix}",
        description="x",
        mission="x",
        status="active",
        execution_mode=execution_mode,
        staging_status=staging_status,
        implementation_launched_at=datetime.now(UTC) if launched else None,
        series_number=random.randint(1, 9000),
    )
    db_session.add(project)
    await db_session.commit()
    return {"project": project, "product": product}


async def _seed_orchestrator_and_agent(db_session, tenant_key: str, project) -> dict:
    orch_job = AgentJob(
        job_id=str(uuid4()),
        tenant_key=tenant_key,
        project_id=project.id,
        job_type="orchestrator",
        mission="orchestrate",
        status="active",
        created_at=datetime.now(UTC),
    )
    db_session.add(orch_job)
    await db_session.flush()

    orch_exec = AgentExecution(
        id=str(uuid4()),
        agent_id=str(uuid4()),
        job_id=orch_job.job_id,
        tenant_key=tenant_key,
        agent_display_name="orchestrator",
        status="idle",
        started_at=datetime.now(UTC),
    )
    db_session.add(orch_exec)
    await db_session.flush()

    child_job = AgentJob(
        job_id=str(uuid4()),
        tenant_key=tenant_key,
        project_id=project.id,
        job_type="implementer",
        mission="implement",
        status="active",
        created_at=datetime.now(UTC),
    )
    db_session.add(child_job)
    await db_session.flush()

    child_exec = AgentExecution(
        id=str(uuid4()),
        agent_id=str(uuid4()),
        job_id=child_job.job_id,
        tenant_key=tenant_key,
        agent_display_name="implementer",
        status="waiting",
        spawned_by=orch_exec.agent_id,
        started_at=datetime.now(UTC),
    )
    db_session.add(child_exec)
    await db_session.commit()
    return {"orchestrator": orch_exec, "child": child_exec}




@pytest_asyncio.fixture
async def primary_tenant_key() -> str:
    return TenantManager.generate_tenant_key()


@pytest_asyncio.fixture
async def secondary_tenant_key() -> str:
    return TenantManager.generate_tenant_key()


class _TenantSwitch:
    def __init__(self, value: str):
        self.value = value


class _CapturingWebSocketManager:

    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def broadcast_to_tenant(self, tenant_key: str, event_type: str, data: dict) -> None:
        self.calls.append({"tenant_key": tenant_key, "event_type": event_type, "data": data})

    def is_available(self) -> bool:
        return True

    def events(self, event_type: str) -> list[dict]:
        return [c for c in self.calls if c["event_type"] == event_type]

    def event_types(self) -> list[str]:
        return [c["event_type"] for c in self.calls]


@pytest_asyncio.fixture
async def ws_spy() -> _CapturingWebSocketManager:
    return _CapturingWebSocketManager()


@pytest_asyncio.fixture
async def lifecycle_mcp_client(db_manager, db_session, primary_tenant_key, ws_spy, monkeypatch):
    from api import app_state
    from api.endpoints import mcp_sdk_server
    from api.endpoints.mcp_tools import _base
    from giljo_mcp.tools.tool_accessor import ToolAccessor

    state = app_state.state
    prior_tool_accessor = state.tool_accessor
    prior_tenant_manager = state.tenant_manager
    prior_db_manager = state.db_manager

    if state.tenant_manager is None:
        state.tenant_manager = TenantManager()
    state.db_manager = db_manager

    state.tool_accessor = ToolAccessor(
        db_manager=db_manager,
        tenant_manager=state.tenant_manager,
        test_session=db_session,
        websocket_manager=ws_spy,
    )

    tenant_switch = _TenantSwitch(primary_tenant_key)
    monkeypatch.setattr(_base, "_resolve_tenant", lambda ctx: tenant_switch.value)
    monkeypatch.setattr(_base, "_resolve_user_id", lambda ctx: None)

    def _new_client():
        return create_connected_server_and_client_session(mcp_sdk_server.mcp)

    try:
        yield _new_client, tenant_switch
    finally:
        state.tool_accessor = prior_tool_accessor
        state.tenant_manager = prior_tenant_manager
        state.db_manager = prior_db_manager




async def test_stage_project_through_transport_returns_prompt_and_stops(
    lifecycle_mcp_client, db_session, primary_tenant_key
):
    new_client, _switch = lifecycle_mcp_client
    seeded = await _seed_product_project(db_session, primary_tenant_key)

    async with new_client() as session:
        result = await session.call_tool("stage_project", {"project_id": seeded["project"].id, "mode": "claude"})

    assert result.is_error is False, _error_text(result)
    payload = _payload(result)
    assert payload["status"] == "staged"
    assert payload["mode"] == "claude"
    assert payload["execution_mode"] == "subagent"
    assert payload["prompt"], "staging prompt must be non-empty"
    assert payload["orchestrator_id"]
    assert payload["estimated_prompt_tokens"] > 0
    assert "STOP" in payload["next_action"]["why"]
    assert "Implement" in payload["next_action"]["why"]

    row = (await db_session.execute(select(Project).where(Project.id == seeded["project"].id))).scalar_one()
    assert row.staging_status == "staged"
    assert row.execution_mode == "subagent"


@pytest.mark.parametrize(
    "mode,expected_execution_mode",
    [
        ("multi_terminal", "multi_terminal"),
        ("subagent", "subagent"),
        ("claude", "subagent"),
        ("codex", "subagent"),
        ("gemini", "subagent"),
        ("antigravity", "subagent"),
    ],
)
async def test_stage_project_mode_matrix_all_non_empty(
    lifecycle_mcp_client, db_session, primary_tenant_key, mode, expected_execution_mode
):
    new_client, _switch = lifecycle_mcp_client
    seeded = await _seed_product_project(db_session, primary_tenant_key, execution_mode=None)

    async with new_client() as session:
        result = await session.call_tool("stage_project", {"project_id": seeded["project"].id, "mode": mode})

    assert result.is_error is False, _error_text(result)
    payload = _payload(result)
    assert payload["prompt"], f"mode {mode} produced an empty prompt"
    assert payload["execution_mode"] == expected_execution_mode
    assert "STOP" in payload["next_action"]["why"]


async def test_stage_project_invalid_mode_rejected_at_boundary(lifecycle_mcp_client, db_session, primary_tenant_key):
    new_client, _switch = lifecycle_mcp_client
    seeded = await _seed_product_project(db_session, primary_tenant_key)

    async with new_client() as session:
        result = await session.call_tool("stage_project", {"project_id": seeded["project"].id, "mode": "bogus"})

    assert result.is_error is True, "invalid mode must be rejected (Literal boundary validation)"




async def test_stage_project_calls_owning_service_not_a_raw_write(lifecycle_mcp_client, db_session, primary_tenant_key):
    from unittest.mock import patch

    from giljo_mcp.services.project_staging_service import ProjectStagingService

    new_client, _switch = lifecycle_mcp_client
    seeded = await _seed_product_project(db_session, primary_tenant_key, execution_mode=None)

    with patch.object(
        ProjectStagingService, "mark_staged", wraps=ProjectStagingService.mark_staged, autospec=True
    ) as spy:
        async with new_client() as session:
            result = await session.call_tool("stage_project", {"project_id": seeded["project"].id, "mode": "claude"})

    assert result.is_error is False, _error_text(result)
    spy.assert_called_once()
    _self, called_project_id, called_execution_mode = spy.call_args.args
    called_kwargs = spy.call_args.kwargs
    assert called_project_id == seeded["project"].id
    assert called_execution_mode == "subagent"
    assert called_kwargs["tenant_key"] == primary_tenant_key
    assert called_kwargs["db_session"] is not None




async def _seed_active_chain_run(db_session, tenant_key: str, project_id: str) -> str:
    run = SequenceRun(
        id=str(uuid4()),
        tenant_key=tenant_key,
        project_ids=[project_id],
        resolved_order=[project_id],
        execution_mode="claude_code_cli",
        status="running",
        project_statuses={project_id: "pending"},
    )
    db_session.info["tenant_key"] = tenant_key
    db_session.add(run)
    await db_session.commit()
    return run.id


async def test_stage_project_solo_next_action_is_stop_byte_identical(
    lifecycle_mcp_client, db_session, primary_tenant_key
):
    new_client, _switch = lifecycle_mcp_client
    seeded = await _seed_product_project(db_session, primary_tenant_key)

    async with new_client() as session:
        result = await session.call_tool("stage_project", {"project_id": seeded["project"].id, "mode": "claude"})

    assert result.is_error is False, _error_text(result)
    why = _payload(result)["next_action"]["why"]
    assert "Implement" in why, "solo next_action must still state the human Implement gate"
    assert "wait for the user's explicit approval" in why, "solo must still stop for the human gate"
    assert "get_job_mission" not in why, "the chain continue wording must never reach a solo project"


async def test_stage_project_chain_member_continues_not_stop(lifecycle_mcp_client, db_session, primary_tenant_key):
    new_client, _switch = lifecycle_mcp_client
    seeded = await _seed_product_project(db_session, primary_tenant_key)
    await _seed_active_chain_run(db_session, primary_tenant_key, seeded["project"].id)

    async with new_client() as session:
        result = await session.call_tool("stage_project", {"project_id": seeded["project"].id, "mode": "claude"})

    assert result.is_error is False, _error_text(result)
    payload = _payload(result)
    why = payload["next_action"]["why"]
    assert _STAGING_CHAIN_CONTINUE_INSTRUCTION in why
    assert _STAGING_STOP_INSTRUCTION not in why
    assert "STOP HERE" not in why
    assert "MANUALLY press Implement" not in why
    assert "get_job_mission" in why
    assert payload["status"] == "staged"
    assert payload["prompt"], "staging prompt must still be produced on the chain path"




async def test_implement_project_gate_staging_incomplete(lifecycle_mcp_client, db_session, primary_tenant_key):
    new_client, _switch = lifecycle_mcp_client
    seeded = await _seed_product_project(db_session, primary_tenant_key, staging_status="staged", launched=False)

    async with new_client() as session:
        result = await session.call_tool("get_implementation_prompt", {"project_id": seeded["project"].id})

    assert result.is_error is False, _error_text(result)
    payload = _payload(result)
    assert payload["status"] == "gate_not_passed"
    assert payload["reason"] == "staging_incomplete"
    assert payload["next_action"]["tool"] == "stage_project"
    assert "stage_project" in payload["next_action"]["why"]


async def test_implement_project_gate_not_launched_names_dashboard_action(
    lifecycle_mcp_client, db_session, primary_tenant_key
):
    new_client, _switch = lifecycle_mcp_client
    seeded = await _seed_product_project(
        db_session, primary_tenant_key, staging_status="staging_complete", launched=False
    )

    async with new_client() as session:
        result = await session.call_tool("get_implementation_prompt", {"project_id": seeded["project"].id})

    assert result.is_error is False, _error_text(result)
    payload = _payload(result)
    assert payload["status"] == "gate_not_passed"
    assert payload["reason"] == "not_launched"
    assert payload["next_action"]["tool"] is None
    assert "Implement" in payload["next_action"]["why"]
    assert "dashboard" in payload["next_action"]["why"]

    row = (await db_session.execute(select(Project).where(Project.id == seeded["project"].id))).scalar_one()
    assert row.implementation_launched_at is None, "get_implementation_prompt must NEVER set implementation_launched_at"


async def test_implement_project_happy_path_returns_prompt_with_agent_seed(
    lifecycle_mcp_client, db_session, primary_tenant_key
):
    new_client, _switch = lifecycle_mcp_client
    seeded = await _seed_product_project(
        db_session,
        primary_tenant_key,
        staging_status="staging_complete",
        launched=True,
        execution_mode="multi_terminal",
    )
    seeded_team = await _seed_orchestrator_and_agent(db_session, primary_tenant_key, seeded["project"])

    async with new_client() as session:
        result = await session.call_tool("get_implementation_prompt", {"project_id": seeded["project"].id})

    assert result.is_error is False, _error_text(result)
    payload = _payload(result)
    assert payload["status"] == "ready"
    assert payload["prompt"], "implementation prompt must be non-empty"
    assert payload["agent_count"] >= 1
    assert payload["orchestrator_job_id"]
    orch_exec = seeded_team["orchestrator"]
    assert payload["orchestrator_job_id"] == orch_exec.job_id, "must return the orchestrator JOB id"
    assert payload["orchestrator_job_id"] != orch_exec.agent_id, "must NOT return the orchestrator agent_id"
    assert "PER-SESSION AGENT SEED" in payload["prompt"]
    assert "get_job_mission" in payload["prompt"]


async def test_implement_project_subagent_election_never_renders_multi_terminal_seed(
    lifecycle_mcp_client, db_session, primary_tenant_key
):
    new_client, _switch = lifecycle_mcp_client
    seeded = await _seed_product_project(
        db_session,
        primary_tenant_key,
        staging_status="staging_complete",
        launched=True,
        execution_mode="subagent",
    )
    await _seed_orchestrator_and_agent(db_session, primary_tenant_key, seeded["project"])

    async with new_client() as session:
        result = await session.call_tool("get_implementation_prompt", {"project_id": seeded["project"].id})

    assert result.is_error is False, _error_text(result)
    payload = _payload(result)
    assert payload["status"] == "ready"
    prompt = payload["prompt"]
    assert "PER-SESSION AGENT SEED" not in prompt, "subagent election leaked the multi_terminal seed"
    assert "Open a NEW SESSION" not in prompt, "subagent election leaked the multi_terminal seed"
    assert "get_job_mission" in prompt


@pytest.mark.parametrize("execution_mode", sorted(platform_registry.VALID_EXECUTION_MODES))
async def test_implement_project_mode_matrix_every_registry_mode_accepted(
    lifecycle_mcp_client, db_session, primary_tenant_key, execution_mode
):
    new_client, _switch = lifecycle_mcp_client
    seeded = await _seed_product_project(
        db_session,
        primary_tenant_key,
        staging_status="staging_complete",
        launched=True,
        execution_mode=execution_mode,
    )
    await _seed_orchestrator_and_agent(db_session, primary_tenant_key, seeded["project"])

    async with new_client() as session:
        result = await session.call_tool("get_implementation_prompt", {"project_id": seeded["project"].id})

    assert result.is_error is False, f"execution_mode={execution_mode!r}: {_error_text(result)}"
    payload = _payload(result)
    assert payload["status"] == "ready"
    assert payload["prompt"], f"execution_mode={execution_mode!r} produced an empty prompt"


async def test_implement_project_cross_tenant_not_found(
    lifecycle_mcp_client, db_session, primary_tenant_key, secondary_tenant_key
):
    new_client, switch = lifecycle_mcp_client
    switch.value = primary_tenant_key
    seeded = await _seed_product_project(
        db_session, primary_tenant_key, staging_status="staging_complete", launched=True
    )
    await _seed_orchestrator_and_agent(db_session, primary_tenant_key, seeded["project"])

    switch.value = secondary_tenant_key
    async with new_client() as session:
        result = await session.call_tool("get_implementation_prompt", {"project_id": seeded["project"].id})

    assert result.is_error is True, "TENANT LEAK: tenant B must not reach tenant A's project"
    err = _error_text(result).lower()
    assert "not found" in err or "tenant" in err, f"expected a tenant-isolation block, got: {err!r}"
    assert "gate_not_passed" not in err and "ready" not in err


async def test_implement_project_cross_tenant_returns_clean_not_found_no_guard_leak(
    lifecycle_mcp_client, db_session, primary_tenant_key, secondary_tenant_key
):
    new_client, switch = lifecycle_mcp_client
    switch.value = primary_tenant_key
    seeded = await _seed_product_project(
        db_session, primary_tenant_key, staging_status="staging_complete", launched=True
    )
    await _seed_orchestrator_and_agent(db_session, primary_tenant_key, seeded["project"])

    switch.value = secondary_tenant_key
    async with new_client() as session:
        result = await session.call_tool("get_implementation_prompt", {"project_id": seeded["project"].id})

    assert result.is_error is True, "TENANT LEAK: tenant B must not reach tenant A's project"
    err = _error_text(result)
    err_lower = err.lower()

    assert "not found" in err_lower, f"expected a clean not-found, got: {err!r}"

    for leak in ("ORM statement", "flush-derived", "Project", "Tenant context", "tenant_key"):
        assert leak not in err, f"tenant-guard internal leaked to the agent ({leak!r}): {err!r}"

    assert "unexpected internal error" not in err_lower, (
        f"cross-tenant block was sanitized to the generic 500 instead of clean not-found: {err!r}"
    )

    assert "gate_not_passed" not in err and '"ready"' not in err




async def test_stage_project_equivalent_to_rest_staging(lifecycle_mcp_client, db_session, primary_tenant_key):
    from unittest.mock import MagicMock

    from api.endpoints import prompts
    from giljo_mcp.services.project_service import ProjectService

    new_client, _switch = lifecycle_mcp_client
    seeded = await _seed_product_project(db_session, primary_tenant_key, execution_mode=None)

    current_user = MagicMock()
    current_user.id = uuid4()
    current_user.tenant_key = primary_tenant_key
    current_user.username = "equiv-user"

    ws_dep = MagicMock()
    ws_dep.is_available.return_value = False

    tenant_manager = MagicMock()
    tenant_manager.get_current_tenant.return_value = primary_tenant_key
    project_service = ProjectService(
        db_manager=MagicMock(),
        tenant_manager=tenant_manager,
        test_session=db_session,
    )

    rest_response = await prompts.generate_staging_prompt(
        project_id=seeded["project"].id,
        tool="claude-code",
        execution_mode="claude_code_cli",
        current_user=current_user,
        db=db_session,
        ws_dep=ws_dep,
        project_service=project_service,
    )

    async with new_client() as session:
        tool_result = await session.call_tool("stage_project", {"project_id": seeded["project"].id, "mode": "claude"})
    assert tool_result.is_error is False, _error_text(tool_result)
    tool_payload = _payload(tool_result)

    assert tool_payload["prompt"] == rest_response.prompt, (
        "stage_project staging prompt must be content-equivalent to GET /api/prompts/staging"
    )
    assert tool_payload["orchestrator_id"] == rest_response.orchestrator_id



_PROMPT_EVENT = "orchestrator:prompt_generated"

_IDENTITY_FIELDS = ("project_id", "orchestrator_id", "agent_id", "execution_id")


def _rest_staging_call(db_session, tenant_key: str, ws_dep):
    from unittest.mock import MagicMock

    from giljo_mcp.services.project_service import ProjectService

    current_user = MagicMock()
    current_user.id = uuid4()
    current_user.tenant_key = tenant_key
    current_user.username = "be9332-user"

    tenant_manager = MagicMock()
    tenant_manager.get_current_tenant.return_value = tenant_key

    return {
        "current_user": current_user,
        "db": db_session,
        "ws_dep": ws_dep,
        "project_service": ProjectService(
            db_manager=MagicMock(),
            tenant_manager=tenant_manager,
            test_session=db_session,
        ),
    }


async def test_be9332_mcp_stage_project_emits_orchestrator_prompt_generated(
    lifecycle_mcp_client, ws_spy, db_session, primary_tenant_key
):
    new_client, _switch = lifecycle_mcp_client
    seeded = await _seed_product_project(db_session, primary_tenant_key)

    async with new_client() as session:
        result = await session.call_tool("stage_project", {"project_id": seeded["project"].id, "mode": "claude"})

    assert result.is_error is False, _error_text(result)
    assert _payload(result)["status"] == "staged"

    emitted = ws_spy.events(_PROMPT_EVENT)
    assert len(emitted) == 1, (
        f"MCP stage_project must emit exactly one {_PROMPT_EVENT}; "
        f"got {len(emitted)}. All events seen: {ws_spy.event_types()}"
    )

    call = emitted[0]
    assert call["tenant_key"] == primary_tenant_key

    data = call["data"]
    for field in _IDENTITY_FIELDS:
        assert data.get(field), f"{_PROMPT_EVENT} payload is missing a non-empty {field!r}: {data!r}"
    assert data["project_id"] == seeded["project"].id
    assert data["thin_client"] is True
    assert data["product_id"] == seeded["product"].id


async def test_be9332_rest_and_mcp_prompt_payloads_agree(lifecycle_mcp_client, ws_spy, db_session, primary_tenant_key):
    from api.endpoints import prompts

    new_client, _switch = lifecycle_mcp_client
    seeded = await _seed_product_project(db_session, primary_tenant_key, execution_mode=None)

    rest_ws = _CapturingWebSocketManager()

    await prompts.generate_staging_prompt(
        project_id=seeded["project"].id,
        tool="claude-code",
        execution_mode="claude_code_cli",
        **_rest_staging_call(db_session, primary_tenant_key, rest_ws),
    )

    async with new_client() as session:
        tool_result = await session.call_tool("stage_project", {"project_id": seeded["project"].id, "mode": "claude"})
    assert tool_result.is_error is False, _error_text(tool_result)

    rest_events = rest_ws.events(_PROMPT_EVENT)
    mcp_events = ws_spy.events(_PROMPT_EVENT)

    assert len(rest_events) == 1, (
        f"REST staging must still emit exactly one {_PROMPT_EVENT} (DoD item 3: REST unchanged); "
        f"got {len(rest_events)}: {rest_ws.event_types()}"
    )
    assert len(mcp_events) == 1, f"MCP stage_project must emit exactly one {_PROMPT_EVENT}; got {len(mcp_events)}"

    rest_data = rest_events[0]["data"]
    mcp_data = mcp_events[0]["data"]

    for field in _IDENTITY_FIELDS:
        assert rest_data.get(field), f"REST payload lost {field!r} — regression: {rest_data!r}"
        assert mcp_data.get(field) == rest_data.get(field), (
            f"payload drift on {field!r}: MCP={mcp_data.get(field)!r} REST={rest_data.get(field)!r}"
        )

    assert mcp_events[0]["tenant_key"] == rest_events[0]["tenant_key"] == primary_tenant_key

    assert rest_data.get("product_id") == mcp_data.get("product_id") == seeded["product"].id


async def test_be9332_rest_orchestrator_thin_still_emits(db_session, primary_tenant_key):
    from api.endpoints import prompts
    from api.schemas.prompt import OrchestratorPromptRequest

    seeded = await _seed_product_project(db_session, primary_tenant_key)
    ws = _CapturingWebSocketManager()
    call = _rest_staging_call(db_session, primary_tenant_key, ws)

    await prompts.generate_orchestrator_prompt_thin(
        request=OrchestratorPromptRequest(project_id=seeded["project"].id, tool="claude-code"),
        current_user=call["current_user"],
        db=db_session,
        ws_dep=ws,
    )

    emitted = ws.events(_PROMPT_EVENT)
    assert len(emitted) == 1, (
        f"/prompts/orchestrator-thin must still emit exactly one {_PROMPT_EVENT}; "
        f"got {len(emitted)}: {ws.event_types()}"
    )
    data = emitted[0]["data"]
    assert emitted[0]["tenant_key"] == primary_tenant_key
    assert data["project_id"] == seeded["project"].id
    assert data["orchestrator_id"]
    assert data["execution_id"], "site A relies on execution_id as the store's unique_key"
    assert data["thin_client"] is True
    assert data["estimated_tokens"] >= 0
    assert data["timestamp"]
    assert data["product_id"] == seeded["product"].id
    assert "agent_id" not in data
    assert "tool" not in data


async def test_be9332_stage_project_without_websocket_manager_still_stages(
    db_manager, db_session, primary_tenant_key, monkeypatch
):
    from api import app_state
    from api.endpoints import mcp_sdk_server
    from api.endpoints.mcp_tools import _base
    from giljo_mcp.tools.tool_accessor import ToolAccessor

    state = app_state.state
    prior_tool_accessor = state.tool_accessor
    prior_tenant_manager = state.tenant_manager
    prior_db_manager = state.db_manager

    if state.tenant_manager is None:
        state.tenant_manager = TenantManager()
    state.db_manager = db_manager
    state.tool_accessor = ToolAccessor(
        db_manager=db_manager,
        tenant_manager=state.tenant_manager,
        test_session=db_session,
        websocket_manager=None,
    )
    monkeypatch.setattr(_base, "_resolve_tenant", lambda ctx: primary_tenant_key)
    monkeypatch.setattr(_base, "_resolve_user_id", lambda ctx: None)

    try:
        seeded = await _seed_product_project(db_session, primary_tenant_key)
        async with create_connected_server_and_client_session(mcp_sdk_server.mcp) as session:
            result = await session.call_tool("stage_project", {"project_id": seeded["project"].id, "mode": "claude"})

        assert result.is_error is False, _error_text(result)
        payload = _payload(result)
        assert payload["status"] == "staged"
        assert payload["prompt"]
    finally:
        state.tool_accessor = prior_tool_accessor
        state.tenant_manager = prior_tenant_manager
        state.db_manager = prior_db_manager


async def test_be9332_broadcast_failure_does_not_fail_staging(
    lifecycle_mcp_client, ws_spy, db_session, primary_tenant_key, monkeypatch
):

    async def _boom(**_kwargs):
        raise RuntimeError("simulated WebSocket failure")

    monkeypatch.setattr(ws_spy, "broadcast_to_tenant", _boom)

    new_client, _switch = lifecycle_mcp_client
    seeded = await _seed_product_project(db_session, primary_tenant_key)

    async with new_client() as session:
        result = await session.call_tool("stage_project", {"project_id": seeded["project"].id, "mode": "claude"})

    assert result.is_error is False, _error_text(result)
    payload = _payload(result)
    assert payload["status"] == "staged"
    assert payload["prompt"]

    row = (await db_session.execute(select(Project).where(Project.id == seeded["project"].id))).scalar_one()
    assert row.staging_status == "staged"


async def test_be9332_stage_returns_execution_id_for_frontend_map_key(
    lifecycle_mcp_client, db_session, primary_tenant_key
):
    new_client, _switch = lifecycle_mcp_client
    seeded = await _seed_product_project(db_session, primary_tenant_key)

    async with new_client() as session:
        result = await session.call_tool("stage_project", {"project_id": seeded["project"].id, "mode": "claude"})

    assert result.is_error is False, _error_text(result)
    payload = _payload(result)
    assert payload.get("execution_id"), f"stage_project payload must carry execution_id: {payload.keys()}"
    assert payload["execution_id"] != payload["orchestrator_id"]

    row = (
        await db_session.execute(select(AgentExecution).where(AgentExecution.id == payload["execution_id"]))
    ).scalar_one()
    assert row.tenant_key == primary_tenant_key




class _GateProject:
    def __init__(self, staging_status, implementation_launched_at):
        self.id = "p-gate"
        self.staging_status = staging_status
        self.implementation_launched_at = implementation_launched_at


async def test_check_implementation_allowed_staging_incomplete():
    with pytest.raises(ImplementationNotReadyError) as exc:
        ProjectStagingService.check_implementation_allowed(_GateProject("staged", None))
    assert exc.value.reason == "staging_incomplete"


async def test_check_implementation_allowed_not_launched():
    with pytest.raises(ImplementationNotReadyError) as exc:
        ProjectStagingService.check_implementation_allowed(_GateProject("staging_complete", None))
    assert exc.value.reason == "not_launched"
    assert exc.value.message == "Implementation has not been launched yet for this project."


async def test_check_implementation_allowed_passes_when_both_set():
    ProjectStagingService.check_implementation_allowed(_GateProject("staging_complete", datetime.now(UTC)))




async def test_be9622_stage_project_start_is_phased_not_a_stop(lifecycle_mcp_client, db_session, primary_tenant_key):
    new_client, _switch = lifecycle_mcp_client
    seeded = await _seed_product_project(db_session, primary_tenant_key)

    async with new_client() as session:
        result = await session.call_tool("stage_project", {"project_id": seeded["project"].id, "mode": "claude"})

    assert result.is_error is False, _error_text(result)
    next_action = _payload(result)["next_action"]
    assert next_action["tool"] == "health_check", (
        f"the START response must point at the first phase, not nowhere: {next_action!r}"
    )
    why = next_action["why"]
    assert not why.startswith("STAGING COMPLETE"), (
        f"the response that STARTS staging must not announce staging is complete: {why!r}"
    )
    for phase_marker in ("(1)", "(2)", "(3)", "(4)", "(5)"):
        assert phase_marker in why, f"phase {phase_marker} missing from the staging phases: {why!r}"
    assert "get_staging_instructions" in why
    assert "complete_job" in why
    assert "does not mean staging is complete" in why


async def test_be9622_chain_start_defers_get_job_mission_to_the_end(
    lifecycle_mcp_client, db_session, primary_tenant_key
):
    new_client, _switch = lifecycle_mcp_client
    seeded = await _seed_product_project(db_session, primary_tenant_key)
    await _seed_active_chain_run(db_session, primary_tenant_key, seeded["project"].id)

    async with new_client() as session:
        result = await session.call_tool("stage_project", {"project_id": seeded["project"].id, "mode": "claude"})

    assert result.is_error is False, _error_text(result)
    next_action = _payload(result)["next_action"]
    assert next_action["tool"] == "health_check"
    why = next_action["why"]
    assert not why.startswith("STAGING COMPLETE"), why
    assert "get_job_mission" in why, "the chain continue instruction must survive, at the END"
    assert why.index("get_job_mission") > why.index("(5)"), (
        "get_job_mission must be reached only in the final phase, not before staging starts"
    )
    assert "MANUALLY press Implement" not in why


async def test_be9622_implementation_gate_refusal_carries_the_stop_text(
    lifecycle_mcp_client, db_session, primary_tenant_key
):
    new_client, _switch = lifecycle_mcp_client
    seeded = await _seed_product_project(
        db_session, primary_tenant_key, staging_status="staging_complete", launched=False
    )
    await _seed_orchestrator_and_agent(db_session, primary_tenant_key, seeded["project"])

    async with new_client() as session:
        result = await session.call_tool("get_implementation_prompt", {"project_id": seeded["project"].id})

    assert result.is_error is False, _error_text(result)
    payload = _payload(result)
    assert payload["status"] == "gate_not_passed"
    assert payload["reason"] == "not_launched"
    assert _STAGING_STOP_INSTRUCTION in payload["next_action"]["why"], (
        "the gate refusal must carry the STAGING COMPLETE -- STOP HERE text verbatim"
    )
