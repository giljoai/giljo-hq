# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-9333 MCP-boundary regression: an agent whose template does not resolve
must SAY SO instead of silently handing back a generic agent.

Two independent code paths lose the requested identity, and both are exercised
here through the real FastMCP transport (the BE-5042 rule: the agent-facing
surface is the ``@mcp.tool`` wrapper, so a service test alone is insufficient).

PATH 1 -- spawn-time name resolution
``JobLifecycleService._validate_spawn_agent`` skips the template allowlist
entirely when ``agent_display_name == "orchestrator"``
(``job_lifecycle_service.py:533``). ``_resolve_spawn_template`` then finds no
template, stores ``template_id=None``, and the spawn SUCCEEDS. Because
``AgentJob.job_type`` is the display name verbatim
(``job_lifecycle_service.py:728``), the job reads back as an orchestrator and
``MissionService`` composes the DEFAULT orchestrator identity for it
(``mission_service.py:583``). The caller asked for agent X and received a
generic orchestrator, with nothing in ``SpawnResult`` saying so.

The bypass itself is load-bearing and must stay: no ``orchestrator`` template
row is ever seeded (``template_seeder.seed_tenant_templates`` skips the
system-managed role), so the documented chain sub-orchestrator spawn
``spawn_job(agent_display_name="orchestrator", agent_name="orchestrator")``
(``chapters_chain.py:343``/``:386``) resolves no template BY DESIGN. Hence the
third test below, which pins that the sentinel still spawns.

PATH 2 -- read-time template resolution (the live exposure)
``MissionService._resolve_mission_template`` looks the bound template up by id
and ``get_template_by_id`` filters ``deleted_at IS NULL``
(``mission_repository.py:135``). A job spawned against a healthy template
therefore DEGRADES while running the moment a user trashes that template:
``AgentJob.template_id`` is not cleared at soft-delete, so the next
``get_job_mission`` returns ``agent_identity: null`` with ``blocked: false``
and ``error: null`` -- a running specialist silently loses its role framing.

Pattern: tests/integration/test_be9325_spawn_boundary_trashed_template.py.

Project: BE-9333.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from mcp.shared.memory import create_connected_server_and_client_session
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.models import Project
from giljo_mcp.models.agent_identity import AgentJob
from giljo_mcp.models.templates import AgentTemplate
from giljo_mcp.tenant import TenantManager


pytestmark = pytest.mark.asyncio


async def _seed_project(session: AsyncSession, tenant_key: str) -> str:
    """An ACTIVE project past the implementation gate, so get_job_mission renders."""
    suffix = uuid.uuid4().hex[:8]
    project = Project(
        id=str(uuid.uuid4()),
        name=f"BE-9333 Boundary {suffix}",
        description="MCP-boundary unresolved-identity project.",
        mission="Stage then write.",
        status="active",
        tenant_key=tenant_key,
        series_number=1,
        execution_mode="multi_terminal",
        created_at=datetime.now(UTC),
        implementation_launched_at=datetime.now(UTC),
    )
    session.add(project)
    session.info["tenant_key"] = tenant_key
    await session.flush()
    return project.id


async def _seed_live_template(session: AsyncSession, tenant_key: str) -> str:
    """A healthy, spawnable template -- the agent the user actually asked for."""
    name = f"be9333-live-{uuid.uuid4().hex[:8]}"
    session.add(
        AgentTemplate(
            id=str(uuid.uuid4()),
            tenant_key=tenant_key,
            name=name,
            role="implementer",
            category="custom",
            system_instructions="sys",
            user_instructions="You implement backend changes with tests first.",
            is_active=True,
        )
    )
    await session.flush()
    return name


async def _seed_user_template_named_orchestrator(session: AsyncSession, tenant_key: str) -> None:
    """A user-created template whose NAME is 'orchestrator'.

    Nothing prevents this: every ``SYSTEM_MANAGED_ROLES`` gate in the codebase keys on a
    template's ``role`` (``template_service.py:468``, ``template_repository.py:332``,
    ``templates/crud.py:42``, ``template_seeder.py:125``), never on its ``name``. So the
    documented chain sub-orchestrator spawn -- which passes ``agent_name="orchestrator"``
    expecting to bind nothing -- binds THIS row instead.
    """
    session.add(
        AgentTemplate(
            id=str(uuid.uuid4()),
            tenant_key=tenant_key,
            name="orchestrator",
            role="implementer",
            category="custom",
            system_instructions="sys",
            user_instructions="House orchestrator rules the user wrote themselves.",
            is_active=True,
        )
    )
    await session.flush()


