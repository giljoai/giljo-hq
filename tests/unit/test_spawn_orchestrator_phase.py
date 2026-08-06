# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
Unit tests for CE-0026 + CE-0032: orchestrator project_phase invariants.

Behaviors covered:
  a. create_orchestrator_fixture sets project_phase='staging'.
  b. ProjectLaunchService._spawn_orchestrator (via launch_project) sets phase='staging'.
  c. ThinClientPromptGenerator._find_or_create_orchestrator (create path) sets phase='staging'.
  d. (CE-0032) launch_project reuses the same orch row across phases; no second exec is spawned.
  e. Back-compat default: AgentExecution without explicit project_phase reads as 'implementation'.
  f. CHECK constraint: inserting project_phase='garbage' raises an IntegrityError.

Under CE-0032's single-orchestrator-entity model, every spawn path writes
project_phase='staging' (the column persists for back-compat; new logic
keys on project flags). No code ever writes 'implementation' to a new row.
"""

from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.models.agent_identity import AgentExecution, AgentJob
from giljo_mcp.models.products import Product
from giljo_mcp.models.projects import Project
from giljo_mcp.repositories.project_lifecycle_repository import ProjectLifecycleRepository


# ============================================================================
# Shared helpers
# ============================================================================


async def _seed_product(db_session: AsyncSession, tenant_key: str) -> Product:
    product = Product(
        id=str(uuid4()),
        tenant_key=tenant_key,
        name=f"Phase Unit Test Product {uuid4().hex[:6]}",
        description="CE-0026 spawn phase unit tests",
        is_active=True,
    )
    db_session.add(product)
    await db_session.flush()
    return product


async def _seed_active_project(
    db_session: AsyncSession,
    tenant_key: str,
    product_id: str,
    *,
    staging_status: str | None = None,
) -> Project:
    project = Project(
        id=str(uuid4()),
        tenant_key=tenant_key,
        product_id=product_id,
        name=f"Phase Unit Test Project {uuid4().hex[:6]}",
        description="CE-0026 spawn phase unit tests",
        mission="CE-0026 test mission",
        status="active",
        staging_status=staging_status,
        series_number=random.randint(1, 9000),
        created_at=datetime.now(UTC),
    )
    db_session.add(project)
    await db_session.flush()
    return project


def _make_launch_service(db_session: AsyncSession, tenant_key: str):
    """Build a ProjectLaunchService bound to the test session."""
    from giljo_mcp.services.project_launch_service import ProjectLaunchService

    db_manager = MagicMock()
    tenant_manager = MagicMock()
    tenant_manager.get_current_tenant.return_value = tenant_key
    return ProjectLaunchService(
        db_manager=db_manager,
        tenant_manager=tenant_manager,
        test_session=db_session,
    )


# ============================================================================
# (a) create_orchestrator_fixture sets project_phase='staging'
# ============================================================================


@pytest.mark.asyncio
async def test_create_orchestrator_fixture_sets_staging_phase(
    db_session: AsyncSession,
    test_tenant_key: str,
):
    """create_orchestrator_fixture (called on project activation) must set
    project_phase='staging' on the AgentExecution it creates.

    CE-0026: The fixture is created before staging has begun — the first
    orchestrator execution always belongs to the staging phase.
    """
    product = await _seed_product(db_session, test_tenant_key)
    project = await _seed_active_project(db_session, test_tenant_key, product.id)
    await db_session.commit()

    repo = ProjectLifecycleRepository()
    result = await repo.create_orchestrator_fixture(db_session, test_tenant_key, project)

    execution_id = result["execution_id"]
    execution = (await db_session.execute(select(AgentExecution).where(AgentExecution.id == execution_id))).scalar_one()

    assert execution.project_phase == "staging", (
        f"CE-0026: create_orchestrator_fixture must set project_phase='staging', got {execution.project_phase!r}"
    )


# ============================================================================
# (b) ProjectLaunchService._spawn_orchestrator sets phase='staging'
# ============================================================================


@pytest.mark.asyncio
async def test_launch_project_spawn_orchestrator_sets_staging_phase(
    db_session: AsyncSession,
    test_tenant_key: str,
):
    """launch_project on a fresh project calls _spawn_orchestrator which must
    set project_phase='staging' on the created AgentExecution.

    CE-0026: spawn at launch is the staging session.
    """
    product = await _seed_product(db_session, test_tenant_key)
    project = await _seed_active_project(db_session, test_tenant_key, product.id)
    await db_session.commit()

    svc = _make_launch_service(db_session, test_tenant_key)
    result = await svc.launch_project(project_id=project.id)

    assert result.orchestrator_job_id is not None

    # Find the execution created for this job.
    execution = (
        await db_session.execute(
            select(AgentExecution).where(
                AgentExecution.job_id == result.orchestrator_job_id,
                AgentExecution.tenant_key == test_tenant_key,
                AgentExecution.agent_display_name == "orchestrator",
            )
        )
    ).scalar_one()

    assert execution.project_phase == "staging", (
        f"CE-0026: _spawn_orchestrator must set project_phase='staging', got {execution.project_phase!r}"
    )
    # launch should also set staging_status on the project.
    refreshed_project = (
        await db_session.execute(select(Project).where(Project.id == project.id, Project.tenant_key == test_tenant_key))
    ).scalar_one()
    assert refreshed_project.staging_status == "staging", (
        "CE-0026: _spawn_orchestrator must set project.staging_status='staging'"
    )


# ============================================================================
# (c) ThinClientPromptGenerator._find_or_create_orchestrator (create path)
# ============================================================================


@pytest.mark.asyncio
async def test_thin_prompt_generator_creates_orchestrator_with_staging_phase(
    db_session: AsyncSession,
    test_tenant_key: str,
):
    """ThinClientPromptGenerator._find_or_create_orchestrator, when no orchestrator
    exists, creates a new execution with project_phase='staging'.

    CE-0026: thin_client_generator creation path is the staging session.
    """
    from giljo_mcp.thin_prompt_generator import ThinClientPromptGenerator

    product = await _seed_product(db_session, test_tenant_key)
    project = await _seed_active_project(db_session, test_tenant_key, product.id)
    await db_session.commit()

    generator = ThinClientPromptGenerator(db=db_session, tenant_key=test_tenant_key)

    orchestrator_id, _agent_id, _execution_id = await generator._find_or_create_orchestrator(
        project_id=project.id,
        project=project,
        field_toggles={},
        depth_config={},
        user_id=None,
        tool="universal",
    )

    assert orchestrator_id is not None

    # Read back the execution that was created.
    execution = (
        await db_session.execute(
            select(AgentExecution).where(
                AgentExecution.job_id == orchestrator_id,
                AgentExecution.tenant_key == test_tenant_key,
            )
        )
    ).scalar_one()

    assert execution.project_phase == "staging", (
        f"CE-0026: ThinClientPromptGenerator._find_or_create_orchestrator must set "
        f"project_phase='staging' on new execution, got {execution.project_phase!r}"
    )


# ============================================================================
# (d) Was: _spawn_implementation_execution tests.
#     CE-0032 removed the helper and the multi-exec model entirely; under the
#     single-orchestrator-entity model launch_project reuses the existing orch
#     exec across phases (waiting at staging-end, working at impl start). The
#     spawn-time tests below were deleted in CE-0032 along with the helper.
#     CE-0027 billing-unstick + idempotency-for-active tests also deleted
#     (msg-006 in the private agentcomms log) because the bug class no longer
#     exists once the multi-exec model is gone.
# ============================================================================


@pytest.mark.asyncio
async def test_launch_project_reuses_orch_across_phases_ce_0032(
    db_session: AsyncSession,
    test_tenant_key: str,
):
    """CE-0032 single-orchestrator-entity invariant.

    Pre-CE-0032 launch_project would call _spawn_implementation_execution
    when it saw a completed staging orch + staging_complete project. Under
    CE-0032 the same orch row persists; launch_project must NOT create a
    second exec row regardless of the existing orch's status.

    Seeds a post-staging orch at status='waiting' (the truth post-CE-0032)
    and confirms launch_project returns _build_reuse_result with the same
    row and no new exec is created.
    """
    product = await _seed_product(db_session, test_tenant_key)
    project = await _seed_active_project(db_session, test_tenant_key, product.id, staging_status="staging_complete")

    job_id = str(uuid4())
    job = AgentJob(
        job_id=job_id,
        tenant_key=test_tenant_key,
        project_id=project.id,
        job_type="orchestrator",
        mission="CE-0032 single-exec reuse",
        status="active",
        created_at=datetime.now(UTC),
    )
    db_session.add(job)
    orch_exec = AgentExecution(
        agent_id=str(uuid4()),
        job_id=job_id,
        tenant_key=test_tenant_key,
        agent_display_name="orchestrator",
        status="waiting",  # CE-0032 truth: orch row sits at 'waiting' post-staging
        started_at=datetime.now(UTC) - timedelta(minutes=10),
        project_phase="staging",
    )
    db_session.add(orch_exec)
    await db_session.commit()

    svc = _make_launch_service(db_session, test_tenant_key)
    result = await svc.launch_project(project_id=project.id)

    assert result.orchestrator_job_id == job_id, "CE-0032: launch_project must reuse the same AgentJob"

    executions = list(
        (
            await db_session.execute(
                select(AgentExecution).where(
                    AgentExecution.job_id == job_id,
                    AgentExecution.tenant_key == test_tenant_key,
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(executions) == 1, (
        f"CE-0032: launch_project MUST NOT spawn a second orch exec; got {len(executions)} rows"
    )
    assert executions[0].agent_id == orch_exec.agent_id


# ============================================================================
# (e) Back-compat default: no explicit project_phase → 'implementation'
# ============================================================================


@pytest.mark.asyncio
async def test_agent_execution_default_project_phase_is_implementation(
    db_session: AsyncSession,
    test_tenant_key: str,
):
    """AgentExecution inserted without an explicit project_phase must read back
    as 'implementation' (the migration DEFAULT).

    This guards the back-compat promise: existing rows from before CE-0026
    appear as implementation-phase, which is the safe fallback.
    """
    product = await _seed_product(db_session, test_tenant_key)
    project = await _seed_active_project(db_session, test_tenant_key, product.id)

    job_id = str(uuid4())
    job = AgentJob(
        job_id=job_id,
        tenant_key=test_tenant_key,
        project_id=project.id,
        job_type="orchestrator",
        mission="back-compat default test",
        status="active",
        created_at=datetime.now(UTC),
    )
    db_session.add(job)

    # Insert WITHOUT specifying project_phase — relies on the column default.
    execution = AgentExecution(
        agent_id=str(uuid4()),
        job_id=job_id,
        tenant_key=test_tenant_key,
        agent_display_name="orchestrator",
        status="working",
        started_at=datetime.now(UTC),
        # project_phase deliberately omitted — testing the default
    )
    db_session.add(execution)
    await db_session.commit()
    await db_session.refresh(execution)

    assert execution.project_phase == "implementation", (
        f"CE-0026: back-compat default for project_phase must be 'implementation', got {execution.project_phase!r}"
    )


# ============================================================================
# (f) CHECK constraint rejects invalid project_phase values
# ============================================================================


@pytest.mark.asyncio
async def test_agent_execution_check_constraint_rejects_invalid_phase(
    db_session: AsyncSession,
    test_tenant_key: str,
):
    """Inserting project_phase='garbage' must raise an IntegrityError.

    The CHECK constraint ck_agent_execution_project_phase restricts values
    to ('staging', 'implementation'). Anything else must be rejected at the
    DB level, not silently accepted.

    Note: we insert via raw SQL to bypass SQLAlchemy's Python-layer defaults
    and exercise the actual DB constraint.
    """
    product = await _seed_product(db_session, test_tenant_key)
    project = await _seed_active_project(db_session, test_tenant_key, product.id)

    job_id = str(uuid4())
    job = AgentJob(
        job_id=job_id,
        tenant_key=test_tenant_key,
        project_id=project.id,
        job_type="orchestrator",
        mission="CHECK constraint test",
        status="active",
        created_at=datetime.now(UTC),
    )
    db_session.add(job)
    await db_session.flush()

    agent_id = str(uuid4())
    exec_id = str(uuid4())

    async def _insert_invalid_phase() -> None:
        await db_session.execute(
            text(
                """
                INSERT INTO agent_executions
                  (id, agent_id, job_id, tenant_key, agent_display_name, status,
                   health_status, messages_sent_count, messages_waiting_count,
                   messages_read_count, progress, accumulated_duration_seconds,
                   reactivation_count, tool_type, project_phase)
                VALUES
                  (:id, :agent_id, :job_id, :tenant_key, :display, :status,
                   :health, 0, 0, 0, 0, 0.0, 0, :tool, :phase)
                """
            ),
            {
                "id": exec_id,
                "agent_id": agent_id,
                "job_id": job_id,
                "tenant_key": test_tenant_key,
                "display": "orchestrator",
                "status": "working",
                "health": "unknown",
                "tool": "universal",
                "phase": "garbage",
            },
        )
        await db_session.flush()

    with pytest.raises((IntegrityError, Exception)) as exc_info:
        await _insert_invalid_phase()

    # Verify the exception is constraint-related.
    err_str = str(exc_info.value).lower()
    assert any(term in err_str for term in ("check", "constraint", "project_phase", "integrity")), (
        f"CE-0026: expected a CHECK constraint IntegrityError for project_phase='garbage', got: {exc_info.value!r}"
    )
