# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

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
from tests.helpers.product_crew_helper import adopt_all_templates


pytestmark = pytest.mark.asyncio

_TEST_CSRF_TOKEN = secrets.token_urlsafe(32)

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

        conductor_identity = await mint_conductor_job(session, tenant_key=tenant_key, run_id=run.id)
        run.conductor_agent_id = conductor_identity["agent_id"]

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
    return "cli_mode_rules" in staging_response


async def _run_mode(db_manager, seed: dict) -> str:
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
    seed = await _seed_divergent_chain(db_manager)

    response = await _staging_instructions(db_manager, seed)

    assert not _renders_as_subagent(response), (
        "chain member rendered the SUBAGENT spawn syntax (cli_mode_rules) while the "
        f"chain's execution mode is {CHAIN_MODE!r} — the member is being run in the "
        "harness it was staged with individually, not the one picked for the chain"
    )


async def test_chain_member_boundaries_do_not_contradict_each_other(db_manager):
    seed = await _seed_divergent_chain(db_manager)

    from giljo_mcp.services.mission_service import MissionService

    mission = await MissionService(db_manager=db_manager, tenant_manager=TenantManager()).get_agent_mission(
        job_id=seed["member_job_id"], tenant_key=seed["tenant_key"]
    )
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
    from giljo_mcp.services.mission_service import MissionService

    seed = await _seed_divergent_chain(db_manager, member_mode=member_mode, chain_mode=chain_mode)

    mission = await MissionService(db_manager=db_manager, tenant_manager=TenantManager()).get_agent_mission(
        job_id=seed["member_job_id"], tenant_key=seed["tenant_key"]
    )
    protocol = mission.full_protocol or ""

    has_ch6 = "CH6: CHECK-IN" in protocol
    header_is_multi_terminal = "EXECUTION_MODE: multi_terminal" in protocol

    assert has_ch6 is expect_ch6, (
        f"chain={chain_mode!r} column={member_mode!r}: CH6 auto check-in "
        f"{'missing' if expect_ch6 else 'present'} — it resolved the project column while "
        "the header resolved the run"
    )
    assert has_ch6 == header_is_multi_terminal, (
        "CH6 and the EXECUTION_MODE header disagree inside the same protocol string"
    )


async def test_solo_project_still_follows_its_own_execution_mode(db_manager):
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
    seed = await _seed_divergent_chain(db_manager, launched_members=1, locked=False, run_status="pending")

    resp = await api_client.get(f"/api/v1/prompts/chain-staging/{seed['run_id']}", headers=seed["headers"])
    assert resp.status_code == 200, f"a launched member must not break chain staging: {resp.text}"

    response = await _staging_instructions(db_manager, seed)
    assert not _renders_as_subagent(response), (
        "an already-launched chain member was left rendering its own divergent mode; "
        "its column cannot be rewritten, so the read path must resolve the chain's mode"
    )


async def _add_specialist(db_manager, seed: dict) -> str:
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
    from giljo_mcp.models.templates import AgentTemplate
    from giljo_mcp.services.job_lifecycle_service import JobLifecycleService

    seed = await _seed_divergent_chain(db_manager)

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
            for (_pid,) in (
                await session.execute(select(Product.id).where(Product.tenant_key == seed["tenant_key"]))
            ).all():
                await adopt_all_templates(session, seed["tenant_key"], _pid)
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
    seed = await _seed_divergent_chain(db_manager, member_mode=None, locked=False, run_status="pending")

    resp = await api_client.get(f"/api/v1/prompts/chain-implementation/{seed['run_id']}", headers=seed["headers"])
    assert resp.status_code == 200

    response = await _staging_instructions(db_manager, seed)
    assert response.get("status") == "BLOCKED", f"expected a loud refusal, got {response.get('status')!r}"
    assert response.get("action") == "STOP"
    assert not _renders_as_subagent(response), "a blocked member must not also render a harness"
    assert seed["head_name"] in (response.get("message") or ""), (
        f"the refusal must name the offending project: {response.get('message')!r}"
    )


async def test_run_execution_mode_is_frozen_while_the_chain_is_running(api_client: AsyncClient, db_manager):
    seed = await _seed_divergent_chain(db_manager)

    resp = await api_client.patch(
        f"/api/v1/sequence-runs/{seed['run_id']}",
        json={"execution_mode": MEMBER_MODE},
        headers=seed["headers"],
    )
    assert resp.status_code == 422, f"expected the mode write to be refused, got {resp.status_code}: {resp.text}"

    assert await _run_mode(db_manager, seed) == CHAIN_MODE, "the refused write must not have landed"


async def test_run_execution_mode_is_still_editable_before_any_launch(api_client: AsyncClient, db_manager):
    seed = await _seed_divergent_chain(db_manager, run_status="pending", locked=False)

    resp = await api_client.patch(
        f"/api/v1/sequence-runs/{seed['run_id']}",
        json={"execution_mode": MEMBER_MODE},
        headers=seed["headers"],
    )
    assert resp.status_code == 200, f"a pre-Stage mode change must still be allowed: {resp.text}"


async def test_mode_still_editable_when_members_are_staged_but_nothing_launched(api_client: AsyncClient, db_manager):
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

    restage = await api_client.post(f"/api/v1/projects/{seed['head_pid']}/restage", headers=seed["headers"])
    assert restage.status_code >= 400, (
        "restage unexpectedly succeeded on a launched project — if this ever starts "
        "working, the refusal message should name it instead of Reset"
    )

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