async def _soft_delete_template(session: AsyncSession, tenant_key: str, name: str) -> None:
    """Trash a template exactly as the templates UI does: stamp deleted_at, leave is_active."""
    row = (
        await session.execute(
            select(AgentTemplate).where(
                AgentTemplate.tenant_key == tenant_key,
                AgentTemplate.name == name,
                AgentTemplate.deleted_at.is_(None),
            )
        )
    ).scalar_one()
    row.deleted_at = datetime.now(UTC)
    await session.flush()


@pytest_asyncio.fixture
async def spawn_boundary_client(monkeypatch, db_manager, db_session):
    """In-memory FastMCP client wired to a REAL ToolAccessor on the test session."""
    from api import app_state
    from api.endpoints import mcp_sdk_server
    from giljo_mcp.tools.tool_accessor import ToolAccessor

    state = app_state.state
    prior_tool_accessor = state.tool_accessor
    prior_tenant_manager = state.tenant_manager
    prior_db_manager = state.db_manager

    tenant_manager = TenantManager()
    state.tenant_manager = tenant_manager
    state.db_manager = db_manager
    state.tool_accessor = ToolAccessor(
        db_manager=db_manager,
        tenant_manager=tenant_manager,
        test_session=db_session,
    )

    tenant_key = TenantManager.generate_tenant_key()
    from api.endpoints.mcp_tools import _base

    monkeypatch.setattr(_base, "_resolve_tenant", lambda ctx: tenant_key)
    monkeypatch.setattr(_base, "_resolve_user_id", lambda ctx: None)

    async def _noop(*args, **kwargs):
        return None

    monkeypatch.setattr("giljo_mcp.services.silence_detector.auto_clear_silent", _noop)
    monkeypatch.setattr("giljo_mcp.services.heartbeat.touch_heartbeat", _noop)

    def _new_client():
        return create_connected_server_and_client_session(mcp_sdk_server.mcp)

    try:
        yield _new_client, tenant_key, db_session
    finally:
        state.tool_accessor = prior_tool_accessor
        state.tenant_manager = prior_tenant_manager
        state.db_manager = prior_db_manager


def _payload(call_tool_result) -> dict:
    if getattr(call_tool_result, "structuredContent", None):
        return call_tool_result.structuredContent
    return json.loads(call_tool_result.content[0].text)


def _error_text(call_tool_result) -> str:
    return "\n".join(getattr(b, "text", "") or "" for b in call_tool_result.content)


async def test_spawn_job_rejects_an_unresolvable_name_on_the_orchestrator_door(spawn_boundary_client) -> None:
    """PATH 1: the orchestrator door must not silently swap the requested agent
    for the default orchestrator.

    ``agent_display_name="orchestrator"`` bypasses the template allowlist, so a
    name that resolves to nothing is accepted, a job is created with
    ``template_id`` NULL, and the agent reads back the composed DEFAULT
    orchestrator identity. The caller has no way to detect that the agent it
    asked for was never bound -- ``blocked`` is false, ``error`` is null, and
    the dashboard looks healthy.
    """
    new_client, tenant_key, db_session = spawn_boundary_client
    project_id = await _seed_project(db_session, tenant_key)
    live_name = await _seed_live_template(db_session, tenant_key)
    missing_name = f"be9333-missing-{uuid.uuid4().hex[:8]}"

    async with new_client() as session:
        result = await session.call_tool(
            "spawn_job",
            {
                "agent_display_name": "orchestrator",
                "agent_name": missing_name,
                "project_id": project_id,
                "mission": "Do the work.",
            },
        )

    assert result.isError is True, (
        "spawn_job accepted an agent_name that resolves to no template. The caller asked for "
        f"'{missing_name}' and would silently receive the DEFAULT orchestrator identity instead. "
        f"Got: {_payload(result)!r}"
    )
    error_text = _error_text(result)
    assert missing_name in error_text, "The rejection must name the agent that was asked for."
    assert live_name in error_text, "The rejection must list the agents that DO exist, so the caller can self-correct."

    job_rows = await db_session.execute(select(AgentJob).where(AgentJob.tenant_key == tenant_key))
    assert job_rows.scalars().all() == [], (
        "spawn_job created a job row for an agent that does not exist. Nothing may be persisted "
        "for a spawn whose requested identity could never be bound."
    )


