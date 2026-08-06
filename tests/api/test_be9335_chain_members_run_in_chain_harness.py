# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-9335 regression — a chain member runs in the CHAIN's harness, not its own.

The defect: a chain's execution mode lives on the RUN, but most boundary readers
resolved ``project.execution_mode``. Only the chain-STAGING prompt endpoint copied
the run's mode down to the members, so a chain driven straight to IMPLEMENTATION
left every member on whatever mode it carried from being staged individually.

The damaging state is a DIVERGENT mode, not an absent one: the per-project gate
never fires (the member *has* a mode), so nothing complains and the member is
simply told the wrong harness. Worse, it is told BOTH — the mission protocol
header already resolved the run (BE-6177) while the staging instructions and the
spawn bootstrap resolved the project column.

The fix routes every chain-member mode read through one resolver
(``effective_execution_mode``) for which the RUN is authoritative, and freezes the
run's mode once any member has crossed its launch gate, so the resolved value
cannot shift under a live chain.

Edition scope: CE.
"""

from __future__ import annotations

import os
import secrets
import uuid
from datetime import UTC, datetime

import bcrypt
import pytest
from httpx import AsyncClient
from sqlalchemy import select

from giljo_mcp.auth.jwt_manager import JWTManager
from giljo_mcp.models import Product, Project, User
from giljo_mcp.models.agent_identity import AgentExecution, AgentJob
from giljo_mcp.models.base import generate_uuid
from giljo_mcp.models.organizations import Organization
from giljo_mcp.models.sequence_runs import SequenceRun
from giljo_mcp.services.conductor_job_minter import mint_conductor_job
from giljo_mcp.services.mission_orchestration_service import MissionOrchestrationService
from giljo_mcp.tenant import TenantManager


pytestmark = pytest.mark.asyncio

_TEST_CSRF_TOKEN = secrets.token_urlsafe(32)

# The individually-staged members' own mode, and the mode the user picked FOR THE
# CHAIN. They differ — that divergence is the whole defect.
MEMBER_MODE = "subagent"
CHAIN_MODE = "multi_terminal"


async def _seed_divergent_chain(
    db_manager,
    *,
    member_mode: str | None = MEMBER_MODE,
    chain_mode: str = CHAIN_MODE,
    run_status: str = "running",
    locked: bool = True,
    launched_members: int = 0,
    member_staging_status: str = "staged",
) -> dict:
    """Seed the straight-to-implementation state: members staged individually, chain linked.

    Each member carries ``member_mode`` (what it was staged with on its own) while
    the run carries ``chain_mode`` (what the user picked for the chain).

    ``member_staging_status`` defaults to ``"staged"`` deliberately, and it is
    load-bearing: it is what the solo staging endpoint writes, and it is the state
    in which the boundary actually RENDERS the mode-specific fields. A
    ``staging_complete`` member short-circuits into ``check_staging_redirect`` and
    returns a redirect with no mode fields at all — a test seeded that way passes
    without proving anything.

    ``launched_members`` is how many members (in order) have crossed their launch
    gate. That is the signal that says agents are LIVE with prompts already
    rendered, and it is what the run's mode-freeze keys on — not the run's
    lock/ultralock tier, which only means the Implement button is available.
    """
    async with db_manager.get_session_async() as session:
        suffix = uuid.uuid4().hex[:8]
        tenant_key = TenantManager.generate_tenant_key()

        org = Organization(name=f"Org {suffix}", slug=f"org-{suffix}", tenant_key=tenant_key, is_active=True)
        session.add(org)
        await session.flush()

        user = User(
            username=f"u_{suffix}",
            email=f"u_{suffix}@example.com",
            password_hash=bcrypt.hashpw(b"pw", bcrypt.gensalt()).decode(),
            tenant_key=tenant_key,
            role="developer",
            org_id=org.id,
        )
        session.add(user)
        await session.flush()

        product = Product(
            id=str(uuid.uuid4()),
            name=f"Product {suffix}",
            description="Test product",
            tenant_key=tenant_key,
            is_active=True,
        )
        session.add(product)
        await session.flush()

        projects = []
        for index, label in enumerate(("Alpha", "Beta")):
            proj = Project(
                id=str(uuid.uuid4()),
                name=f"{label} {suffix}",
                description=f"{label} project",
                mission=f"Build the {label.lower()} component.",
                tenant_key=tenant_key,
                product_id=product.id,
                # "inactive": only one ACTIVE project per product is allowed
                # (idx_project_single_active_per_product), and project status is
                # irrelevant to mode resolution.
                status="inactive",
                series_number=uuid.uuid4().int % 9000 + 1,
                execution_mode=member_mode,
                staging_status=member_staging_status,
                implementation_launched_at=(datetime.now(UTC) if index < launched_members else None),
            )
            session.add(proj)
            projects.append(proj)
        session.info["tenant_key"] = tenant_key
        await session.flush()

        p1, p2 = projects

        run = SequenceRun(
            id=str(uuid.uuid4()),
            tenant_key=tenant_key,
            project_ids=[p1.id, p2.id],
            resolved_order=[p1.id, p2.id],
            current_index=0,
            execution_mode=chain_mode,
            status=run_status,
            locked=locked,
            chain_mission="Deliver both components in order.",
            project_statuses={p1.id: "pending", p2.id: "pending"},
        )
        session.add(run)
        await session.flush()

        run.conductor_agent_id = await mint_conductor_job(session, tenant_key=tenant_key, run_id=run.id)

        # The head project's sub-orchestrator: the agent that actually receives the
        # wrong harness. project_phase="implementation" mirrors a driven member.
        member_job_id = generate_uuid()
        member_agent_id = generate_uuid()
        session.add(
            AgentJob(
                job_id=member_job_id,
                tenant_key=tenant_key,
                project_id=p1.id,
                mission="Build the alpha component.",
                job_type="orchestrator",
                status="active",
            )
        )
        session.add(
            AgentExecution(
                agent_id=member_agent_id,
                job_id=member_job_id,
                tenant_key=tenant_key,
                agent_display_name="orchestrator",
                agent_name="orchestrator",
                status="waiting",
                health_status="unknown",
                project_phase="implementation",
            )
        )
        await session.commit()

        os.environ.setdefault("JWT_SECRET", "test_secret_key")
        token = JWTManager.create_access_token(
            user_id=user.id,
            username=user.username,
            role="developer",
            tenant_key=tenant_key,
        )
        return {
            "headers": {
                "Cookie": f"access_token={token}; csrf_token={_TEST_CSRF_TOKEN}",
                "X-CSRF-Token": _TEST_CSRF_TOKEN,
            },
            "run_id": run.id,
            "head_pid": p1.id,
            "head_name": p1.name,
            "tail_pid": p2.id,
            "member_job_id": member_job_id,
            "member_agent_id": member_agent_id,
            "conductor_agent_id": run.conductor_agent_id,
            "tenant_key": tenant_key,
        }


def _renders_as_subagent(staging_response: dict) -> bool:
    """True when the staging response carries the SUBAGENT render, not multi_terminal.

    ``cli_mode_rules`` is emitted only for a subagent-shaped mode;
    ``phase_assignment_instructions`` only for multi_terminal. Asserting on the
    rendered artifact (rather than on a column) is what makes this a test of what
    the agent is actually told.
    """
    return "cli_mode_rules" in staging_response


async def _run_mode(db_manager, seed: dict) -> str:
    """Read the run's stored mode back. The tenant-scope listener needs the
    contextvar set — an explicit tenant_key predicate alone does not satisfy it."""
    token = TenantManager.set_current_tenant(seed["tenant_key"])
    try:
        async with db_manager.get_session_async() as session:
            row = (
                await session.execute(
                    select(SequenceRun).where(
                        SequenceRun.id == seed["run_id"],
                        SequenceRun.tenant_key == seed["tenant_key"],
                    )
                )
            ).scalar_one()
            return row.execution_mode
    finally:
        from giljo_mcp.tenant import current_tenant

        current_tenant.reset(token)


async def _staging_instructions(db_manager, seed: dict) -> dict:
    svc = MissionOrchestrationService(db_manager=db_manager, tenant_manager=TenantManager())
    return await svc.get_staging_instructions(job_id=seed["member_job_id"], tenant_key=seed["tenant_key"])


async def test_chain_member_staging_instructions_follow_the_run_not_the_project(db_manager):
    """A chain member is told the CHAIN's harness by get_staging_instructions.

    Fail-first: on master the member renders ``cli_mode_rules`` (its own
    individually-staged ``subagent`` mode) even though the chain is
    ``multi_terminal``.
    """
    seed = await _seed_divergent_chain(db_manager)

    response = await _staging_instructions(db_manager, seed)

    assert not _renders_as_subagent(response), (
        "chain member rendered the SUBAGENT spawn syntax (cli_mode_rules) while the "
        f"chain's execution mode is {CHAIN_MODE!r} — the member is being run in the "
        "harness it was staged with individually, not the one picked for the chain"
    )


async def test_chain_member_boundaries_do_not_contradict_each_other(db_manager):
    """The mission header and the staging instructions must not disagree.

    The mission protocol header already resolves the RUN (BE-6177) while the
    staging instructions resolved the project column — so on master the same
    member is simultaneously told ``multi_terminal`` (header) and the subagent
    spawn syntax (staging). Whichever mode wins, the two must agree.
    """
    seed = await _seed_divergent_chain(db_manager)

    from giljo_mcp.services.mission_service import MissionService

    mission = await MissionService(db_manager=db_manager, tenant_manager=TenantManager()).get_agent_mission(
        job_id=seed["member_job_id"], tenant_key=seed["tenant_key"]
    )
    # MissionResponse is a pydantic model, not a dict.
    protocol = mission.full_protocol or ""
    header_says_multi_terminal = "EXECUTION_MODE: multi_terminal" in protocol

    staging_says_subagent = _renders_as_subagent(await _staging_instructions(db_manager, seed))

    assert not (header_says_multi_terminal and staging_says_subagent), (
        "the same chain member was told BOTH harnesses: the mission protocol header "
        "says multi_terminal (run-derived) while the staging instructions emit the "
        "subagent spawn syntax (project-derived)"
    )


@pytest.mark.parametrize(
    ("member_mode", "chain_mode", "expect_ch6"),
    [
        ("subagent", "multi_terminal", True),
        ("multi_terminal", "subagent", False),
    ],
)
async def test_ch6_auto_checkin_follows_the_same_mode_as_the_header(
    db_manager, member_mode: str, chain_mode: str, expect_ch6: bool
):
    """The CH6 auto check-in block must key off the SAME mode as the header.

    This branch is orchestrator-gated, so unlike the specialist team-table branch
    it sits exactly where the chain mode IS resolved — and it read the raw project
    column while the header two hundred lines above resolved the run. It therefore
    disagreed with the header in both directions on the same protocol string: a
    multi_terminal chain silently LOST its auto check-in loop, and a subagent chain
    was SHIPPED a multi_terminal loop it must never run.
    """
    from giljo_mcp.services.mission_service import MissionService

    seed = await _seed_divergent_chain(db_manager, member_mode=member_mode, chain_mode=chain_mode)

    mission = await MissionService(db_manager=db_manager, tenant_manager=TenantManager()).get_agent_mission(
        job_id=seed["member_job_id"], tenant_key=seed["tenant_key"]
    )
    protocol = mission.full_protocol or ""

    has_ch6 = "CH6: AUTO CHECK-IN PROTOCOL" in protocol
    header_is_multi_terminal = "EXECUTION_MODE: multi_terminal" in protocol

    assert has_ch6 is expect_ch6, (
        f"chain={chain_mode!r} column={member_mode!r}: CH6 auto check-in "
        f"{'missing' if expect_ch6 else 'present'} — it resolved the project column while "
        "the header resolved the run"
    )
    # The real invariant: CH6 and the header are two renders of ONE decision.
    assert has_ch6 == header_is_multi_terminal, (
        "CH6 and the EXECUTION_MODE header disagree inside the same protocol string"
    )


async def test_solo_project_still_follows_its_own_execution_mode(db_manager):
    """No active run ⇒ the project column stays authoritative (solo unchanged)."""
    seed = await _seed_divergent_chain(db_manager, run_status="completed")

    response = await _staging_instructions(db_manager, seed)

    assert _renders_as_subagent(response), (
        "a project with no ACTIVE run must keep rendering its own execution_mode; "
        "the chain resolver must not leak into the solo path"
    )


@pytest.mark.parametrize("route", ["chain-staging", "chain-implementation"])
async def test_both_chain_prompt_routes_leave_members_on_the_chain_mode(
    api_client: AsyncClient, db_manager, route: str
):
    """Neither chain entry point may leave a member on a divergent mode.

    The defect is the ASYMMETRY between the two routes, so this is parametrised
    over both: a test that only exercised chain-implementation would let the
    reverse regression (someone removing the staging propagation) through.
    """
    seed = await _seed_divergent_chain(db_manager, locked=False, run_status="pending")

    resp = await api_client.get(f"/api/v1/prompts/{route}/{seed['run_id']}", headers=seed["headers"])
    assert resp.status_code == 200, f"{route} returned {resp.status_code}: {resp.text}"

    svc = MissionOrchestrationService(db_manager=db_manager, tenant_manager=TenantManager())
    response = await svc.get_staging_instructions(job_id=seed["member_job_id"], tenant_key=seed["tenant_key"])

    assert not _renders_as_subagent(response), (
        f"after GET /prompts/{route}, the chain member still renders the subagent "
        f"spawn syntax instead of the chain's {CHAIN_MODE!r} harness"
    )


async def test_launched_member_keeps_running_the_chain_mode_and_staging_still_succeeds(
    api_client: AsyncClient, db_manager
):
    """An ALREADY-LAUNCHED member stays consistent, and the staging loop still tolerates it.

    The staging propagation writes through ProjectService, which refuses an
    ``execution_mode`` write once ``implementation_launched_at`` is stamped; the
    loop swallows that and moves on. Two things must hold together, and the
    launched member is where they could come apart:

    1. chain-staging still returns 200 with a launched member in the chain (the
       skip is tolerated, not fatal) — the DoD-3 guard behaviour, preserved.
    2. the launched member is still rendered the CHAIN's harness. Its own column
       is now unwritable, so under a propagate-only fix it would be pinned to the
       divergent mode forever; resolving at READ time is what keeps it consistent,
       and the run's mode is frozen so that answer cannot move under it.
    """
    seed = await _seed_divergent_chain(db_manager, launched_members=1, locked=False, run_status="pending")

    resp = await api_client.get(f"/api/v1/prompts/chain-staging/{seed['run_id']}", headers=seed["headers"])
    assert resp.status_code == 200, f"a launched member must not break chain staging: {resp.text}"

    response = await _staging_instructions(db_manager, seed)
    assert not _renders_as_subagent(response), (
        "an already-launched chain member was left rendering its own divergent mode; "
        "its column cannot be rewritten, so the read path must resolve the chain's mode"
    )


async def _add_specialist(db_manager, seed: dict) -> str:
    """Give the head project one launchable non-orchestrator agent.

    ``implement()`` synthesises per-terminal launch commands only for these, so a
    member with none cannot exhibit the mode-dependent branch at all.
    """
    token = TenantManager.set_current_tenant(seed["tenant_key"])
    try:
        async with db_manager.get_session_async() as session:
            session.info["tenant_key"] = seed["tenant_key"]
            job_id = generate_uuid()
            session.add(
                AgentJob(
                    job_id=job_id,
                    tenant_key=seed["tenant_key"],
                    project_id=seed["head_pid"],
                    mission="Implement the alpha component.",
                    job_type="implementer",
                    status="active",
                )
            )
            session.add(
                AgentExecution(
                    agent_id=generate_uuid(),
                    job_id=job_id,
                    tenant_key=seed["tenant_key"],
                    agent_display_name="implementer",
                    agent_name="implementer",
                    status="waiting",
                    health_status="unknown",
                    project_phase="implementation",
                )
            )
            await session.commit()
            return job_id
    finally:
        from giljo_mcp.tenant import current_tenant

        current_tenant.reset(token)


async def test_solo_implement_path_on_a_chain_member_uses_the_chain_harness(db_manager):
    """The dashboard Play button on a chain member must render the CHAIN's harness.

    This is the most reachable path in the whole defect and it needs no headless
    caller: the solo Play button is live on a chain member's Jobs tab, so opening
    a member project and pressing Play calls
    ``GET /api/v1/prompts/implementation/{member_id}`` -> ``implement()``, which
    read ``project.execution_mode`` raw at four sites. The human gate does not
    stand in the way — a chain sub-orchestrator's staging-end auto-stamps
    ``implementation_launched_at``.

    ``launch_commands`` is the crisp observable: ``implement()`` synthesises the
    per-terminal launch array only for multi_terminal, so on a divergent member it
    came back empty while the chain was multi_terminal all along.
    """
    from giljo_mcp.thin_prompt_generator import ThinClientPromptGenerator

    seed = await _seed_divergent_chain(
        db_manager,
        member_staging_status="staging_complete",
        launched_members=2,
    )
    await _add_specialist(db_manager, seed)

    token = TenantManager.set_current_tenant(seed["tenant_key"])
    try:
        async with db_manager.get_session_async() as session:
            session.info["tenant_key"] = seed["tenant_key"]
            payload = await ThinClientPromptGenerator(session, seed["tenant_key"]).implement(
                project_id=seed["head_pid"], user_id=None
            )
    finally:
        from giljo_mcp.tenant import current_tenant

        current_tenant.reset(token)

    assert payload["launch_commands"], (
        "the solo implement path rendered a chain member with its own divergent "
        f"{MEMBER_MODE!r} mode instead of the chain's {CHAIN_MODE!r} — no per-terminal "
        "launch commands were produced for a multi_terminal chain"
    )


async def test_spawn_bootstrap_for_a_chain_member_follows_the_chain_mode(db_manager):
    """A worker spawned into a chain member gets the CHAIN's bootstrap.

    The spawn bootstrap is the other half of the "told BOTH harnesses"
    contradiction: ``spawn_job`` handed the agent an inline subagent bootstrap
    (the member's own mode) while the mission header said multi_terminal. A
    multi_terminal spawn must instead return the dashboard pointer, so this pins
    ``agent_prompt_location``.
    """
    from giljo_mcp.models.templates import AgentTemplate
    from giljo_mcp.services.job_lifecycle_service import JobLifecycleService

    seed = await _seed_divergent_chain(db_manager)

    # spawn_job validates agent_name against the tenant's templates.
    token = TenantManager.set_current_tenant(seed["tenant_key"])
    try:
        async with db_manager.get_session_async() as session:
            session.info["tenant_key"] = seed["tenant_key"]
            session.add(
                AgentTemplate(
                    id=str(uuid.uuid4()),
                    tenant_key=seed["tenant_key"],
                    name="implementer",
                    role="implementer",
                    category="core",
                    system_instructions="# implementer",
                    is_active=True,
                    version="1.0.0",
                )
            )
            await session.commit()
    finally:
        from giljo_mcp.tenant import current_tenant

        current_tenant.reset(token)

    result = await JobLifecycleService(db_manager=db_manager, tenant_manager=TenantManager()).spawn_job(
        agent_display_name="implementer",
        agent_name="implementer",
        project_id=seed["head_pid"],
        tenant_key=seed["tenant_key"],
        mission="Implement the alpha component.",
    )

    assert result.agent_prompt_location == "dashboard", (
        "a worker spawned into a multi_terminal chain must get the dashboard pointer; "
        f"got {result.agent_prompt_location!r}, i.e. the member's own {MEMBER_MODE!r} bootstrap"
    )


async def test_orchestrator_identity_for_a_legacy_mode_member_follows_the_chain(db_manager):
    """The orchestrator IDENTITY's harness override must follow the chain too.

    The identity is composed with a tool derived from the mode. For the two
    canonical modes that composition is byte-identical, so this is only observable
    on a LEGACY member row (``claude_code_cli`` -> tool ``claude-code``), which the
    codebase deliberately still tolerates. There the identity gains a Claude
    Code-only harness override — which must NOT be shipped to a member the chain is
    running as multi_terminal.
    """
    from giljo_mcp.services.mission_service import MissionService

    seed = await _seed_divergent_chain(db_manager, member_mode="claude_code_cli")

    mission = await MissionService(db_manager=db_manager, tenant_manager=TenantManager()).get_agent_mission(
        job_id=seed["member_job_id"], tenant_key=seed["tenant_key"]
    )

    assert "HARNESS REMINDER OVERRIDE (Claude Code only" not in (mission.agent_identity or ""), (
        "the chain member's orchestrator identity carried the Claude Code harness "
        "override from its own legacy execution_mode, while the chain runs multi_terminal"
    )


async def test_member_with_no_mode_of_its_own_still_refuses_loudly(api_client: AsyncClient, db_manager):
    """Scope boundary, pinned: an ABSENT member mode still BLOCKS; it is not coerced.

    This fix makes the run authoritative where the member HAS a mode — the silent
    failure. It deliberately does not loosen the NULL-state gate, so a member that
    never had a mode of its own is still refused with a STOP an agent can act on,
    rather than being silently run on the chain's mode. The distinction that
    matters is refuse-loudly vs run-wrong-harness-silently; this test pins which
    side of it the absent case sits on, so a later change to the gate is a
    deliberate decision rather than a drift.
    """
    seed = await _seed_divergent_chain(db_manager, member_mode=None, locked=False, run_status="pending")

    resp = await api_client.get(f"/api/v1/prompts/chain-implementation/{seed['run_id']}", headers=seed["headers"])
    assert resp.status_code == 200

    response = await _staging_instructions(db_manager, seed)
    assert response.get("status") == "BLOCKED", f"expected a loud refusal, got {response.get('status')!r}"
    assert response.get("action") == "STOP"
    assert not _renders_as_subagent(response), "a blocked member must not also render a harness"
    # A loud refusal that does not say WHICH member is at fault makes the user hunt
    # for it — in a chain there is more than one candidate.
    assert seed["head_name"] in (response.get("message") or ""), (
        f"the refusal must name the offending project: {response.get('message')!r}"
    )


async def test_run_execution_mode_is_frozen_while_the_chain_is_running(api_client: AsyncClient, db_manager):
    """The run's mode cannot be changed once the run is ultralocked.

    With the RUN authoritative for its members, an unguarded mode write would
    re-point every member's harness mid-flight — the exact desync the per-project
    post-launch lock exists to prevent. ``locked`` and ``chain_mission`` were
    already gated here; ``execution_mode`` was not, which is what let a caller
    stage a chain, change the mode off-UI, and then drive members on the old one.

    Driven through the REST PATCH because that is where the server decides. The
    dashboard's own ``patchRunMode`` refuses while ``run.locked``, but that guard
    is client-side only and does not cover every state the server must, so the
    refusal has to live here.
    """
    seed = await _seed_divergent_chain(db_manager)

    resp = await api_client.patch(
        f"/api/v1/sequence-runs/{seed['run_id']}",
        json={"execution_mode": MEMBER_MODE},
        headers=seed["headers"],
    )
    assert resp.status_code == 422, f"expected the mode write to be refused, got {resp.status_code}: {resp.text}"

    assert await _run_mode(db_manager, seed) == CHAIN_MODE, "the refused write must not have landed"


async def test_run_execution_mode_is_still_editable_before_any_launch(api_client: AsyncClient, db_manager):
    """The freeze must not seize the normal pre-Stage mode picker.

    Guards the obvious over-correction: the mode write must leave a pending,
    unlocked run fully editable, which is exactly what the dashboard mode selector
    does before Stage Chain.
    """
    seed = await _seed_divergent_chain(db_manager, run_status="pending", locked=False)

    resp = await api_client.patch(
        f"/api/v1/sequence-runs/{seed['run_id']}",
        json={"execution_mode": MEMBER_MODE},
        headers=seed["headers"],
    )
    assert resp.status_code == 200, f"a pre-Stage mode change must still be allowed: {resp.text}"


async def test_mode_still_editable_when_members_are_staged_but_nothing_launched(api_client: AsyncClient, db_manager):
    """Members individually staged to completion, nothing launched → still editable.

    Regression guard. Keying the mode freeze on the ULTRALOCK tier was wrong: that
    tier means "the Implement button is available" (any member at
    ``staging_complete``), not "agents are live". It refused this state, which the
    server had always allowed, and the refusal it offered pointed at Unstage —
    which is itself refused at that tier, so the remedy was a dead end. The freeze
    keys on the launch gate instead, so this state stays editable.
    """
    seed = await _seed_divergent_chain(
        db_manager,
        run_status="pending",
        locked=False,
        member_staging_status="staging_complete",
        launched_members=0,
    )

    resp = await api_client.patch(
        f"/api/v1/sequence-runs/{seed['run_id']}",
        json={"execution_mode": MEMBER_MODE},
        headers=seed["headers"],
    )
    assert resp.status_code == 200, (
        "a staged-but-never-launched chain must keep its mode editable — no agent has "
        f"been handed a rendered prompt yet. Got {resp.status_code}: {resp.text}"
    )
    assert await _run_mode(db_manager, seed) == MEMBER_MODE, "the accepted write must have landed"


async def test_mode_frozen_once_a_member_is_launched_even_on_a_pending_unlocked_run(
    api_client: AsyncClient, db_manager
):
    """The freeze must engage on the straight-to-implementation path itself.

    ``GET /prompts/chain-implementation`` is a pure READ — it sets neither
    ``status`` nor ``locked``. So a chain driven straight to implementation stays
    ``pending`` + unlocked while its members are launched and running. Keying the
    freeze on the run's lock tier therefore left the mode writable during exactly
    the flow this project is about, and flipping it re-pointed a LIVE member's
    harness mid-flight. The launch gate is the signal that closes it.
    """
    seed = await _seed_divergent_chain(
        db_manager,
        run_status="pending",
        locked=False,
        launched_members=1,
    )

    resp = await api_client.patch(
        f"/api/v1/sequence-runs/{seed['run_id']}",
        json={"execution_mode": MEMBER_MODE},
        headers=seed["headers"],
    )
    assert resp.status_code == 422, (
        "a launched member means agents are live with prompts already rendered; the "
        f"chain's mode must be frozen even though the run is still pending/unlocked. Got {resp.status_code}"
    )
    assert await _run_mode(db_manager, seed) == CHAIN_MODE, "the refused write must not have landed"


async def test_frozen_mode_error_names_the_launched_project_and_a_remedy_that_actually_works(
    api_client: AsyncClient, db_manager
):
    """The refusal names the member AND a remedy that survives being DRIVEN.

    This test drives the remedy end to end rather than grepping the message for a
    verb, because the previous wording pointed at Re-stage and Re-stage is refused
    in the exact state that produces this error: both writers of
    ``implementation_launched_at`` require ``staging_complete``, and restage refuses
    ``staging_complete AND launched`` (and refuses every other staging_status
    outright). Naming an unreachable remedy is the same defect as the original
    regression, only better worded.

    Reset is the path that genuinely works, and it is destructive — it hard-deletes
    the project's agents — so the message says so instead of implying a cheap fix.
    """
    seed = await _seed_divergent_chain(
        db_manager,
        run_status="pending",
        locked=False,
        launched_members=1,
        member_staging_status="staging_complete",
    )

    refusal = await api_client.patch(
        f"/api/v1/sequence-runs/{seed['run_id']}",
        json={"execution_mode": MEMBER_MODE},
        headers=seed["headers"],
    )
    assert refusal.status_code == 422
    detail = refusal.text
    assert seed["head_name"] in detail, f"the launched member's name must appear in the refusal: {detail}"

    # The remedy the message does NOT name, driven: proves why it is not named.
    restage = await api_client.post(f"/api/v1/projects/{seed['head_pid']}/restage", headers=seed["headers"])
    assert restage.status_code >= 400, (
        "restage unexpectedly succeeded on a launched project — if this ever starts "
        "working, the refusal message should name it instead of Reset"
    )

    # The remedy the message DOES name, driven: it must actually unblock the change.
    reset = await api_client.post(f"/api/v1/projects/{seed['head_pid']}/reset", headers=seed["headers"])
    assert reset.status_code == 200, f"the named remedy must be reachable: {reset.text}"

    retry = await api_client.patch(
        f"/api/v1/sequence-runs/{seed['run_id']}",
        json={"execution_mode": MEMBER_MODE},
        headers=seed["headers"],
    )
    assert retry.status_code == 200, (
        f"after carrying out the remedy the refusal named, the mode change must succeed: {retry.text}"
    )
    assert await _run_mode(db_manager, seed) == MEMBER_MODE
