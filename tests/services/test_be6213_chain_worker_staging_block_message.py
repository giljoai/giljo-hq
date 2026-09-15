# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import random
import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.models import Product, Project
from giljo_mcp.models.agent_identity import AgentExecution, AgentJob
from giljo_mcp.services.mission_service import MissionService
from giljo_mcp.services.sequence_run_service import SequenceRunService
from giljo_mcp.tenant import TenantManager


pytestmark = pytest.mark.asyncio

_SOLO_WORKER_MESSAGE = (
    "Your mission is blocked. The user must click the 'Implement' "
    "button in the GiljoAI dashboard before you can receive your mission. "
    "Please inform your user of this requirement and wait."
)


async def _seed_project(session: AsyncSession, tenant_key: str) -> str:
    product = Product(
        id=str(uuid.uuid4()),
        name=f"BE-6213 Product {uuid.uuid4().hex[:6]}",
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
        name=f"BE-6213 {uuid.uuid4().hex[:6]}",
        description="Chain member.",
        mission="Be a chain member.",
        status="active",
        tenant_key=tenant_key,
        product_id=product.id,
        series_number=random.randint(1, 9000),
        execution_mode="claude_code_cli",
        implementation_launched_at=None,
        created_at=datetime.now(UTC),
    )
    session.add(project)
    session.info["tenant_key"] = tenant_key
    await session.flush()
    return project.id


async def _seed_worker_job(session: AsyncSession, tenant_key: str, project_id: str) -> AgentJob:
    job_id = str(uuid.uuid4())
    job = AgentJob(
        job_id=job_id,
        tenant_key=tenant_key,
        project_id=project_id,
        mission="implement the thing",
        job_type="implementer",
        status="active",
        job_metadata={},
    )
    session.add(job)
    session.add(
        AgentExecution(
            agent_id=str(uuid.uuid4()),
            job_id=job_id,
            tenant_key=tenant_key,
            agent_display_name="implementer",
            agent_name="implementer",
            status="waiting",
            health_status="unknown",
            project_phase="staging",
            started_at=datetime.now(UTC),
        )
    )
    session.info["tenant_key"] = tenant_key
    await session.flush()
    return job


def _mission_svc(session: AsyncSession, db_manager) -> MissionService:
    return MissionService(db_manager=db_manager, tenant_manager=TenantManager(), test_session=session)


def _run_svc(session: AsyncSession) -> SequenceRunService:
    return SequenceRunService(db_manager=None, tenant_manager=TenantManager(), session=session)




async def test_chain_worker_staging_block_is_chain_worded(db_session: AsyncSession, db_manager) -> None:
    tenant = TenantManager.generate_tenant_key()
    p1 = await _seed_project(db_session, tenant)
    p2 = await _seed_project(db_session, tenant)
    await _run_svc(db_session).create(
        project_ids=[p1, p2], resolved_order=[p1, p2], execution_mode="claude_code_cli", tenant_key=tenant
    )
    job = await _seed_worker_job(db_session, tenant, p1)

    response = await _mission_svc(db_session, db_manager).get_agent_mission(job.job_id, tenant)

    assert response.blocked is True
    instruction = response.user_instruction or ""
    assert "click the 'Implement'" not in instruction and "must click" not in instruction, (
        "a chain worker must NOT be told to click the (non-existent) Implement button"
    )
    assert instruction != _SOLO_WORKER_MESSAGE
    assert "staging" in instruction.lower()
    assert "get_job_mission" in instruction




async def test_solo_worker_keeps_byte_identical_message(db_session: AsyncSession, db_manager) -> None:
    tenant = TenantManager.generate_tenant_key()
    p1 = await _seed_project(db_session, tenant)
    job = await _seed_worker_job(db_session, tenant, p1)

    response = await _mission_svc(db_session, db_manager).get_agent_mission(job.job_id, tenant)

    assert response.blocked is True
    assert response.user_instruction == _SOLO_WORKER_MESSAGE, "the SOLO worker message must remain byte-identical"
