# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.models import Product, Project
from giljo_mcp.models.agent_identity import AgentExecution, AgentJob
from giljo_mcp.services.mission_service import MissionService
from giljo_mcp.services.protocol_sections.chapters_chain import _build_ch_sub_orchestrator
from giljo_mcp.services.sequence_run_service import SequenceRunService
from giljo_mcp.tenant import TenantManager




async def _seed_project(session: AsyncSession, tenant_key: str) -> str:
    product = Product(
        id=str(uuid.uuid4()),
        name=f"BE-6196 Product {uuid.uuid4().hex[:6]}",
        description="Chain product.",
        tenant_key=tenant_key,
        is_active=False,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    session.add(product)
    await session.flush()
    project = Project(
        id=str(uuid.uuid4()),
        name=f"BE-6196 {uuid.uuid4().hex[:6]}",
        description="Chain member.",
        mission="Be a chain member.",
        status="active",
        tenant_key=tenant_key,
        product_id=product.id,
        series_number=1,
        execution_mode="claude_code_cli",
        created_at=datetime.now(UTC),
    )
    session.add(project)
    session.info["tenant_key"] = tenant_key
    await session.flush()
    return project.id


async def _seed_orchestrator_job(session: AsyncSession, tenant_key: str, project_id: str) -> AgentJob:
    job_id = str(uuid.uuid4())
    job = AgentJob(
        job_id=job_id,
        tenant_key=tenant_key,
        project_id=project_id,
        mission="orchestrate this project",
        job_type="orchestrator",
        status="active",
        job_metadata={},
    )
    session.add(job)
    session.add(
        AgentExecution(
            agent_id=str(uuid.uuid4()),
            job_id=job_id,
            tenant_key=tenant_key,
            agent_display_name="orchestrator",
            agent_name="SubOrch",
            status="waiting",
            health_status="unknown",
            project_phase="implementation",
        )
    )
    session.info["tenant_key"] = tenant_key
    await session.flush()
    return job


def _mission_svc(session: AsyncSession) -> MissionService:
    return MissionService(db_manager=None, tenant_manager=TenantManager(), test_session=session)


def _run_svc(session: AsyncSession) -> SequenceRunService:
    return SequenceRunService(db_manager=None, tenant_manager=TenantManager(), session=session)




@pytest.mark.asyncio
async def test_chain_member_gate_passes_no_block(db_session: AsyncSession) -> None:
    tenant = TenantManager.generate_tenant_key()
    p1 = await _seed_project(db_session, tenant)
    p2 = await _seed_project(db_session, tenant)

    await _run_svc(db_session).create(
        project_ids=[p1, p2],
        resolved_order=[p1, p2],
        execution_mode="claude_code_cli",
        tenant_key=tenant,
    )

    job = await _seed_orchestrator_job(db_session, tenant, p1)

    svc = _mission_svc(db_session)
    project, gate = await svc._check_implementation_gate(db_session, job, job.job_id, tenant)

    assert gate is None, "a released chain member's orchestrator must NOT be gated (§14 — it runs free)"
    assert project is not None, "the project is still returned for downstream protocol assembly"




@pytest.mark.asyncio
async def test_solo_blocked_gate_unchanged(db_session: AsyncSession) -> None:
    tenant = TenantManager.generate_tenant_key()
    p1 = await _seed_project(db_session, tenant)
    job = await _seed_orchestrator_job(db_session, tenant, p1)

    svc = _mission_svc(db_session)
    _project, gate = await svc._check_implementation_gate(db_session, job, job.job_id, tenant)

    assert gate is not None, "a not-yet-launched solo orchestrator gate must block"
    instruction = gate.user_instruction or ""
    assert instruction == (
        "Staging is complete but implementation has not been launched. "
        "Return to the dashboard and click Implement, then start (or paste) your "
        "orchestrator prompt in your agent session (terminal, desktop, or web tab)."
    ), "the solo human-gate message must remain byte-identical"




def test_combined_suborch_prose() -> None:
    chapter = _build_ch_sub_orchestrator(
        run_id="r",
        position=2,
        n_projects=3,
        execution_mode="claude_code_cli",
        chain_mission="CONTRACT TEXT",
    )
    low = chapter.lower()

    assert "CH_SUB_ORCHESTRATOR" in chapter
    assert "project 2 of 3" in chapter
    assert "hub_thread_id" in chapter

    assert "get_job_mission" in chapter, "the combined flow must instruct the single get_job_mission seam call"
    assert "no gate" in low or "no per-project gate" in low, "the sub-orch must be told there is NO gate to wait behind"
    assert "once" in low or "immediately" in low, "the single immediate seam fetch must replace the blocking poll"

    assert "launch_implementation" not in chapter, "the sub-orch must NEVER be told to call launch_implementation"
    assert "do not" in low, "the chapter must explicitly forbid self-launching"

    assert "do not wait for a human" in low

    assert "CONTRACT TEXT" in chapter, "the chain mission must be inlined when provided"

    assert "update_project_mission" in chapter, "the sub-orch authors its own project mission"
    assert "write_project_closeout" in chapter, "the close-out call is the conductor's advance signal"




def test_suborch_chapter_chain_mission_none() -> None:
    chapter = _build_ch_sub_orchestrator(
        run_id="r",
        position=1,
        n_projects=2,
        execution_mode="claude_code_cli",
        chain_mission=None,
    )

    assert "CH_SUB_ORCHESTRATOR" in chapter
    assert "project 1 of 2" in chapter
    assert "CHAIN MISSION (live)" not in chapter, "no inlined-mission header when chain_mission is None"
    assert "get_context" in chapter, "with no inlined mission, the sub-orch must fetch context"
