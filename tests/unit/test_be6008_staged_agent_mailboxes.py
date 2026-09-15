# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.database import tenant_session_context
from giljo_mcp.models import Project
from giljo_mcp.models.agent_identity import AgentExecution, AgentJob
from giljo_mcp.models.products import Product
from giljo_mcp.models.templates import AgentTemplate
from giljo_mcp.services.comm_thread_service import CommThreadService
from giljo_mcp.services.job_lifecycle_service import JobLifecycleService
from giljo_mcp.services.mission_service import MissionService
from giljo_mcp.services.taxonomy_ops import ensure_default_types_seeded
from giljo_mcp.tenant import TenantManager
from tests.helpers.product_crew_helper import adopt_all_templates


pytestmark = pytest.mark.asyncio


async def _seed_product(session: AsyncSession, tenant_key: str) -> str:
    product_id = str(uuid.uuid4())
    session.add(Product(id=product_id, tenant_key=tenant_key, name=f"BE-6008 Product {uuid.uuid4().hex[:8]}"))
    session.info["tenant_key"] = tenant_key
    await session.flush()
    return product_id


async def _seed_project(
    session: AsyncSession,
    tenant_key: str,
    execution_mode: str = "multi_terminal",
    *,
    implementation_launched: bool = False,
) -> str:
    suffix = uuid.uuid4().hex[:8]
    product_id = await _seed_product(session, tenant_key)
    project = Project(
        id=str(uuid.uuid4()),
        product_id=product_id,
        name=f"BE-6008 Project {suffix}",
        description="Two-phase spawn regression project.",
        mission="Stage agents, then write missions.",
        status="active",
        tenant_key=tenant_key,
        series_number=1,
        execution_mode=execution_mode,
        created_at=datetime.now(UTC),
        implementation_launched_at=datetime.now(UTC) if implementation_launched else None,
    )
    session.add(project)
    session.info["tenant_key"] = tenant_key
    await session.flush()
    return project.id


async def _seed_template(session: AsyncSession, tenant_key: str, name: str = "implementer") -> None:
    session.add(
        AgentTemplate(
            id=str(uuid.uuid4()),
            tenant_key=tenant_key,
            name=name,
            is_active=True,
        )
    )
    session.info["tenant_key"] = tenant_key
    await session.flush()

    products = await session.execute(select(Product.id).where(Product.tenant_key == tenant_key))
    for (product_id,) in products.all():
        await adopt_all_templates(session, tenant_key, product_id)


async def _get_execution(session: AsyncSession, tenant_key: str, job_id: str) -> AgentExecution:
    row = await session.execute(
        select(AgentExecution).where(
            AgentExecution.tenant_key == tenant_key,
            AgentExecution.job_id == job_id,
        )
    )
    return row.scalar_one()


async def _get_job(session: AsyncSession, tenant_key: str, job_id: str) -> AgentJob:
    row = await session.execute(select(AgentJob).where(AgentJob.tenant_key == tenant_key, AgentJob.job_id == job_id))
    return row.scalar_one()




async def test_two_phase_spawn_then_mission_write_transitions_staged_to_waiting(
    db_session: AsyncSession,
) -> None:
    tenant_key = TenantManager.generate_tenant_key()
    project_id = await _seed_project(db_session, tenant_key)
    await _seed_template(db_session, tenant_key, "implementer")

    lifecycle = JobLifecycleService(
        db_manager=None,  # type: ignore[arg-type]
        tenant_manager=TenantManager(),
        test_session=db_session,
    )

    result = await lifecycle.spawn_job(
        agent_display_name="implementer",
        agent_name="implementer",
        project_id=project_id,
        tenant_key=tenant_key,
    )
    job_id = result.job_id

    execution = await _get_execution(db_session, tenant_key, job_id)
    job = await _get_job(db_session, tenant_key, job_id)
    assert execution.status == "staged", "mission-less spawn must create a 'staged' execution"
    assert job.mission is None, "a staged job's mission must be NULL until Phase-2"

    mission_service = MissionService(
        db_manager=None,  # type: ignore[arg-type]
        tenant_manager=TenantManager(),
        test_session=db_session,
    )
    await mission_service.update_agent_mission(
        job_id=job_id, tenant_key=tenant_key, mission="Implement BE-6008 unit X."
    )

    execution_after = await _get_execution(db_session, tenant_key, job_id)
    job_after = await _get_job(db_session, tenant_key, job_id)
    assert execution_after.status == "waiting", "Phase-2 write must transition staged -> waiting"
    assert job_after.mission == "Implement BE-6008 unit X."


async def test_spawn_with_mission_is_waiting_not_staged(db_session: AsyncSession) -> None:
    tenant_key = TenantManager.generate_tenant_key()
    project_id = await _seed_project(db_session, tenant_key)
    await _seed_template(db_session, tenant_key, "implementer")

    lifecycle = JobLifecycleService(
        db_manager=None,  # type: ignore[arg-type]
        tenant_manager=TenantManager(),
        test_session=db_session,
    )
    result = await lifecycle.spawn_job(
        agent_display_name="implementer",
        agent_name="implementer",
        project_id=project_id,
        tenant_key=tenant_key,
        mission="Do the work now.",
    )

    execution = await _get_execution(db_session, tenant_key, result.job_id)
    assert execution.status == "waiting"