async def test_orchestrator_sentinel_still_spawns_without_a_template_row(spawn_boundary_client) -> None:
    """PATH 1 guard: closing the door must NOT break the by-design sentinel.

    ``seed_tenant_templates`` never creates an ``orchestrator`` row (it is a
    system-managed role), and the chain protocol tells every conductor to spawn
    its sub-orchestrator with ``agent_name="orchestrator"``. That spawn resolves
    no template on purpose and must keep succeeding.
    """
    new_client, tenant_key, db_session = spawn_boundary_client
    project_id = await _seed_project(db_session, tenant_key)

    async with new_client() as session:
        result = await session.call_tool(
            "spawn_job",
            {
                "agent_display_name": "orchestrator",
                "agent_name": "orchestrator",
                "project_id": project_id,
                "mission": "Drive this project.",
            },
        )

    assert result.isError is not True, (
        f"The orchestrator sentinel spawn was rejected -- this breaks every chain "
        f"sub-orchestrator spawn. Got: {_error_text(result)!r}"
    )
    assert _payload(result)["job_id"], "The sentinel spawn must return a real job."


async def test_get_job_mission_signals_a_template_deleted_after_binding(spawn_boundary_client) -> None:
    """PATH 2: a running specialist whose template is deleted must be TOLD.

    Spawn against a live template (healthy identity), then soft-delete that
    template exactly as the templates UI does. ``AgentJob.template_id`` is left
    pointing at the trashed row, ``get_template_by_id`` filters it out, and the
    next ``get_job_mission`` returns ``agent_identity: null`` with no flag, no
    note and no log -- the agent keeps working with no role framing and nothing
    connects the quality drop to the deletion.
    """
    new_client, tenant_key, db_session = spawn_boundary_client
    project_id = await _seed_project(db_session, tenant_key)
    live_name = await _seed_live_template(db_session, tenant_key)

    async with new_client() as session:
        spawned = _payload(
            await session.call_tool(
                "spawn_job",
                {
                    "agent_display_name": "implementer",
                    "agent_name": live_name,
                    "project_id": project_id,
                    "mission": "Do the work.",
                },
            )
        )
    job_id = spawned["job_id"]

    # Control: while the template is live the agent has a real identity.
    async with new_client() as session:
        healthy = _payload(await session.call_tool("get_job_mission", {"job_id": job_id}))
    assert healthy["agent_identity"], "Precondition failed: a live template must yield an identity."

    # The user tidies up an agent they believe is unused. Nothing warns them a live job is bound to it.
    template_row = (
        await db_session.execute(
            select(AgentTemplate).where(
                AgentTemplate.tenant_key == tenant_key,
                AgentTemplate.name == live_name,
            )
        )
    ).scalar_one()
    template_row.deleted_at = datetime.now(UTC)
    await db_session.flush()

    async with new_client() as session:
        degraded = _payload(await session.call_tool("get_job_mission", {"job_id": job_id}))

    assert degraded["agent_identity"], (
        "agent_identity came back empty after the bound template was deleted. The agent that was "
        "working a moment ago now has no role framing at all, and nothing in the response says so. "
        "A bound-then-deleted template must yield an explicit identity block, not a bare null."
    )
    assert "deleted" in degraded["agent_identity"].lower(), (
        "The identity block must say WHAT happened (the agent template was deleted) so the agent "
        f"can act on it. Got: {degraded['agent_identity']!r}"
    )
    assert degraded.get("identity_status") == "template_unresolved", (
        "get_job_mission gave no typed signal that the bound template no longer resolves, so no "
        f"caller can detect the degradation programmatically. Got: {degraded.get('identity_status')!r}"
    )
    # It is a degradation, not a stop: the agent must keep working on its mission.
    assert degraded.get("blocked") is not True, "A tidied-up template must not stop a running agent."
    # The key rides the wire ONLY when there is something to act on, so a healthy response
    # stays byte-identical and the key's PRESENCE is itself the signal.
    assert "identity_status" not in healthy, (
        f"A healthy response must not carry the degradation key. Got: {healthy.get('identity_status')!r}"
    )


async def _spawn_and_read(session_factory, payload: dict) -> tuple[str, dict]:
    """spawn_job then get_job_mission through the transport; return (job_id, mission payload)."""
    async with session_factory() as session:
        spawned = _payload(await session.call_tool("spawn_job", payload))
    job_id = spawned["job_id"]
    async with session_factory() as session:
        mission = _payload(await session.call_tool("get_job_mission", {"job_id": job_id}))
    return job_id, mission


