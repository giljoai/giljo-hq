# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-9402 MCP-boundary regression: the served identity block is gated on the
project's STORED execution-mode election.

``projects.execution_mode`` is a user election the server genuinely has (unlike
what sits on the client's disk). It decides whether ``get_job_mission`` ships the
agent's identity block:

===================  =====================  ==========================================
Election             identity block served  Why
===================  =====================  ==========================================
``subagent``         NO                     The election means "files carry the
                                            persona": the harness loads the installed
                                            ``gil-*`` / ``.claude/agents/*`` template at
                                            spawn, so serving it again double-feeds the
                                            same 1,300-2,400 tokens per agent.
``multi_terminal``   YES                    A launched terminal boots on the ~50-token
                                            prompt from ``build_loaded_prompt``
                                            (``launch_command_synth.py``). The server is
                                            its ONLY identity channel.
unset / unrecognised YES                    Fail-safe default -- never strand an agent
                                            because a mode was not chosen. (A NULL is
                                            blocked further upstream and never reaches
                                            the serve site at all; see the guard test.)
===================  =====================  ==========================================

Exercised through the real FastMCP transport, not the service: the agent-facing
surface is the ``@mcp.tool`` wrapper (the BE-5042 rule -- a fix that passes every
service test still ships broken when the boundary is untested).

FAIL-FIRST: against master the identity block is served unconditionally, so the
``subagent`` row below FAILS and the other two pass.

Fixture pattern: tests/integration/test_be9333_unresolved_agent_identity_boundary.py.

Project: BE-9402.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.models import Product, Project
from giljo_mcp.models.templates import AgentTemplate
from giljo_mcp.tenant import TenantManager
from tests.helpers.mcp_session_fixture import create_connected_server_and_client_session


pytestmark = pytest.mark.asyncio


# The distinctive prose only the SERVED identity block can carry. The installed
# template file is rendered from the same row, so asserting on this string is an
# assertion about the wire -- not about the template's existence.
_PERSONA_MARKER = "You implement backend changes with tests first."

# TSK-9323: one marker per COMPOSED FIELD. compose_template_identity reads three
# columns -- user_instructions, behavioral_rules, success_criteria -- and this suite
# used to mark only the first, so nothing anywhere pinned that the rules and criteria
# branches render at all: either could have been deleted with every row still green.
# Established by execution, not by reading: the TSK-9323 marker test planted a unique
# string in all three columns and observed all three arrive in a multi_terminal
# agent_identity.
_RULE_MARKER = "Never widen scope without a ruling."
_CRITERION_MARKER = "The regression test fails before the fix and passes after."

# The NEGATIVE channel. compose_template_identity excludes system_instructions on
# purpose -- the thin prompt already handles MCP bootstrap -- and that exclusion was
# likewise unpinned. Distinctive prose, not a short token: a three-letter value could
# pass this assertion as a substring of unrelated text and prove nothing.
_SYSTEM_ONLY_MARKER = "Bootstrap the MCP session before doing anything else."


async def _seed_project(session: AsyncSession, tenant_key: str, execution_mode: str) -> str:
    """An ACTIVE project past the implementation gate, at the given mode election.

    Always seeded with a VALID election: ``spawn_job`` refuses a project without one
    (``require_execution_mode``), so the legacy/unrecognised states are reached by
    rewriting the column after the spawn, exactly as they arise in a real database.
    """
    suffix = uuid.uuid4().hex[:8]
    # BE-9437: a project belongs to a product. Its own, so an active
    # seed cannot collide under idx_project_single_active_per_product.
    _owning_product_project = Product(
        id=str(uuid.uuid4()),
        tenant_key=tenant_key,
        name=f"Owning Product {uuid.uuid4().hex[:6]}",
        description="seeded",
        is_active=False,
    )
    session.add(_owning_product_project)
    project = Project(
        id=str(uuid.uuid4()),
        name=f"BE-9402 {execution_mode} {suffix}",
        description="MCP-boundary mode-elected-identity project.",
        mission="Stage then write.",
        status="active",
        tenant_key=tenant_key,
        product_id=_owning_product_project.id,
        series_number=1,
        execution_mode=execution_mode,
        created_at=datetime.now(UTC),
        implementation_launched_at=datetime.now(UTC),
    )
    session.add(project)
    session.info["tenant_key"] = tenant_key
    await session.flush()
    return project.id


async def _seed_live_template(session: AsyncSession, tenant_key: str) -> str:
    """A healthy, spawnable specialist template -- the persona under test."""
    name = f"be9402-live-{uuid.uuid4().hex[:8]}"
    session.add(
        AgentTemplate(
            id=str(uuid.uuid4()),
            tenant_key=tenant_key,
            name=name,
            role="implementer",
            category="custom",
            system_instructions=_SYSTEM_ONLY_MARKER,
            user_instructions=_PERSONA_MARKER,
            behavioral_rules=[_RULE_MARKER],
            success_criteria=[_CRITERION_MARKER],
            is_active=True,
        )
    )
    await session.flush()
    return name


@pytest_asyncio.fixture
async def mission_boundary_client(monkeypatch, db_manager, db_session):
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
        return call_tool_result.structured_content
    return json.loads(call_tool_result.content[0].text)


def _error_text(call_tool_result) -> str:
    return "\n".join(getattr(b, "text", "") or "" for b in call_tool_result.content)


async def _spawn_specialist_and_read_mission(session_factory, project_id: str, agent_name: str) -> dict:
    """spawn_job a bound specialist, then read its mission -- both through the transport."""
    async with session_factory() as session:
        spawn_result = await session.call_tool(
            "spawn_job",
            {
                "agent_display_name": "implementer",
                "agent_name": agent_name,
                "project_id": project_id,
                "mission": "Do the work.",
            },
        )
    assert spawn_result.is_error is not True, (
        f"Precondition: the spawn must succeed. Got: {_error_text(spawn_result)!r}"
    )
    job_id = _payload(spawn_result)["job_id"]

    async with session_factory() as session:
        mission = _payload(await session.call_tool("get_job_mission", {"job_id": job_id}))
    return mission


async def test_subagent_election_omits_the_identity_block(mission_boundary_client) -> None:
    """ROW 1 -- ``subagent``: the identity block must NOT be served.

    In subagent mode the orchestrator spawns each worker through its harness's
    own subagent mechanism, which loads the installed template file. That file is
    rendered from the very same template row, so serving the identity again hands
    the agent a byte-for-byte duplicate of what it already booted with -- measured
    at 1,300-2,400 tokens per agent, ~8-14k across a six-agent run.

    FAILS against master: the serve is unconditional there.
    """
    new_client, tenant_key, db_session = mission_boundary_client
    project_id = await _seed_project(db_session, tenant_key, "subagent")
    agent_name = await _seed_live_template(db_session, tenant_key)

    mission = await _spawn_specialist_and_read_mission(new_client, project_id, agent_name)

    assert not mission.get("agent_identity"), (
        "get_job_mission served the identity block to a SUBAGENT-mode agent. The mode election "
        "means the harness already loaded this persona from the installed template file, so the "
        "agent is being fed the same 1,300-2,400 tokens twice. Got "
        f"{len(mission.get('agent_identity') or '')} chars of identity."
    )
    assert _PERSONA_MARKER not in (mission.get("agent_identity") or ""), (
        "The template's own prose reached the wire in subagent mode -- this is the duplication itself."
    )
    # The omission is a deliberate election, NOT the BE-9333 degraded state. A healthy
    # template resolved fine, so no degradation key may ride the wire and alarm the agent.
    assert "identity_status" not in mission, (
        "Omitting the identity by mode election must not masquerade as a BE-9333 degradation. "
        f"Got: {mission.get('identity_status')!r}"
    )
    # Only the identity is withheld. The mission and protocol are how the agent works at all.
    assert mission.get("mission"), "Withholding the identity must never withhold the mission."
    assert mission.get("full_protocol"), "Withholding the identity must never withhold the protocol."
    # FE-9408: provenance describes the identity, so it must be withheld WITH it. A source
    # line on a response carrying no identity would attribute text this response did not
    # send, and would name a rung of the override ladder that the installed file the agent
    # is actually reading never consulted -- worse than silence, because it reads as an answer.
    assert "identity_source" not in mission, (
        "The identity was withheld but its provenance line rode the wire anyway. "
        f"Got: {mission.get('identity_source')!r}"
    )


async def test_multi_terminal_election_still_serves_the_identity_block(mission_boundary_client) -> None:
    """ROW 2 -- ``multi_terminal``: the identity block MUST still be served.

    A launched terminal boots on ``build_loaded_prompt``'s ~50-token natural-language
    prompt (``launch_command_synth.py``) -- "call get_job_mission and execute it".
    Nothing else reaches that process. Withhold the identity here and the agent runs
    with no role framing at all, which is the failure mode the mode gate exists to
    avoid, inverted.
    """
    new_client, tenant_key, db_session = mission_boundary_client
    project_id = await _seed_project(db_session, tenant_key, "multi_terminal")
    agent_name = await _seed_live_template(db_session, tenant_key)

    mission = await _spawn_specialist_and_read_mission(new_client, project_id, agent_name)

    assert mission.get("agent_identity"), (
        "A multi_terminal agent received NO identity block. Its terminal booted on a ~50-token "
        "prompt, so the server is its only identity channel -- it is now running with no role framing."
    )
    assert _PERSONA_MARKER in mission["agent_identity"], (
        f"The served identity must carry the bound template's own instructions. Got: {mission['agent_identity']!r:.300}"
    )
    # TSK-9323: all THREE composed fields must travel, not just user_instructions.
    # compose_template_identity has a separate branch per field; before this row asserted
    # them, the behavioral_rules and success_criteria branches were unpinned and could
    # have been deleted with this suite still green.
    assert _RULE_MARKER in mission["agent_identity"], (
        "The served identity dropped the template's behavioral_rules. A multi_terminal agent "
        f"boots on a ~50-token prompt, so it now has no behavioral constraints at all. "
        f"Got: {mission['agent_identity']!r:.300}"
    )
    assert _CRITERION_MARKER in mission["agent_identity"], (
        "The served identity dropped the template's success_criteria -- the agent does not know "
        f"what finished looks like. Got: {mission['agent_identity']!r:.300}"
    )
    # The exclusion is as load-bearing as the inclusions: system_instructions is deliberately
    # NOT composed (the thin prompt already handles MCP bootstrap). Serving it would re-feed
    # bootstrap prose to an agent that is already bootstrapped.
    assert _SYSTEM_ONLY_MARKER not in mission["agent_identity"], (
        "system_instructions reached the served identity. That field is excluded by design; "
        f"its presence is a separate defect from any of the above. Got: {mission['agent_identity']!r:.300}"
    )


async def test_unrecognised_election_falls_back_to_serving_the_identity_block(mission_boundary_client) -> None:
    """ROW 3 -- unset / unrecognised (the WO's "headless"): serve, fail-safe.

    Which state actually REACHES the serve site matters here, and the two halves of
    "NULL / unset / headless" arrive differently:

    * A **NULL** never reaches it. ``check_implementation_gate`` returns a blocked
      response first (``mission_implementation_gate.py:60``), so identity is never
      composed at all -- pinned by the guard test below.
    * An **unknown but non-empty** token DOES reach it, by explicit design:
      ``execution_mode_selected`` deliberately does not check membership, leaving an
      unrecognised mode to "the HO1020 render-layer fail-safes" rather than hard-blocking
      a legacy row (``execution_mode_gate.py:101-109``).

    So this row is the render-layer fail-safe, and the rule it pins is: omit ONLY on an
    explicit subagent election. Anything the server cannot positively identify as
    subagent gets served -- serving costs duplicate tokens at worst, withholding
    strands an agent with no persona at all.
    """
    new_client, tenant_key, db_session = mission_boundary_client
    project_id = await _seed_project(db_session, tenant_key, "multi_terminal")
    agent_name = await _seed_live_template(db_session, tenant_key)

    async with new_client() as session:
        spawn_result = await session.call_tool(
            "spawn_job",
            {
                "agent_display_name": "implementer",
                "agent_name": agent_name,
                "project_id": project_id,
                "mission": "Do the work.",
            },
        )
    assert spawn_result.is_error is not True, (
        f"Precondition: the spawn must succeed. Got: {_error_text(spawn_result)!r}"
    )
    job_id = _payload(spawn_result)["job_id"]

    # A legacy / unrecognised stored election, reaching the render layer exactly as
    # execution_mode_gate documents. The write boundaries keep NEW rows valid; this
    # models the old row they cannot retroactively fix.
    project_row = (
        await db_session.execute(select(Project).where(Project.id == project_id, Project.tenant_key == tenant_key))
    ).scalar_one()
    project_row.execution_mode = "headless"
    await db_session.flush()

    async with new_client() as session:
        mission = _payload(await session.call_tool("get_job_mission", {"job_id": job_id}))

    assert mission.get("blocked") is not True, (
        "Precondition: an unknown-but-non-empty mode must reach the render layer, not hard-block "
        f"(execution_mode_gate.py:101-109). Got: {mission.get('user_instruction')!r}"
    )
    assert mission.get("agent_identity"), (
        "A project whose election the server could not recognise received no identity block. Only an "
        "EXPLICIT subagent election may withhold it -- an unrecognised mode must fail SAFE and serve."
    )
    assert _PERSONA_MARKER in mission["agent_identity"], (
        f"The fail-safe serve must carry the real persona. Got: {mission['agent_identity']!r:.300}"
    )


async def test_subagent_election_still_serves_the_composed_orchestrator_identity(mission_boundary_client) -> None:
    """CARVE-OUT 1 — ``orchestrator_default`` is served even on a subagent election.

    The omission above is justified by "the installed file already carries this
    persona". That justification does not reach the orchestrator identity, for two
    independent reasons:

    * A subagent-mode orchestrator is the user's ROOT session. It is not spawned
      through the harness's subagent mechanism, so no file feeds it at all.
    * It is composed by ``compose_orchestrator_identity`` off
      ``resolve_orchestrator_override`` -- the BE-9385d product -> tenant -> seeded-default
      chain, plus the system harness block. That is tenant DATA resolved server-side;
      no file on the client's disk could carry it. Withholding it would not
      de-duplicate anything, it would silently delete the per-product orchestrator
      customization BE-9385d shipped.

    Pinned as a test rather than trusted to the comment: without this, deleting the
    ``identity_status`` term from ``should_serve_identity`` leaves every other test
    in this file green while stranding every subagent-mode orchestrator.
    """
    new_client, tenant_key, db_session = mission_boundary_client
    project_id = await _seed_project(db_session, tenant_key, "subagent")

    async with new_client() as session:
        spawned = await session.call_tool(
            "spawn_job",
            {
                "agent_display_name": "orchestrator",
                "agent_name": "orchestrator",
                "project_id": project_id,
                "mission": "Drive this project.",
            },
        )
    assert spawned.is_error is not True, f"Precondition: the sentinel spawn must succeed. {_error_text(spawned)!r}"
    job_id = _payload(spawned)["job_id"]

    async with new_client() as session:
        mission = _payload(await session.call_tool("get_job_mission", {"job_id": job_id}))

    assert mission.get("agent_identity"), (
        "A SUBAGENT-mode orchestrator received no identity block. Nothing else can give it one: "
        "it is the root session, so no installed file feeds it, and its identity is composed from "
        "server-side tenant data that no file could carry. It is now running with no role framing."
    )
    assert "Orchestrator Agent" in mission["agent_identity"], (
        f"The composed orchestrator identity must survive the mode gate. Got: {mission['agent_identity']!r:.300}"
    )
    assert "identity_status" not in mission, (
        f"The composed default is healthy by design and must carry no degradation key. "
        f"Got: {mission.get('identity_status')!r}"
    )


async def test_subagent_election_still_serves_a_degraded_identity_block(mission_boundary_client) -> None:
    """CARVE-OUT 2 — BE-9333's degradation report is served even on a subagent election.

    ``template_unresolved`` is not a persona; it is a four-line error report saying the
    bound template was deleted mid-run, and no installed file carries it. Withholding it
    would restore precisely the signal-less null that BE-9333 exists to remove -- an agent
    degrading silently with nothing connecting the quality drop to the deletion.

    So the omission is narrowed to the identity a file actually duplicates: a healthy
    bound-template persona (``resolved``).
    """
    new_client, tenant_key, db_session = mission_boundary_client
    project_id = await _seed_project(db_session, tenant_key, "subagent")
    agent_name = await _seed_live_template(db_session, tenant_key)

    async with new_client() as session:
        spawned = await session.call_tool(
            "spawn_job",
            {
                "agent_display_name": "implementer",
                "agent_name": agent_name,
                "project_id": project_id,
                "mission": "Do the work.",
            },
        )
    job_id = _payload(spawned)["job_id"]

    # The user trashes the template exactly as the templates UI does.
    template_row = (
        await db_session.execute(
            select(AgentTemplate).where(
                AgentTemplate.tenant_key == tenant_key,
                AgentTemplate.name == agent_name,
            )
        )
    ).scalar_one()
    template_row.deleted_at = datetime.now(UTC)
    await db_session.flush()

    async with new_client() as session:
        degraded = _payload(await session.call_tool("get_job_mission", {"job_id": job_id}))

    assert degraded.get("agent_identity"), (
        "The BE-9333 degradation block was withheld in subagent mode. That is not de-duplication -- "
        "no installed file carries this report -- it is a silent null, the exact state BE-9333 removed."
    )
    assert "deleted" in degraded["agent_identity"].lower(), (
        f"The served block must still name the cause. Got: {degraded['agent_identity']!r:.300}"
    )
    assert degraded.get("identity_status") == "template_unresolved", (
        f"The typed degradation signal must survive the mode gate. Got: {degraded.get('identity_status')!r}"
    )


async def test_legacy_generic_mcp_election_still_serves_the_identity_block(mission_boundary_client) -> None:
    """CARVE-OUT 3 -- ``generic_mcp`` is a subagent TOPOLOGY with no local file channel.

    ``is_subagent_mode("generic_mcp")`` is True, and correctly so: "no CLI -> subagent"
    is the right answer to the topology question, and the protocol body renders it that
    way. But gating IDENTITY on that answer would strand these sessions, because the two
    questions diverge here and only here:

    * generic_mcp has no CLI, so ``giljo_setup`` has nowhere to install ``gil-*`` files.
    * Its own shipped prose says so -- ``_CH3_GENERIC``: "Agent templates are served by
      the MCP server, not local files" -- and its topology is one session per job order
      seeded with a thin prompt, i.e. the multi_terminal situation.
    * These rows are real: the legacy tokens live in prod and CE self-hoster databases
      permanently, tolerated in code with no migration.

    Hence :func:`has_local_agent_file_channel`, a separate named question. This row fails
    if anyone "unifies" it back into ``is_subagent_mode``.
    """
    new_client, tenant_key, db_session = mission_boundary_client
    project_id = await _seed_project(db_session, tenant_key, "multi_terminal")
    agent_name = await _seed_live_template(db_session, tenant_key)

    async with new_client() as session:
        spawned = await session.call_tool(
            "spawn_job",
            {
                "agent_display_name": "implementer",
                "agent_name": agent_name,
                "project_id": project_id,
                "mission": "Do the work.",
            },
        )
    job_id = _payload(spawned)["job_id"]

    # The stored legacy election, as it exists on a self-hoster's row today.
    project_row = (
        await db_session.execute(select(Project).where(Project.id == project_id, Project.tenant_key == tenant_key))
    ).scalar_one()
    project_row.execution_mode = "generic_mcp"
    await db_session.flush()

    async with new_client() as session:
        mission = _payload(await session.call_tool("get_job_mission", {"job_id": job_id}))

    assert mission.get("agent_identity"), (
        "A legacy generic_mcp agent received no identity block. That mode has no CLI and no "
        "installed agent files -- its own protocol prose says templates are served by the MCP "
        "server, not local files -- so the server is its only identity channel, exactly as for "
        "multi_terminal. It is now running with no role framing."
    )
    assert _PERSONA_MARKER in mission["agent_identity"], (
        f"The served identity must carry the bound template's own prose. Got: {mission['agent_identity']!r:.300}"
    )


async def test_a_null_election_is_blocked_before_identity_is_ever_composed(mission_boundary_client) -> None:
    """GUARD for ROW 3's other half: a NULL election blocks upstream of the serve site.

    Recorded so the mode gate is never "simplified" by pointing it at BE-9402's
    fail-safe: the two do different jobs. ``check_implementation_gate`` refuses a
    NULL outright, which is why the serve-site fail-safe only ever has to answer
    for tokens that are present but unrecognised.
    """
    new_client, tenant_key, db_session = mission_boundary_client
    project_id = await _seed_project(db_session, tenant_key, "multi_terminal")
    agent_name = await _seed_live_template(db_session, tenant_key)

    async with new_client() as session:
        spawn_result = await session.call_tool(
            "spawn_job",
            {
                "agent_display_name": "implementer",
                "agent_name": agent_name,
                "project_id": project_id,
                "mission": "Do the work.",
            },
        )
    job_id = _payload(spawn_result)["job_id"]

    project_row = (
        await db_session.execute(select(Project).where(Project.id == project_id, Project.tenant_key == tenant_key))
    ).scalar_one()
    project_row.execution_mode = None
    await db_session.flush()

    async with new_client() as session:
        mission = _payload(await session.call_tool("get_job_mission", {"job_id": job_id}))

    assert mission.get("blocked") is True, (
        "A NULL election must be blocked by the implementation gate before any identity is composed. "
        f"Got: {mission!r:.300}"
    )
    assert "execution mode" in (mission.get("user_instruction") or "").lower(), (
        f"The block must tell the user to pick a mode. Got: {mission.get('user_instruction')!r}"
    )