async def _spawn_and_fetch_mission(db_session: AsyncSession, tenant_key: str, execution_mode: str):
    project_id = await _seed_project(
        db_session, tenant_key, execution_mode=execution_mode, implementation_launched=True
    )
    await _seed_template(db_session, tenant_key, "implementer")

    lifecycle = JobLifecycleService(
        db_manager=None,  # type: ignore[arg-type]
        tenant_manager=TenantManager(),
        test_session=db_session,
    )
    result = await lifecycle.spawn_job(
        agent_display_name="implementer",
        agent_name="implementer",
        project_id=project_id,
        tenant_key=tenant_key,
        mission="Implement the feature.",
    )

    mission_service = MissionService(
        db_manager=None,  # type: ignore[arg-type]
        tenant_manager=TenantManager(),
        test_session=db_session,
    )
    return await mission_service.get_agent_mission(job_id=result.job_id, tenant_key=tenant_key)


async def test_multi_terminal_specialist_mission_has_roster_and_authority_chapters(
    db_session: AsyncSession,
) -> None:
    tenant_key = TenantManager.generate_tenant_key()
    response = await _spawn_and_fetch_mission(db_session, tenant_key, "multi_terminal")

    protocol = response.full_protocol
    assert "CH_TEAM: LIVE PROJECT ROSTER" in protocol, "multi_terminal specialist must get the live roster chapter"
    assert "CH_MESSAGING: WHO AUTHORS WORK" in protocol, "multi_terminal specialist must get the authority chapter"

    assert "## YOUR TEAM" not in response.mission, (
        "multi_terminal specialist mission body must NOT carry the static roster (live CH_TEAM supersedes it)"
    )


async def test_cli_mode_specialist_mission_omits_roster_and_authority_chapters(
    db_session: AsyncSession,
) -> None:
    tenant_key = TenantManager.generate_tenant_key()
    response = await _spawn_and_fetch_mission(db_session, tenant_key, "claude_code_cli")

    protocol = response.full_protocol
    assert "CH_TEAM: LIVE PROJECT ROSTER" not in protocol, "CLI mode must NOT inject the live roster chapter"
    assert "CH_MESSAGING: WHO AUTHORS WORK" not in protocol, "CLI mode must NOT inject the authority chapter"

    assert "## YOUR TEAM" in response.mission, (
        "CLI mode specialist must still carry the static roster in its mission body"
    )




async def test_message_to_staged_agent_is_persisted_and_delivered(db_session: AsyncSession) -> None:
    tenant_key = TenantManager.generate_tenant_key()
    project_id = await _seed_project(db_session, tenant_key)
    await _seed_template(db_session, tenant_key, "implementer")

    lifecycle = JobLifecycleService(
        db_manager=None,  # type: ignore[arg-type]
        tenant_manager=TenantManager(),
        test_session=db_session,
    )
    staged = await lifecycle.spawn_job(
        agent_display_name="implementer",
        agent_name="implementer",
        project_id=project_id,
        tenant_key=tenant_key,
    )
    staged_agent_id = staged.agent_id

    sender = await lifecycle.spawn_job(
        agent_display_name="orchestrator",
        agent_name="orchestrator",
        project_id=project_id,
        tenant_key=tenant_key,
        mission="Coordinate.",
    )

    execution = await _get_execution_for_agent(db_session, tenant_key, staged_agent_id)
    assert execution.status == "staged", "precondition: target agent is staged"

    with tenant_session_context(db_session, tenant_key):
        await ensure_default_types_seeded(db_session, tenant_key)

    comm = CommThreadService(
        db_manager=None,  # type: ignore[arg-type]
        tenant_manager=TenantManager(),
        session=db_session,
    )
    thread = await comm.resolve_or_create_bound_thread(project_id=project_id, tenant_key=tenant_key)
    post_result = await comm.post_to_thread(
        thread_id=thread["thread_id"],
        content="INFO: schema is ready for you.",
        from_agent=sender.agent_id,
        to_participant=staged_agent_id,
        tenant_key=tenant_key,
    )
    assert post_result["recipients"] == [staged_agent_id], "the staged agent must be an accepted recipient"

    history = await comm.get_thread_history(
        thread_id=thread["thread_id"],
        as_participant=staged_agent_id,
        tenant_key=tenant_key,
    )
    contents = [m.get("content") for m in history["messages"]]
    assert any("schema is ready for you" in (c or "") for c in contents), (
        "a staged agent must receive Hub posts addressed to it"
    )


async def _get_execution_for_agent(session: AsyncSession, tenant_key: str, agent_id: str) -> AgentExecution:
    row = await session.execute(
        select(AgentExecution).where(
            AgentExecution.tenant_key == tenant_key,
            AgentExecution.agent_id == agent_id,
        )
    )
    return row.scalar_one()
