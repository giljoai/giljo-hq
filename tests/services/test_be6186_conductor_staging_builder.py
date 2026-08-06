# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-6186: project-less conductor STAGING fetch + rewritten CH_CHAIN_STAGING.

Regression at the failing layer (MissionOrchestrationService.get_staging_instructions
for a project-less conductor) plus the prose contract of the rewritten chapter:

1. test_projectless_conductor_staging_returns_real_protocol
   get_staging_instructions for the dedicated, project-less conductor returns the
   rewritten CH_CHAIN_STAGING (per-project-missions + sub-orch-jobs script + the
   conductor's OWN job_id) under orchestrator_protocol, NOT the STOP
   "USE_RUNTIME_MISSION" placeholder.

2. test_non_conductor_projectless_orphan_falls_back_to_stop
   A project-less orchestrator that is NOT the live conductor of any active run
   still gets the STOP-shaped directive (the fallback is preserved).

3. test_chain_staging_prose_contract (Task 4 prose checks)
   The rewritten CH_CHAIN_STAGING contains no TERMINATE_CHAIN, no head-agent
   "spawn"/"SPAWN its agents" language; complete_job is the last call; head is
   symmetric.

4. test_solo_staging_render_byte_identical_deletion (DELETION TEST)
   A solo project's staging render contains none of the chain chapters and is
   byte-identical to the no-chain render (the chain chapters render only for the
   conductor).

Parallel-safe: DB-touching tests use db_session (TransactionalTestContext). No
module-level mutable state. Edition Scope: CE.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.models import Product, Project
from giljo_mcp.models.agent_identity import AgentExecution, AgentJob
from giljo_mcp.services.mission_service import MissionService
from giljo_mcp.services.sequence_run_service import SequenceRunService
from giljo_mcp.tenant import TenantManager


async def _seed_project(session: AsyncSession, tenant_key: str, product_id: str | None = None) -> str:
    """Seed a chain-member project under a real product (so its product_id resolves).

    BE-6177 (UNIT 1): the conductor reads deep via get_context(product_id=...), so the
    head project must carry a real product_id. When product_id is None a fresh product
    is minted; pass the same product_id to put several projects under one product.
    """
    if product_id is None:
        # is_active=False so seeding several projects (each its own product) in one
        # tenant does not violate idx_product_single_active_per_tenant (only one
        # ACTIVE product per tenant). The deep-read handle only needs a valid FK.
        product = Product(
            id=str(uuid.uuid4()),
            name=f"BE-6186 Product {uuid.uuid4().hex[:6]}",
            description="Chain product.",
            tenant_key=tenant_key,
            is_active=False,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        session.add(product)
        await session.flush()
        product_id = product.id
    project = Project(
        id=str(uuid.uuid4()),
        name=f"BE-6186 {uuid.uuid4().hex[:6]}",
        description="Chain member.",
        mission="Be a chain member.",
        status="active",
        tenant_key=tenant_key,
        product_id=product_id,
        series_number=1,
        execution_mode="claude_code_cli",
        created_at=datetime.now(UTC),
    )
    session.add(project)
    session.info["tenant_key"] = tenant_key
    await session.flush()
    return project.id


def _run_svc(session: AsyncSession) -> SequenceRunService:
    return SequenceRunService(db_manager=None, tenant_manager=TenantManager(), session=session)


async def _conductor_job_id(session: AsyncSession, tenant_key: str, conductor_agent_id: str) -> str:
    row = await session.execute(
        select(AgentExecution.job_id).where(
            AgentExecution.tenant_key == tenant_key,
            AgentExecution.agent_id == conductor_agent_id,
        )
    )
    return str(row.scalar_one())


def _mission_svc(session: AsyncSession) -> MissionService:
    return MissionService(db_manager=None, tenant_manager=TenantManager(), test_session=session)


# ---------------------------------------------------------------------------
# 1. project-less conductor get_staging_instructions returns the real protocol
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_projectless_conductor_staging_returns_real_protocol(db_session: AsyncSession) -> None:
    tenant = TenantManager.generate_tenant_key()
    p1 = await _seed_project(db_session, tenant)
    p2 = await _seed_project(db_session, tenant)

    run = await _run_svc(db_session).create(
        project_ids=[p1, p2],
        resolved_order=[p1, p2],
        execution_mode="claude_code_cli",
        tenant_key=tenant,
    )
    conductor_agent_id = run["conductor_agent_id"]
    conductor_job_id = await _conductor_job_id(db_session, tenant, conductor_agent_id)

    resp = await _mission_svc(db_session).get_staging_instructions(conductor_job_id, tenant)

    # Not the STOP placeholder.
    assert resp.get("action") != "USE_RUNTIME_MISSION", "conductor must get the real staging protocol, not the STOP"
    assert resp.get("status") == "CHAIN_CONDUCTOR_STAGING"

    protocol = resp["orchestrator_protocol"]
    staging = protocol["ch_chain_staging"]
    assert "ch_capability" in protocol, "CH_CAPABILITY must accompany the staging chapter"
    # BE-6177 (UNIT 1): the script still mints each project's sub-orchestrator
    # (stage_project) but writes ONLY the chain mission — NEVER each project's mission.
    assert "stage_project" in staging, "the script must stage each project's sub-orchestrator"
    assert "update_project_mission" not in staging, (
        "the conductor writes ONLY the chain mission; it must NOT write each project's mission"
    )
    # The conductor reads deep before planning (get_context) so its contracts are concrete.
    assert "get_context" in staging, "the conductor must be told to read deep via get_context before planning"
    # The conductor's OWN job_id appears (its write channel for the chain mission).
    assert conductor_job_id in staging, "the conductor's own job_id must be threaded into CH_CHAIN_STAGING"
    assert f'update_job_mission(job_id="{conductor_job_id}"' in staging, (
        "the chain mission is written to the conductor's OWN job via update_job_mission"
    )
    # Identity surfaces the conductor's own job_id, project_id None, and the deep-read
    # product_id handle (head project's product_id; here both seeded projects share it).
    assert resp["identity"]["job_id"] == conductor_job_id
    assert resp["identity"]["project_id"] is None
    assert resp["identity"]["product_id"] is not None, (
        "the head project's product_id must surface in identity for the conductor's deep read"
    )
    assert resp["identity"]["product_id"] in staging, "the resolved product_id must be threaded into the read-deep step"


# ---------------------------------------------------------------------------
# 2. a project-less orchestrator that is NOT a live conductor falls back to STOP
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_non_conductor_projectless_orphan_falls_back_to_stop(db_session: AsyncSession) -> None:
    """A project-less orchestrator with no active conductor run still gets the STOP."""
    tenant = TenantManager.generate_tenant_key()

    # Hand-mint a project-less orchestrator job that is NOT any run's conductor.
    job_id = str(uuid.uuid4())
    agent_id = str(uuid.uuid4())
    db_session.add(
        AgentJob(
            job_id=job_id,
            tenant_key=tenant,
            project_id=None,
            mission=None,
            job_type="orchestrator",
            status="active",
            job_metadata={},
        )
    )
    db_session.add(
        AgentExecution(
            agent_id=agent_id,
            job_id=job_id,
            tenant_key=tenant,
            agent_display_name="orchestrator",
            agent_name="Orphan",
            status="waiting",
            health_status="unknown",
            project_phase="implementation",
        )
    )
    db_session.info["tenant_key"] = tenant
    await db_session.flush()

    resp = await _mission_svc(db_session).get_staging_instructions(job_id, tenant)
    assert resp.get("action") == "USE_RUNTIME_MISSION", "a non-conductor project-less orch keeps the STOP fallback"
    assert resp.get("status") == "CHAIN_CONDUCTOR"


# ---------------------------------------------------------------------------
# 3. CH_CHAIN_STAGING prose contract (Task 4 assertions)
# ---------------------------------------------------------------------------


def test_chain_staging_prose_contract() -> None:
    from giljo_mcp.services.protocol_sections.chapters_chain import _build_ch_chain_staging

    chapter = _build_ch_chain_staging(
        run_id="run-x",
        resolved_order=["head", "p2", "p3"],
        execution_mode="claude_code_cli",
        job_id="job-77",
        product_id="prod-x",
    )
    low = chapter.lower()

    assert "terminate_chain" not in low, "no TERMINATE_CHAIN prose in the staging chapter"
    # No head-agent spawn language (the dropped dual-hat). The conductor spawns no agents.
    assert "spawn its agents" not in low, "no 'SPAWN its agents' head-agent language"
    assert "spawn no agents" in low, "the conductor must be told to spawn NO agents for any project"
    # complete_job is described as the last call.
    assert "complete_job" in low and "last" in low, "complete_job must be the LAST call"
    # The head is symmetric, not special.
    assert "symmetric" in low and "not special" in low, "the head must be stated symmetric, NOT special"
    # The conductor's job_id is threaded in.
    assert "job-77" in chapter

    # BE-6177 (UNIT 1): the conductor mints each project's sub-orchestrator
    # (stage_project) but writes ONLY the chain mission — it NEVER writes a project
    # mission, so update_project_mission must be ABSENT from the staging script.
    assert "stage_project" in chapter, "the conductor still mints each project's sub-orchestrator"
    assert "update_project_mission" not in chapter, (
        "the conductor writes ONLY the chain mission; update_project_mission must be gone"
    )
    # The conductor reads deep before planning (get_context with the threaded product_id).
    assert "get_context" in chapter, "the read-deep step (get_context) must be present"
    assert "prod-x" in chapter, "the product_id must be threaded into the read-deep step"
    # The chain mission carries a structured per-project contract (consumes/produces/must leave).
    assert "consumes" in low, "the per-project contract must name what each project consumes"
    assert "produces" in low, "the per-project contract must name what each project produces"
    assert "must leave" in low, "the per-project contract must name the invariants each project leaves"


# ---------------------------------------------------------------------------
# 3b. BE-6187: CH_CHAIN_STAGING Step 0 stands up the Hub thread (conductor prose)
# ---------------------------------------------------------------------------


def test_ch_chain_staging_includes_hub_thread_step() -> None:
    """BE-6187: the conductor creates the Hub thread itself as Step 0 (create_thread).

    BE-9291 DELIBERATELY CHANGED what this asserts. It used to require the chapter to
    name ``search_threads`` and to carry the run_id "so sub-orchs can find the Hub
    thread" — because discovery really did work by substring-matching the run_id out of
    the subject. Discovery now runs on ``comm_threads.sequence_run_id``, a real FK, so
    naming ``search_threads`` here would pin a mechanism that no longer exists.

    The INTENT is unchanged and still enforced: the chapter must name a discovery path,
    and the run_id must still appear — but now as the value the conductor STAMPS on the
    thread, not as a substring anyone parses back out.
    """
    from giljo_mcp.services.protocol_sections.chapters_chain import _build_ch_chain_staging

    chapter = _build_ch_chain_staging(
        run_id="run-test", resolved_order=["p1", "p2"], execution_mode="claude_code_cli", job_id="job-77"
    )
    low = chapter.lower()

    # The conductor stands up the Hub thread itself (no server-side creation).
    assert "create_thread" in chapter, "the conductor must be told to create_thread for the Hub"
    # It must STAMP the link -- that is the only thing marking the thread as this run's hub.
    assert "sequence_run_id" in chapter, "the conductor must be told to stamp sequence_run_id"
    assert "run-test" in chapter, "the run_id must appear as the value to stamp"
    # And the chapter must name the discovery path sub-orchs actually use.
    assert "hub_thread_id" in chapter, "the discovery path (get_context chain) must be named"
    assert "search_threads" not in chapter, "the retired substring-discovery path must not be re-introduced here"
    # Existing prose contracts still hold.
    assert "terminate_chain" not in low, "no TERMINATE_CHAIN prose"
    assert "symmetric" in low and "not special" in low, "head stays symmetric"
    assert "complete_job" in low and "last" in low, "complete_job must be the LAST call"


# ---------------------------------------------------------------------------
# 3c. BE-6187: conductor staging tools expose create_thread + join_thread
# ---------------------------------------------------------------------------


def test_conductor_staging_tools_include_thread_tools() -> None:
    """BE-6187: build_conductor_staging_response advertises create_thread + join_thread
    so the conductor can stand up and join the Hub thread during staging."""
    from giljo_mcp.services.conductor_staging_builder import build_conductor_staging_response
    from giljo_mcp.services.sequence_chain_context import ChainContext

    chain_ctx = ChainContext(
        run_id="run-tools",
        role="conductor",
        current_index=0,
        resolved_order=["p1", "p2"],
        is_staging=True,
        conductor_agent_id="cond-1",
        execution_mode="claude_code_cli",
    )
    resp = build_conductor_staging_response(chain_ctx=chain_ctx, job_id="job-77", agent_id="cond-1", tenant_key="tk_x")

    tools = resp["mcp_tools_available"]
    assert "create_thread" in tools, "the conductor must be able to create the Hub thread"
    assert "join_thread" in tools, "the conductor must be able to join the Hub thread"


# ---------------------------------------------------------------------------
# 4. DELETION TEST: a solo project's staging render is byte-identical
# ---------------------------------------------------------------------------


def test_solo_staging_render_byte_identical_deletion() -> None:
    """A solo (chain_ctx=None) staging render carries none of the chain chapters and
    is byte-identical to the no-chain render; the chain chapters render ONLY for the
    conductor."""
    from giljo_mcp.services.protocol_builder import _build_orchestrator_protocol

    common = {
        "cli_mode": True,
        "project_id": "proj-solo",
        "orchestrator_id": "job-solo",
        "tenant_key": "tk_solo",
        "include_implementation_reference": False,
    }
    baseline = _build_orchestrator_protocol(**common)
    explicit_none = _build_orchestrator_protocol(**common, chain_ctx=None)

    assert baseline == explicit_none, "chain_ctx=None staging render must be byte-identical to the no-chain render"
    for chapter_key in ("ch_capability", "ch_chain_staging", "ch_chain_drive"):
        assert chapter_key not in baseline, f"{chapter_key} must NOT render for a solo project"