async def test_orchestrator_typed_job_signals_a_deleted_specialist_template(spawn_boundary_client) -> None:
    """ROUTE (a): an orchestrator-TYPED job bound to a real template must not
    silently revert to the default orchestrator identity when that template goes.

    `agent_display_name="orchestrator"` makes `AgentJob.job_type` "orchestrator"
    (`job_lifecycle_service.py:728`), and the orchestrator fallback fires on
    `job_type` alone. So a job that WAS bound to a live specialist and lost it
    took the fallback -- composing the DEFAULT orchestrator identity and
    reporting `orchestrator_default`, which is stripped from the wire as healthy.
    The agent silently became a generic orchestrator: the exact defect BE-9333
    exists to kill, surviving on the one path job_type short-circuits.
    """
    new_client, tenant_key, db_session = spawn_boundary_client
    project_id = await _seed_project(db_session, tenant_key)
    live_name = await _seed_live_template(db_session, tenant_key)

    job_id, healthy = await _spawn_and_read(
        new_client,
        {
            "agent_display_name": "orchestrator",
            "agent_name": live_name,
            "project_id": project_id,
            "mission": "Drive this project.",
        },
    )
    assert "House orchestrator rules" not in (healthy["agent_identity"] or "")
    assert "identity_status" not in healthy, "Precondition: a bound, live template is healthy."

    await _soft_delete_template(db_session, tenant_key, live_name)

    async with new_client() as session:
        degraded = _payload(await session.call_tool("get_job_mission", {"job_id": job_id}))

    assert degraded.get("identity_status") == "template_unresolved", (
        "An orchestrator-typed job whose bound template was DELETED silently received the default "
        "orchestrator identity instead of a signal. job_type short-circuited the BE-9333 branch. "
        f"Got: {degraded.get('identity_status')!r}"
    )
    assert "deleted" in (degraded["agent_identity"] or "").lower(), (
        f"The identity block must name the cause. Got: {degraded['agent_identity']!r}"
    )
    assert degraded.get("blocked") is not True, "The signal must not stop a running agent."


async def test_documented_suborch_spawn_signals_a_deleted_user_template(spawn_boundary_client) -> None:
    """ROUTE (b): documented calls only.

    A user creates a template NAMED 'orchestrator' -- permitted, because every
    SYSTEM_MANAGED_ROLES gate keys on `role`, never on `name`. The documented chain
    sub-orchestrator spawn `spawn_job(agent_display_name="orchestrator",
    agent_name="orchestrator")` then BINDS that row rather than binding nothing.
    Delete it and the agent silently reverts to the seeded default orchestrator.
    """
    new_client, tenant_key, db_session = spawn_boundary_client
    project_id = await _seed_project(db_session, tenant_key)
    await _seed_user_template_named_orchestrator(db_session, tenant_key)

    job_id, healthy = await _spawn_and_read(
        new_client,
        {
            "agent_display_name": "orchestrator",
            "agent_name": "orchestrator",
            "project_id": project_id,
            "mission": "Drive this sub-project.",
        },
    )
    assert "House orchestrator rules" in (healthy["agent_identity"] or ""), (
        "Precondition failed: the documented sub-orch spawn did not bind the user's template, so "
        f"this route is not what it claims. Got: {healthy['agent_identity']!r:.200}"
    )

    await _soft_delete_template(db_session, tenant_key, "orchestrator")

    async with new_client() as session:
        degraded = _payload(await session.call_tool("get_job_mission", {"job_id": job_id}))

    assert degraded.get("identity_status") == "template_unresolved", (
        "Deleting the user's own 'orchestrator' template silently swapped in the seeded default. "
        f"Reached through documented calls only. Got: {degraded.get('identity_status')!r}"
    )
    assert "House orchestrator rules" not in (degraded["agent_identity"] or ""), (
        "The deleted template's prose must not survive its deletion."
    )


async def test_never_bound_orchestrator_still_gets_the_default_cleanly(spawn_boundary_client) -> None:
    """GUARD: the by-design case must stay silent.

    An orchestrator that was NEVER bound (no 'orchestrator' template row exists) is the
    normal, healthy case -- it must still compose the seeded default identity and must NOT
    carry a spurious degradation signal.
    """
    new_client, tenant_key, db_session = spawn_boundary_client
    project_id = await _seed_project(db_session, tenant_key)

    _job_id, mission = await _spawn_and_read(
        new_client,
        {
            "agent_display_name": "orchestrator",
            "agent_name": "orchestrator",
            "project_id": project_id,
            "mission": "Drive this project.",
        },
    )

    assert "identity_status" not in mission, (
        "A never-bound orchestrator is healthy by design and must carry no degradation key. "
        f"Got: {mission.get('identity_status')!r}"
    )
    assert "Orchestrator Agent" in (mission["agent_identity"] or ""), (
        f"The composed default orchestrator identity must still be delivered. Got: {mission['agent_identity']!r:.200}"
    )
